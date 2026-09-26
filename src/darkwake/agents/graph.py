"""
src/darkwake/agents/graph.py
----------------------------
LangGraph multi-agent debate: Technical → (Bullish | Bearish | Chokepoint) → Risk Manager

Key design decisions
- StateGraph(DebateState) works because DebateState is a TypedDict, not a
  Pydantic BaseModel.  Pydantic BaseModel causes INVALID_GRAPH_NODE_RETURN_VALUE.
- graph.invoke() must receive a plain dict (or TypedDict). Never pass a
  Pydantic model instance to invoke().
- with_structured_output() is used so LLM responses are parsed into strongly-
  typed Pydantic objects instead of raw strings.
- Supports both plain OpenAI keys (OPENAI_API_KEY) and OpenRouter keys
  (OPENROUTER_API_KEY).  Set OPENAI_API_BASE to override the base URL if needed.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from darkwake.agents.prompts import (
    BEARISH_PROMPT,
    BULLISH_PROMPT,
    CHOKEPOINT_PROMPT,
    RISK_MANAGER_PROMPT,
    TECHNICAL_PROMPT,
)
from darkwake.agents.schemas import AgentOutput, DebateState, RiskVerdictOutput


def create_debate_graph(api_key: Optional[str] = None):
    """
    Build and compile the 5-agent LangGraph debate workflow.

    Priority for API key:
      1. api_key argument (e.g. sent via POST body)
      2. OPENAI_API_KEY env var
      3. OPENROUTER_API_KEY env var (auto-sets base URL to openrouter.ai)
    """
    resolved_key = (
        api_key
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
    )
    if not resolved_key:
        raise ValueError(
            "No LLM API key found. Set OPENAI_API_KEY or OPENROUTER_API_KEY "
            "in your .env file, or pass api_key in the request body."
        )

    # Determine base URL: explicit override → OpenRouter fallback → default OpenAI
    api_base = os.getenv("OPENAI_API_BASE")
    if api_base is None and os.getenv("OPENROUTER_API_KEY"):
        api_base = "https://openrouter.ai/api/v1"

    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

    llm_kwargs: Dict[str, Any] = {
        "model": model_name,
        "openai_api_key": resolved_key,
        "temperature": 0.3,
    }
    if api_base:
        llm_kwargs["openai_api_base"] = api_base

    llm = ChatOpenAI(**llm_kwargs)

    # Separate structured-output chains for agent outputs vs risk verdict
    agent_llm = llm.with_structured_output(AgentOutput)
    risk_llm = llm.with_structured_output(RiskVerdictOutput)

    # ------------------------------------------------------------------
    # Node definitions — each must return a plain dict whose keys are
    # valid DebateState field names.
    # ------------------------------------------------------------------

    def technical_analyst_node(state: DebateState) -> Dict[str, Any]:
        context = (
            f"Brent crude price: ${state['brent_price']:.2f}  "
            f"24h change: {state.get('price_change_24h', 'N/A')}%\n"
            f"News headlines: {state.get('news_headlines', [])}\n"
            f"Chokepoint transit data: {state.get('chokepoint_data', [])}"
        )
        output: AgentOutput = agent_llm.invoke(
            [SystemMessage(content=TECHNICAL_PROMPT), HumanMessage(content=context)]
        )
        # Ensure agent_name is set correctly regardless of what the LLM returns
        output.agent_name = "Technical Analyst"
        return {"technical_output": output}

    def bullish_analyst_node(state: DebateState) -> Dict[str, Any]:
        context = (
            f"Brent crude price: ${state['brent_price']:.2f}\n"
            f"News: {state.get('news_headlines', [])}\n"
            f"Technical analysis: {state.get('technical_output')}"
        )
        output: AgentOutput = agent_llm.invoke(
            [SystemMessage(content=BULLISH_PROMPT), HumanMessage(content=context)]
        )
        output.agent_name = "Bullish Analyst"
        return {"bullish_output": output}

    def bearish_analyst_node(state: DebateState) -> Dict[str, Any]:
        context = (
            f"Brent crude price: ${state['brent_price']:.2f}\n"
            f"News: {state.get('news_headlines', [])}\n"
            f"Technical analysis: {state.get('technical_output')}"
        )
        output: AgentOutput = agent_llm.invoke(
            [SystemMessage(content=BEARISH_PROMPT), HumanMessage(content=context)]
        )
        output.agent_name = "Bearish Analyst"
        return {"bearish_output": output}

    def chokepoint_analyst_node(state: DebateState) -> Dict[str, Any]:
        context = (
            f"Latest chokepoint transit data:\n{state.get('chokepoint_data', [])}\n\n"
            f"Brent price context: ${state['brent_price']:.2f}"
        )
        output: AgentOutput = agent_llm.invoke(
            [SystemMessage(content=CHOKEPOINT_PROMPT), HumanMessage(content=context)]
        )
        output.agent_name = "Chokepoint Analyst"
        return {"chokepoint_output": output}

    def risk_manager_node(state: DebateState) -> Dict[str, Any]:
        tech = state.get("technical_output")
        bull = state.get("bullish_output")
        bear = state.get("bearish_output")
        choke = state.get("chokepoint_output")

        def _fmt(agent: Optional[AgentOutput]) -> str:
            if agent is None:
                return "(no output)"
            return (
                f"[{agent.agent_name}] stance={agent.stance} "
                f"confidence={agent.confidence}\n{agent.reasoning}"
            )

        context = (
            f"=== TECHNICAL ===\n{_fmt(tech)}\n\n"
            f"=== BULLISH ===\n{_fmt(bull)}\n\n"
            f"=== BEARISH ===\n{_fmt(bear)}\n\n"
            f"=== CHOKEPOINT/GEOPOLITICAL ===\n{_fmt(choke)}"
        )
        verdict: RiskVerdictOutput = risk_llm.invoke(
            [SystemMessage(content=RISK_MANAGER_PROMPT), HumanMessage(content=context)]
        )
        return {"risk_verdict": verdict}

    # ------------------------------------------------------------------
    # Graph assembly
    # ------------------------------------------------------------------
    workflow = StateGraph(DebateState)

    workflow.add_node("technical_analyst", technical_analyst_node)
    workflow.add_node("bullish_analyst", bullish_analyst_node)
    workflow.add_node("bearish_analyst", bearish_analyst_node)
    workflow.add_node("chokepoint_analyst", chokepoint_analyst_node)
    workflow.add_node("risk_manager", risk_manager_node)

    # Technical runs first, then bull/bear/chokepoint run in parallel,
    # then risk manager synthesises everything.
    workflow.set_entry_point("technical_analyst")
    workflow.add_edge("technical_analyst", "bullish_analyst")
    workflow.add_edge("technical_analyst", "bearish_analyst")
    workflow.add_edge("technical_analyst", "chokepoint_analyst")
    workflow.add_edge("bullish_analyst", "risk_manager")
    workflow.add_edge("bearish_analyst", "risk_manager")
    workflow.add_edge("chokepoint_analyst", "risk_manager")
    workflow.add_edge("risk_manager", END)

    return workflow.compile()