"""Wiki-grounded game data for the advisor.

Fetches class pages and the Alternate Advancement page from the EQL wiki
(eqlwiki.com, via the local MCP server), compacts their verbose tables into
terse one-liners an LLM can digest, and caches results for a day.

Fails soft: returns "" when the MCP server or wiki is unavailable, so the
advisor can still answer ungrounded (and says so).

Wiki text shapes this parser expects (verified 2026-07-06):
- Class pages: "Spells[edit | edit source]" then "Level N[edit...]" blocks;
  each spell row starts with the name DOUBLED and a stat blob
  ("StrikeStrikePAL(1)Mana: 7Cast: ..."), followed by table columns on their
  own lines: Type, Target, Mana, Max Effect, Duration, Description, ...
- "Alternate Advancement" page: General/Archetype/<Class> Class/Special AA
  sections, each a table of 4-line records: Name / Ranks / Cost / Description.
"""
import logging
import re
from typing import List, Optional

from backend.cache import wiki_page_cache
from backend.config import settings
from backend.mcp_client import get_mcp_client

logger = logging.getLogger(__name__)

WIKI_TTL = 24 * 3600
AA_PAGE = "Alternate Advancement"
MAX_CONTEXT_CHARS = 20_000

RE_LEVEL = re.compile(r"Level (\d+)\[edit[^\]]*\]")
RE_EDIT = re.compile(r"\[edit[^\]]*\]")


def _doubled_name(line: str) -> Optional[str]:
    """Spell rows start with the name doubled: 'StrikeStrikePAL(1)...'."""
    best = None
    limit = min(len(line) // 2, 48)
    for i in range(2, limit + 1):
        if line[:i] == line[i:2 * i]:
            best = line[:i]
    return best


def _iter_spell_rows(page_text: str):
    """Yield (level, name, cols) for every spell row on a class page."""
    start = page_text.find("Spells[edit")
    if start < 0:
        return
    end_m = re.search(r"\n[A-Z][A-Za-z' ]*AAs\[edit|\nSkills\[edit", page_text[start:])
    section = page_text[start:start + end_m.start()] if end_m else page_text[start:]

    headers = list(RE_LEVEL.finditer(section))
    for idx, h in enumerate(headers):
        lvl = int(h.group(1))
        stop = headers[idx + 1].start() if idx + 1 < len(headers) else len(section)
        lines = [ln.strip() for ln in section[h.end():stop].split("\n")]
        i = 0
        while i < len(lines):
            ln = lines[i]
            name = _doubled_name(ln) if ("Mana:" in ln or "Cast:" in ln) else None
            if not name:
                i += 1
                continue
            cols: List[str] = []
            j = i + 1
            while (j < len(lines) and lines[j] != ""
                   and "Mana:" not in lines[j] and "Cast:" not in lines[j]):
                cols.append(lines[j])
                j += 1
            yield lvl, name, cols
            i = j


def compact_spells(page_text: str, lo: int, hi: int) -> List[str]:
    """Compact a class page's per-level spell tables to one line per spell."""
    out: List[str] = []
    for lvl, name, cols in _iter_spell_rows(page_text):
        if lvl < lo or lvl > hi:
            continue
        kind = cols[0] if len(cols) > 0 else "?"
        target = cols[1] if len(cols) > 1 else ""
        mana = cols[2] if len(cols) > 2 else "?"
        desc = cols[5] if len(cols) > 5 else ""
        piece = f"L{lvl} {name} [{kind}" + (f", {target}" if target else "")
        piece += f", {mana} mana]"
        if desc and desc != name:
            piece += f" {desc[:120]}"
        out.append(piece)
    return out


# Spell pages carry a "Classes" section: "Necromancer - Level 1" per line.
RE_CLASS_LINE = re.compile(r"^([A-Z][A-Za-z ]+?) - Level \d+\s*$", re.MULTILINE)


_TRADESKILLS = {
    "Alchemy", "Alcohol Tolerance", "Baking", "Begging", "Blacksmithing",
    "Brewing", "Fishing", "Fletching", "Jewelry Making", "Make Poison",
    "Pottery", "Research", "Tailoring", "Tinkering", "Swimming",
}


async def build_modes_context() -> str:
    """Combat stances + invocations (builds db, cached 24h; '' if down)."""
    cached = wiki_page_cache.get("modes_context")
    if cached is not None:
        return cached
    sc = await get_mcp_client().call_tool("eql_builds_modes", {})
    if sc is None:
        return ""
    out = []
    for kind in ("stances", "invocations"):
        for m in sc.get(kind, []) or []:
            desc = str(m.get("description", "")).split(". ")[0][:170]
            out.append(f"{m.get('name')}: {desc}")
    text = chr(10).join(out)
    wiki_page_cache.set(text, WIKI_TTL, "modes_context")
    return text


async def class_skills_context(cls: str) -> str:
    """Combat-relevant skill caps for one class ('' when unavailable)."""
    cid = cls.strip().lower()
    cached = wiki_page_cache.get("skills_context", cid)
    if cached is not None:
        return cached
    sc = None
    for candidate in (cid, cid.replace(" ", ""), cid.replace(" ", "-")):
        sc = await get_mcp_client().call_tool("eql_builds_skills",
                                              {"classId": candidate})
        if sc and sc.get("skills"):
            break
    if not sc:
        return ""
    skills = [s for s in (sc.get("skills") or [])
              if s.get("name") not in _TRADESKILLS and s.get("cap", 0) > 0]
    skills.sort(key=lambda s: -s["cap"])
    text = "; ".join(f"{s['name']} (cap {s['cap']}, from L{s.get('trainedAt', 1)})"
                     for s in skills[:24])
    wiki_page_cache.set(text, WIKI_TTL, "skills_context", cid)
    return text


async def spell_classes(spell: str) -> Optional[set]:
    """Full class names that can cast `spell`, read from the spell's own wiki
    page (complete — unlike class pages, which truncate at 40k chars).
    None = wiki down or no such page (e.g. clicky-only effects): can't judge.
    An empty set (page exists, no Classes section) also means can't judge."""
    key = spell.strip().lower()
    cached = wiki_page_cache.get("spell_classes", key)
    if cached is not None:
        return cached
    sc = await get_mcp_client().call_tool(
        "eql_builds_spell", {"idOrName": spell.strip()})
    sp = (sc or {}).get("spell")
    if sp and sp.get("classes"):
        alias = {"Shadowknight": "Shadow Knight"}
        classes = {alias.get(str(x).title(), str(x).title()) for x in sp["classes"]}
        wiki_page_cache.set(classes, WIKI_TTL, "spell_classes", key)
        return classes
    page = await get_mcp_client().wiki_page(spell.strip(), max_characters=4000)
    if page is None:
        return None  # not cached: source may just be down, retry later
    text = page.get("text", "")
    m = re.search(r"\nClasses\n(.*?)\n(?:Spell Effects|Details)", text, re.DOTALL)
    section = m.group(1) if m else ""
    classes = {mm.group(1).strip() for mm in RE_CLASS_LINE.finditer(section)}
    wiki_page_cache.set(classes, WIKI_TTL, "spell_classes", key)
    return classes


def compact_aas(page_text: str, classes: List[str]) -> List[str]:
    """General + Archetype + the trio's Class AAs + Special, one line each."""
    text = RE_EDIT.sub("", page_text)

    def section(start_pat: str, end_pats: List[str]) -> str:
        m = re.search(start_pat, text)
        if not m:
            return ""
        rest = text[m.end():]
        cut = len(rest)
        for ep in end_pats:
            em = re.search(ep, rest)
            if em:
                cut = min(cut, em.start())
        return rest[:cut]

    # Class sections first: a global size cap trims the tail, and the trio's
    # class AAs matter more than General crafting passives.
    chunks = []
    for cls in classes:
        chunks.append((cls, section(
            rf"\n{re.escape(cls)} Class AAs\n",
            [r"\n[A-Z][A-Za-z ]+ Class AAs\n", r"\nSpecial AAs\n"])))
    chunks.append(("Archetype", section(r"\nArchetype AAs\n", [r"\nClass AAs\n"])))
    chunks.append(("Special", section(r"\nSpecial AAs\n", [])))
    chunks.append(("General", section(r"\nGeneral AAs\n", [r"\nArchetype AAs\n"])))

    out: List[str] = []
    for label, sect in chunks:
        for para in re.split(r"\n\s*\n", sect):
            ls = [x.strip() for x in para.strip().split("\n") if x.strip()]
            if len(ls) < 4 or ls[0] == "Name" or not re.fullmatch(r"\d+", ls[1]):
                continue
            desc = re.sub(r"\s+", " ", " ".join(ls[3:]))[:180]
            if label == "General" and "recipes" in desc:
                continue  # crafting Masteries: real but never advisor-worthy
            out.append(f"[{label}] {ls[0]} (ranks {ls[1]}, cost {ls[2]}) {desc}")
    return out


async def build_wiki_context(classes: List[str], level: Optional[int],
                             max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Assembled, size-capped wiki context for the advisor prompt ('' if none)."""
    if not settings.mcp_enabled or not classes:
        return ""
    lvl = level or 1
    lo, hi = max(1, lvl - 8), lvl + 12
    mcp = get_mcp_client()
    parts: List[str] = []

    for cls in classes:
        cached = wiki_page_cache.get("advisor_spells", cls, lo, hi)
        if cached is None:
            page = await mcp.wiki_page(cls)
            if page is not None:
                cached = "\n".join(compact_spells(page.get("text", ""), lo, hi)[:60])
                wiki_page_cache.set(cached, WIKI_TTL, "advisor_spells", cls, lo, hi)
            else:
                cached = ""  # fetch failed -- do not cache, retry next consult
        if cached:
            parts.append(f"## {cls} spells (window L{lo}-L{hi}): name [type, target, mana] effect\n{cached}")

    modes = await build_modes_context()
    if modes:
        parts.append("## Combat stances & invocations (pick per situation)" + chr(10) + modes)
    for cls in classes:
        sk = await class_skills_context(cls)
        if sk:
            parts.append(f"## {cls} skill caps (weapon/combat training)" + chr(10) + sk)

    key = "/".join(classes)
    cached = wiki_page_cache.get("advisor_aas", key)
    if cached is None:
        page = await mcp.wiki_page(AA_PAGE)
        if page is not None:
            cached = "\n".join(compact_aas(page.get("text", ""), classes)[:160])
            wiki_page_cache.set(cached, WIKI_TTL, "advisor_aas", key)
        else:
            cached = ""  # fetch failed -- do not cache, retry next consult
    if cached:
        parts.append("## AAs: [tab] name (ranks, cost per rank) effect\n" + cached)

    return "\n\n".join(parts)[:max_chars]