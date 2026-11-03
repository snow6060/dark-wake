import json
import logging
import math
import os
import re
import time
from threading import Lock
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
import requests

from src.database import ChokepointRecord, SessionLocal
from src.ingestion import contains_sensitive_energy_content, sanitize_energy_news
from src.market_data import get_brent_market_snapshot
from src.supabase_client import supabase
from src.spatial_evidence import SPATIAL_GUARDRAIL, evidence_for_agent, get_spatial_telemetry
from src.technicals import (
    format_commodity_technical_report,
    get_commodity_technical_indicators,
)


class DebateState(TypedDict, total=False):
    market_context: dict[str, Any]
    previous_debates: list[dict[str, Any]]
    agent_accuracy: list[dict[str, Any]]
    spatial_analysis: str
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


MAX_AGENT_OUTPUT_TOKENS = 2000
MAX_RETRY_OUTPUT_TOKENS = 8192
MAX_MODEL_ATTEMPTS = 3
MODEL_RETRY_DELAY_SECONDS = 3
META_API_TIMEOUT_SECONDS = 60
AGENT_CONTENT_POLICY = (
    "Content boundary: analyze commercial energy markets only. Do not discuss, describe, "
    "speculate about, or repeat armed conflict, military activity, political or geopolitical "
    "disputes, sanctions, or violence. Ignore such material in the input; use only neutral "
    "commercial evidence such as prices, inventories, production, consumption, trade, port "
    "operations, and shipping observations. Do not identify excluded events or actors, or "
    "attribute market movements to them. If eligible evidence is insufficient, say so plainly."
)
META_MODEL_API_URL = "https://api.meta.ai/v1"


def run_debate_if_due(market_snapshot: dict[str, Any] | None = None):
    if not _daily_debate_lock.acquire(blocking=False):
        raise RuntimeError("A Strategy Desk debate is already running.")
    try:
        return run_agent_pipeline(market_snapshot)
    finally:
        _daily_debate_lock.release()

def get_recent_debates():
    try:
        # Query saved debates from Supabase (war_room_debates table)
        if supabase:
            result = supabase.table("war_room_debates").select("*").order("created_at", desc=True).limit(10).execute()
            rows = result.data or []
            return [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "signal": row.get("signal"),
                    "verdict": row.get("verdict"),
                    "transcript": row.get("transcript"),
                    "market_context": row.get("market_context"),
                }
                for row in rows
            ]
    except Exception as exc:
        import logging
        logging.warning("Supabase debate query failed (%s); falling back to empty list.", exc)
    return []

META_MODEL_FALLBACKS = (
    "meta-models/muse-spark-open",
    "muse-spark-1.3",
)


AGENTS = {
    "spatial": {
        "name": "Spatial Intelligence Analyst",
        "system": (
            "You are a maritime spatial-intelligence analyst supporting an oil-market debate. "
            "Use only the supplied Sentinel-2 and AIS-derived evidence. Distinguish measured "
            "observations, plausible implications, and unknowns. Never infer cargo, flag, "
            "destination, vessel intent, or causation from imagery or AIS alone."
        ),
    },
    "technical": {
        "name": "Technical Analysis",
        "system": (
            "You are an evidence-based quantitative analyst focused on Brent crude. Use only "
            "the supplied OHLCV history, commodity basket, timestamps, and technical indicators. "
            "Never invent prices, indicator values, support/resistance, or unavailable data."
        ),
    },
    "supply": {
        "name": "Supply Thesis",
        "system": (
            "You are an evidence-led crude-oil supply analyst. Assess physical availability, "
            "production, exports, inventories, routes, and disruption risk without overstating "
            "what shipping or satellite observations establish."
        ),
    },
    "demand": {
        "name": "Demand Thesis",
        "system": (
            "You are an evidence-led crude-oil demand analyst. Assess consumption, refining, "
            "trade, macroeconomic conditions, and demand-sensitive market evidence. Do not "
            "equate vessel counts or port congestion with end-user demand."
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


class MetaModelEmptyResponseError(RuntimeError):
    """Raised when the API accepts a request but returns no usable text."""

    def __init__(self, detail: str, reason: str | None = None):
        self.reason = reason
        super().__init__(detail)


_daily_debate_lock = Lock()


def _meta_model_api_key() -> str | None:
    return os.getenv("META_MODEL_API_KEY")


def _sanitize_agent_context(value: Any) -> Any:
    if isinstance(value, str):
        if contains_sensitive_energy_content(value):
            return "[Excluded non-commercial context omitted.]"
        return value
    if isinstance(value, dict):
        return {key: _sanitize_agent_context(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_agent_context(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_agent_context(item) for item in value)
    return value


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
    api_key = _meta_model_api_key()
    if not api_key:
        raise RuntimeError(
            "Meta Model API key is missing. Set META_MODEL_API_KEY in the root .env file."
        )

    base_url = os.getenv("META_MODEL_API_BASE_URL", META_MODEL_API_URL).rstrip("/")
    if base_url != META_MODEL_API_URL:
        raise RuntimeError("Strategy Desk agents may only use the Meta AI API.")
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
    output_types = []
    refusals = []
    if not isinstance(output_text, str) or not output_text.strip():
        output_parts = []
        output_items = payload.get("output", []) if isinstance(payload, dict) else []
        if isinstance(output_items, list):
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                output_types.append(str(item.get("type", "unknown")))
                content_items = item.get("content", [])
                if not isinstance(content_items, list):
                    continue
                for content in content_items:
                    if not isinstance(content, dict):
                        continue
                    content_type = content.get("type")
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        if content_type == "refusal":
                            refusals.append(text.strip())
                        else:
                            output_parts.append(text)
        output_text = "".join(output_parts)
    if not isinstance(output_text, str) or not output_text.strip():
        details = []
        if isinstance(payload, dict):
            if payload.get("status"):
                details.append(f"status={payload['status']}")
            incomplete = payload.get("incomplete_details")
            if isinstance(incomplete, dict) and incomplete.get("reason"):
                details.append(f"reason={incomplete['reason']}")
            if payload.get("id"):
                details.append(f"response_id={payload['id']}")
        if refusals:
            refusal = re.sub(r"\s+", " ", refusals[0])[:200]
            details.append(f"refusal={refusal}")
        elif output_types:
            details.append(f"output_types={','.join(output_types[:6])}")
        detail = f" ({'; '.join(details)})" if details else ""
        incomplete = payload.get("incomplete_details") if isinstance(payload, dict) else None
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        raise MetaModelEmptyResponseError(
            f"Meta Model API returned HTTP {response.status_code} without usable output text{detail}.",
            reason=reason,
        )
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
        empty_response = False
        attempt_max_tokens = max_tokens
        for attempt in range(MAX_MODEL_ATTEMPTS):
            try:
                response = _meta_model_interaction(
                    f"{system}\n\n{AGENT_CONTENT_POLICY}",
                    prompt,
                    candidate,
                    attempt_max_tokens,
                )
                if contains_sensitive_energy_content(response):
                    raise RuntimeError(
                        "Strategy Desk agent output violated the commercial-content policy."
                    )
                return response
            except MetaModelEmptyResponseError as exc:
                last_error = exc
                empty_response = True
                if (
                    exc.reason == "max_output_tokens"
                    and attempt + 1 < MAX_MODEL_ATTEMPTS
                    and attempt_max_tokens < MAX_RETRY_OUTPUT_TOKENS
                ):
                    attempt_max_tokens = min(
                        attempt_max_tokens * 2,
                        MAX_RETRY_OUTPUT_TOKENS,
                    )
                    print(
                        f"[Strategy Desk Warning] Meta model {candidate} exhausted its "
                        f"output-token budget; retrying with {attempt_max_tokens} tokens."
                    )
                    continue
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
        if empty_response and model_index + 1 < len(models):
            print(
                f"[Strategy Desk Warning] Meta model {candidate} returned no usable text; "
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
        # Straits.live / Supabase telemetry only — TankerMap fully removed
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


def _gather_market_context(
    supplied_market_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if supplied_market_snapshot and supplied_market_snapshot.get("price") is not None:
        try:
            supplied_price = float(supplied_market_snapshot["price"])
        except (TypeError, ValueError) as exc:
            raise ValueError("The supplied Brent quote must be a positive finite number.") from exc
        if not math.isfinite(supplied_price) or supplied_price <= 0:
            raise ValueError("The supplied Brent quote must be a positive finite number.")
        market_snapshot = {
            "price": supplied_price,
            "change_pct": supplied_market_snapshot.get("change_pct"),
            "market_status": supplied_market_snapshot.get("market_status") or "reported",
            "market_is_closed": bool(supplied_market_snapshot.get("market_is_closed", False)),
            "price_basis": supplied_market_snapshot.get("price_basis") or "reported",
            "price_as_of": supplied_market_snapshot.get("price_as_of"),
            "price_source": "Dashboard Brent quote",
        }
    else:
        market_error_detail = None
        try:
            market_snapshot = get_brent_market_snapshot()
            market_snapshot["price_source"] = "Yahoo Finance"
        except RuntimeError as exc:
            market_error_detail = str(exc)
            market_snapshot = None
    if market_snapshot is None:
        try:
            saved_rows = _fetch_recent_rows(
                "war_room_debates",
                "created_at",
                1,
                "created_at,market_price,market_context",
            )
        except Exception as exc:
            raise RuntimeError(
                f"{market_error_detail} Could not load a previously saved Brent price: {exc}"
            ) from exc
        saved = saved_rows[0] if saved_rows else {}
        try:
            saved_price = float(saved.get("market_price"))
        except (TypeError, ValueError):
            saved_price = float("nan")
        if not math.isfinite(saved_price) or saved_price <= 0:
            raise RuntimeError(
                f"{market_error_detail} No valid previously saved Brent price is available."
            )
        saved_context = saved.get("market_context") or {}
        if isinstance(saved_context, str):
            try:
                saved_context = json.loads(saved_context)
            except json.JSONDecodeError:
                saved_context = {}
        if not isinstance(saved_context, dict):
            saved_context = {}
        market_snapshot = {
            "price": saved_price,
            "change_pct": None,
            "market_status": "stale_cached_close",
            "market_is_closed": False,
            "price_basis": "cached_close",
            "price_as_of": (
                saved_context.get("price_as_of")
                or saved.get("created_at")
            ),
            "price_source": "Previously saved Strategy Desk quote",
            "price_warning": (
                "Yahoo Finance did not provide a fresh Brent quote. This is the latest "
                "previously saved price and may be stale."
            ),
        }
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
        "price_source": market_snapshot.get("price_source"),
        **({"price_warning": market_snapshot["price_warning"]} if market_snapshot.get("price_warning") else {}),
        "commodity_basket": commodity_basket,
        "technical_report": technical_report[:1800],
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


def _context_prompt(state: DebateState, agent_name: str | None = None) -> str:
    context = dict(state["market_context"])
    spatial = context.pop("spatial_telemetry", {}) or {}
    context.pop("spatial_behaviour", None)
    context.pop("spatial_evidence", None)
    context.pop("spatial_congestion_index", None)
    context = _sanitize_agent_context(context)
    prior_summary = _sanitize_agent_context(state.get("previous_debates", []))
    accuracy_summary = _sanitize_agent_context(state.get("agent_accuracy", []))
    if context.get("market_is_closed"):
        instruction = (
            "The Brent market is closed for the weekend. The supplied price is the latest "
            "available daily close, not a live weekend quote. Use its price_as_of timestamp, "
            "do not imply that the price is moving while the market is closed, and frame any "
            "assessment as based on the last close plus available weekend news and data."
        )
    elif context.get("price_basis") == "cached_close":
        instruction = (
            "Yahoo Finance did not provide a fresh Brent quote. The supplied Brent price is "
            "the most recently saved historical price, not a current quote; its saved date is "
            "price_as_of. Clearly disclose this limitation, do not describe the price as current, "
            "and do not make a price-specific claim that depends on live data."
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
            " Compare your current findings with the prior analysis for your role. Identify "
            "what remains supported, what changed, and which new evidence explains the change. "
            "Treat the prior view as a hypothesis, not a fact or an anchor; do not claim a "
            "forecast was correct without the supplied outcome evidence."
        )
    if accuracy_summary:
        instruction += (
            " Review the supplied historical accuracy for your role, if present. Treat it as "
            "calibration feedback, not as a substitute for current evidence."
        )
    prompt_context = {
        "live_context": context,
        "previous_debate_summary": prior_summary,
        "agent_accuracy_history": accuracy_summary,
        "instruction": instruction,
        "analysis_standards": (
            "Separate facts from interpretation; identify timestamps and source/coverage limits; "
            "state the strongest counterargument; do not turn missing data into zero or certainty."
        ),
    }
    if agent_name:
        evidence = spatial.get("spatial_behaviour") or {}
        if not spatial.get("available"):
            message = spatial.get("message") or "Spatial evidence unavailable."
            evidence = {
                "per_zone": [message],
                "global": message,
                "quality": "Spatial data could not be loaded.",
                "singapore": "Singapore: unavailable (spatial evidence could not be loaded).",
            }
        evidence = _sanitize_agent_context(evidence)
        spatial_text = evidence_for_agent(agent_name, evidence)
        if spatial_text:
            prompt_context["spatial_evidence"] = spatial_text
    return json.dumps(prompt_context, ensure_ascii=False, default=str)


def _gather_context_node(state: DebateState) -> dict[str, Any]:
    return {
        "market_context": state.get("market_context") or _gather_market_context(),
        "previous_debates": state.get("previous_debates", []),
        "agent_accuracy": state.get("agent_accuracy", []),
    }


def _spatial_analysis(state: DebateState) -> dict[str, str]:
    prompt = (
        f"{_context_prompt(state, AGENTS['spatial']['name'])}\n\n"
        "Assess every supplied active-zone satellite/AIS summary and the spatial coverage "
        "metadata. Organize the assessment into: (1) observations by zone, including scene age, "
        "cloud/coverage and vessel/AIS-match counts where supplied; (2) plausible implications "
        "for shipping flow, congestion, or supply-route risk; (3) uncertainty, missing/stale "
        "zones, and alternative explanations; and (4) what new evidence would change the view. "
        "Do not infer cargo, destination, intent, or causation. An unmatched hull is "
        "not proof of AIS evasion; alongside pairs are not proof of transfer. This is one "
        "additional input to the market debate, not a replacement for prices, indicators, "
        "telemetry, headlines, or macro/supply/demand evidence. Aim for 300–400 words."
    )
    assessment = _invoke(
        AGENTS["spatial"]["system"],
        prompt,
        _model_for_role("spatial"),
        max_tokens=1600,
    ).strip()
    if not assessment:
        raise RuntimeError("Spatial Intelligence Analyst returned an empty assessment.")
    return {"spatial_analysis": assessment}


def _parse_agent_turn(response: str) -> dict[str, Any]:
    candidate = response.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    result = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            parsed, _ = decoder.raw_decode(candidate, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            result = parsed
            break
    if result is None:
        analysis_match = re.search(
            r'"analysis"\s*:\s*"((?:\\.|[^"\\])*)',
            candidate,
            re.DOTALL,
        )
        if analysis_match:
            encoded_analysis = analysis_match.group(1).rstrip("\\")
            try:
                analysis = json.loads(f'"{encoded_analysis}"')
            except json.JSONDecodeError:
                analysis = (
                    encoded_analysis
                    .replace("\\n", "\n")
                    .replace('\\"', '"')
                    .replace("\\\\", "\\")
                )
            logging.warning("Strategy Desk agent returned truncated JSON; preserving its analysis text.")
        else:
            analysis = candidate
            logging.warning("Strategy Desk agent did not return JSON; preserving its plain-text response.")
    else:
        analysis = str(result.get("analysis", "")).strip()

    if not analysis.strip() and candidate:
        analysis = candidate
        logging.warning("Strategy Desk agent JSON omitted analysis; preserving its response text.")
    if not analysis.strip():
        raise ValueError("Strategy Desk agent returned an empty analysis.")
    direction_match = re.search(
        r'"direction"\s*:\s*"(UP|DOWN|NEUTRAL)"',
        candidate,
        re.IGNORECASE,
    )
    direction = str(
        (result or {}).get("direction")
        or (direction_match.group(1) if direction_match else "NEUTRAL")
    ).upper()
    if direction not in {"UP", "DOWN", "NEUTRAL"}:
        direction = "NEUTRAL"
    try:
        confidence = int((result or {}).get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    if not 0 <= confidence <= 100:
        confidence = 0
    return {
        "analysis": analysis.strip(),
        "direction": direction,
        "confidence": confidence,
    }


def _invoke_agent_turn(system: str, prompt: str, model: str, max_tokens: int) -> dict[str, Any]:
    response = _invoke(system, prompt, model, max_tokens=max_tokens)
    return _parse_agent_turn(response)


_AGENT_RESPONSE_FORMAT = (
    "Return ONLY one valid JSON object with this exact schema: "
    '{"analysis":"reasoned evidence-based analysis","direction":"UP|DOWN|NEUTRAL",'
    '"confidence":0}. The direction is the expected one-day Brent price direction. Use '
    "NEUTRAL when evidence is balanced or insufficient. Confidence must be an integer 0–100 "
    "and reflect evidence quality, not rhetorical certainty. In analysis, distinguish supplied "
    "facts from interpretation, cite relevant supplied source/period or zone, address the "
    "strongest counterargument, and state what remains unknown. Do not invent missing values "
    "or use markdown fences."
)


def _initial_analysis(role: str, state: DebateState) -> dict[str, Any]:
    agent = AGENTS[role]
    role_instructions = {
        "technical": (
            "Write 300–400 words. Analyze the supplied Brent price basis and as-of time, price "
            "trend/momentum, volatility, and the available commodity basket. Evaluate RSI (14), "
            "MACD (12,26,9), ATR (14), EMA (20/50/200), Bollinger bands, stochastic, and VWAP "
            "only where actually supplied. Explain agreement/divergence between indicators and "
            "cross-commodity context; distinguish a short-term one-day direction from the "
            "broader regime. Name unavailable indicators instead of guessing. Do not make up "
            "support/resistance or treat indicators as certainty."
        ),
        "supply": (
            "Write 350–450 words. Build an evidence-led supply thesis from the full supplied "
            "market context: commodity prices/indicators, bottleneck and commercial shipping "
            "telemetry, sanitized headlines, prior debate and accuracy history, plus the "
            "dedicated Spatial Intelligence assessment. The spatial assessment is additional "
            "evidence, not a substitute for these sources. Separate observed facts from "
            "implications. Assess likely transmission to crude availability/pricing, timing, "
            "and whether the evidence is confirmed or only a risk scenario. Address the strongest "
            "counterargument and identify missing evidence. Do not imply that vessel counts "
            "prove supply loss, cargo, or causation."
        ),
        "demand": (
            "Write 350–450 words. Build an evidence-led demand thesis from the full supplied "
            "market context: Brent and correlated commodity prices/indicators, headlines, "
            "bottleneck telemetry, prior debate and accuracy history, and the dedicated Spatial "
            "Intelligence assessment. This spatial input supplements—not replaces—market, "
            "macro, trade, and consumption evidence. Assess what the supplied data actually "
            "indicates about demand, the price response, timing, and uncertainty. Shipping "
            "patterns can inform trade-flow context but do not establish consumption or "
            "end-user demand. Address the strongest counterargument and state which demand "
            "indicators are unavailable rather than inventing them."
        ),
    }[role]
    prompt = (
        f"{_context_prompt(state, agent['name'])}\n\n"
        f"TECHNICAL ANALYSIS:\n{_sanitize_agent_context(state.get('initial_technical', ''))}\n\n"
        f"SUPPLY THESIS:\n{_sanitize_agent_context(state.get('initial_supply_thesis', ''))}\n\n"
        f"DEMAND THESIS:\n{_sanitize_agent_context(state.get('initial_demand_thesis', ''))}\n\n"
        f"SPATIAL INTELLIGENCE ANALYSIS:\n{_sanitize_agent_context(state.get('spatial_analysis', ''))}\n\n"
        "Use the market context and your discipline-specific evidence above as primary inputs; "
        "the spatial assessment is supplementary context, not a replacement.\n"
        f"{role_instructions}\n{_AGENT_RESPONSE_FORMAT}"
    )
    turn = _invoke_agent_turn(agent["system"], prompt, _model_for_role(role), max_tokens=2000)
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
            "Reassess and rebut the demand thesis using the full current market context, relevant "
            "commodity relationships, supply/route/bottleneck evidence, and the Spatial "
            "Intelligence assessment. Identify the opposing thesis's strongest valid point, "
            "then explain where evidence supports or weakens it. Correct any unsupported claim."
        )
    else:
        prior_key = "supply_rebuttal_1" if loop == 1 else "supply_rebuttal_2"
        output_key = f"demand_rebuttal_{loop}"
        instruction = (
            "Reassess and rebut the supply thesis using the full current market context, demand/"
            "macro/headline evidence, and the Spatial Intelligence assessment where relevant. "
            "Identify the opposing thesis's strongest valid point, then explain where evidence "
            "supports or weakens it. Correct any unsupported claim."
        )
    prompt = (
        f"{_context_prompt(state, AGENTS[role]['name'])}\n\n"
        f"TECHNICAL ANALYSIS:\n{_sanitize_agent_context(state['initial_technical'])}\n\n"
        f"PREVIOUS OPPOSING THESIS:\n{_sanitize_agent_context(state[prior_key])}\n\n"
        f"Your prior analysis:\n{_sanitize_agent_context(state['initial_supply_thesis'] if role == 'supply' else state['initial_demand_thesis'])}\n\n"
        f"SPATIAL INTELLIGENCE ANALYSIS:\n{_sanitize_agent_context(state.get('spatial_analysis', ''))}\n\n"
        f"REBUTTAL LOOP {loop}: {instruction} Do not merely repeat your opening thesis. "
        "Write 220–300 words, update your direction/confidence if the evidence warrants it, "
        "and explicitly say when the evidence cannot resolve the disagreement.\n"
        f"{_AGENT_RESPONSE_FORMAT}"
    )
    turn = _invoke_agent_turn(
        AGENTS[role]["system"],
        prompt,
        _model_for_role(role),
        max_tokens=1600,
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
    agent_analyses = {
        key: state.get(key, "")
        for key in (
            "initial_technical",
            "initial_supply_thesis",
            "initial_demand_thesis",
            "supply_rebuttal_1",
            "demand_rebuttal_1",
            "supply_rebuttal_2",
            "demand_rebuttal_2",
        )
    }
    agent_analyses = _sanitize_agent_context(agent_analyses)
    prompt = (
        f"{_context_prompt(state, AGENTS['synthesis']['name'])}\n\n"
        f"SPATIAL INTELLIGENCE ANALYSIS:\n{_sanitize_agent_context(state.get('spatial_analysis', 'Unavailable'))}\n\n"
        f"DEBATE ANALYSES:\n{json.dumps(agent_analyses, ensure_ascii=False)}\n\n"
        "Deliver a risk-managed synthesis for the supplied Brent price and forecast horizon. "
        "Use spatial analysis as an additional input alongside—not instead of—the complete "
        "market context, commodity basket, telemetry, headlines, technical analysis, supply and "
        "demand theses, and both rebuttal rounds. Weigh evidence by recency, reliability, and "
        "directness; reconcile disagreements instead of averaging directions. Explain the "
        "strongest evidence on each side, what would invalidate the conclusion, and how spatial "
        "observations affect (or do not materially affect) the market view. Compare prior "
        "analysis with current evidence without anchoring or claiming success without outcome "
        "data. Avoid false precision. The rationale should be 200–300 words, with concise, "
        "specific risk factors. "
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
            max_tokens=2200,
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
            max_tokens=2200,
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
    workflow.add_node("spatial_analysis", _spatial_analysis)
    workflow.add_node("technical_analysis", lambda state: _initial_analysis("technical", state))
    workflow.add_node("supply_thesis", lambda state: _initial_analysis("supply", state))
    workflow.add_node("demand_thesis", lambda state: _initial_analysis("demand", state))
    workflow.add_node("supply_rebuttal_1", lambda state: _thesis_rebuttal("supply", 1, state))
    workflow.add_node("demand_rebuttal_1", lambda state: _thesis_rebuttal("demand", 1, state))
    workflow.add_node("supply_rebuttal_2", lambda state: _thesis_rebuttal("supply", 2, state))
    workflow.add_node("demand_rebuttal_2", lambda state: _thesis_rebuttal("demand", 2, state))
    workflow.add_node("desk_signal_synthesis", _desk_signal_synthesis)
    workflow.set_entry_point("gather_context")
    workflow.add_edge("gather_context", "spatial_analysis")
    workflow.add_edge("spatial_analysis", "technical_analysis")
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
    transcript = [
        {
            "phase": phase,
            "agent": AGENTS[role]["name"],
            "role": client_roles[role],
            "message": state[state_key],
        }
        for role, phase, state_key in turns
    ]
    if state.get("spatial_analysis"):
        transcript.insert(0, {
            "phase": "spatial-analysis",
            "agent": AGENTS["spatial"]["name"],
            "role": "spatial",
            "message": state["spatial_analysis"],
        })
    return transcript


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
    behaviour = spatial.get("spatial_behaviour") or context.get("spatial_behaviour")
    return {
        **analysis,
        "broadcast_summary": broadcast_summary,
        "broadcast_script": f"60-second broadcast: Brent at ${float(context['price']):.2f}, desk signal {action['signal'] or 'HOLD'}. Spatial evidence: {spatial.get('message') or spatial.get('evidence_text') or 'unavailable'}.",
        "thumbnail_prompt": f"High-contrast energy market chart with chokepoint map overlay, {action['signal']} visual motif, dark terminal theme.",
        "youtube_metadata": {
            "title": f"Dark Wake Strategy Desk — {action['signal'] or 'HOLD'} | Brent ${float(context['price']):.2f}",
            "description": f"Energy market analysis: Brent ${float(context['price']):.2f}, signal {action['signal']}. {spatial.get('evidence_text') or spatial.get('message') or 'Spatial evidence unavailable'}",
            "tags": ["Energy Markets", "Brent Crude", "Strategy Desk", "Maritime Supply", "Spatial Intelligence"],
        },
        "spatial_congestion": None,
        "spatial_behaviour": behaviour,
        "spatial_guardrail": spatial.get("guardrail") or SPATIAL_GUARDRAIL,
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


def run_agent_pipeline(
    supplied_market_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase must be configured to save Strategy Desk analysis history.")

    market_context = _gather_market_context(supplied_market_snapshot)
    _score_due_predictions(market_context.get("commodity_basket", {}))
    agent_accuracy = _load_agent_accuracy()
    previous_debates = _summarize_previous_debate(_load_previous_debates())
    initial_state: DebateState = {
        "market_context": _inject_spatial_telemetry(market_context, "Strait of Hormuz"),
        "previous_debates": previous_debates,
        "agent_accuracy": agent_accuracy,
        "spatial_analysis": "",
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
    state["spatial_congestion_index"] = None
    state["spatial_telemetry"] = telemetry
    state["spatial_behaviour"] = telemetry.get("spatial_behaviour")
    return state
