"""Direct reader for the eqlbuilds.com dataset snapshot.

The MCP server clone ships a CI-refreshed snapshot of eqlbuilds.com (per-
class spell lists with EXACT unlock levels, AA ranks/costs, skills) under
dist/data/eqlbuilds. Reading the JSON directly beats per-lookup stdio calls:
deterministic, instant, and it works even where Node cannot run. Everything
here is optional — no clone means every function returns None/{} and the
callers keep their MCP/wiki fallback paths.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

_cache: dict = {"file": None, "mtime": None, "data": None, "index": None}


def _snapshot_file() -> Optional[Path]:
    if not settings.mcp_server_dir:
        return None
    for sub in ("dist", "src"):
        p = Path(settings.mcp_server_dir) / sub / "data" / "eqlbuilds" / "classes.json"
        if p.exists():
            return p
    return None


def _class_key(name: str) -> str:
    """'Shadow Knight' -> 'shadowKnight' (the snapshot's key style)."""
    words = (name or "").strip().lower().split()
    return words[0] + "".join(w.title() for w in words[1:]) if words else ""


def _pretty(key: str) -> str:
    """'shadowKnight' -> 'Shadow Knight'."""
    spaced = re.sub("(?<!^)([A-Z])", lambda m: " " + m.group(1), key)
    return spaced.title()


def classes_data() -> Optional[dict]:
    f = _snapshot_file()
    if f is None:
        return None
    try:
        mtime = f.stat().st_mtime
        if _cache["file"] != str(f) or _cache["mtime"] != mtime:
            _cache.update(file=str(f), mtime=mtime, index=None,
                          data=json.loads(f.read_text(encoding="utf-8")))
            logger.info("eqlbuilds snapshot loaded: %s", f)
        return _cache["data"]
    except Exception:
        logger.exception("eqlbuilds snapshot unreadable")
        return None


def available() -> bool:
    return classes_data() is not None


def class_spells(cls_name: str) -> Optional[list]:
    d = classes_data()
    if not d:
        return None
    c = d.get(_class_key(cls_name))
    return c.get("spellList") if c else None


def class_aas(cls_name: str) -> Optional[list]:
    d = classes_data()
    if not d:
        return None
    c = d.get(_class_key(cls_name))
    return c.get("alternateAbilityList") if c else None


def _index() -> dict:
    """spell name (lower) -> {'levels': {Pretty Class: level}, 'entry': first}"""
    d = classes_data()
    if not d:
        return {}
    if _cache["index"] is None:
        idx: dict = {}
        for key, c in d.items():
            pretty = _pretty(key)
            for s in c.get("spellList") or []:
                slot = idx.setdefault(str(s.get("name", "")).lower(),
                                      {"levels": {}, "entry": s})
                slot["levels"][pretty] = s.get("level")
        _cache["index"] = idx
    return _cache["index"]


def spell_levels(name: str) -> dict:
    """{Pretty Class: unlock level} for a spell; {} when unknown/no snapshot."""
    hit = _index().get((name or "").strip().lower())
    return dict(hit["levels"]) if hit else {}


def spell_entry(name: str) -> Optional[dict]:
    """Full snapshot record with classes attached — a spell_record substitute
    when the MCP server cannot answer."""
    hit = _index().get((name or "").strip().lower())
    if not hit:
        return None
    return {**hit["entry"],
            "classes": sorted(hit["levels"]),
            "levels": dict(hit["levels"])}


def class_spell_lines(cls_name: str, lo: int, hi: int) -> Optional[list]:
    """Compact per-level spell lines for the advisor prompt window, straight
    from the snapshot (exact levels). None = no snapshot / unknown class."""
    spells = class_spells(cls_name)
    if spells is None:
        return None
    out = []
    for s in sorted(spells, key=lambda x: (x.get("level") or 0, x.get("name") or "")):
        lv = s.get("level")
        if lv is None or not (lo <= lv <= hi):
            continue
        desc = (s.get("resolvedDescription") or s.get("description") or "")
        desc = " ".join(desc.split())[:110]
        mana = s.get("manaCost")
        out.append(f"L{lv} {s.get('name')}"
                   + (f" [mana {mana}]" if mana else "")
                   + (f" {desc}" if desc else ""))
    return out


def class_aa_lines(classes: list) -> Optional[list]:
    """AA lines (name, ranks, per-rank costs, description) for a class trio,
    deduped across the trio's lists. None = no snapshot."""
    if not available():
        return None
    seen, out = set(), []
    for cls in classes:
        for a in class_aas(cls) or []:
            name = a.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            desc = " ".join((a.get("description") or "").split())[:150]
            cat = a.get("category") or "class"
            cost = a.get("costLabel") or "?"
            out.append(f"[{cat}] {name} (ranks {a.get('maxRank', '?')}, "
                       f"cost {cost}) {desc}")
    return out
