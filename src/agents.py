import json
import os
import re
import time
from threading import Lock
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from google import genai
from langgraph.graph import END, StateGraph

from src.database import ChokepointRecord, SessionLocal, TankerMapDailyRecord
from src.market_data import get_brent_price
from src.supabase_client import supabase
from src.technicals import get_technical_indicators


class DebateState(TypedDict, total=False):
    market_context: dict[str, Any]
    previous_debates: list[dict[str, Any]]
    initial_technical: str
    initial_bullish: str
    initial_bearish: str
    verdict: dict[str, Any]


MAX_AGENT_OUTPUT_TOKENS = 1200
MAX_MODEL_ATTEMPTS = 3
MODEL_RETRY_DELAY_SECONDS = 3
GOOGLE_MODEL = "gemini-3.8-flash"
DEBATE_REFRESH_INTERVAL = timedelta(hours=12)


AGENTS = {
    "technical": {
        "name": "Technical Analysis",
        "system": (
            "You are an expert Quantitative Technical Analyst. Focus on price action, volume "
            "behavior, MFI, OBV, and liquidity zones."
        ),
    },
    "bullish": {
        "name": "Bull Case",
        "system": (
            "You are an aggressive Bullish Oil Market Analyst. Keep under 250 words."
        ),
    },
    "bearish": {
        "name": "Bear Case",
        "system": (
            "You are a professional Bearish Oil Market Analyst. Keep under 250 words."
        ),
    },
    "risk": {
        "name": "Risk Manager",
    },
}

class GoogleAIQuotaError(RuntimeError):
    """Raised when Google AI rejects a request for quota or rate-limit reasons."""


_daily_debate_lock = Lock()


def _google_api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY")


def _model_for_role(role: str) -> str:
    if role not in AGENTS:
        raise ValueError(f"Unknown War Room agent role: {role}")
    return GOOGLE_MODEL


def _google_interaction(
    system: str,
    prompt: str,
    model: str,
    max_tokens: int,
) -> str:
    client: genai.Client | None = None
    try:
        client = genai.Client(api_key=_google_api_key())
        response = client.interactions.create(
            model=model,
            input=prompt,
            system_instruction=system,
            generation_config={"max_output_tokens": max_tokens},
            store=False,
        )
        return str(response.output_text or "").strip()
    finally:
        if client is not None:
            client.close()


def _provider_status(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    status = getattr(status, "value", status)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _is_google_quota_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    return _provider_status(exc) == 429 or any(
        phrase in error_text
        for phrase in (
            "resource exhausted",
            "resource_exhausted",
            "quota",
            "rate limit",
            "too many requests",
        )
    )


def _provider_error_detail(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    body = getattr(response, "text", None)
    if not body:
        body = str(exc)
    return re.sub(r"\s+", " ", str(body)).strip()[:350]


def _invoke(
    system: str,
    prompt: str,
    model: str,
    max_tokens: int = MAX_AGENT_OUTPUT_TOKENS,
) -> str:
    if not _google_api_key():
        raise RuntimeError(
            "Google AI API key is missing. Set GOOGLE_API_KEY in the root .env file."
        )

    last_error: Exception | None = None
    for attempt in range(MAX_MODEL_ATTEMPTS):
        try:
            content = _google_interaction(system, prompt, model, max_tokens)
            if content:
                return content
            last_error = ValueError("Google AI Interactions API returned empty content.")
        except Exception as exc:
            status_code = _provider_status(exc)
            error_text = str(exc).lower()
            is_retryable = (
                status_code in {408, 429, 500, 502, 503, 504}
                or (isinstance(status_code, int) and status_code >= 500)
                or _is_google_quota_error(exc)
                or isinstance(exc, (TimeoutError, ConnectionError, OSError))
                or any(
                    phrase in error_text
                    for phrase in (
                        "resource exhausted",
                        "resource_exhausted",
                        "quota",
                        "rate limit",
                        "temporarily unavailable",
                        "service unavailable",
                        "too many requests",
                        "empty content",
                    )
                )
            )
            if not is_retryable:
                raise RuntimeError(
                    f"Google AI request failed for {model}"
                    f"{f' (HTTP {status_code})' if status_code else ''}: "
                    f"{_provider_error_detail(exc)}"
                ) from exc
            last_error = exc

        if attempt + 1 < MAX_MODEL_ATTEMPTS:
            print(
                f"[War Room Warning] Google AI model {model} did not complete "
                f"({attempt + 1}/{MAX_MODEL_ATTEMPTS}); retrying."
            )
            time.sleep(MODEL_RETRY_DELAY_SECONDS * (attempt + 1))

    assert last_error is not None
    status_code = _provider_status(last_error)
    error_detail = _provider_error_detail(last_error)
    if _is_google_quota_error(last_error):
        raise GoogleAIQuotaError(
            "Google AI API quota or rate limit reached after "
            f"{MAX_MODEL_ATTEMPTS} attempts. Check the Gemini API quota for your project. "
            f"Details: {error_detail}"
        ) from last_error
    raise RuntimeError(
        f"Google AI model {model} failed after {MAX_MODEL_ATTEMPTS} attempts: "
        f"{error_detail}"
    ) from last_error


def _fetch_recent_rows(
    table_name: str,
    order_column: str,
    limit: int,
    columns: str = "*",
) -> list[dict[str, Any]]:
    if not supabase:
        return []
    response = (
        supabase.table(table_name)
        .select(columns)
        .order(order_column, desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def _gather_telemetry() -> tuple[list[dict[str, Any]], str]:
    db = SessionLocal()
    try:
        tankermap_rows = (
            db.query(TankerMapDailyRecord)
            .order_by(TankerMapDailyRecord.date.desc())
            .limit(10)
            .all()
        )
        tankermap_data = [
            {
                "chokepoint_name": row.chokepoint_name,
                "date": row.date.isoformat(),
                "tankers": row.vessel_count_total,
                "tanker_breakdown": {
                    "lng": row.vessel_count_lng,
                    "crude": row.vessel_count_crude,
                    "product": row.vessel_count_product,
                },
                "source": "TankerMap",
            }
            for row in tankermap_rows
        ]
        tankermap_latest_date = tankermap_rows[0].date.isoformat() if tankermap_rows else None
    finally:
        db.close()

    if supabase:
        for table_name, order_column in (
            ("chokepoint_telemetry", "date"),
            ("chokepoint_records", "date"),
        ):
            try:
                columns = (
                    "chokepoint_name,date,tankers,estimated_oil_flow,source"
                    if table_name == "chokepoint_telemetry"
                    else "chokepoint_name,date,vessel_count_tanker,vessel_count_total,baseline_avg,deviation_pct"
                )
                rows = _fetch_recent_rows(table_name, order_column, 5, columns)
                if rows:
                    cloud_latest_date = max(
                        str(row.get("date") or "")[:10]
                        for row in rows
                    )
                    if tankermap_data and tankermap_latest_date >= cloud_latest_date:
                        return tankermap_data[:5], "local tankermap_chokepoint_daily"
                    return [
                        {
                            key: row.get(key)
                            for key in (
                                "chokepoint_name",
                                "date",
                                "tankers",
                                "vessel_count_tanker",
                                "vessel_count_total",
                                "estimated_oil_flow",
                                "baseline_avg",
                                "deviation_pct",
                            )
                            if row.get(key) is not None
                        }
                        for row in rows[:5]
                    ], table_name
            except Exception:
                continue

    if tankermap_data:
        return tankermap_data[:5], "local tankermap_chokepoint_daily"

    db = SessionLocal()
    try:
        rows = db.query(ChokepointRecord).order_by(ChokepointRecord.date.desc()).limit(10).all()
        return [
            {
                "chokepoint_name": row.chokepoint_name,
                "date": row.date.isoformat(),
                "tankers": row.vessel_count_tanker,
                "vessel_count_tanker": row.vessel_count_tanker,
                "vessel_count_total": row.vessel_count_total,
                "baseline_avg": row.baseline_avg,
                "deviation_pct": row.deviation_pct,
            }
            for row in rows
        ], "local chokepoint_daily"
    finally:
        db.close()


def _gather_headlines() -> tuple[list[dict[str, Any]], str]:
    if not supabase:
        return [], "unavailable"
    for table_name in ("rss_news", "news_headlines"):
        try:
            columns = (
                "title,source,link,summary,created_at,sentiment"
                if table_name == "rss_news"
                else "title,source,link,created_at,sentiment"
            )
            rows = _fetch_recent_rows(table_name, "created_at", 5, columns)
            if rows:
                return [
                    {
                        "title": str(row.get("title", ""))[:220],
                        "source": str(row.get("source", ""))[:50],
                        "summary": str(row.get("summary") or "")[:240],
                        "sentiment": str(row.get("sentiment", ""))[:20],
                    }
                    for row in rows[:5]
                ], table_name
        except Exception:
            continue
    return [], "unavailable"


def _gather_market_context() -> dict[str, Any]:
    price = float(get_brent_price())
    market_rows: list[dict[str, Any]] = []
    if supabase:
        try:
            market_rows = _fetch_recent_rows(
                "market_prices",
                "updated_at",
                5,
                "symbol,price,change_pct,updated_at",
            )
        except Exception:
            market_rows = []

    market_record = next(
        (row for row in market_rows if row.get("symbol") in ("BZ=F", "BrentCash", "brentCash")),
        None,
    )
    telemetry, telemetry_source = _gather_telemetry()
    headlines, news_source = _gather_headlines()
    try:
        technical_report = get_technical_indicators()
    except Exception as exc:
        technical_report = f"Technical indicator retrieval failed: {exc}"

    return {
        "symbol": "BZ=F",
        "instrument": "Brent Crude (brentCash)",
        "price": price,
        "daily_change_pct": market_record.get("change_pct") if market_record else None,
        "technical_report": technical_report[:700],
        "telemetry": telemetry,
        "telemetry_source": telemetry_source,
        "headlines": headlines,
        "news_source": news_source,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_previous_debates() -> list[dict[str, Any]]:
    if not supabase:
        return []
    try:
        return _fetch_recent_rows(
            "war_room_debates",
            "created_at",
            1,
            "created_at,market_price,signal,short_term_trend,long_term_trend,verdict,transcript",
        )
    except Exception as exc:
        raise RuntimeError(
            "War Room history is unavailable. Run the provided war_room_debates SQL in Supabase, "
            f"then refresh the backend. Details: {exc}"
        ) from exc


def _one_sentence(text: Any, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    normalized = re.sub(r"[.!?]+", ";", normalized).strip(" ;")
    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return normalized or "No concise rationale was saved"


def _summarize_previous_debate(
    debates: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not debates:
        return []

    previous = debates[0]
    verdict = previous.get("verdict") or {}
    if isinstance(verdict, str):
        try:
            verdict = json.loads(verdict)
        except json.JSONDecodeError:
            verdict = {}
    transcript = previous.get("transcript") or []
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except json.JSONDecodeError:
            transcript = []
    debate_point = next(
        (
            message.get("message")
            for message in reversed(transcript)
            if isinstance(message, dict) and message.get("message")
        ),
        verdict.get("rationale", ""),
    )
    signal = str(previous.get("signal") or verdict.get("signal") or "unknown").upper()
    price = previous.get("market_price")
    price_text = f" at ${float(price):.2f}" if price is not None else ""
    first_sentence = (
        f"Previous verdict: {signal}{price_text}; "
        f"{_one_sentence(verdict.get('rationale'), 170)}."
    )
    second_sentence = (
        f"Key debate point: {_one_sentence(debate_point, 170)}."
    )
    return [{"summary": f"{first_sentence} {second_sentence}"}]


def _context_prompt(state: DebateState) -> str:
    context = state["market_context"]
    prior_summary = state.get("previous_debates", [])
    return json.dumps(
        {
            "live_context": context,
            "previous_debate_summary": prior_summary,
            "instruction": (
                "Use live data as authoritative; compare it with the two-sentence prior summary."
            ),
        },
        ensure_ascii=False,
        default=str,
    )


def _gather_context_node(state: DebateState) -> dict[str, Any]:
    return {
        "market_context": _gather_market_context(),
        "previous_debates": state.get("previous_debates", []),
    }


def _initial_analysis(role: str, state: DebateState) -> dict[str, Any]:
    agent = AGENTS[role]
    role_instructions = {
        "technical": (
            "Provide a detailed quantitative technical analysis of the supplied indicators. "
            "Discuss price action, moving averages, RSI, MACD, volume behavior, MFI, OBV, and "
            "liquidity zones where the data supports it. Cite supplied values and timeframes; "
            "explicitly say when an indicator or value is unavailable. Do not invent figures."
        ),
        "bullish": (
            "Build a substantive bullish oil-market defense using the supplied macroeconomic, "
            "geopolitical, chokepoint, news, supply, and demand evidence. Address Hormuz and "
            "Bab-el-Mandeb transit risks and OPEC+ only where supported by the supplied context. "
            "Connect the evidence to the technical analysis; do not invent facts."
        ),
    }[role]
    prompt = _context_prompt(state)
    if role == "bullish":
        prompt += (
            f"\n\nTECHNICAL ANALYSIS:\n{state['initial_technical']}\n\n"
            "Use the technical evidence along with market context in your bullish defense."
        )
    report = _invoke(
        agent["system"],
        f"{prompt}\n\n{role_instructions}",
        _model_for_role(role),
    )
    return {f"initial_{role}": report}


def _bearish_rebuttal(state: DebateState) -> dict[str, Any]:
    agent = AGENTS["bearish"]
    prompt = (
        f"{_context_prompt(state)}\n\n"
        f"TECHNICAL ANALYSIS:\n{state['initial_technical']}\n\n"
        f"BULLISH ANALYST'S ARGUMENT:\n{state['initial_bullish']}\n\n"
        "Give a substantive, evidence-led bearish rebuttal. Address the bull's strongest claim, "
        "then assess macroeconomic conditions, geopolitical/chokepoint risks, OPEC+ supply, "
        "demand, and the main downside catalysts where the supplied evidence supports them. "
        "Connect the evidence to technical price action. Do not invent facts."
    )
    report = _invoke(agent["system"], prompt, _model_for_role("bearish"))
    return {"initial_bearish": report}


def _parse_verdict(response: str) -> dict[str, Any]:
    candidate = response.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    verdict = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            parsed, _ = decoder.raw_decode(candidate, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            verdict = parsed
            break
    if verdict is None:
        preview = re.sub(r"\s+", " ", candidate)[:240] or "<empty response>"
        raise ValueError(
            f"Risk Manager response did not contain a valid JSON object: {preview}"
        )

    raw_signal = re.sub(r"[^A-Z]", "", str(verdict.get("signal", "")).upper())
    signal = {
        "BUY": "BUY",
        "LONG": "BUY",
        "BULLISH": "BUY",
        "SELL": "SELL",
        "SHORT": "SELL",
        "BEARISH": "SELL",
        "HOLD": "HOLD",
        "WAIT": "HOLD",
        "NEUTRAL": "HOLD",
    }.get(raw_signal)
    if signal is None:
        raise ValueError("Risk Manager returned an invalid signal.")
    short_trend = str(verdict.get("short_term_trend", "")).upper()
    long_trend = str(verdict.get("long_term_trend", "")).upper()
    allowed_trends = {"BULLISH", "BEARISH", "NEUTRAL"}
    if short_trend not in allowed_trends or long_trend not in allowed_trends:
        raise ValueError("Risk Manager returned an invalid trend direction.")

    support = float(verdict["support"])
    resistance = float(verdict["resistance"])
    if not 0 < support < resistance:
        raise ValueError("Risk Manager returned invalid support/resistance levels.")

    return {
        "signal": signal,
        "conviction": max(0, min(100, int(verdict["conviction"]))),
        "short_term_trend": short_trend,
        "long_term_trend": long_trend,
        "support": support,
        "resistance": resistance,
        "entry": verdict.get("entry"),
        "stop_loss": verdict.get("stop_loss"),
        "take_profit": verdict.get("take_profit"),
        "rationale": str(verdict["rationale"]),
        "risk_factors": [str(item) for item in verdict.get("risk_factors", [])],
    }


def _risk_manager(state: DebateState) -> dict[str, Any]:
    context = state["market_context"]
    prompt = (
        f"{_context_prompt(state)}\n\n"
        f"OPENING ARGUMENTS:\n{json.dumps({key: state[key] for key in ('initial_technical', 'initial_bullish', 'initial_bearish')}, ensure_ascii=False)}\n\n"
        "Deliver a risk-managed verdict for the current Brent price. Reconcile the technical "
        "analysis with the bull's case and bear's rebuttal. Compare with the previous run and "
        "avoid false precision. "
        "Respond ONLY as JSON with this exact shape: "
        '{"signal":"BUY|SELL|HOLD","conviction":0,"short_term_trend":"BULLISH|BEARISH|NEUTRAL",'
        '"long_term_trend":"BULLISH|BEARISH|NEUTRAL","support":0.0,"resistance":0.0,'
        '"entry":null,"stop_loss":null,"take_profit":null,"rationale":"...",'
        '"risk_factors":["..."]}. '
        f"Support and resistance must be numeric levels around current price ${context['price']}. "
        "Give a specific multi-point rationale, explain the strongest evidence on both sides, "
        "state the forecast horizon, and express conviction as a calibrated 0-100 score. "
        "Use only support/resistance levels justified by the supplied context. "
        "This is analytical information, not a guarantee."
    )
    system = (
        "You are the independent oil desk risk manager. Decide, do not average. "
        "Return valid JSON only. The signal field must be exactly BUY, SELL, or HOLD. "
        "Do not use LONG, SHORT, WAIT, or other signal labels."
    )
    model = _model_for_role("risk")
    try:
        response = _invoke(
            system,
            prompt,
            model,
        )
        return {"verdict": _parse_verdict(response)}
    except (ValueError, KeyError, TypeError) as parse_error:
        repair_prompt = (
            "Your previous answer could not be parsed as the required verdict. "
            "Return only one valid JSON object matching the exact schema in the original "
            "request. Do not include markdown fences or commentary.\n\n"
            f"Validation error: {parse_error}\n"
            f"Previous answer:\n{response[:2400] if 'response' in locals() else '<empty response>'}\n\n"
            f"Original request:\n{prompt}"
        )
        repaired_response = _invoke(
            system,
            repair_prompt,
            model,
        )
        try:
            return {"verdict": _parse_verdict(repaired_response)}
        except (ValueError, KeyError, TypeError) as repair_error:
            raise RuntimeError(
                "Risk Manager returned an unusable verdict after one JSON-format retry: "
                f"{repair_error}"
            ) from repair_error


def compile_trading_graph():
    workflow = StateGraph(DebateState)
    workflow.add_node("gather_context", _gather_context_node)
    workflow.add_node("technical_analysis", lambda state: _initial_analysis("technical", state))
    workflow.add_node("bullish_case", lambda state: _initial_analysis("bullish", state))
    workflow.add_node("bearish_rebuttal", _bearish_rebuttal)
    workflow.add_node("risk_manager", _risk_manager)
    workflow.set_entry_point("gather_context")
    workflow.add_edge("gather_context", "technical_analysis")
    workflow.add_edge("technical_analysis", "bullish_case")
    workflow.add_edge("bullish_case", "bearish_rebuttal")
    workflow.add_edge("bearish_rebuttal", "risk_manager")
    workflow.add_edge("risk_manager", END)
    return workflow.compile()


def _transcript_for_state(state: dict[str, Any]) -> list[dict[str, str]]:
    phases = {
        "technical": "initial-analysis",
        "bullish": "initial-analysis",
        "bearish": "bearish-rebuttal",
    }
    opening_messages = [
        {
            "phase": phases[role],
            "agent": AGENTS[role]["name"],
            "role": role,
            "message": state[f"initial_{role}"],
        }
        for role in ("technical", "bullish", "bearish")
    ]
    return opening_messages


def run_agent_pipeline() -> dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase must be configured to save War Room debate history.")

    previous_debates = _summarize_previous_debate(_load_previous_debates())
    initial_state: DebateState = {
        "previous_debates": previous_debates,
        "initial_technical": "",
        "initial_bullish": "",
        "initial_bearish": "",
        "verdict": {},
    }
    final_state = compile_trading_graph().invoke(initial_state)
    transcript = _transcript_for_state(final_state)
    context = final_state["market_context"]
    verdict = final_state["verdict"]
    row = {
        "symbol": context["symbol"],
        "market_price": context["price"],
        "signal": verdict["signal"],
        "short_term_trend": verdict["short_term_trend"],
        "long_term_trend": verdict["long_term_trend"],
        "support": verdict["support"],
        "resistance": verdict["resistance"],
        "market_context": context,
        "transcript": transcript,
        "verdict": verdict,
    }
    result = supabase.table("war_room_debates").insert(row).execute()
    saved = (result.data or [{}])[0]
    return {
        "id": saved.get("id"),
        "created_at": saved.get("created_at") or datetime.now(timezone.utc).isoformat(),
        **row,
    }


def _debate_created_at(debate: dict[str, Any]) -> datetime | None:
    created_at = debate.get("created_at")
    if not created_at:
        return None
    try:
        created = (
            created_at
            if isinstance(created_at, datetime)
            else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        )
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)


def run_debate_if_due() -> dict[str, Any]:
    """Reuse the latest debate for 12 hours; otherwise generate and persist a fresh one."""
    with _daily_debate_lock:
        now = datetime.now(timezone.utc)
        recent = get_recent_debates(limit=1)
        if recent:
            created_at = _debate_created_at(recent[0])
            if created_at and now - created_at < DEBATE_REFRESH_INTERVAL:
                return recent[0]
        return run_agent_pipeline()


def get_recent_debates(limit: int = 10) -> list[dict[str, Any]]:
    if not supabase:
        raise RuntimeError("Supabase must be configured to load War Room debate history.")
    try:
        return _fetch_recent_rows("war_room_debates", "created_at", limit)
    except Exception as exc:
        raise RuntimeError(
            "War Room history is unavailable. Run the provided war_room_debates SQL in Supabase. "
            f"Details: {exc}"
        ) from exc
