"""LangGraph agent workflow.

Two nodes: gather (route intent -> tools) and respond (format with LLM,
fall back to deterministic text if the LLM call fails, e.g. no credits).

Nodes return PARTIAL state updates (LangGraph merges them); returning the
full state would duplicate the message list via the add_messages reducer.

Model swapping: `_build_llm()` is the single seam — see CLAUDE.md.
"""
import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph

from backend.agent.state import AgentState
from backend.agent.tools import (
    get_aa_suggestions,
    get_leveling_zone_suggestions,
    get_spell_suggestions,
)
from backend.config import settings

logger = logging.getLogger(__name__)


def _build_llm():
    """Instantiate the chat model per settings. Add providers here."""
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI  # requires langchain-openai
        return ChatOpenAI(model=settings.model)
    if settings.llm_provider == "lmstudio":
        # LM Studio speaks the OpenAI API. Start its local server (Developer
        # tab); enable JIT model loading + idle auto-unload for load-on-demand.
        from langchain_openai import ChatOpenAI  # requires langchain-openai
        return ChatOpenAI(model=settings.model, base_url=settings.lmstudio_base_url,
                          api_key="lm-studio", temperature=0.3)
    if settings.llm_provider == "local":
        from langchain_ollama import ChatOllama  # requires langchain-ollama
        return ChatOllama(model=settings.model)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key or "unset")


llm = _build_llm()


def _content_of(message) -> str:
    if isinstance(message, dict):
        return message.get("content", "")
    if isinstance(message, BaseMessage):
        return message.content or ""
    return str(message)


async def gather(state: AgentState) -> dict:
    """Detect intent from the latest user message and run matching tools."""
    messages = state.get("messages", [])
    if not messages:
        return {}
    user_text = _content_of(messages[-1]).lower()
    profile = state.get("profile", {})

    want_spells = any(w in user_text for w in ("spell", "learn", "cast", "scribe"))
    want_aa = any(w in user_text for w in ("aa", "advancement", "train", "ability point"))
    want_zones = any(w in user_text for w in ("zone", "level", "where", "hunt", "camp", "grind"))
    if not (want_spells or want_aa or want_zones):
        want_spells = want_aa = want_zones = True

    update: dict = {}
    if want_spells:
        update["spell_suggestions"] = await get_spell_suggestions(profile)
    if want_aa:
        update["aa_suggestions"] = await get_aa_suggestions(profile)
    if want_zones:
        update["zone_suggestions"] = await get_leveling_zone_suggestions(profile)
    return update


async def respond(state: AgentState) -> dict:
    """Compose the reply. Try the LLM for prose; fall back to plain formatting."""
    profile = state.get("profile", {})
    spells = state.get("spell_suggestions") or []
    aas = state.get("aa_suggestions") or []
    zones = state.get("zone_suggestions") or []
    current_zone = state.get("current_zone")
    recent = state.get("recent_activity")

    classes = " / ".join(filter(None, [
        profile.get("primary_class"), profile.get("secondary_class"),
        profile.get("tertiary_class")])) or "Unknown classes"
    level = profile.get("level") or "?"

    lines = [f"**{classes}**, level {level}, {profile.get('playstyle', 'balanced')} focus."]
    if current_zone:
        lines.append(f"You're in **{current_zone}** right now.")
    lines.append("")

    if spells:
        lines.append("**Spells to learn:**")
        for s in spells[:5]:
            lines.append(f"- {s['name']} (P{s['priority']}) — {s['reason']}")
        lines.append("")
    if aas:
        lines.append("**AAs to train:**")
        for a in aas[:5]:
            lines.append(f"- {a['name']} (Tier {a['priority']}) — {a['reason']}")
        lines.append("")
    if zones:
        lines.append("**Where to hunt:**")
        for z in zones[:3]:
            lines.append(f"- {z['name']} — {z['reason']}")
        lines.append("")

    fallback_text = "\n".join(lines).strip()
    text = fallback_text

    try:
        context = fallback_text
        if recent:
            context += f"\n\nLive log context: {recent}"
        prompt = (
            "You are an EverQuest Legends companion. Rewrite the following "
            "suggestion data as a concise, friendly answer (max 3 short "
            "paragraphs plus the lists). Keep the lists, sharpen the reasons, "
            "emphasize multiclass synergy, and reference the live log context "
            "if given.\n\n" + context
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        if response.content:
            text = response.content
    except Exception as e:
        logger.warning(f"LLM formatting unavailable, using fallback: {str(e)[:120]}")

    return {"messages": [{"role": "assistant", "content": text}]}


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("gather", gather)
    graph.add_node("respond", respond)
    graph.add_edge("gather", "respond")
    graph.add_edge("respond", END)
    graph.set_entry_point("gather")
    return graph.compile()


_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent_graph()
    return _agent
