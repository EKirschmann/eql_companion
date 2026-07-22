"""Passive reader for the game's loot filter (LF_<Character>_<server>.ini
in <game>/userdata). Format per terry-wilkerson/EQL-Loot-Filter-Manager
and rari/eqltools (independently agreeing): caret-delimited rows
`item_id^filter_id^icon_id^name`, with either a `[Filters]` section
header or `#` comment lines — skip both. On-disk action ids:
1 = Always Store, 2 = Always Loot, 3 = Always Merge, 4 = Always Sell.
Item +N tiers appear as separate rows (own item_id each); duplicate ids
are legal. THE GAME REWRITES THIS FILE LIVE (appends looted items), so
reads are mtime-cached and refreshed automatically. Read-only — we
never write game files.
"""
import logging
import os
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

ACTIONS = {1: "store", 2: "loot", 3: "merge", 4: "sell"}

_cache: dict = {}


def _path(name: Optional[str], server: Optional[str]) -> Optional[Path]:
    if not name or not server:
        return None
    p = Path(settings.eql_game_dir) / "userdata" / f"LF_{name}_{server}.ini"
    return p if p.is_file() else None


def load(name: Optional[str], server: Optional[str]) -> Optional[dict]:
    """{"actions": {item_name_lower: action}, "counts": {action: n},
    "file", "updated"} or None when no filter file exists."""
    p = _path(name, server)
    if p is None:
        return None
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return None
    key = str(p)
    hit = _cache.get(key)
    if hit and hit["_mtime"] == mtime:
        return hit
    actions: dict = {}
    counts: dict = {}
    try:
        for line in p.read_text(encoding="cp1252",
                                errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("[") or s.startswith("#"):
                continue
            parts = s.split("^")
            if len(parts) < 4:
                continue
            try:
                fid = int(parts[1])
            except ValueError:
                continue
            action = ACTIONS.get(fid)
            if not action:
                continue
            item = "^".join(parts[3:]).strip()
            if item:
                actions[item.lower()] = action
                counts[action] = counts.get(action, 0) + 1
    except OSError:
        logger.exception("Loot filter read failed: %s", p)
        return None
    out = {"actions": actions, "counts": counts, "file": p.name,
           "updated": mtime, "_mtime": mtime}
    _cache[key] = out
    if len(_cache) > 16:
        _cache.clear()
    return out


def action_for(name: Optional[str], server: Optional[str],
               item: str) -> Optional[str]:
    """The filter action for an item, checking the exact name first and
    the +N-stripped base second (tiers are separate rows but users often
    filter the base)."""
    import re
    lf = load(name, server)
    if not lf:
        return None
    low = item.lower().strip()
    return (lf["actions"].get(low)
            or lf["actions"].get(re.sub(r"\s*\+\d+$", "", low)))