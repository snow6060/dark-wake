# src/darkwake/agents/schemas.py
"""
Pydantic models for individual agent outputs.
DebateState is a TypedDict (not Pydantic BaseModel) because LangGraph's
StateGraph requires a dict-compatible state type — passing a Pydantic model
instance to graph.invoke() raises INVALID_GRAPH_NODE_RETURN_VALUE.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured outputs — these are Pydantic models so with_structured_output()
# can parse LLM responses into them cleanly.
# ---------------------------------------------------------------------------

class AgentOutput(BaseModel):
    agent_name: str = Field(
        ..., description="Name of the agent, e.g. 'Technical Analyst'"
    )
    stance: str = Field(
        ..., description="One-word stance: Bullish, Bearish, or Neutral"
    )
    reasoning: str = Field(
        ..., description="Full analytical reasoning and narrative"
    )
    key_metrics: Dict[str, str] = Field(
        default_factory=dict,
        description="Key data points or metrics cited in the analysis",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class RiskVerdictOutput(BaseModel):
    summary: str = Field(
        ..., description="Executive summary of the market situation and debate"
    )
    recommended_action: str = Field(
        ..., description="LONG, SHORT, or HOLD"
    )
    risk_score: float = Field(
        ..., ge=0.0, le=10.0, description="Portfolio risk score from 0 to 10"
    )
    key_drivers: List[str] = Field(
        ..., description="Bullet-point drivers for the decision"
    )


# ---------------------------------------------------------------------------
# LangGraph state — must be a TypedDict (or plain dict), NOT a Pydantic model.
# LangGraph merges node return-dicts into this state; Pydantic BaseModel breaks
# that merge and raises INVALID_GRAPH_NODE_RETURN_VALUE.
# ---------------------------------------------------------------------------

class DebateState(TypedDict, total=False):
    # --- inputs ---
    brent_price: float
    price_change_24h: Optional[float]
    news_headlines: List[str]
    chokepoint_data: List[dict]

    # --- agent outputs (populated as the graph runs) ---
    technical_output: Optional[AgentOutput]
    bullish_output: Optional[AgentOutput]
    bearish_output: Optional[AgentOutput]
    chokepoint_output: Optional[AgentOutput]
    risk_verdict: Optional[RiskVerdictOutput]

    # --- audit trail ---
    messages: List[str]