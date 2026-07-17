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
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage

from backend.llm_runtime import active as llm_active, get_llm
from backend.config import settings
from backend.game_data import (build_wiki_context, hunting_candidates, is_resurrection,
                               is_travel_ritual, same_spell_line,
                               supersedes_for_slots)

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are the advisor inside an EverQuest Legends (EQL) companion app. EQL is a reimagined pre-Kunark EverQuest (launched 2026). Mechanics that matter:
- A character runs THREE classes at once (primary / secondary / tertiary) that level together; cross-class synergy drives every decision.
- Travel magic (rings, circles, zephyrs, gate, succor/evacuate) is cast via the RITUALS system, outside the spell bar — it never occupies a spell slot. Never put travel spells in the loadout or in replace pairs.
- Reanimation / Reconstitution / Reparation are RESURRECTION spells: they return a DEAD group member to their corpse with experience. They heal nothing and provide zero sustain — never describe them as healing or self-sustain, and never slot them for a solo focus (you cannot cast while dead).
- Spell slots are scarce: only __SLOTS_NOTE__ spells can be memorized at once.
- AAs are available from level 1 (General / Archetype / Class / Special tabs) and persist across class swaps.

__WIKI_HEADER__
__WIKI__

CHARACTER
__CONTEXT__

Reply with ONLY a JSON object (no markdown fences, no prose) shaped exactly like:
{
  "note": "one short sentence of overall counsel, or null",
  "must_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "should_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "nice_to_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "prebuffs": [{"name": "...", "cls": "...", "reason": "..."}],
  "replace": [{"using": "...", "upgrade": "...", "why": "..."}],
  "aa_now": [{"name": "...", "cost": 3, "reason": "..."}],
  "aa_save": [{"name": "...", "cost": 12, "reason": "..."}],
  "horizon": [{"level": 33, "cls": "...", "name": "...", "reason": "..."}],
  "locations": [{"zone": "...", "why": "...", "notable": "..."}],
  "class_notes": [{"topic": "...", "advice": "..."}]
}

Rules:
- The loadout is tiered and must USE ALL __SLOTS_NOTE__ slots. Choose ONLY from the "Spellbook USABLE NOW" list (owned AND at or below the character's level). Name the job each pick does. Never pick a spell superseded by another owned spell.
  - must_have: the core spells that should always be memorized, in priority order (typically 5-7).
  - should_have: fills the REMAINING slots, in priority order — must_have + should_have together must total EXACTLY __SLOTS_NOTE__ picks.
  - nice_to_have: 10-14 EXTRA alternatives beyond the slot count, in priority order, so the player can swap by situation (different zone, tougher pulls, low mana).
- prebuffs: separate from the loadout — list PERMANENT buffs (marked in the character data) FIRST: they persist until death, are cast exactly once, and must never be described as needing refreshing. Then long-duration self-buffs worth keeping up (damage shields like Bramblecoat, AC/HP buffs, Spirit of Wolf). The player memorizes one temporarily, casts it, then swaps the slot back to combat spells — so do NOT waste loadout slots on long buffs; put them here. Owned and level-legal only.
- Summoned-pet lines (skeletons, elementals, warders): only ever slot the HIGHEST-level pet the character owns — older ranks are strictly weaker versions of the same pet.
- Respect the focus STRICTLY: for solo focuses, never slot group-only utility — resurrection and corpse-recovery lines, buffs that can only target others — those are dead slots when playing alone.
- If a "Missing spells they could BUY" list is present, fold the best purchases into note or horizon (say they are vendor purchases).
- replace: ONLY same-spell-line pairs — the upgrade must do the same job with the same primary effect (Symbol of Transal -> Symbol of Ryltan; Minor Healing -> Healing). A teleport, utility, or AA ability is NEVER upgraded by a nuke or an unrelated spell. Cover: recently-cast spells superseded by a better OWNED spell, and owned loadout spells with a significant same-line upgrade within 2 levels (say the level). Omit any pair you are not sure about; every pair is machine-verified and wrong ones are discarded.
- aa_now: what to buy right now with the available points (use the per-rank costs in the data). Owned AA ranks are __AA_RANKS_NOTE__ — state assumptions briefly.
- aa_save: 1-3 savings goals, especially anything that preps for the horizon items.
- horizon: the significant spells/abilities arriving within the NEXT 2 LEVELS for any of the three classes (exact level from the tables), plus any AA worth buying in advance for them.
- locations: 2-4 hunting spots for the level and focus. When a "Hunting grounds" list is present in the character data, choose ONLY zones from that list, using its exact names — never a city, never a zone outside the list (picks outside it are machine-discarded). Prefer spots whose band centers on the level over ones they are outgrowing; where you know a notable drop that pairs with this trio, name it in "notable" (else use "").
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
    inv = ctx.get("inventory_worn")
    if inv:
        lines.append("- Equipped gear (from /outputfile inventory): "
                     + "; ".join(f"{k}: {v}" for k, v in sorted(inv.items())))
    miss = ctx.get("missing_spells")
    if miss:
        lines.append("- Missing spells they could BUY now (from /outputfile "
                     "missingspells): "
                     + ", ".join(f"{s['name']} (L{s['level']})" for s in miss))
    casts = ctx.get("recent_casts") or []
    lines.append("- Recently cast (live log, newest first): "
                 + (", ".join(casts) if casts else "none seen"))
    perm = ctx.get("_permanent") or []
    if perm:
        lines.append("- PERMANENT buffs owned (last until death — cast ONCE "
                     "after login/death, NEVER tell the user to refresh them, "
                     "never spend a combat slot on them): " + ", ".join(perm))
    hunt = ctx.get("_hunting") or []
    if hunt:
        def fmt(c):
            q = c.get("quality")
            tag = {"efficient": "EFFICIENT exp here", "ok": "doable"}.get(q, q)
            return f"{c['zone']} ({c['band']}, {tag})"
        at_lv = [c for c in hunt if c.get("at_level")]
        stretch = [c for c in hunt if not c.get("at_level")]
        txt = "; ".join(fmt(c) for c in at_lv[:20])
        if stretch:
            txt += (" | STRETCH ONLY (content starts above them — pick at most "
                    "one, only if the focus wants a challenge): "
                    + "; ".join(f"{c['zone']} ({c['band']})" for c in stretch[:6]))
        lines.append("- Hunting grounds (community Recommended-Levels table, "
                     "in-era zones only; the community rates per-level "
                     "efficiency — STRONGLY prefer EFFICIENT zones): " + txt)
    book = ctx.get("spellbook")
    if book:
        level = ctx.get("level")
        usable = [s for s in book["castable"]
                  if level is None or s["level"] <= level]
        future = [s for s in book["castable"]
                  if level is not None and s["level"] > level]
        owned = "; ".join(f"{s['name']} (L{s['level']})" for s in usable)
        lines.append(f"- Spellbook USABLE NOW (owned AND at or below their "
                     f"level; from /outputfile spellbook, {book['age_hours']}h "
                     f"old): {owned}")
        if future:
            lines.append("- Owned but ABOVE their level (scribed for later — "
                         "cannot be memorized yet, NEVER put in the loadout): "
                         + ", ".join(f"{s['name']} (L{s['level']})" for s in future))
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


def _lmstudio_budget(prompt_chars: int) -> int:
    """max_tokens that fits the CURRENTLY loaded context window. JIT
    reloads can bring a model back at a small default context; sizing the
    request to reality prevents the engine's cryptic 400 overflow error."""
    if llm_active()["provider"] != "lmstudio":
        return 0  # frontier/other providers: no bind — their defaults are fine
    try:
        import urllib.request
        base = settings.lmstudio_base_url.rsplit("/v1", 1)[0]
        with urllib.request.urlopen(base + "/api/v0/models", timeout=3) as r:
            models = json.loads(r.read()).get("data", [])
        ctx = next((m.get("loaded_context_length") for m in models
                    if m.get("state") == "loaded"
                    and m.get("loaded_context_length")), None)
        if not ctx:
            return 6000
        est_prompt = prompt_chars // 3 + 200  # ~3 chars/token, safety pad
        return max(1200, min(12000, int(ctx) - est_prompt - 256))
    except Exception:
        return 6000


def _extract_json(text: str) -> Optional[dict]:
    # thinking models (qwen3 family) prefix <think> blocks — cut them out so
    # stray braces inside the reasoning can't confuse the JSON scan
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
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
        "loadout": [], "must_have": [], "should_have": [],
        "nice_to_have": [], "prebuffs": [], "replace": [],
        "aa_now": [{"name": a["name"], "cost": None, "reason": a["desc"]} for a in aas],
        "aa_save": [], "horizon": [], "locations": [], "class_notes": [],
    }


# self-buffs that are NOT persistent states: travel (26/83/88/104), item
# summons (32), pets (33/71), feign death (74), resurrection (81)
_NOT_PERM_SPAS = {26, 32, 33, 71, 74, 81, 83, 88, 104}
_SELF_TARGET = 6


def _permanent_buffs(ctx: dict) -> List[str]:
    """Owned usable spells that are permanent-until-death self-buffs:
    self-target + zero duration ticks in the eqlbuilds snapshot (verified:
    Instrument of Nife, Greater Wolf Form, Bramblecoat all match; timed
    buffs like Spirit of Wolf carry real ticks; enemy utility like Stun is
    excluded by target type). Damage shields have negative bases, so no
    positivity requirement."""
    from backend import builds_data
    from backend.game_data import _primary_effect
    level = ctx.get("level")
    out = []
    for s in (ctx.get("spellbook") or {}).get("castable", []):
        if level is not None and s["level"] > level:
            continue
        e = builds_data.spell_entry(s["name"])
        if (not e or (e.get("durationTicks") or 0) != 0
                or e.get("targetTypeId") != _SELF_TARGET):
            continue
        pe = _primary_effect(e)
        if pe and pe[0] not in _NOT_PERM_SPAS:
            out.append(s["name"])
    return out


# gem-order stack for generated spell sets: direct damage, DoTs, AoE up
# front; heals pinned to gem 8+; utility, then summons and pet utility last
_AE_TARGETS = {4, 8}          # point-blank / targeted AE
_PET_TARGET = 14
_GEM_STACK = ("dd", "dot", "aoe", "heal", "utility", "summon", "summon_util")


def _gem_category(name: str) -> str:
    from backend import builds_data
    from backend.game_data import _primary_effect
    e = builds_data.spell_entry(name)
    if not e:
        return "utility"
    pe = _primary_effect(e)
    tgt = e.get("targetTypeId")
    ticks = e.get("durationTicks") or 0
    spa, basev = (pe[0], pe[1] or 0) if pe else (None, 0)
    if spa in (33, 71):
        return "summon"
    if spa == 32 or tgt == _PET_TARGET:
        return "summon_util"
    if tgt in _AE_TARGETS:
        return "aoe"
    if spa == 0 and basev < 0:
        return "dot" if ticks > 0 else "dd"
    if spa == 0 and basev >= 0 and tgt == 51:
        return "heal"
    return "utility"


def stack_gem_order(names: List[str]) -> List[str]:
    """Order picks for the in-game set: DD, DoT, AoE from gem 1; healing
    starting gem 8 where possible; then utility, summons, summon utility."""
    cats = {n: _gem_category(n) for n in names}

    def bucket(*cs):
        return [n for n in names if cats[n] in cs]

    offense = bucket("dd") + bucket("dot") + bucket("aoe")
    heals = bucket("heal")
    tail = bucket("utility") + bucket("summon") + bucket("summon_util")
    slots = offense[:7]
    spill = offense[7:]
    while len(slots) < 7 and heals and tail:
        slots.append(tail.pop(0))  # keep heals at gem 8 when there is filler
    return (slots + heals + spill + tail)[:14]


async def _extra_alternatives(ctx: dict, exclude: set, want: int) -> List[dict]:
    """Deterministic nice-to-have backfill: highest-level owned usable spells
    not already picked — travel/res/superseded-by-owned dropped. Guarantees
    the player has swap options even when the LLM lists few."""
    level = ctx.get("level")
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}
    usable = [s for s in book.get("castable", [])
              if (level is None or s["level"] <= level)
              and s["name"] not in exclude]
    names = [s["name"] for s in usable]
    out = []
    for s in sorted(usable, key=lambda x: -x["level"]):
        if len(out) >= want:
            break
        n = s["name"]
        try:
            if await is_travel_ritual(n) or (solo and await is_resurrection(n)):
                continue
            if any(await supersedes_for_slots(n, o) for o in names if o != n):
                continue
        except Exception:
            continue
        cat, _ = await _spell_cat(n)
        out.append({"name": n, "cls": "", "level": s["level"],
                    "reason": f"owned {cat} alternative (auto-added)"})
    return out


def _gate_locations(locs: List[dict], hunt: List[dict]) -> List[dict]:
    """Keep only picks present in the in-era hunting table (when we have it).
    The table is authoritative for WHERE; the LLM only supplies the why."""
    if not hunt:
        return locs
    def key(s: str) -> str:
        return re.sub(r"^the\s+", "", (s or "").casefold()).strip()
    allowed = {key(c["zone"]): c for c in hunt}
    kept, used, stretch_used = [], set(), 0
    for loc in locs:
        k = key(loc.get("zone"))
        match = allowed.get(k) or next(
            (c for kk, c in allowed.items() if k and (k in kk or kk in k)), None)
        if not match:
            logger.info("Dropped out-of-table location: %s", loc.get("zone"))
            continue
        if not match.get("at_level"):
            if stretch_used:  # at most one above-band pick survives
                logger.info("Dropped extra stretch location: %s", match["zone"])
                continue
            stretch_used += 1
        loc["zone"] = f"{match['zone']} ({match['band']})"
        used.add(match["zone"])
        kept.append(loc)
    for c in hunt:  # backfill with the best at-level zones from the table
        if len(kept) >= 3:
            break
        if c.get("at_level") and c["zone"] not in used:
            kept.append({"zone": f"{c['zone']} ({c['band']})",
                         "why": "In this level band per the community "
                                "Recommended-Levels table.",
                         "notable": ""})
            used.add(c["zone"])
    return kept


# ------------------------------------------------- deterministic (no-LLM)

BUILTIN_NOTE = ("Deterministic counsel — no LLM configured. Picks are "
                "mechanically derived (owned, level-legal, non-superseded, "
                "categorized by spell effect); priorities are heuristic "
                "rather than tactical. Pick a model in the Counsel selector "
                "for reasoned advice.")


async def _spell_cat(name: str) -> tuple:
    """(category, grounded) from the spell's primary effect."""
    from backend.game_data import spell_record, _primary_effect
    try:
        rec = await spell_record(name)
    except Exception:
        rec = None
    if not rec:
        return "other", False
    pe = _primary_effect(rec)
    if not pe:
        return "other", True
    eid, basev = pe[0], (pe[1] or 0)
    if eid == 0:
        if basev > 0:
            return "heal", True
        if basev < 0:
            return "damage", True
        return "other", True  # zero-base rank-1 records: sign unknowable
    if eid == 100:  # heal/damage over time
        return ("heal" if basev >= 0 else "damage"), True
    if eid == 99 or (eid == 3 and basev < 0):
        return "control", True
    if basev > 0:
        return "buff", True
    return "other", True


async def _builtin_counsel(ctx: dict) -> dict:
    level = ctx.get("level")
    slots = ctx.get("spell_slots") or 8
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}
    usable = [s for s in book.get("castable", [])
              if level is None or s["level"] <= level]
    grounded_any = False
    infos = []
    for s in usable:
        name = s["name"]
        try:
            if await is_travel_ritual(name):
                continue
            if solo and await is_resurrection(name):
                continue
        except Exception:
            pass
        cat, grounded = await _spell_cat(name)
        grounded_any = grounded_any or grounded
        infos.append({"name": name, "level": s["level"], "cat": cat})
    names = [i["name"] for i in infos]
    keep, replaced = [], []
    for i in infos:  # drop spells superseded by another owned usable spell
        sup = None
        for other in names:
            if other != i["name"]:
                try:
                    if await supersedes_for_slots(i["name"], other):
                        sup = other
                        break
                except Exception:
                    pass
        if sup:
            replaced.append({"using": i["name"], "upgrade": sup,
                             "note": "owned upgrade in the same spell line"})
        else:
            keep.append(i)
    return await _compose_builtin(ctx, bycat_of(keep), replaced,
                                  grounded_any, level, slots)


def bycat_of(keep: list) -> dict:
    bycat: dict = {}
    for i in sorted(keep, key=lambda x: -x["level"]):
        bycat.setdefault(i["cat"], []).append(i)
    return bycat


async def _compose_builtin(ctx, bycat, replaced, grounded_any,
                           level, slots) -> dict:
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}

    def take(cat, n):
        out = []
        while n > 0 and bycat.get(cat):
            out.append(bycat[cat].pop(0))
            n -= 1
        return out

    def entry(i, why):
        return {"name": i["name"], "cls": "", "reason": why,
                "level": i["level"]}

    must = [entry(i, f"highest-level owned damage spell (L{i['level']})")
            for i in take("damage", 6 if solo else 4)]
    must += [entry(i, f"strongest owned heal (L{i['level']})")
             for i in take("heal", 1)]
    must += [entry(i, f"owned control spell (L{i['level']})")
             for i in take("control", 1)]
    should = []
    for cat, why in (("heal", "backup heal"), ("control", "extra control"),
                     ("damage", "additional damage option"),
                     ("other", "utility")):
        while len(must) + len(should) < slots and bycat.get(cat):
            should.append(entry(bycat[cat].pop(0), why))
    nice = []
    for cat in ("damage", "heal", "control", "other"):
        for i in (bycat.get(cat) or [])[:3]:
            nice.append(entry(i, f"alternative {cat} spell"))
    prebuffs = [entry(i, "positive-effect buff — cast it, then swap the slot "
                         "back to combat spells")
                for i in (bycat.get("buff") or [])[:6]]
    horizon = []
    if level is not None:
        for s in book.get("castable", []):
            if level < s["level"] <= level + 2:
                horizon.append({"level": s["level"], "cls": "",
                                "name": s["name"],
                                "reason": "already scribed — usable on level-up"})
        for s in (ctx.get("missing_spells") or []):
            if level < s["level"] <= level + 2:
                horizon.append({"level": s["level"], "cls": "",
                                "name": s["name"],
                                "reason": "missing — vendor purchase"})
    aas = ctx.get("owned_aas") or {}
    avail = ctx.get("aa_available")
    priced = [(n, v) for n, v in sorted(aas.items()) if v.get("cost")]
    afford = sorted((x for x in priced
                     if avail is None or x[1]["cost"] <= avail),
                    key=lambda x: x[1]["cost"])
    aa_now = [{"name": n, "cost": v["cost"],
               "reason": "cheapest affordable next rank (deterministic mode "
                         "ranks by cost, not synergy)"}
              for n, v in afford[:4]]
    aa_save = [{"name": n, "cost": v["cost"],
                "reason": "highest-cost known rank — long-term goal"}
               for n, v in sorted(priced, key=lambda x: -x[1]["cost"])[:2]]
    locations = [{"zone": f"{c['zone']} ({c['band']})",
                  "why": "In this level band per the community "
                         "Recommended-Levels table.", "notable": ""}
                 for c in (ctx.get("_hunting") or [])
                 if c.get("at_level")][:3]
    return {
        "source": "builtin",
        "grounding": "wiki" if grounded_any else "memory",
        "note": BUILTIN_NOTE,
        "loadout": (must + should)[:slots],
        "must_have": must, "should_have": should,
        "nice_to_have": nice[:12], "prebuffs": prebuffs,
        "replace": replaced[:6],
        "aa_now": aa_now, "aa_save": aa_save,
        "horizon": horizon[:8], "locations": locations,
        "class_notes": [{"topic": "Deterministic mode",
                         "advice": "Slots are filled by effect category and "
                                   "spell level. For synergy-aware tactics, "
                                   "pick an LLM in the Counsel selector."}],
    }


_SLOT_TOKENS = {
    "ear": "EAR", "wrist": "WRIST", "fingers": "FINGER", "range": "RANGE",
    "primary": "PRIMARY", "secondary": "SECONDARY", "head": "HEAD",
    "face": "FACE", "neck": "NECK", "shoulders": "SHOULDERS", "arms": "ARMS",
    "back": "BACK", "hands": "HANDS", "chest": "CHEST", "legs": "LEGS",
    "feet": "FEET", "waist": "WAIST", "ammo": "AMMO",
}


async def _fits_slot(item: str, slot: str) -> bool:
    """Wiki Slot-line check: a Piercing dagger can't be a Range rec. Any
    Slot / Held accept anything; items without slot data pass (the
    unknown-stats guard keeps those honest)."""
    low = slot.lower().strip()
    low = re.sub(r"\s+\d+$", "", low)  # "ear 2" -> "ear"
    token = _SLOT_TOKENS.get(low)
    if token is None:
        return True
    from backend.game_data import item_line
    line = await item_line(item)
    m = re.search(r"Slot: ([A-Z ]+)", line or "")
    if not m:
        return True
    return token in m.group(1).split()


def _item_base(name: str) -> str:
    return re.sub(r"\s*[+]\d+$", "", name or "").strip()


def _item_rank(name: str) -> int:
    m = re.search(r"[+](\d+)$", name or "")
    return int(m.group(1)) if m else 0


async def _builtin_gear(ctx: dict) -> dict:
    """No-LLM gear counsel: rank-upgrade detection is exact (same base item
    at a higher +N owned elsewhere); cross-item comparisons need a model."""
    worn = ctx.get("worn") or {}
    items = ctx.get("inventory_items") or []
    recs = []
    for slot, cur in worn.items():
        cb, cr = _item_base(cur), _item_rank(cur)
        best = None
        for it in items:
            if it.get("where") == "worn":
                continue
            r = _item_rank(it["name"])
            if (_item_base(it["name"]) == cb and r > cr
                    and (best is None or r > _item_rank(best["name"]))):
                best = it
        if best:
            recs.append({"slot": slot, "current": cur,
                         "recommend": best["name"],
                         "why": f"same item at higher rank "
                                f"(+{_item_rank(best['name'])} vs +{cr})",
                         "where": best["where"]})
    exalts = [{"name": x["name"], "move_to": "",
               "why": (f"socketed in {x['host']} ({x['host_loc']})"
                       if x.get("host") else f"loose in the {x['where']}")}
              for x in (ctx.get("exaltations") or [])]
    return {
        "source": "builtin",
        "note": "Deterministic gear check — no LLM. Exact-upgrade detection "
                "only (same item at a higher +N rank in bags or bank); "
                "cross-item stat comparisons and farming targets need a "
                "model from the Counsel selector.",
        "slots": _full_slot_table(recs, worn),
        "farm": [], "exaltations": exalts, "unknown": [], "pet_gear": [],
    }


def _gate_aas(items: List[dict], owned: dict) -> List[dict]:
    """Drop AA recommendations for ranks the character already owns (per
    the /alternateadv list roster) — "Slay Undead rank 5" is noise when
    ranks >= 5 are bought."""
    if not owned:
        return items
    omap = {k.lower(): v for k, v in owned.items()}
    out = []
    for it in items:
        name = str(it.get("name") or "")
        m = re.search(r"^(.*?)[\s(]+ranks?\s*(\d+)\s*[)]?\s*$", name, re.I)
        base = (m.group(1) if m else name).strip().rstrip("(").strip()
        want = int(m.group(2)) if m else None
        o = omap.get(base.lower())
        if o and want is not None and (o.get("ranks") or 0) >= want:
            logger.info("Dropped AA rec — rank already owned: %s", name)
            continue
        out.append(it)
    return out


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
        try:
            ctx["_hunting"] = (await hunting_candidates(int(ctx["level"]))
                               if ctx.get("level") else [])
        except Exception:
            ctx["_hunting"] = []
        ctx["_permanent"] = _permanent_buffs(ctx)
        if llm_active()["provider"] == "none":
            body = await _builtin_counsel(ctx)
            base["grounding"] = body.pop("grounding", "memory")
            return {**base, **body}
        wiki = await build_wiki_context(
            classes, ctx.get("level"),
            max_chars=12_000 if ctx.get("spellbook") else 20_000)
    except Exception:
        logger.exception("Wiki context failed; advising ungrounded")
    base["grounding"] = "wiki" if wiki else "memory"

    try:
        # Thinking models burn a large reasoning budget BEFORE emitting the
        # answer (gemma ~4-5k reasoning tokens here) and it counts against
        # completion tokens — so size everything to the LOADED context.
        prompt = _build_prompt(ctx, wiki)
        budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
        if budget and budget < 3000:
            # context too small for the full prompt + thinking: shrink wiki
            wiki = wiki[:5000]
            prompt = _build_prompt(ctx, wiki)
            budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
        llm = get_llm()
        bound = llm
        if budget:
            try:
                bound = llm.bind(max_tokens=budget)
            except Exception:
                pass
        try:
            response = await bound.ainvoke([HumanMessage(content=prompt)])
        except Exception as first_err:
            # whatever slipped through: retry once, half the prompt + budget
            logger.warning("Advisor first attempt failed (%.80s); retrying "
                           "smaller", str(first_err))
            prompt = _build_prompt(ctx, wiki[:4000])
            if budget:
                try:
                    bound = llm.bind(max_tokens=max(1200, budget // 2))
                except Exception:
                    pass
            response = await bound.ainvoke([HumanMessage(content=prompt)])
        data = _extract_json(response.content or "")
        if not data:
            raise ValueError("no JSON object in LLM reply")
        solo = (ctx.get("playstyle") or "").startswith("solo")
        usable = ([s["name"] for s in book["castable"]
                   if s["level"] <= ctx["level"]]
                  if (book and ctx.get("level") is not None) else [])
        allowed = {n.lower() for n in usable} if usable else None

        async def _gate_picks(picks, label):
            """Owned + level-legal, not a travel ritual, and not superseded
            by another owned usable spell. Spell records are cached, so the
            pairwise scan is only slow on the first consult of the day."""
            out = []
            for s in picks:
                name = s["name"]
                if allowed is not None and name.lower() not in allowed:
                    logger.info("Dropped over-level/unowned %s pick: %s",
                                label, name)
                    continue
                try:
                    if await is_travel_ritual(name):
                        logger.info("Dropped travel ritual from %s: %s",
                                    label, name)
                        continue
                except Exception:
                    pass
                if solo:
                    try:
                        if await is_resurrection(name):
                            logger.info("Dropped resurrection spell from solo "
                                        "%s: %s", label, name)
                            continue
                    except Exception:
                        pass
                superseded = None
                for other in usable:
                    if other.lower() == name.lower():
                        continue
                    try:
                        if await supersedes_for_slots(name, other):
                            superseded = other
                            break
                    except Exception:
                        continue
                if superseded:
                    logger.info("Dropped %s pick %s — superseded by owned %s",
                                label, name, superseded)
                    continue
                out.append(s)
            return out

        must_have = await _gate_picks(
            _clean_list(data.get("must_have"), ("name", "cls", "reason"), cap=10),
            "must_have")
        should_have = await _gate_picks(
            _clean_list(data.get("should_have"), ("name", "cls", "reason"), cap=14),
            "should_have")
        nice_to_have = await _gate_picks(
            _clean_list(data.get("nice_to_have"), ("name", "cls", "reason"), cap=16),
            "nice_to_have")
        # auto-promote: gates may have removed picks — refill the slots from
        # the nice-to-have alternatives (they passed the same gates)
        slots_n = ctx.get("spell_slots")
        if slots_n:
            while len(must_have) + len(should_have) < slots_n and nice_to_have:
                promoted = nice_to_have.pop(0)
                promoted = {**promoted,
                            "reason": "(promoted alternative) " + str(promoted.get("reason", ""))}
                should_have.append(promoted)
        # annotate every pick with its spellbook level (deterministic)
        level_by_name = {s["name"].lower(): s["level"]
                         for s in (book["castable"] if book else [])}
        for lst in (must_have, should_have, nice_to_have):
            for s in lst:
                s["level"] = level_by_name.get(str(s["name"]).lower())
        loadout = must_have + should_have  # combined = the actual slot fill
        prebuffs = await _gate_picks(
            _clean_list(data.get("prebuffs"), ("name", "cls", "reason"), cap=8),
            "prebuffs")
        for s in prebuffs:
            s["level"] = level_by_name.get(str(s["name"]).lower())
        replace = _clean_list(data.get("replace"), ("using", "upgrade", "why"),
                              cap=8, require="using")
        verified = []
        for p in replace:
            try:
                if (p.get("upgrade")
                        and not await is_travel_ritual(p["using"])
                        and not await is_travel_ritual(p["upgrade"])
                        and await same_spell_line(p["using"], p["upgrade"])):
                    verified.append(p)
                else:
                    logger.info("Dropped unverified replace pair: %s -> %s",
                                p.get("using"), p.get("upgrade"))
            except Exception:
                pass  # verification unavailable — drop rather than mislead
        if len(nice_to_have) < 12:
            picked = {p.get("name") for p in
                      must_have + should_have + nice_to_have + prebuffs}
            nice_to_have = nice_to_have + await _extra_alternatives(
                ctx, picked, 12 - len(nice_to_have))
        return {
            **base, "source": "llm",
            "note": data.get("note"),
            "loadout": loadout,
            "must_have": must_have,
            "should_have": should_have,
            "nice_to_have": nice_to_have,
            "prebuffs": prebuffs,
            "replace": verified,
            "aa_now": _gate_aas(
                _clean_list(data.get("aa_now"), ("name", "cost", "reason"), cap=6),
                ctx.get("owned_aas") or {}),
            "aa_save": _gate_aas(
                _clean_list(data.get("aa_save"), ("name", "cost", "reason"), cap=4),
                ctx.get("owned_aas") or {}),
            "horizon": _clean_list(data.get("horizon"), ("level", "cls", "name", "reason"), cap=8),
            "locations": _gate_locations(
                _clean_list(data.get("locations"), ("zone", "why", "notable"),
                            cap=5, require="zone"),
                ctx.get("_hunting") or []),
            "class_notes": _clean_list(data.get("class_notes"), ("topic", "advice"),
                                       cap=6, require="topic"),
        }
    except Exception as e:
        logger.warning("Advisor LLM unavailable, using fallback: %.140s", str(e))
        try:
            body = await _builtin_counsel(ctx)
            base["grounding"] = body.pop("grounding", "memory")
            body["note"] = (f"LLM unavailable ({str(e)[:60]}) — showing "
                            "deterministic counsel instead. " + BUILTIN_NOTE)
            return {**base, **body}
        except Exception:
            return {**base, "source": "builtin", **_fallback_body(ctx, str(e)[:80])}


# --------------------------------------------------------------------- gear

GEAR_PROMPT = """You are the equipment advisor inside an EverQuest Legends companion app. EQL is a reimagined pre-Kunark EverQuest. A character runs THREE classes, and gear is equippable when ANY ONE of those classes can use it — one match is enough, it stays equipped across class swaps. Each item below is pre-marked [USABLE] or [NOT USABLE by this trio]; NEVER re-derive class eligibility yourself and NEVER reject a [USABLE] item because some of the trio cannot use it.
Recommend a TWO-HANDER for Primary ONLY when it beats the current primary AND secondary COMBINED — the off-hand goes empty — and say that comparison in the why.
CRITICAL — upgrade ranks: the stats listed are the BASE (+0) values. EQL's +N upgrade system boosts stats enormously (a +2 helm can have 3-4x the base AC and large HP/resists the base lacks). When a worn item has a higher +N than a challenger, assume its real stats are far above the listing. Items marked STATS UNKNOWN have no data at all — NEVER invent their stats and NEVER recommend replacing them (you cannot make an honest comparison).

Paired slots: "Ear 1"/"Ear 2", "Wrist 1"/"Wrist 2", "Fingers 1"/"Fingers 2", "Any Slot 1"/"Any Slot 2" hold TWO independent items each — treat each numbered slot separately and remember both currently-worn items of a pair are listed. The two "Any Slot"s are EQL's generic slots: ANY equippable item can sit there (weapons included) and its stats apply, so recommend the best owned items that don't fit elsewhere; also consider "Ammo" and "Held" if something owned is worth parking there.

CHARACTER
__CONTEXT__

OWNED EQUIPMENT (from /outputfile inventory; [worn/bags/bank] shows where each lives; stats and drop sources are from the game's wiki):
__GEAR__

EXALTATIONS (socketable effect-stones extracted from items; they grant the named item's effect and CAN BE MOVED between gear sockets). Sockets are TYPED — focus / clicky / worn / proc (per eqlegendstools.com) — and a stone only fits a socket of its effect's type. Proc stones fit WEAPON sockets only (Primary/Secondary/Range). Each stone below carries its inferred type; recommend moves only between same-type sockets, and where a stone's type reads "unknown", say so instead of guessing:
__EXALTS__

__PET_BLOCK__

Reply with ONLY a JSON object (no fences, no prose):
{
  "note": "one-sentence overall read of their gearing, or null",
  "slots": [{"slot": "Chest", "current": "...", "recommend": "...", "why": "..."}],
  "farm": [{"item": "...", "slot": "...", "zone": "...", "source": "...", "why": "..."}],
  "exaltations": [{"name": "...", "move_to": "...", "why": "..."}],
  "pet_gear": [{"item": "...", "slot": "...", "why": "..."}]
}

Rules:
- slots: go slot by slot; only include a slot when there is something to say — a better OWNED item sitting in bags/bank than what is worn ("recommend" = that owned item, exactly as named above), an empty slot they own a filler for, or a confirmation that the worn item is their best ("recommend" = the worn item). Recommend only [USABLE] items; the tag is authoritative. Race restrictions DO NOT EXIST in EQL. Anything marked [worn] is being worn RIGHT NOW and is proven equippable — never claim a worn item is unusable.
- Hands: a weapon with a 2H skill (2H Slash/2H Blunt/2H Piercing) occupies BOTH Primary and Secondary. Never recommend a 2H weapon together with any Secondary item; compare 1H+1H (or 1H+shield) as a package against the 2H alone.
- farm: 3-6 realistic upgrade targets for their level. STRONGLY prefer items whose drop data appears above or that you know drop in zones near their level; give the zone and the mob/vendor in "source". Never invent stats; mark uncertainty briefly in "why" when relying on memory.
- Weapons: consider the classes' usable weapon skills; for a Monk trio prefer fist/blunt options.
- exaltations: review where each exaltation is socketed vs what it grants. Recommend moves ONLY when clearly better (an unused bank exaltation with a strong effect, or an effect wasted on unused gear); "move_to" = the item to socket it into. Skip trivial shuffles; note uncertainty about socket compatibility.
"""


def _exalt_socket_type(effect: Optional[str]) -> str:
    """focus / clicky / worn / proc from the wiki Effect line's wording.
    Socket taxonomy per eqlegendstools.com."""
    if not effect:
        return "unknown"
    low = effect.lower()
    if "combat" in low or "proc" in low:
        return "proc"
    if "worn" in low:
        return "worn"
    if "focus" in low:
        return "focus"
    if "casting time" in low or "must equip" in low or "any slot" in low             or "triggered" in low:
        return "clicky"
    return "unknown"


async def _exalt_effect(base_item: str) -> Optional[str]:
    """The effect line an exaltation grants = its base item's Effect."""
    from backend.game_data import item_line
    line = await item_line(base_item)
    if not line:
        return None
    m = re.search(r"Effect: [^;|]+", line)
    return m.group(0) if m else "no listed effect (stat stone?)"


# every equippable slot in the EQL inventory export — the gear table always
# shows all 24, backfilling slots the LLM didn't address. "Any Slot" x2 are
# EQL's generic slots (hold any equippable item); no Charm/Power Source here.
CANON_SLOTS = [
    "Any Slot 1", "Any Slot 2", "Ear 1", "Ear 2", "Head", "Face", "Neck",
    "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Range", "Hands",
    "Primary", "Secondary", "Fingers 1", "Fingers 2", "Chest", "Legs",
    "Feet", "Waist", "Ammo", "Held",
]


def _full_slot_table(slots: List[dict], worn: Optional[dict]) -> List[dict]:
    """Merge LLM recommendations onto the fixed 23-slot roster: unaddressed
    slots keep the worn item, empty slots say so. Non-canonical slot names
    from the LLM are appended rather than lost."""
    def norm(s):
        return "".join(ch for ch in (s or "").casefold() if ch.isalnum())
    by = {}
    for s in slots:
        by.setdefault(norm(s.get("slot")), s)
    # a bare pair name ("Ear") from the LLM lands on the pair's first slot
    out = []
    for slot in CANON_SLOTS:
        cur = (worn or {}).get(slot)
        s = by.pop(norm(slot), None)
        if s is None and slot.endswith(" 1"):
            s = by.pop(norm(slot[:-2]), None)
        if s:
            s["slot"] = slot
            if not s.get("current") and cur:
                s["current"] = cur
            out.append(s)
        else:
            out.append({"slot": slot, "current": cur or "",
                        "recommend": cur or None,
                        "why": "keep — no better owned option flagged"
                               if cur else "empty — nothing owned equips here",
                        "where": "worn" if cur else None})
    out.extend(by.values())
    return out


def _gate_exalt_moves(recs: List[dict], unusable: set,
                      owned_exalts: List[dict]) -> List[dict]:
    """Drop moves for trio-unusable stones AND moves to the stone's CURRENT
    host — the inventory export already says where every stone sits."""
    host_of = {}
    for x in owned_exalts or []:
        hb = _item_base(x.get("host") or "").lower()
        for key in (x["name"].lower(),
                    re.sub(r"\s*[(]exaltation[)]$", "", x["name"].lower()).strip()):
            host_of[key] = hb
    out = []
    for r in recs:
        low = r["name"].lower()
        if low in unusable or f"{low} (exaltation)" in unusable:
            continue
        cur = host_of.get(low) or host_of.get(f"{low} (exaltation)")
        if cur and r.get("move_to") and _item_base(r["move_to"]).lower() == cur:
            logger.info("Dropped exaltation rec — %s is already socketed "
                        "in %s", r["name"], r["move_to"])
            continue
        out.append(r)
    return out


async def generate_gear_advice(ctx: dict) -> dict:
    from backend.game_data import build_gear_context

    items = ctx.get("inventory_items") or []
    base = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "context": {"classes": ctx.get("class_str"), "level": ctx.get("level"),
                    "race": ctx.get("race"),
                    "items": len(items)},
    }
    if not items:
        return {**base, "source": "builtin", "note":
                "No inventory export found — type /outputfile inventory "
                "in-game, then press check exports.",
                "slots": [], "farm": [], "exaltations": [], "pet_gear": [], "unknown": []}
    if llm_active()["provider"] == "none":
        return {**base, **(await _builtin_gear(ctx))}
    classes = [x.strip() for x in (ctx.get("class_str") or "").split("/")
               if x.strip()]
    gear = await build_gear_context(items, classes)
    exalts = ctx.get("exaltations") or []
    exalt_lines = []
    unusable_exalts = set()
    from backend.game_data import _trio_usable, item_line as _gd_item_line
    for x in exalts:
        bname = re.sub(r"\s*[(]Exaltation[)]$", "", x["name"]).strip()
        eff = None
        usable = None
        try:
            full_line = await _gd_item_line(bname)
            if full_line:
                m2 = re.search(r"Effect: [^;|]+", full_line)
                eff = m2.group(0) if m2 else "no listed effect (stat stone?)"
                usable = _trio_usable(full_line, classes)
        except Exception:
            pass
        host = (f"socketed in {x['host']} ({x['host_loc']})" if x.get("host")
                else f"loose in the {x['where']}")
        styp = _exalt_socket_type(eff)
        fits = ("weapon sockets only (Primary/Secondary/Range)"
                if styp == "proc" else f"{styp} sockets"
                if styp != "unknown" else "unknown socket type")
        if usable is False:
            # the stone keeps its base item's class restriction — no one in
            # this trio can use its effect at all
            unusable_exalts.add(x["name"].lower())
            cls_tag = " — [NOT USABLE by this trio: base item's class list excludes all three — bank fodder, never recommend moving it]"
        else:
            cls_tag = ""
        exalt_lines.append(f"{x['name']} — {host}"
                           + (f" — grants {eff}" if eff else "")
                           + f" — type: {styp} (fits {fits}){cls_tag}")
    base["context"]["with_stats"] = len(gear["lines"])
    base["context"]["unknown"] = len(gear["unknown"])

    lines = [
        f"- Classes: {ctx.get('class_str') or 'unknown'}",
        f"- Level: {ctx.get('level') or 'unknown'}",
        f"- Race: {ctx.get('race') or 'unknown'}",
        f"- Focus: {ctx.get('playstyle') or 'balanced'}",
        f"- Currently worn: "
        + "; ".join(f"{k}: {v}" for k, v in sorted((ctx.get('worn') or {}).items())),
    ]
    pet_slots = ctx.get("pet_slots") or 0
    if pet_slots > 0:
        pet_block = (
            f"PET LOADOUT: the pet has {pet_slots} equipment slots. Pets "
            "equip items HANDED to them — weapons boost their damage (procs "
            "work), armor their AC — and handed items are DESTROYED when "
            "the pet dies or is re-summoned. From bags/bank ONLY (never "
            "worn gear, never exaltation hosts), pick up to "
            f"{pet_slots} items for the pet in 'pet_gear': at least one "
            "weapon, then the best remaining armor. THE PLAYER ALWAYS HAS "
            "STAT PRIORITY: never assign the pet an item that would beat "
            "something the player wears in a comparable slot — the pet gets "
            "the leftovers after every player upgrade is settled.")
    else:
        pet_block = ("PET LOADOUT: none — pet_gear must be []. (The player "
                     "sets their pet's slot count in the Advisor tab when "
                     "they run a pet.)")
    prompt = (GEAR_PROMPT
              .replace("__PET_BLOCK__", pet_block)
              .replace("__CONTEXT__", chr(10).join(lines))
              .replace("__GEAR__", chr(10).join(gear["lines"]))
              .replace("__EXALTS__", chr(10).join(exalt_lines) or "none owned"))
    budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
    llm = get_llm()
    bound = llm
    if budget:
        try:
            bound = llm.bind(max_tokens=budget)
        except Exception:
            pass
    try:
        response = await bound.ainvoke([HumanMessage(content=prompt)])
        data = _extract_json(response.content or "")
        if not data:
            raise ValueError("no JSON object in LLM reply")
    except Exception as e:
        logger.warning("Gear advisor failed: %.140s", str(e))
        try:
            body = await _builtin_gear(ctx)
            body["note"] = (f"LLM unavailable ({str(e)[:60]}) — showing the "
                            "deterministic gear check instead. " + body["note"])
            return {**base, **body}
        except Exception:
            pass
        return {**base, "source": "builtin",
                "note": f"Live gear counsel needs the LLM ({str(e)[:60]}).",
                "slots": [], "farm": [], "exaltations": [], "pet_gear": [],
                "unknown": gear["unknown"][:10]}

    from backend.game_data import item_line as _item_line
    owned = {s["name"].lower() for s in items}
    owned_base = {re.sub(r"\s*[+]\d+$", "", n) for n in owned}
    where_by_base: dict = {}
    for it in items:
        b = re.sub(r"\s*[+]\d+$", "", it["name"].lower())
        where_by_base.setdefault(b, set()).add(it["where"])
    slots = []
    for s in _clean_list(data.get("slots"), ("slot", "current", "recommend", "why"),
                         cap=20, require="slot"):
        rec = str(s.get("recommend") or "").lower()
        rec_base = re.sub(r"\s*[+]\d+$", "", rec)
        cur = str(s.get("current") or "").lower()
        cur_base = re.sub(r"\s*[+]\d+$", "", cur)

        def _rank(n):
            m = re.search(r"[+](\d+)$", n)
            return int(m.group(1)) if m else 0

        unknown_bases = {re.sub(r"\s*[+]\d+$", "", u.lower())
                         for u in gear["unknown"]}
        if (cur_base and cur_base in unknown_bases and rec_base != cur_base):
            logger.info("Dropped %s rec — current item '%s' has no stat data "
                        "to compare against", s.get("slot"), s.get("current"))
            continue
        if rec_base == cur_base and rec != cur and _rank(rec) <= _rank(cur):
            logger.info("Dropped %s rec — same item at equal/lower rank", s.get("slot"))
            continue
        if rec and not await _fits_slot(rec, str(s.get("slot") or "")):
            logger.info("Dropped %s rec — %s does not fit that slot",
                        s.get("slot"), rec)
            continue
        if rec and (rec in owned or rec_base in owned_base):
            wset = where_by_base.get(rec_base, set())
            s["where"] = ("bags" if "bags" in wset else
                          "bank" if "bank" in wset else
                          "worn" if "worn" in wset else None)
            slots.append(s)
        else:
            logger.info("Dropped gear recommendation not in inventory: %s",
                        s.get("recommend"))
    # hands consistency: a 2H primary recommendation empties the secondary
    primary = next((s for s in slots
                    if str(s.get("slot", "")).lower() == "primary"
                    and s.get("recommend")), None)
    if primary:
        try:
            line = await _item_line(primary["recommend"])
        except Exception:
            line = None
        if line and "Skill: 2H" in line:
            before = len(slots)
            slots = [s for s in slots
                     if str(s.get("slot", "")).lower() != "secondary"]
            if len(slots) != before:
                logger.info("Dropped secondary slot rec — 2H primary "
                            "recommendation occupies both hands")
    pet_gear = []
    exalt_hosts = {(x.get("host") or "").lower()
                   for x in (ctx.get("exaltations") or [])}
    owned_locs = {}
    for it in items:
        owned_locs.setdefault(it["name"].lower(), it.get("where"))
    for ph in _clean_list(data.get("pet_gear"), ("item", "slot", "why"),
                          cap=max(0, int(ctx.get("pet_slots") or 0)),
                          require="item"):
        low = ph["item"].lower()
        where = owned_locs.get(low)
        if where in ("bags", "bank") and low not in exalt_hosts:
            ph["where"] = where
            pet_gear.append(ph)
        else:
            logger.info("Dropped pet-gear rec: %s (%s)", ph["item"], where)
    table = _full_slot_table(slots, ctx.get("worn"))
    prim = next((r for r in table if r["slot"] == "Primary"
                 and r.get("recommend")), None)
    if prim:
        try:
            pl = await _item_line(prim["recommend"])
        except Exception:
            pl = None
        if pl and "Skill: 2H" in pl:
            for r in table:
                if r["slot"] == "Secondary":
                    r["recommend"] = None
                    r["where"] = None
                    r["why"] = ("— freed by the recommended 2H primary "
                                "(occupies both hands)")
    return {**base, "source": "llm",
            "note": data.get("note"),
            "pet_gear": pet_gear,
            "slots": table,
            "farm": _clean_list(data.get("farm"),
                                ("item", "slot", "zone", "source", "why"),
                                cap=8, require="item"),
            "exaltations": _gate_exalt_moves(
                _clean_list(data.get("exaltations"),
                            ("name", "move_to", "why"),
                            cap=8, require="name"),
                unusable_exalts, exalts),
            "unknown": gear["unknown"][:10]}
