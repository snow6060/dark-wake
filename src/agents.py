import os
import json
from datetime import datetime
from typing import TypedDict, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from src.market_data import get_brent_price, get_oil_news
from src.technicals import get_technical_indicators
from src.database import SessionLocal, ChokepointRecord

class AgentState(TypedDict):
    price: float
    news: list
    technical_report: str
    chokepoint_data: str
    bullish_report: str
    bearish_report: str
    chokepoint_report: str
    risk_verdict: str

def get_llm():
    return ChatOpenAI(
        model="qwen/qwen3.8-flash",
        base_url="https://openrouter.ai/api/v1",
        max_tokens=1200,
        api_key=os.getenv("OPENAI_API_KEY")
    )

def get_deepseek_llm():
    return ChatOpenAI(
        model="deepseek/deepseek-v4.1-flash",
        base_url="https://openrouter.ai/api/v1",
        max_tokens=1200,
        api_key=os.getenv("OPENAI_API_KEY")
    )

def node_gather_context(state: AgentState) -> Dict[str, Any]:
    price = get_brent_price()
    news = get_oil_news()
    tech_data = get_technical_indicators()
    
    db = SessionLocal()
    records = db.query(ChokepointRecord).order_by(ChokepointRecord.date.desc()).limit(5).all()
    choke_summaries = []
    for r in records:
        choke_summaries.append(
            f"- {r.chokepoint_name} ({r.date}): Total Vessels: {r.vessel_count_total}, Tankers: {r.vessel_count_tanker}, Baseline: {r.baseline_avg}, Deviation: {r.deviation_pct:+.1f}%"
        )
    db.close()
    
    chokepoint_text = "\n".join(choke_summaries) if choke_summaries else "No chokepoint telemetry currently available."
    
    llm = get_llm()
    tech_prompt = [
        SystemMessage(content="You are an expert Quantitative Technical Analyst. Focus on price action, volume behavior, MFI, OBV, and liquidity zones."),
        HumanMessage(content=f"Current Price: ${price}\n\nTechnical Data:\n{tech_data}\n\nEvaluate institutional accumulation vs distribution.")
    ]
    tech_res = llm.invoke(tech_prompt).content

    return {
        "price": price,
        "news": news,
        "technical_report": tech_res,
        "chokepoint_data": chokepoint_text
    }

def node_chokepoint_analyst(state: AgentState) -> Dict[str, Any]:
    llm = get_llm()
    prompt = [
        SystemMessage(content="You are a Chokepoint & Geopolitical Supply Risk Analyst. Analyze maritime transit data (Strait of Hormuz, Bab-el-Mandeb) and assess how vessel traffic deviations impact physical crude supply risks."),
        HumanMessage(content=f"Current Brent Price: ${state['price']}\n\nChokepoint Telemetry & Deviations:\n{state['chokepoint_data']}\n\nProvide a concise geopolitical supply risk assessment.")
    ]
    response = llm.invoke(prompt).content
    return {"chokepoint_report": response}

def node_bullish_analyst(state: AgentState) -> Dict[str, Any]:
    llm = get_deepseek_llm()
    news_text = "\n".join([f"- {item['title']}" for item in state['news']])
    prompt = [
        SystemMessage(content="You are an aggressive Bullish Oil Market Analyst. Keep under 250 words."),
        HumanMessage(content=f"Current Price: ${state['price']}\n\nNews:\n{news_text}\n\nTechnicals:\n{state['technical_report']}\n\nChokepoint Assessment:\n{state['chokepoint_report']}\n\nGive your bullish defense.")
    ]
    response = llm.invoke(prompt).content
    return {"bullish_report": response}

def node_bearish_analyst(state: AgentState) -> Dict[str, Any]:
    llm = get_llm()
    news_text = "\n".join([f"- {item['title']}" for item in state['news']])
    prompt = [
        SystemMessage(content="You are a professional Bearish Oil Market Analyst. Keep under 250 words."),
        HumanMessage(content=f"Current Price: ${state['price']}\n\nNews:\n{news_text}\n\nTechnicals:\n{state['technical_report']}\n\nBullish Argument:\n{state['bullish_report']}\n\nProvide bearish rebuttal considering supply trends.")
    ]
    response = llm.invoke(prompt).content
    return {"bearish_report": response}

def node_risk_manager(state: AgentState) -> Dict[str, Any]:
    llm = get_llm()
    prompt = [
        SystemMessage(content="You are the Chief Risk Manager. Synthesize reports into a structured final verdict."),
        HumanMessage(content=f"Price: ${state['price']}\n\nTech:\n{state['technical_report']}\n\nChokepoint Insights:\n{state['chokepoint_report']}\n\nBull:\n{state['bullish_report']}\n\nBear:\n{state['bearish_report']}\n\nProvide structured Final Decision (WAIT/LONG/SHORT), Conviction Level, Core Rationale, and Actionable Risk Parameters (Entry, Stop-Loss, Take-Profit).")
    ]
    response = llm.invoke(prompt).content
    return {"risk_verdict": response}

def compile_trading_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("gather_context", node_gather_context)
    workflow.add_node("chokepoint_analyst", node_chokepoint_analyst)
    workflow.add_node("bullish_analyst", node_bullish_analyst)
    workflow.add_node("bearish_analyst", node_bearish_analyst)
    workflow.add_node("risk_manager", node_risk_manager)
    
    workflow.set_entry_point("gather_context")
    workflow.add_edge("gather_context", "chokepoint_analyst")
    workflow.add_edge("chokepoint_analyst", "bullish_analyst")
    workflow.add_edge("bullish_analyst", "bearish_analyst")
    workflow.add_edge("bearish_analyst", "risk_manager")  # Routes correctly to Risk Manager now
    workflow.add_edge("risk_manager", END)
    
    return workflow.compile()

def run_agent_pipeline() -> Dict[str, Any]:
    app_graph = compile_trading_graph()
    initial_state = {
        "price": 0.0, "news": [], "technical_report": "", 
        "chokepoint_data": "", "bullish_report": "", 
        "bearish_report": "", "chokepoint_report": "", "risk_verdict": ""
    }
    final_state = app_graph.invoke(initial_state)
    
    os.makedirs("logs", exist_ok=True)
    filename = f"logs/trade_log_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(final_state, f, indent=4)
        
    return final_state