# src/darkwake/agents/graph.py
import os
import time
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from src.darkwake.agents.schemas import DebateState, AgentOutput, RiskVerdictOutput
from src.darkwake.agents.prompts import (
    TECHNICAL_PROMPT, BULLISH_PROMPT, BEARISH_PROMPT, 
    CHOKEPOINT_PROMPT, RISK_MANAGER_PROMPT
)
from src.darkwake.agents.logger import save_debate_audit_log

def get_llm(model: str = "qwen/qwen3.8-flash", api_key: Optional[str] = None):
    active_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not active_key:
        raise ValueError("No OpenRouter API key provided. Please supply one or set OPENROUTER_API_KEY.")
        
    return ChatOpenAI(
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key=active_key,
        temperature=0.2,
        max_tokens=1000
    )

def invoke_with_retry(structured_llm, messages, max_retries=3, delay=2):
    for attempt in range(max_retries):
        try:
            return structured_llm.invoke(messages)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay)

def run_technical_agent(state: DebateState, api_key: Optional[str] = None) -> Dict[str, Any]:
    llm = get_llm("qwen/qwen3.8-flash", api_key=api_key)
    structured_llm = llm.with_structured_output(AgentOutput)
    prompt = f"Current Brent Price: ${state.brent_price}\n24h Change: {state.price_change_24h}%\nRecent News: {state.news_headlines}"
    messages = [SystemMessage(content=TECHNICAL_PROMPT), HumanMessage(content=prompt)]
    output = invoke_with_retry(structured_llm, messages)
    output.agent_name = "Technical Analyst"
    return {"technical_output": output, "messages": state.messages + ["Executed Technical Analyst"]}

def run_bullish_agent(state: DebateState, api_key: Optional[str] = None) -> Dict[str, Any]:
    llm = get_llm("deepseek/deepseek-v4.1-flash", api_key=api_key)
    structured_llm = llm.with_structured_output(AgentOutput)
    prompt = f"Current Brent Price: ${state.brent_price}\nNews Headlines: {state.news_headlines}"
    messages = [SystemMessage(content=BULLISH_PROMPT), HumanMessage(content=prompt)]
    output = invoke_with_retry(structured_llm, messages)
    output.agent_name = "Bullish Analyst"
    return {"bullish_output": output, "messages": state.messages + ["Executed Bullish Analyst"]}

def run_bearish_agent(state: DebateState, api_key: Optional[str] = None) -> Dict[str, Any]:
    llm = get_llm("qwen/qwen3.8-flash", api_key=api_key)
    structured_llm = llm.with_structured_output(AgentOutput)
    prompt = f"Current Brent Price: ${state.brent_price}\nNews Headlines: {state.news_headlines}\nBullish Stance: {state.bullish_output.reasoning if state.bullish_output else 'N/A'}"
    messages = [SystemMessage(content=BEARISH_PROMPT), HumanMessage(content=prompt)]
    output = invoke_with_retry(structured_llm, messages)
    output.agent_name = "Bearish Analyst"
    return {"bearish_output": output, "messages": state.messages + ["Executed Bearish Analyst"]}

def run_chokepoint_agent(state: DebateState, api_key: Optional[str] = None) -> Dict[str, Any]:
    llm = get_llm("deepseek/deepseek-v4.1-flash", api_key=api_key)
    structured_llm = llm.with_structured_output(AgentOutput)
    cp_summary = "\n".join([
        f"- {cp.get('portname')}: {cp.get('n_total')} vessels (Baseline: {cp.get('baseline_mean')}, Deviation: {cp.get('deviation_pct')}%)"
        for cp in state.chokepoint_data
    ]) if state.chokepoint_data else "No recent chokepoint telemetry available."
    
    prompt = f"Latest Chokepoint Transit Data (PortWatch):\n{cp_summary}"
    messages = [SystemMessage(content=CHOKEPOINT_PROMPT), HumanMessage(content=prompt)]
    output = invoke_with_retry(structured_llm, messages)
    output.agent_name = "Chokepoint Analyst"
    return {"chokepoint_output": output, "messages": state.messages + ["Executed Chokepoint Analyst"]}

def run_risk_manager(state: DebateState, api_key: Optional[str] = None) -> Dict[str, Any]:
    llm = get_llm("qwen/qwen3.8-flash", api_key=api_key)
    structured_llm = llm.with_structured_output(RiskVerdictOutput)
    
    debate_summary = f"""
    Technical: {state.technical_output.dict() if state.technical_output else 'N/A'}
    Bullish: {state.bullish_output.dict() if state.bullish_output else 'N/A'}
    Bearish: {state.bearish_output.dict() if state.bearish_output else 'N/A'}
    Chokepoint: {state.chokepoint_output.dict() if state.chokepoint_output else 'N/A'}
    """
    prompt = f"Synthesize the agent debate and provide final risk verdict:\n{debate_summary}"
    messages = [SystemMessage(content=RISK_MANAGER_PROMPT), HumanMessage(content=prompt)]
    output = invoke_with_retry(structured_llm, messages)
    
    state.risk_verdict = output
    state.messages.append("Executed Risk Manager")
    
    save_debate_audit_log(state)
    return {"risk_verdict": output, "messages": state.messages}

def create_debate_graph(api_key: Optional[str] = None):
    workflow = StateGraph(DebateState)
    
    workflow.add_node("technical", lambda s: run_technical_agent(s, api_key))
    workflow.add_node("bullish", lambda s: run_bullish_agent(s, api_key))
    workflow.add_node("bearish", lambda s: run_bearish_agent(s, api_key))
    workflow.add_node("chokepoint", lambda s: run_chokepoint_agent(s, api_key))
    workflow.add_node("risk_manager", lambda s: run_risk_manager(s, api_key))
    
    workflow.set_entry_point("technical")
    workflow.add_edge("technical", "bullish")
    workflow.add_edge("bullish", "bearish")
    workflow.add_edge("bearish", "chokepoint")
    workflow.add_edge("chokepoint", "risk_manager")
    workflow.add_edge("risk_manager", END)
    
    return workflow.compile()