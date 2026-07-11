"""Owned-state ingestion: /outputfile spellbook + /alternateadv list.

`/outputfile spellbook` (in-game) writes <Name>_<server>-<CLS>-Spellbook.txt
into the game folder: "<level>\t<spell name>" per line. Real levels are
spells castable by the CURRENT class trio; level 255 entries are spells
owned via other loadouts.

`/alternateadv list` (in-game) prints owned AAs into the LOG; the parser for
that lives in log_system once a real sample exists (format TBD).
"""
import time
from pathlib import Path
from typing import Optional

from backend.config import settings

_cache: dict = {}


_find_cache: dict = {}


def find_spellbook(name: str, server: str) -> Optional[Path]:
    """Newest export for the character; the glob is memoized for 10s
    because snapshot() polls this every second."""
    key = (name.lower(), server.lower())
    hit = _find_cache.get(key)
    if hit and time.time() - hit[1] < 10:
        return hit[0]
    game = Path(settings.eql_game_dir)
    matches = sorted(game.glob(f"{name}_{server}-*-Spellbook.txt"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    path = matches[0] if matches else None
    _find_cache[key] = (path, time.time())
    return path


def load_spellbook(name: Optional[str], server: Optional[str]) -> Optional[dict]:
    """Parsed spellbook export, cached by file mtime. None when absent."""
    if not name or not server:
        return None
    path = find_spellbook(name, server)
    if not path:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if _cache.get("key") == key:
        return _cache["value"]
    castable, other = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            lvl = int(parts[0])
        except ValueError:
            continue
        spell = parts[1].strip()
        if not spell:
            continue
        if lvl >= 255:
            other.append(spell)          # owned via another loadout
        else:
            castable.append({"level": lvl, "name": spell})
    castable.sort(key=lambda s: (s["level"], s["name"]))
    value = {
        "file": path.name,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
        "age_hours": round((time.time() - mtime) / 3600.0, 1),
        "castable": castable,
        "other_loadouts": sorted(set(other)),
    }
    _cache["key"] = key
    _cache["value"] = value
    return value
