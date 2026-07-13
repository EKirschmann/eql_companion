"""Owned-state ingestion: /outputfile spellbook + /alternateadv list.

`/outputfile spellbook` (in-game) writes <Name>_<server>-<CLS>-Spellbook.txt
into the game folder: "<level>\t<spell name>" per line. Real levels are
spells castable by the CURRENT class trio; level 255 entries are spells
owned via other loadouts.

`/alternateadv list` (in-game) prints owned AAs into the LOG; the parser for
that lives in log_system once a real sample exists (format TBD).
"""
import re
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


# ------------------------------------------------------------- other exports

EXPORT_KINDS = ("Spellbook", "MissingSpells", "Inventory", "Achievements")

# The slots that actually appear in the EQL inventory export (verified
# against a live file): no Charm / Power Source in this game — instead two
# generic "Any Slot"s (can hold any equippable item) plus Ammo and Held.
WORN_SLOTS = {
    "Any Slot", "Ear", "Head", "Face", "Neck", "Shoulders", "Arms", "Back",
    "Wrist", "Range", "Hands", "Primary", "Secondary", "Fingers", "Chest",
    "Legs", "Feet", "Waist", "Ammo", "Held",
}

_export_cache: dict = {}


def clear_find_cache() -> None:
    """Force fresh directory scans (the 'check exports' button)."""
    _find_cache.clear()


def _find_export(name: str, server: str, kind: str) -> Optional[Path]:
    """Newest '<name>_<server>*<Kind>.txt' (EQL inserts the class code)."""
    key = (name.lower(), server.lower(), kind.lower())
    hit = _find_cache.get(key)
    if hit and time.time() - hit[1] < 10:
        return hit[0]
    game = Path(settings.eql_game_dir)
    prefix = f"{name}_{server}".lower()
    suffix = f"{kind.lower()}.txt"
    best = None
    for p in game.glob(f"{name}_{server}*.txt"):
        low = p.name.lower()
        if low.startswith(prefix) and low.endswith(suffix):
            if best is None or p.stat().st_mtime > best.stat().st_mtime:
                best = p
    _find_cache[key] = (best, time.time())
    return best


def _parse_level_rows(text: str):
    castable, other = [], []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            lvl = int(parts[0])
        except ValueError:
            continue
        entry = parts[1].strip()
        if not entry:
            continue
        (other if lvl >= 255 else castable).append(
            entry if lvl >= 255 else {"level": lvl, "name": entry})
    castable.sort(key=lambda s: (s["level"], s["name"]))
    return castable, sorted(set(other))


def load_export(name: Optional[str], server: Optional[str],
                kind: str) -> Optional[dict]:
    """Parsed export of the given kind, cached by mtime. None when absent.
    Formats: Spellbook/MissingSpells = 'level<TAB>name' rows; Inventory =
    TSV with a Location/Name header; Achievements = format pending a first
    real sample (line count only)."""
    if not name or not server:
        return None
    path = _find_export(name, server, kind)
    if not path:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime, kind, 4)  # bump on parser changes
    hit = _export_cache.get(key)
    if hit is not None:
        return hit
    text = path.read_text(encoding="utf-8", errors="replace")
    value = {
        "kind": kind,
        "file": path.name,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
        "age_hours": round((time.time() - mtime) / 3600.0, 1),
    }
    if kind in ("Spellbook", "MissingSpells"):
        castable, other = _parse_level_rows(text)
        value["castable"] = castable
        value["other_loadouts"] = other
        value["count"] = len(castable)
    elif kind == "Inventory":
        # Ear/Wrist/Fingers are PAIRED: the export emits two identical
        # location labels — number them or the second overwrites the first.
        # "<Loc>-SlotN" sub-rows are either bag contents (under General/Bank
        # containers) or ITEM SOCKETS: "(Exaltation)" entries live there.
        paired = {"Ear", "Wrist", "Fingers", "Any Slot"}
        worn, items, exalts, count, seen_slots = {}, [], [], 0, {}
        last_item_at = {}
        sub_re = re.compile(r"^(.+?)-Slot(\d+)$")
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or parts[0].lower() == "location":
                continue
            count += 1
            loc, item = parts[0].strip(), parts[1].strip()
            if not item or item.lower() == "empty":
                continue
            m = sub_re.match(loc)
            if m:
                parent = m.group(1)
                in_bank = parent.lower().startswith("bank")
                if "(exaltation)" in item.lower():
                    exalts.append({
                        "name": item, "socket": int(m.group(2)),
                        "host_loc": parent,
                        "host": last_item_at.get(parent),
                        "where": ("worn" if parent in WORN_SLOTS
                                  else "bank" if in_bank else "bags"),
                    })
                    continue
                if parent in WORN_SLOTS:
                    continue  # non-exalt socket rows on gear: nothing to track
                items.append({"loc": loc,
                              "where": "bank" if in_bank else "bags",
                              "name": item})
                continue
            last_item_at[loc] = item
            if loc in WORN_SLOTS:
                seen_slots[loc] = seen_slots.get(loc, 0) + 1
                key = (f"{loc} {seen_slots[loc]}" if loc in paired else loc)
                worn[key] = item
                where = "worn"
            elif loc.lower().startswith("bank"):
                where = "bank"
            else:
                where = "bags"
            items.append({"loc": loc, "where": where, "name": item})
        value["worn"] = worn
        value["items"] = items
        value["exaltations"] = exalts
        value["count"] = count
    else:  # Achievements — structure unknown until a real export exists
        lines = [ln for ln in text.splitlines() if ln.strip()]
        value["count"] = len(lines)
    _export_cache[key] = value
    if len(_export_cache) > 64:
        _export_cache.clear()
    return value


def exports_status(name: Optional[str], server: Optional[str]) -> dict:
    """Presence + freshness of every export kind (for the sync chips)."""
    out = {}
    for kind in EXPORT_KINDS:
        e = load_export(name, server, kind)
        out[kind.lower()] = (
            {"found": True, "file": e["file"], "updated": e["updated"],
             "age_hours": e["age_hours"], "count": e.get("count")}
            if e else {"found": False})
    return out
