# src/darkwake/api/main.py
"""FastAPI app — Phase 1 chokepoint time-series + Phase 2 multi-agent debate."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from darkwake.config import settings
from darkwake.db import ChokepointTransit, SessionLocal, get_db, init_db
from darkwake.agents.graph import create_debate_graph
from darkwake.agents.logger import save_debate_audit_log
from darkwake.agents.schemas import AgentOutput, RiskVerdictOutput

app = FastAPI(title="DarkWake Oil Intelligence API", version="0.2.0")


class AnalyzeRequest(BaseModel):
    api_key: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Health / utility
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "timestamp": dt.datetime.utcnow().isoformat()}


@app.get("/chokepoints")
def list_chokepoints() -> dict:
    return {"chokepoints": list(settings.chokepoints.keys())}


# ---------------------------------------------------------------------------
# Phase 1 — time-series data
# ---------------------------------------------------------------------------

@app.get("/chokepoints/{chokepoint_key}/timeseries")
def chokepoint_timeseries(
    chokepoint_key: str,
    days: int = Query(90, ge=1, le=3650, description="Trailing days to return"),
) -> dict:
    if chokepoint_key not in settings.chokepoints:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown chokepoint '{chokepoint_key}'. Known: {list(settings.chokepoints)}",
        )

    cutoff = dt.date.today() - dt.timedelta(days=days)
    with SessionLocal() as session:
        records = (
            session.execute(
                select(ChokepointTransit)
                .where(
                    ChokepointTransit.chokepoint_key == chokepoint_key,
                    ChokepointTransit.date >= cutoff,
                )
                .order_by(ChokepointTransit.date.asc())
            )
            .scalars()
            .all()
        )

    return {
        "chokepoint": chokepoint_key,
        "count": len(records),
        "series": [
            {
                "date": rec.date.isoformat(),
                "portname": rec.portname,
                "n_total": rec.n_total,
                "n_tanker": rec.n_tanker,
                "n_dry_bulk": rec.n_dry_bulk,
                "n_container": rec.n_container,
                "n_general_cargo": rec.n_general_cargo,
                "n_roro": rec.n_roro,
                "capacity_tanker": rec.capacity_tanker,
                "capacity": rec.capacity,
                "baseline_n_total": rec.baseline_n_total,
                "deviation_pct": rec.deviation_pct,
            }
            for rec in records
        ],
    }


# ---------------------------------------------------------------------------
# Phase 2 — multi-agent debate
# ---------------------------------------------------------------------------

def _to_dict(obj) -> Optional[dict]:
    """Safely convert Pydantic model to dict, or return None."""
    if obj is None:
        return None
    if isinstance(obj, (AgentOutput, RiskVerdictOutput)):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return None


@app.post("/api/analyze")
def run_market_analysis(
    payload: Optional[AnalyzeRequest] = None,
    db: Session = Depends(get_db),
) -> dict:
    """
    Run the full 5-agent LangGraph debate (Technical → Bullish/Bearish/Chokepoint
    → Risk Manager) and return structured JSON results.

    Pass your API key in the request body as {"api_key": "sk-..."}, or set
    OPENAI_API_KEY / OPENROUTER_API_KEY in your .env file.
    """
    runtime_api_key = payload.api_key if payload else None

    # --- pull latest chokepoint readings from the DB ---
    latest_records: list[dict] = []
    for cp_key in settings.chokepoints.keys():
        rec = (
            db.execute(
                select(ChokepointTransit)
                .where(ChokepointTransit.chokepoint_key == cp_key)
                .order_by(ChokepointTransit.date.desc())
            )
            .scalars()
            .first()
        )
        if rec:
            latest_records.append(
                {
                    "chokepoint_key": rec.chokepoint_key,
                    "portname": rec.portname,
                    "date": rec.date.isoformat() if rec.date else None,
                    "n_total": rec.n_total,
                    "baseline_mean": rec.baseline_n_total,
                    "deviation_pct": rec.deviation_pct,
                }
            )

    # --- build initial state as a PLAIN DICT (TypedDict) ---
    # IMPORTANT: Do NOT pass a Pydantic BaseModel to graph.invoke().
    # LangGraph requires a plain dict; passing a Pydantic model causes
    # INVALID_GRAPH_NODE_RETURN_VALUE.
    initial_state: dict = {
        "brent_price": 74.50,
        "price_change_24h": 1.25,
        "news_headlines": [
            "OPEC+ signals possible output policy review for next quarter",
            "Tanker traffic through key Middle East chokepoints remains closely watched",
        ],
        "chokepoint_data": latest_records,
        "technical_output": None,
        "bullish_output": None,
        "bearish_output": None,
        "chokepoint_output": None,
        "risk_verdict": None,
        "messages": [],
    }

    try:
        graph = create_debate_graph(api_key=runtime_api_key)

        # invoke() returns a dict — DebateState is a TypedDict, so this is
        # already the right shape.
        result: dict = graph.invoke(initial_state)

        # persist JSON audit log
        save_debate_audit_log(result)

        return {
            "status": "success",
            "timestamp": dt.datetime.utcnow().isoformat(),
            "brent_price": result.get("brent_price"),
            "technical": _to_dict(result.get("technical_output")),
            "bullish": _to_dict(result.get("bullish_output")),
            "bearish": _to_dict(result.get("bearish_output")),
            "chokepoint": _to_dict(result.get("chokepoint_output")),
            "risk_verdict": _to_dict(result.get("risk_verdict")),
            "audit_trail": result.get("messages", []),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc