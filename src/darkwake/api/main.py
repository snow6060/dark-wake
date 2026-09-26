# src/darkwake/api/main.py
"""FastAPI app serving stored chokepoint time series and multi-agent debate analytics."""
from __future__ import annotations

import datetime as dt
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from darkwake.config import settings
from darkwake.db import ChokepointTransit, SessionLocal, init_db, get_db
from darkwake.agents.schemas import DebateState
from darkwake.agents.graph import create_debate_graph

app = FastAPI(title="DarkWake Oil Intelligence API", version="0.2.0")


class AnalyzeRequest(BaseModel):
    api_key: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": dt.datetime.utcnow().isoformat()}


@app.get("/chokepoints")
def list_chokepoints() -> dict[str, list[str]]:
    return {"chokepoints": list(settings.chokepoints.keys())}


@app.get("/chokepoints/{chokepoint_key}/timeseries")
def chokepoint_timeseries(
    chokepoint_key: str,
    days: int = Query(90, ge=1, le=3650, description="How many trailing days to return"),
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


@app.post("/api/analyze")
def run_market_analysis(payload: Optional[AnalyzeRequest] = None, db: Session = Depends(get_db)):
    """Triggers the full 5-agent LangGraph debate incorporating latest chokepoint database metrics."""
    runtime_api_key = payload.api_key if payload else None
    
    # Grab the latest record for each chokepoint from SQLite storage
    latest_records = []
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
            latest_records.append({
                "chokepoint_key": rec.chokepoint_key,
                "portname": rec.portname,
                "date": rec.date.isoformat() if rec.date else None,
                "n_total": rec.n_total,
                "baseline_mean": rec.baseline_n_total,
                "deviation_pct": rec.deviation_pct
            })
            
    initial_state = DebateState(
        brent_price=74.50,
        price_change_24h=1.25,
        news_headlines=[
            "OPEC+ signals possible output policy review for next quarter",
            "Tanker traffic through key Middle East chokepoints remains closely watched"
        ],
        chokepoint_data=latest_records
    )
    
    try:
        app_graph = create_debate_graph(api_key=runtime_api_key)
        result_state_dict = app_graph.invoke(initial_state)
        
        if isinstance(result_state_dict, dict):
            return {
                "status": "success",
                "timestamp": dt.datetime.utcnow().isoformat(),
                "brent_price": result_state_dict.get("brent_price"),
                "technical": result_state_dict.get("technical_output"),
                "bullish": result_state_dict.get("bullish_output"),
                "bearish": result_state_dict.get("bearish_output"),
                "chokepoint": result_state_dict.get("chokepoint_output"),
                "risk_verdict": result_state_dict.get("risk_verdict"),
                "audit_trail": result_state_dict.get("messages")
            }
        else:
            return {
                "status": "success",
                "timestamp": dt.datetime.utcnow().isoformat(),
                "result": result_state_dict.dict()
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))