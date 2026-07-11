"""Advisor v2: owned-state-grounded counsel for the Advisor tab.

Pipeline per consult: character context (trio, level, focus, zone, AA points,
spell slots) + the /outputfile spellbook (what the character actually OWNS)
+ recently-cast spells from the log + compacted EQL-wiki data -> one LLM call
-> strict JSON:
  loadout      what to memorize right now (fills the spell slots, owned only)
  replace      spells in use that a better spell supersedes
  aa_now/save  AA purchase order vs savings goal
  horizon      significant unlocks in the NEXT 2 LEVELS + prep for them
  locations    where to hunt for this level/trio (+ notable paired drops)
  class_notes  weapon-skill / exaltation guidance per class

Fails soft: without the wiki the model grounds in classic-EQ knowledge and
says so; without the LLM a deterministic fallback keeps the tab alive.
Owned AA ranks come from /alternateadv list when available (parser pending
a real log sample); until then the model is told ranks are unknown.
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage

from backend.agent.graph import llm
from backend.game_data import build_wiki_context

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are the advisor inside an EverQuest Legends (EQL) companion app. EQL is a reimagined pre-Kunark EverQuest (launched 2026). Mechanics that matter:
- A character runs THREE classes at once (primary / secondary / tertiary) that level together; cross-class synergy drives every decision.
- Spell slots are scarce: only __SLOTS_NOTE__ spells can be memorized at once.
- AAs are available from level 1 (General / Archetype / Class / Special tabs) and persist across class swaps.

__WIKI_HEADER__
__WIKI__

CHARACTER
__CONTEXT__

Reply with ONLY a JSON object (no markdown fences, no prose) shaped exactly like:
{
  "note": "one short sentence of overall counsel, or null",
  "loadout": [{"name": "...", "cls": "...", "reason": "..."}],
  "replace": [{"using": "...", "upgrade": "...", "why": "..."}],
  "aa_now": [{"name": "...", "cost": 3, "reason": "..."}],
  "aa_save": [{"name": "...", "cost": 12, "reason": "..."}],
  "horizon": [{"level": 33, "cls": "...", "name": "...", "reason": "..."}],
  "locations": [{"zone": "...", "why": "...", "notable": "..."}],
  "class_notes": [{"topic": "...", "advice": "..."}]
}

Rules:
- loadout: EXACTLY the best __SLOTS_NOTE__ picks, most important first, chosen ONLY from the "Spellbook" list below (spells the character owns and can cast right now). Optimize for the current zone and focus; name the job each slot does (nuke, snare, heal-over-time, buff...). Do not waste slots on spells superseded by another owned spell.
- replace: every spell from "Recently cast" that a better OWNED spell supersedes (same line, higher tier), plus any owned spell in the loadout that gets a significant upgrade within the next 2 levels (say the level).
- aa_now: what to buy right now with the available points (use the per-rank costs in the data). Owned AA ranks are __AA_RANKS_NOTE__ — state assumptions briefly.
- aa_save: 1-3 savings goals, especially anything that preps for the horizon items.
- horizon: the significant spells/abilities arriving within the NEXT 2 LEVELS for any of the three classes (exact level from the tables), plus any AA worth buying in advance for them.
- locations: 2-4 hunting spots that fit the level and focus; where you know a notable drop that pairs with this trio, name it in "notable" (else use "").
- class_notes: one entry per class with practical guidance — for melee: which weapon skill to run right now (e.g. fists vs 1H Blunt for a Monk) and exaltations/disciplines if known. Mark uncertainty plainly when the data above does not cover it; never invent numbers.
"""

WIKI_HEADER_PRESENT = ("AUTHORITATIVE EQL WIKI DATA - prefer these exact names, "
                       "levels, and costs over memory:")
WIKI_HEADER_ABSENT = ("No wiki data is available right now. Ground suggestions in "
                      "classic pre-Kunark EverQuest equivalents and briefly mark "
                      "uncertainty inside each reason.")


def _known(v: Any) -> str:
    return str(v) if v is not None else "unknown"


def _build_prompt(ctx: dict, wiki: str) -> str:
    lines = [
        f"- Name: {ctx.get('name') or 'Unknown'} ({ctx.get('race') or 'race unknown'})",
        f"- Classes (primary/secondary/tertiary): {ctx.get('class_str') or 'unknown'}",
        f"- Level: {_known(ctx.get('level'))}",
        f"- Focus / playstyle: {ctx.get('playstyle') or 'balanced'}",
        f"- Current zone: {ctx.get('zone') or 'unknown'}",
        f"- Unspent AA points: {_known(ctx.get('aa_available'))}",
        f"- Recent log activity: {ctx.get('recent_activity') or 'none'}",
    ]
    aas = ctx.get("owned_aas") or {}
    if aas:
        aal = "; ".join(
            f"{n} x{v['ranks']}" + (f" (next rank {v['cost']}pt)" if v.get("cost") else "")
            for n, v in sorted(aas.items()))
        lines.append(f"- Owned AAs (from /alternateadv list, {len(aas)} distinct): {aal}")
    casts = ctx.get("recent_casts") or []
    lines.append("- Recently cast (live log, newest first): "
                 + (", ".join(casts) if casts else "none seen"))
    book = ctx.get("spellbook")
    if book:
        owned = "; ".join(f"{s['name']} (L{s['level']})" for s in book["castable"])
        lines.append(f"- Spellbook (OWNED, castable by this trio; from /outputfile "
                     f"spellbook, {book['age_hours']}h old): {owned}")
        if book["other_loadouts"]:
            lines.append(f"- Also owns {len(book['other_loadouts'])} spells usable "
                         "only by other loadouts (ignore for the loadout).")
    else:
        lines.append("- Spellbook: NO export found — counsel loadout from the wiki "
                     "tables instead and tell the user to type /outputfile "
                     "spellbook in-game for owned-spell grounding.")
    slots = ctx.get("spell_slots")
    aa = ctx.get("aa_available")
    return (ADVISOR_PROMPT
            .replace("__WIKI_HEADER__", WIKI_HEADER_PRESENT if wiki else WIKI_HEADER_ABSENT)
            .replace("__WIKI__", wiki)
            .replace("__CONTEXT__", "\n".join(lines))
            .replace("__SLOTS_NOTE__", str(slots) if slots is not None else "an unknown number of")
            .replace("__AA_RANKS_NOTE__",
                     "listed in the character data — do not recommend re-buying "
                     "maxed ranks" if ctx.get("owned_aas") else
                     "unknown (tell the user to type /alternateadv list in-game "
                     "to sync them)"))


def _extract_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _clean_list(items: Any, keys: tuple, cap: int = 16, require: str = "name") -> List[dict]:
    out: List[dict] = []
    for it in items or []:
        if not (isinstance(it, dict) and it.get(require)):
            continue
        out.append({k: it.get(k) for k in keys})
        if len(out) >= cap:
            break
    return out


def _fallback_body(ctx: dict, reason: str) -> dict:
    from backend.agent.tools import MOCK_AAS
    playstyle = ctx.get("playstyle") or "balanced"
    aas = MOCK_AAS.get(playstyle, MOCK_AAS["balanced"])
    return {
        "note": (f"Live counsel needs the LLM ({reason}). Start LM Studio's server "
                 f"(or set ANTHROPIC_API_KEY) and press Consult again."),
        "loadout": [], "replace": [],
        "aa_now": [{"name": a["name"], "cost": None, "reason": a["desc"]} for a in aas],
        "aa_save": [], "horizon": [], "locations": [], "class_notes": [],
    }


async def generate_advice(ctx: dict) -> dict:
    classes = [c.strip() for c in (ctx.get("class_str") or "").split("/") if c.strip()]
    book = ctx.get("spellbook")
    base = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "context": {
            "classes": ctx.get("class_str"), "level": ctx.get("level"),
            "playstyle": ctx.get("playstyle"), "zone": ctx.get("zone"),
            "aa_available": ctx.get("aa_available"),
            "spell_slots": ctx.get("spell_slots"),
            "spellbook_file": book["file"] if book else None,
            "spellbook_age_hours": book["age_hours"] if book else None,
            "spellbook_count": len(book["castable"]) if book else None,
        },
    }
    wiki = ""
    try:
        # owned-state lines are large; keep the wiki share smaller when present
        wiki = await build_wiki_context(
            classes, ctx.get("level"),
            max_chars=12_000 if ctx.get("spellbook") else 20_000)
    except Exception:
        logger.exception("Wiki context failed; advising ungrounded")
    base["grounding"] = "wiki" if wiki else "memory"

    try:
        bound = llm
        try:
            bound = llm.bind(max_tokens=2000)  # bound the response reservation
        except Exception:
            pass
        try:
            response = await bound.ainvoke(
                [HumanMessage(content=_build_prompt(ctx, wiki))])
        except Exception as first_err:
            # context-window overflows surface as engine 400s — retry once
            # with a reduced wiki share before giving up
            logger.warning("Advisor first attempt failed (%.80s); retrying "
                           "with reduced wiki context", str(first_err))
            response = await bound.ainvoke(
                [HumanMessage(content=_build_prompt(ctx, wiki[:6000]))])
        data = _extract_json(response.content or "")
        if not data:
            raise ValueError("no JSON object in LLM reply")
        return {
            **base, "source": "llm",
            "note": data.get("note"),
            "loadout": _clean_list(data.get("loadout"), ("name", "cls", "reason"), cap=20),
            "replace": _clean_list(data.get("replace"), ("using", "upgrade", "why"),
                                   cap=8, require="using"),
            "aa_now": _clean_list(data.get("aa_now"), ("name", "cost", "reason"), cap=6),
            "aa_save": _clean_list(data.get("aa_save"), ("name", "cost", "reason"), cap=4),
            "horizon": _clean_list(data.get("horizon"), ("level", "cls", "name", "reason"), cap=8),
            "locations": _clean_list(data.get("locations"), ("zone", "why", "notable"),
                                     cap=5, require="zone"),
            "class_notes": _clean_list(data.get("class_notes"), ("topic", "advice"),
                                       cap=6, require="topic"),
        }
    except Exception as e:
        logger.warning("Advisor LLM unavailable, using fallback: %.140s", str(e))
        return {**base, "source": "builtin", **_fallback_body(ctx, str(e)[:80])}
