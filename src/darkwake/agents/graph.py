import os
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from darkwake.agents.schemas import DebateState, AgentOutput, RiskVerdictOutput
from darkwake.agents.prompts import (
    TECHNICAL_PROMPT, BULLISH_PROMPT, BEARISH_PROMPT,
    CHOKEPOINT_PROMPT, RISK_MANAGER_PROMPT
)


def create_debate_graph(api_key: Optional[str] = None, **kwargs):
    """Builds and compiles the multi-agent LangGraph workflow."""
    
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")

    # If the user is using OpenRouter, they should set OPENROUTER_API_KEY and potentially OPENAI_API_BASE
    api_base = os.getenv("OPENAI_API_BASE")
    if os.getenv("OPENROUTER_API_KEY") and not api_base:
        api_base = "https://openrouter.ai/api/v1"

    llm_kwargs = {
        "model": os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
        "openai_api_key": resolved_api_key,
        "temperature": 0.3
    }
    if api_base:
        llm_kwargs["openai_api_base"] = api_base
        
    llm = ChatOpenAI(**llm_kwargs)

    workflow = StateGraph(DebateState)

    structured_llm = llm.with_structured_output(AgentOutput)
    risk_llm = llm.with_structured_output(RiskVerdictOutput)

    # Define nodes with proper schema construction and top-level state fields
    def technical_analyst_node(state: DebateState) -> Dict[str, Any]:
        prompt = SystemMessage(content=TECHNICAL_PROMPT)
        context_msg = (
            f"Brent Price: {state.brent_price}, "
            f"24h Change: {state.price_change_24h}, "
            f"News: {state.news_headlines}, "
            f"Chokepoint Data: {state.chokepoint_data}"
        )
        response = structured_llm.invoke([prompt, HumanMessage(content=context_msg)])
        response.agent_name = "Technical Analyst"
        return {"technical_output": response}

    def bullish_analyst_node(state: DebateState) -> Dict[str, Any]:
        prompt = SystemMessage(content=BULLISH_PROMPT)
        context_msg = f"Brent Price: {state.brent_price}, News: {state.news_headlines}"
        response = structured_llm.invoke([prompt, HumanMessage(content=context_msg)])
        response.agent_name = "Bullish Analyst"
        return {"bullish_output": response}

    def bearish_analyst_node(state: DebateState) -> Dict[str, Any]:
        prompt = SystemMessage(content=BEARISH_PROMPT)
        context_msg = f"Brent Price: {state.brent_price}, News: {state.news_headlines}"
        response = structured_llm.invoke([prompt, HumanMessage(content=context_msg)])
        response.agent_name = "Bearish Analyst"
        return {"bearish_output": response}

    def chokepoint_analyst_node(state: DebateState) -> Dict[str, Any]:
        prompt = SystemMessage(content=CHOKEPOINT_PROMPT)
        context_msg = f"Chokepoint Data: {state.chokepoint_data}"
        response = structured_llm.invoke([prompt, HumanMessage(content=context_msg)])
        response.agent_name = "Chokepoint Analyst"
        return {"chokepoint_output": response}

    def risk_manager_node(state: DebateState) -> Dict[str, Any]:
        prompt = SystemMessage(content=RISK_MANAGER_PROMPT)
        tech = state.technical_output.reasoning if state.technical_output else ""
        bull = state.bullish_output.reasoning if state.bullish_output else ""
        bear = state.bearish_output.reasoning if state.bearish_output else ""
        choke = state.chokepoint_output.reasoning if state.chokepoint_output else ""
        
        context_str = f"Technical: {tech}\nBullish: {bull}\nBearish: {bear}\nChokepoint: {choke}"
        response = risk_llm.invoke([prompt, HumanMessage(content=context_str)])
        
        return {"risk_verdict": response}

    # Add nodes to graph
    workflow.add_node("technical_analyst", technical_analyst_node)
    workflow.add_node("bullish_analyst", bullish_analyst_node)
    workflow.add_node("bearish_analyst", bearish_analyst_node)
    workflow.add_node("chokepoint_analyst", chokepoint_analyst_node)
    workflow.add_node("risk_manager", risk_manager_node)

    # Define edges
    workflow.set_entry_point("technical_analyst")
    workflow.add_edge("technical_analyst", "bullish_analyst")
    workflow.add_edge("technical_analyst", "bearish_analyst")
    workflow.add_edge("technical_analyst", "chokepoint_analyst")
    workflow.add_edge("bullish_analyst", "risk_manager")
    workflow.add_edge("bearish_analyst", "risk_manager")
    workflow.add_edge("chokepoint_analyst", "risk_manager")
    workflow.add_edge("risk_manager", END)

    return workflow.compile()