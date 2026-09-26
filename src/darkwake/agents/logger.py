"""
src/darkwake/agents/logger.py
------------------------------
Writes a structured JSON audit log for each completed agent debate run.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from darkwake.agents.schemas import AgentOutput, DebateState, RiskVerdictOutput

LOG_DIR = Path("logs")


def _serialize(value: Any) -> Any:
    """Convert Pydantic models and other non-serializable objects to plain dicts."""
    if value is None:
        return None
    if isinstance(value, (AgentOutput, RiskVerdictOutput)):
        return value.model_dump()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def save_debate_audit_log(state: DebateState) -> Path:
    """
    Persist the completed debate state to a timestamped JSON file under logs/.

    Parameters
    ----------
    state : DebateState (TypedDict)
        The final state dict returned by graph.invoke().

    Returns
    -------
    Path
        Absolute path to the written log file.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filepath = LOG_DIR / f"debate_{timestamp}.json"

    log_payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "brent_price": state.get("brent_price"),
        "price_change_24h": state.get("price_change_24h"),
        "news_headlines": state.get("news_headlines", []),
        "chokepoint_data": state.get("chokepoint_data", []),
        "agents": {
            "technical": _serialize(state.get("technical_output")),
            "bullish": _serialize(state.get("bullish_output")),
            "bearish": _serialize(state.get("bearish_output")),
            "chokepoint": _serialize(state.get("chokepoint_output")),
        },
        "risk_verdict": _serialize(state.get("risk_verdict")),
        "messages": state.get("messages", []),
    }

    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(log_payload, fh, indent=2, default=str)

    return filepath