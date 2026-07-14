"""Read + write the game's saved spell sets (LO*.ini [SpellLoadouts]).

The game stores named 14-slot spell sets in <Name>_<server>_LO<N>.ini and
memorizes them in one command: /memspellset <name>. The companion writes its
recommended loadout as a set (default name "companion") so the whole
Memorize-now list lands on the spell bar with one command. Writes are
surgical — only the target set's lines change, everything else is preserved
byte-for-byte, and a one-time .companion-backup copy of the original is
kept beside the file.
"""
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

MAX_SLOTS = 14
_ENTRY = re.compile(r"^SpellLoadout(\d+)\.(inuse|name|slot\d+)=(.*)$")


def find_loadout_ini(name: str, server: str) -> Optional[Path]:
    game = Path(settings.eql_game_dir)
    cands = sorted(game.glob(f"{name}_{server}_LO*.ini"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _section_span(lines: list) -> tuple:
    start = next((i for i, l in enumerate(lines)
                  if l.strip().lower() == "[spellloadouts]"), None)
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            end = i
            break
    return start, end


def read_spell_sets(path: Path) -> list:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start, end = _section_span(lines)
    sets: dict = {}
    if start is None:
        return []
    for l in lines[start + 1:end]:
        m = _ENTRY.match(l.strip())
        if not m:
            continue
        idx, key, val = int(m.group(1)), m.group(2), m.group(3)
        s = sets.setdefault(idx, {"index": idx, "inuse": False,
                                  "name": None, "slots": {}})
        if key == "inuse":
            s["inuse"] = val.strip() == "1"
        elif key == "name":
            s["name"] = val.strip()
        else:
            s["slots"][int(key[4:])] = val.strip()
    out = []
    for idx in sorted(sets):
        s = sets[idx]
        if s["inuse"]:
            out.append({"index": idx, "name": s["name"],
                        "spell_ids": [int(v) for _, v in sorted(s["slots"].items())
                                      if v.lstrip("-").isdigit()]})
    return out


def write_spell_set(path: Path, set_name: str, spell_ids: list) -> dict:
    """Create/overwrite the named set with up to 14 spell ids, first free
    slot if the name is new. Only that set's lines are touched."""
    raw = path.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start, end = _section_span(lines)
    if start is None:
        raise ValueError("no [SpellLoadouts] section in the file")

    existing = read_spell_sets(path)
    target = next((s["index"] for s in existing
                   if (s["name"] or "").lower() == set_name.lower()), None)
    if target is None:
        used = {s["index"] for s in existing}
        # inuse=0 lines exist for 1..60 — pick the lowest not in use
        target = next((i for i in range(1, 61) if i not in used), None)
        if target is None:
            raise ValueError("all 60 spell-set slots are in use")

    prefix = f"SpellLoadout{target}."
    body = [l for l in lines[start + 1:end]
            if not l.strip().startswith(prefix)]
    body.append(f"{prefix}inuse=1")
    body.append(f"{prefix}name={set_name}")
    for i, sid in enumerate(spell_ids[:MAX_SLOTS], 1):
        body.append(f"{prefix}slot{i}={sid}")

    backup = path.with_suffix(path.suffix + ".companion-backup")
    if not backup.exists():
        shutil.copy2(path, backup)

    new_lines = lines[:start + 1] + body + lines[end:]
    path.write_bytes((nl.join(new_lines) + nl).encode("utf-8"))
    logger.info("Wrote spell set %r (index %d, %d spells) to %s",
                set_name, target, len(spell_ids[:MAX_SLOTS]), path.name)
    return {"index": target, "name": set_name,
            "count": len(spell_ids[:MAX_SLOTS]), "file": path.name}
