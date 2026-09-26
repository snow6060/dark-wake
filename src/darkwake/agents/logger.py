# src/darkwake/agents/logger.py
import json
from datetime import datetime
from pathlib import Path
from src.darkwake.agents.schemas import DebateState

LOG_DIR = Path("logs")

def save_debate_audit_log(state: DebateState) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"debate_{timestamp_str}.json"
    
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "brent_price": state.brent_price,
        "price_change_24h": state.price_change_24h,
        "news_headlines": state.news_headlines,
        "chokepoint_data": state.chokepoint_data,
        "agents": {
            "technical": state.technical_output.dict() if state.technical_output else None,
            "bullish": state.bullish_output.dict() if state.bullish_output else None,
            "bearish": state.bearish_output.dict() if state.bearish_output else None,
            "chokepoint": state.chokepoint_output.dict() if state.chokepoint_output else None,
        },
        "risk_verdict": state.risk_verdict.dict() if state.risk_verdict else None,
        "messages": state.messages
    }
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
        
    return str(log_file)