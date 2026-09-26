# src/darkwake/agents/schemas.py
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class AgentOutput(BaseModel):
    agent_name: str = Field(..., description="Name of the agent (e.g., Technical Analyst, Bullish Analyst, Bearish Analyst, Chokepoint Analyst)")
    stance: str = Field(..., description="Short stance summary, e.g., Bullish, Bearish, Neutral")
    reasoning: str = Field(..., description="Detailed analytical reasoning and narrative")
    key_metrics: Dict[str, str] = Field(default_factory=dict, description="Key data points or metrics cited")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0")

class RiskVerdictOutput(BaseModel):
    summary: str = Field(..., description="Executive summary of the market situation and debate")
    recommended_action: str = Field(..., description="Actionable trading/risk recommendation (e.g., LONG, SHORT, HOLD)")
    risk_score: float = Field(..., description="Calculated portfolio risk score from 0 to 10")
    key_drivers: List[str] = Field(..., description="Top bullet points driving the decision")

class DebateState(BaseModel):
    brent_price: float = Field(..., description="Latest Brent crude price")
    price_change_24h: Optional[float] = Field(None, description="24h price change percentage")
    news_headlines: List[str] = Field(default_factory=list, description="Recent relevant oil news headlines")
    chokepoint_data: List[dict] = Field(default_factory=list, description="Latest transit counts and deviations for Hormuz, Bab-el-Mandeb, etc.")
    
    technical_output: Optional[AgentOutput] = None
    bullish_output: Optional[AgentOutput] = None
    bearish_output: Optional[AgentOutput] = None
    chokepoint_output: Optional[AgentOutput] = None
    risk_verdict: Optional[RiskVerdictOutput] = None
    
    messages: List[str] = Field(default_factory=list, description="Audit log trail")