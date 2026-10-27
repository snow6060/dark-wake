import json
import os
import re
import time
from threading import Lock
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
import requests

from src.database import ChokepointRecord, SessionLocal, TankerMapDailyRecord
from src.ingestion import sanitize_energy_news
from src.market_data import get_brent_market_snapshot
from src.supabase_client import supabase
from src.vision import get_spatial_telemetry
from src.technicals import (
    format_commodity_technical_report,
    get_commodity_technical_indicators,
)


class DebateState(TypedDict, total=False):
    market_context: dict[str, Any]
    previous_debates: list[dict[str, Any]]
    agent_accuracy: list[dict[str, Any]]
    initial_technical: str
    initial_supply_thesis: str
    initial_demand_thesis: str
    supply_rebuttal_1: str
    demand_rebuttal_1: str
    supply_rebuttal_2: str
    demand_rebuttal_2: str
    technical_direction: str
    supply_direction: str
    demand_direction: str
    verdict: dict[str, Any]


MAX_AGENT_OUTPUT_TOKENS = 1200
MAX_MODEL_ATTEMPTS = 3
MODEL_RETRY_DELAY_SECONDS = 3
META_API_TIMEOUT_SECONDS = 60
META_MODEL_API_URL = "https://api.meta.ai/v1"
META_MODEL_API_ENABLED = False

def run_debate_if_due(*args, **kwargs):
    import logging
    logging.warning("run_debate_if_due called but debates are hardcoded off (META_MODEL_API_ENABLED=False). No debate executed.")
    return None

META_MODEL_FALLBACKS = (
    "meta-models/muse-spark-open",
    "llama-3.1-70b-instruct",
    "muse-spark-1.3",
)
DEBATE_REFRESH_INTERVAL = timedelta(days=1)


AGENTS = {
    "technical": {
        "name": "Technical Analysis",
        "system": (
            "You are an evidence-based energy commodity quantitative analyst. Use only supplied "
            "OHLCV prices and indicators; never invent market data."
        ),
    },
    "supply": {
        "name": "Supply Thesis",
        "system": (
            "You are an evidence-led oil-market supply analyst. Keep under 250 words."
        ),
    },
    "demand": {
        "name": "Demand Thesis",
        "system": (
            "You are an evidence-led oil-market demand analyst. Keep under 250 words."
        ),
    },
    "synthesis": {
        "name": "Desk Signal & Risk Synthesis",
    },
}

class MetaModelAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class MetaModelQuotaError(RuntimeError):
    """Raised when Meta Model API rejects a request for quota or rate-limit reasons."""


_daily_debate_lock = Lock()


def _meta_model_api_key() -> str | None:
    return os.getenv("META_MODEL_API_KEY") or os.getenv("MODEL_API_KEY")


def _model_for_role(role: str) -> str:
    if role not in AGENTS:
        raise ValueError(f"Unknown Strategy Desk agent role: {role}")
    return os.getenv("META_MODEL_NAME", "meta-models/muse-spark-open-1026")


def _model_candidates(model: str) -> list[str]:
    return list(dict.fromkeys((model, *META_MODEL_FALLBACKS)))


def _meta_model_interaction(
    system: str,
    prompt: str,
    model: str,
    max_tokens: int,
) -> str:
    if not META_MODEL_API_ENABLED:
        raise RuntimeError(
            "Meta Model API calls are disabled during development. "
            "Enable META_MODEL_API_ENABLED in src/agents.py when the project is complete."
        )

    api_key = _meta_model_api_key()
    if not api_key:
        raise RuntimeError(
            "Meta Model API key is missing. Set META_MODEL_API_KEY in the root .env file."
        )

    base_url = os.getenv("META_MODEL_API_BASE_URL", META_MODEL_API_URL).rstrip("/")
    response = requests.post(
        f"{base_url}/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "instructions": system,
            "input": prompt,
            "max_output_tokens": max_tokens,
        },
        timeout=META_API_TIMEOUT_SECONDS,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = error.get("message") if isinstance(error, dict) else error
        detail = str(detail or response.text or f"HTTP {response.status_code}")
        detail = detail.replace(api_key, "[redacted]")
        raise MetaModelAPIError(response.status_code, re.sub(r"\s+", " ", detail)[:350])

    output_text = payload.get("output_text") if isinstance(payload, dict) else None
    if not output_text and isinstance(payload, dict):
        output_parts = []
        for item in payload.get("output", []):
            if item.get("type") == "message":
                output_parts.extend(
                    content.get("text", "")
                    for content in item.get("content", [])
                    if content.get("type") == "output_text"
                )
        output_text = "".join(output_parts)
    if not isinstance(output_text, str) or not output_text.strip():
        raise RuntimeError("Meta Model API returned a response without output text.")
    return output_text.strip()


def _invoke(
    system: str,
    prompt: str,
    model: str,
    max_tokens: int = MAX_AGENT_OUTPUT_TOKENS,
) -> str:
    if not _meta_model_api_key():
        raise RuntimeError(
            "Meta Model API key is missing. Set META_MODEL_API_KEY in the root .env file."
        )

    last_error: Exception | None = None
    models = _model_candidates(model)
    for model_index, candidate in enumerate(models):
        model_not_found = False
        for attempt in range(MAX_MODEL_ATTEMPTS):
            try:
                return _meta_model_interaction(system, prompt, candidate, max_tokens)
            except MetaModelAPIError as exc:
                last_error = exc
                message = exc.detail.lower()
                if (
                    model_index + 1 < len(models)
                    and exc.status_code in {400, 404}
                    and any(token in message for token in ("model", "not_found", "not found", "unsupported"))
                ):
                    model_not_found = True
                    break
                if exc.status_code == 429:
                    raise MetaModelQuotaError(
                        f"Meta Model API quota or rate limit reached: {exc.detail}"
                    ) from exc
                if exc.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise RuntimeError(
                        f"Meta Model API request failed for {candidate} "
                        f"(HTTP {exc.status_code}): {exc.detail}"
                    ) from exc
            except (TimeoutError, ConnectionError, OSError, requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc

            if attempt + 1 < MAX_MODEL_ATTEMPTS:
                time.sleep(MODEL_RETRY_DELAY_SECONDS * (attempt + 1))
        if model_not_found:
            print(
                f"[Strategy Desk Warning] Meta model {candidate} is unavailable; "
                "trying configured fallback."
            )
            continue
        break

    if isinstance(last_error, MetaModelAPIError):
        raise RuntimeError(
            f"Meta Model API model {model} failed after retries: {last_error.detail}"
        ) from last_error
    raise RuntimeError(
        f"Meta Model API model {model} failed after retries: {last_error}"
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


def _load_agent_accuracy() -> list[dict[str, Any]]:
    if not supabase:
        return []
    try:
        return _fetch_recent_rows(
            "strategy_desk_agent_accuracy",
            "updated_at",
            10,
            "agent_name,evaluated_predictions,correct_predictions,accuracy",
        )
    except Exception as exc:
        raise RuntimeError(
            "Agent accuracy memory is unavailable. Apply sql/strategy_desk_memory.sql "
            "in Supabase before running Strategy Desk analysis."
        ) from exc


def _direction_for_change(change_pct: float) -> str:
    if change_pct > 0.1:
        return "UP"
    if change_pct < -0.1:
        return "DOWN"
    return "NEUTRAL"


def _score_due_predictions(
    commodity_basket: dict[str, dict[str, Any]],
    now: datetime | None = None,
) -> int:
    if not supabase:
        return 0
    current_time = now or datetime.now(timezone.utc)
    try:
        rows = _fetch_recent_rows(
            "strategy_desk_predictions",
            "evaluation_due_at",
            1000,
            "id,symbol,base_price,predicted_direction,agent_predictions,evaluation_due_at,actual_price",
        )
    except Exception as exc:
        raise RuntimeError(
            "Strategy Desk prediction history is unavailable. Apply "
            "sql/strategy_desk_memory.sql in Supabase before running analysis."
        ) from exc

    scored_count = 0
    for row in rows:
        if row.get("actual_price") is not None:
            continue
        due_at = row.get("evaluation_due_at")
        if not due_at:
            continue
        due_time = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
        if due_time.tzinfo is None:
            due_time = due_time.replace(tzinfo=timezone.utc)
        if due_time > current_time:
            continue

        observed = commodity_basket.get(row["symbol"], {})
        if observed.get("status") != "available" or observed.get("price") is None:
            continue
        base_price = float(row["base_price"])
        actual_price = float(observed["price"])
        change_pct = (actual_price - base_price) / base_price * 100
        actual_direction = _direction_for_change(change_pct)
        agent_predictions = row.get("agent_predictions") or {}
        agent_results = {
            agent: direction == actual_direction
            for agent, direction in agent_predictions.items()
            if direction in {"UP", "DOWN", "NEUTRAL"}
        }
        try:
            (
                supabase.table("strategy_desk_predictions")
                .update({
                    "actual_price": actual_price,
                    "actual_direction": actual_direction,
                    "direction_correct": row["predicted_direction"] == actual_direction,
                    "agent_results": agent_results,
                    "evaluated_at": current_time.isoformat(),
                })
                .eq("id", row["id"])
                .execute()
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not score Strategy Desk prediction {row['id']}."
            ) from exc
        scored_count += 1

    if scored_count:
        _refresh_agent_accuracy_scores()
    return scored_count


def _refresh_agent_accuracy_scores() -> None:
    try:
        rows = _fetch_recent_rows(
            "strategy_desk_predictions",
            "created_at",
            5000,
            "agent_results",
        )
        scores: dict[str, list[int]] = {}
        for row in rows:
            for agent, correct in (row.get("agent_results") or {}).items():
                values = scores.setdefault(agent, [0, 0])
                values[0] += 1
                values[1] += int(bool(correct))
        if scores:
            updates = [
                {
                    "agent_name": agent,
                    "evaluated_predictions": counts[0],
                    "correct_predictions": counts[1],
                    "accuracy": round(counts[1] / counts[0], 4),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for agent, counts in scores.items()
            ]
            supabase.table("strategy_desk_agent_accuracy").upsert(
                updates,
                on_conflict="agent_name",
            ).execute()
    except Exception as exc:
        raise RuntimeError(
            "Could not refresh Strategy Desk agent accuracy scores. Check "
            "sql/strategy_desk_memory.sql and Supabase permissions."
        ) from exc


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
                headlines = []
                for row in rows[:5]:
                    title, category = sanitize_energy_news(str(row.get("title", "")))
                    summary, _ = sanitize_energy_news(str(row.get("summary") or ""))
                    headlines.append({
                        "title": title[:220],
                        "category": category,
                        "source": str(row.get("source", ""))[:50],
                        "summary": summary[:240],
                        "sentiment": str(row.get("sentiment", ""))[:20],
                    })
                return headlines, table_name
        except Exception:
            continue
    return [], "unavailable"


def _gather_market_context() -> dict[str, Any]:
    market_snapshot = get_brent_market_snapshot()
    telemetry, telemetry_source = _gather_telemetry()
    headlines, news_source = _gather_headlines()
    commodity_basket = get_commodity_technical_indicators()
    technical_report = format_commodity_technical_report(commodity_basket)

    return {
        "symbol": "BZ=F",
        "instrument": "Brent Crude (brentCash)",
        "price": market_snapshot["price"],
        "daily_change_pct": market_snapshot["change_pct"],
        "market_status": market_snapshot["market_status"],
        "market_is_closed": market_snapshot["market_is_closed"],
        "price_basis": market_snapshot["price_basis"],
        "price_as_of": market_snapshot["price_as_of"],
        "commodity_basket": commodity_basket,
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
            "Strategy Desk history is unavailable. Run the provided war_room_debates SQL in Supabase, "
            f"then refresh the backend. Details: {exc}"
        ) from exc


def _compact_analysis(text: Any, max_chars: int = 900) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return normalized or "No prior analysis was saved"


def _summarize_previous_debate(
    debates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
    if not isinstance(verdict, dict):
        verdict = {}
    if not isinstance(transcript, list):
        transcript = []

    role_aliases = {
        "technical": ("technical",),
        "supply_thesis": ("supply_thesis", "supply", "bullish"),
        "demand_thesis": ("demand_thesis", "demand", "bearish"),
    }
    analyses = {
        role: _compact_analysis(
            next(
                (
                    message.get("message")
                    for message in transcript
                    if isinstance(message, dict)
                    and message.get("role") in legacy_roles
                    and message.get("message")
                ),
                "",
            )
        )
        for role, legacy_roles in role_aliases.items()
    }
    signal = str(previous.get("signal") or verdict.get("signal") or "unknown").upper()
    price = previous.get("market_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return [{
        "created_at": previous.get("created_at"),
        "market_price": price,
        "signal": signal,
        "short_term_trend": previous.get("short_term_trend") or verdict.get("short_term_trend"),
        "long_term_trend": previous.get("long_term_trend") or verdict.get("long_term_trend"),
        "verdict_rationale": _compact_analysis(verdict.get("rationale"), 650),
        "agent_analyses": analyses,
    }]


def _context_prompt(state: DebateState) -> str:
    context = state["market_context"]
    prior_summary = state.get("previous_debates", [])
    accuracy_summary = state.get("agent_accuracy", [])
    if context.get("market_is_closed"):
        instruction = (
            "The Brent market is closed for the weekend. The supplied price is the latest "
            "available daily close, not a live weekend quote. Use its price_as_of timestamp, "
            "do not imply that the price is moving while the market is closed, and frame any "
            "assessment as based on the last close plus available weekend news and data."
        )
    elif context.get("price_basis") == "last_close":
        instruction = (
            "An intraday Brent quote is unavailable. The supplied price is the latest available "
            "daily close, not a live quote. Use its price_as_of timestamp and do not describe it "
            "as current intraday pricing."
        )
    else:
        instruction = "Use the latest available market data as authoritative."
    if prior_summary:
        instruction += (
            " Compare your current findings with the prior analysis for your role, identify "
            "what remains supported or has changed, and reassess the earlier view against "
            "current evidence. Treat prior analysis as a hypothesis, not a fact or an anchor; "
            "do not claim a forecast was correct without evidence."
        )
    if accuracy_summary:
        instruction += (
            " Review the supplied historical accuracy for your agent role. Use it as "
            "calibrated feedback, not as a substitute for current market evidence."
        )
    return json.dumps(
        {
            "live_context": context,
            "previous_debate_summary": prior_summary,
            "agent_accuracy_history": accuracy_summary,
            "instruction": instruction,
        },
        ensure_ascii=False,
        default=str,
    )


def _gather_context_node(state: DebateState) -> dict[str, Any]:
    return {
        "market_context": state.get("market_context") or _gather_market_context(),
        "previous_debates": state.get("previous_debates", []),
        "agent_accuracy": state.get("agent_accuracy", []),
    }


def _parse_agent_turn(response: str) -> dict[str, Any]:
    candidate = response.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("Strategy Desk agent response was not valid JSON.") from exc
    if not isinstance(result, dict) or not str(result.get("analysis", "")).strip():
        raise ValueError("Strategy Desk agent response must include non-empty analysis.")
    direction = str(result.get("direction", "")).upper()
    if direction not in {"UP", "DOWN", "NEUTRAL"}:
        raise ValueError("Strategy Desk agent direction must be UP, DOWN, or NEUTRAL.")
    confidence = int(result.get("confidence", -1))
    if not 0 <= confidence <= 100:
        raise ValueError("Strategy Desk agent confidence must be from 0 to 100.")
    return {
        "analysis": str(result["analysis"]).strip(),
        "direction": direction,
        "confidence": confidence,
    }


_AGENT_RESPONSE_FORMAT = (
    "Return ONLY one JSON object with this exact schema: "
    '{"analysis":"concise evidence-based reasoning","direction":"UP|DOWN|NEUTRAL",'
    '"confidence":0}. Direction is the expected one-day Brent price direction; use NEUTRAL '
    "when supplied evidence is balanced or insufficient. Confidence must be an integer 0-100. "
    "Do not include markdown fences."
)


def _initial_analysis(role: str, state: DebateState) -> dict[str, Any]:
    agent = AGENTS[role]
    role_instructions = {
        "technical": (
            "Assess Brent and the full supplied commodity basket. Compare prices and RSI (14), "
            "MACD (12,26,9), ATR (14), EMA (20/50/200), Bollinger bands, stochastic and VWAP "
            "where available. Identify unavailable indicators rather than inventing values."
        ),
        "supply": (
            "Build an evidence-led supply thesis using commodity indicators, commercial shipping "
            "route density, bottleneck telemetry, inventories, trade volumes, and supply data. "
            "Mention only factors present in the supplied context."
        ),
        "demand": (
            "Build an evidence-led demand thesis using commodity indicators, macroeconomic "
            "conditions, inventories, trade volumes, and consumption data. Mention only factors "
            "present in the supplied context."
        ),
    }[role]
    prompt = (
        f"{_context_prompt(state)}\n\n"
        f"TECHNICAL ANALYSIS:\n{state.get('initial_technical', '')}\n\n"
        f"SUPPLY THESIS:\n{state.get('initial_supply_thesis', '')}\n\n"
        f"DEMAND THESIS:\n{state.get('initial_demand_thesis', '')}\n\n"
        f"{role_instructions}\n{_AGENT_RESPONSE_FORMAT}"
    )
    turn = _parse_agent_turn(
        _invoke(agent["system"], prompt, _model_for_role(role))
    )
    state_keys = {
        "technical": ("initial_technical", "technical_direction"),
        "supply": ("initial_supply_thesis", "supply_direction"),
        "demand": ("initial_demand_thesis", "demand_direction"),
    }
    text_key, direction_key = state_keys[role]
    return {text_key: turn["analysis"], direction_key: turn["direction"]}


def _thesis_rebuttal(role: str, loop: int, state: DebateState) -> dict[str, Any]:
    if role not in {"supply", "demand"} or loop not in {1, 2}:
        raise ValueError("Rebuttal role and loop must be supply/demand and 1/2.")
    if role == "supply":
        prior_key = "initial_demand_thesis" if loop == 1 else "demand_rebuttal_1"
        output_key = f"supply_rebuttal_{loop}"
        instruction = (
            "Rebut the demand thesis with specific evidence about supply, commodity "
            "relationships, shipping routes, inventories, and bottlenecks. Correct any earlier "
            "claim that current evidence does not support."
        )
    else:
        prior_key = "supply_rebuttal_1" if loop == 1 else "supply_rebuttal_2"
        output_key = f"demand_rebuttal_{loop}"
        instruction = (
            "Rebut the supply thesis with evidence about demand, prices, inventories, and "
            "macroeconomic conditions. Correct any earlier claim that current evidence does "
            "not support."
        )
    prompt = (
        f"{_context_prompt(state)}\n\n"
        f"TECHNICAL ANALYSIS:\n{state['initial_technical']}\n\n"
        f"PREVIOUS OPPOSING THESIS:\n{state[prior_key]}\n\n"
        f"Your prior analysis:\n{state['initial_supply_thesis'] if role == 'supply' else state['initial_demand_thesis']}\n\n"
        f"REBUTTAL LOOP {loop}: {instruction}\n{_AGENT_RESPONSE_FORMAT}"
    )
    turn = _parse_agent_turn(
        _invoke(AGENTS[role]["system"], prompt, _model_for_role(role))
    )
    direction_key = "supply_direction" if role == "supply" else "demand_direction"
    return {output_key: turn["analysis"], direction_key: turn["direction"]}


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
            f"Desk Signal & Risk Synthesis response did not contain a valid JSON object: {preview}"
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
        raise ValueError("Desk Signal & Risk Synthesis returned an invalid signal.")
    short_trend = str(verdict.get("short_term_trend", "")).upper()
    long_trend = str(verdict.get("long_term_trend", "")).upper()
    allowed_trends = {"BULLISH", "BEARISH", "NEUTRAL"}
    if short_trend not in allowed_trends or long_trend not in allowed_trends:
        raise ValueError("Desk Signal & Risk Synthesis returned an invalid trend direction.")

    support = float(verdict["support"])
    resistance = float(verdict["resistance"])
    if not 0 < support < resistance:
        raise ValueError("Desk Signal & Risk Synthesis returned invalid support/resistance levels.")

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


def _desk_signal_synthesis(state: DebateState) -> dict[str, Any]:
    context = state["market_context"]
    prompt = (
        f"{_context_prompt(state)}\n\n"
        f"DESK ANALYSES:\n{json.dumps({key: state[key] for key in ('initial_technical', 'initial_supply_thesis', 'initial_demand_thesis', 'supply_rebuttal_1', 'demand_rebuttal_1', 'supply_rebuttal_2', 'demand_rebuttal_2')}, ensure_ascii=False)}\n\n"
        "Deliver a risk-managed synthesis for the current Brent price. Reconcile the technical "
        "analysis with the supply and demand theses. Compare the prior synthesis and all "
        "three prior agent analyses with current evidence; say what changed and avoid treating "
        "the old forecast as established fact. Avoid false precision. "
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
        "You are the independent energy desk signal and risk analyst. Decide, do not average. "
        "Return valid JSON only. The signal field must be exactly BUY, SELL, or HOLD. "
        "Do not use LONG, SHORT, WAIT, or other signal labels."
    )
    model = _model_for_role("synthesis")
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
                "Desk Signal & Risk Synthesis returned an unusable result after one JSON-format retry: "
                f"{repair_error}"
            ) from repair_error


def compile_trading_graph():
    workflow = StateGraph(DebateState)
    workflow.add_node("gather_context", _gather_context_node)
    workflow.add_node("technical_analysis", lambda state: _initial_analysis("technical", state))
    workflow.add_node("supply_thesis", lambda state: _initial_analysis("supply", state))
    workflow.add_node("demand_thesis", lambda state: _initial_analysis("demand", state))
    workflow.add_node("supply_rebuttal_1", lambda state: _thesis_rebuttal("supply", 1, state))
    workflow.add_node("demand_rebuttal_1", lambda state: _thesis_rebuttal("demand", 1, state))
    workflow.add_node("supply_rebuttal_2", lambda state: _thesis_rebuttal("supply", 2, state))
    workflow.add_node("demand_rebuttal_2", lambda state: _thesis_rebuttal("demand", 2, state))
    workflow.add_node("desk_signal_synthesis", _desk_signal_synthesis)
    workflow.set_entry_point("gather_context")
    workflow.add_edge("gather_context", "technical_analysis")
    workflow.add_edge("technical_analysis", "supply_thesis")
    workflow.add_edge("supply_thesis", "demand_thesis")
    workflow.add_edge("demand_thesis", "supply_rebuttal_1")
    workflow.add_edge("supply_rebuttal_1", "demand_rebuttal_1")
    workflow.add_edge("demand_rebuttal_1", "supply_rebuttal_2")
    workflow.add_edge("supply_rebuttal_2", "demand_rebuttal_2")
    workflow.add_edge("demand_rebuttal_2", "desk_signal_synthesis")
    workflow.add_edge("desk_signal_synthesis", END)
    return workflow.compile()


def _transcript_for_state(state: dict[str, Any]) -> list[dict[str, str]]:
    turns = (
        ("technical", "initial-analysis", "initial_technical"),
        ("supply", "supply-thesis", "initial_supply_thesis"),
        ("demand", "demand-thesis", "initial_demand_thesis"),
        ("supply", "supply-rebuttal-1", "supply_rebuttal_1"),
        ("demand", "demand-rebuttal-1", "demand_rebuttal_1"),
        ("supply", "supply-rebuttal-2", "supply_rebuttal_2"),
        ("demand", "demand-rebuttal-2", "demand_rebuttal_2"),
    )
    client_roles = {"technical": "technical", "supply": "bullish", "demand": "bearish"}
    return [
        {
            "phase": phase,
            "agent": AGENTS[role]["name"],
            "role": client_roles[role],
            "message": state[state_key],
        }
        for role, phase, state_key in turns
    ]


def _record_prediction(
    analysis_id: str,
    context: dict[str, Any],
    verdict: dict[str, Any],
    agent_directions: dict[str, str],
) -> None:
    basket = context.get("commodity_basket", {})
    brent_telemetry = basket.get("BZ=F", {})
    base_price = brent_telemetry.get("price") or context["price"]
    direction = {"BUY": "UP", "SELL": "DOWN", "HOLD": "NEUTRAL"}[verdict["signal"]]
    payload = {
        "analysis_id": analysis_id,
        "symbol": "BZ=F",
        "base_price": float(base_price),
        "predicted_direction": direction,
        "agent_predictions": agent_directions,
        "evaluation_due_at": (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat(),
    }
    try:
        supabase.table("strategy_desk_predictions").insert(payload).execute()
    except Exception as exc:
        raise RuntimeError(
            "Could not save Strategy Desk forecast memory. Apply "
            "sql/strategy_desk_memory.sql in Supabase."
        ) from exc


def _format_strategy_desk_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    context = analysis.get("market_context") or {}
    verdict = analysis.get("verdict") or {}
    basket = context.get("commodity_basket") or {}
    brent_price = {
        "symbol": context.get("symbol", "BZ=F"),
        "price": context.get("price"),
        "daily_change_pct": context.get("daily_change_pct"),
        "price_basis": context.get("price_basis"),
        "price_as_of": context.get("price_as_of"),
        "indicators": (basket.get("BZ=F") or {}).get("indicators", {}),
    }
    basket_summary = [
        {
            "symbol": symbol,
            "name": item.get("name"),
            "status": item.get("status"),
            "price": item.get("price"),
            "price_basis": item.get("price_basis"),
            "price_as_of": item.get("price_as_of"),
            "indicators": item.get("indicators", {}),
            **({"error": item["error"]} if item.get("error") else {}),
        }
        for symbol, item in basket.items()
    ]
    headline = (context.get("headlines") or [{}])[0]
    action = {
        "signal": verdict.get("signal"),
        "conviction_pct": verdict.get("conviction"),
        "support": verdict.get("support"),
        "resistance": verdict.get("resistance"),
        "rationale": verdict.get("rationale"),
    }
    basket_prices = [
        f"{item['name']} ${item['price']:.2f}"
        for item in basket_summary
        if item.get("status") == "available" and item.get("price") is not None
    ]
    broadcast_summary = "\n\n".join((
        (
            f"Brent crude ({brent_price['symbol']}) is ${float(context['price']):.2f}, "
            f"{float(context.get('daily_change_pct') or 0):+.2f}% on the session. "
            f"This is a {context.get('price_basis', 'reported')} quote as of "
            f"{context.get('price_as_of') or 'the latest available update'}."
        ),
        (
            "The correlated energy basket reports "
            f"{'; '.join(basket_prices) if basket_prices else 'no current prices available'}. "
            "Technical indicators are calculated from daily OHLCV history; unavailable "
            "values are explicitly omitted."
        ),
        (
            f"Desk signal: {action['signal'] or 'unavailable'} at "
            f"{action['conviction_pct'] if action['conviction_pct'] is not None else 'unavailable'}% "
            f"conviction. {action['rationale'] or 'The desk has no saved rationale.'} "
            "Market data and analysis are informational and not investment advice."
        ),
    ))
    spatial = context.get("spatial_telemetry") or {}
    return {
        **analysis,
        "broadcast_summary": broadcast_summary,
        "broadcast_script": f"60-second broadcast: Brent at ${float(context['price']):.2f}, desk signal {action['signal'] or 'HOLD'}. Spatial congestion index {spatial.get('spatial_congestion_index', 'N/A')}.",
        "thumbnail_prompt": f"High-contrast energy market chart with chokepoint map overlay, {action['signal']} visual motif, spatial index {spatial.get('spatial_congestion_index', 'N/A')}, dark terminal theme.",
        "youtube_metadata": {
            "title": f"Dark Wake Strategy Desk — {action['signal'] or 'HOLD'} | Brent ${float(context['price']):.2f}",
            "description": f"Energy market analysis: Brent ${float(context['price']):.2f}, signal {action['signal']}, spatial congestion {spatial.get('spatial_congestion_index', 'N/A')}, vessel count {spatial.get('estimated_vessel_count', 'N/A')}.",
            "tags": ["Energy Markets", "Brent Crude", "Strategy Desk", "Maritime Supply", "SAM 3.1 Vision", "Spatial Intelligence"],
        },
        "spatial_congestion": {
            "chokepoint": spatial.get("chokepoint") or "Strait of Hormuz",
            "congestion_index": spatial.get("spatial_congestion_index"),
            "estimated_vessel_count": spatial.get("estimated_vessel_count"),
            "mask_reference": spatial.get("mask_reference"),
        },
        "brent_price": brent_price,
        "commodity_basket_summary": basket_summary,
        "desk_action": action,
        "top_headline": {
            "headline": headline.get("title") or "No sanitized energy-market headline available.",
            "category": headline.get("category") or "energy_markets",
        },
        "youtube_tags": [
            "Energy Markets",
            "Brent Crude",
            "Commodity Analysis",
            "Maritime Supply Chains",
            "Global Energy",
        ],
    }


def run_agent_pipeline() -> dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase must be configured to save Strategy Desk analysis history.")

    market_context = _gather_market_context()
    _score_due_predictions(market_context.get("commodity_basket", {}))
    agent_accuracy = _load_agent_accuracy()
    previous_debates = _summarize_previous_debate(_load_previous_debates())
    initial_state: DebateState = {
        "market_context": _inject_spatial_telemetry(market_context, "Strait of Hormuz"),
        "previous_debates": previous_debates,
        "agent_accuracy": agent_accuracy,
        "initial_technical": "",
        "initial_supply_thesis": "",
        "initial_demand_thesis": "",
        "supply_rebuttal_1": "",
        "demand_rebuttal_1": "",
        "supply_rebuttal_2": "",
        "demand_rebuttal_2": "",
        "technical_direction": "NEUTRAL",
        "supply_direction": "NEUTRAL",
        "demand_direction": "NEUTRAL",
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
    result_payload = {
        "id": saved.get("id"),
        "created_at": saved.get("created_at") or datetime.now(timezone.utc).isoformat(),
        **row,
    }
    if result_payload["id"] is None:
        raise RuntimeError("Supabase did not return an ID for the saved Strategy Desk analysis.")
    _record_prediction(
        str(result_payload["id"]),
        context,
        verdict,
        {
            "technical": final_state["technical_direction"],
            "supply": final_state["supply_direction"],
            "demand": final_state["demand_direction"],
        },
    )
    return _format_strategy_desk_payload(result_payload)


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


def _inject_spatial_telemetry(state: dict[str, Any], chokepoint: str = "Strait of Hormuz") -> dict[str, Any]:
    telemetry = get_spatial_telemetry(chokepoint)
    state.setdefault("market_context", {})
    state["market_context"]["spatial_congestion_index"] = telemetry.get("spatial_congestion_index")
    state["market_context"]["spatial_telemetry"] = telemetry
    return state



