"""Client spell-file grounding (spells_us.txt).

EQL ships the classic caret-delimited spell table inside the game dir --
the same data the client renders tooltips from. We mine two cheap sets
from it (no scraping, no Node):

- proc_names: spells GRANTED as automatic triggers by other spells
  (SPA 85/323/339/360/361/365/383/419/427/429). These names can appear
  as "by <spell>" damage without any cast; combined with never-seen-a-
  cast log evidence this disambiguates exaltation procs from real casts.
  Limit: ITEM-granted weapon procs are not in the spell file.
- lifetap_names: target_type 13/20 (lifetap / targeted-AE lifetap).
  Your OWN taps log only the damage line -- zero heal lines exist -- so
  the tracker synthesizes the self-heal 1:1 from these.

Format per github.com/Amerzel/eql-info SPELL_FORMAT.md (confirmed against
EQL's file): 173 caret-delimited columns, columns 0-102 stable across
EQL's column-insertion patches; the effects blob ("1|..." with 5 fields
per effect, "$N" separators) is located by CONTENT scanning from the end
because a patch already shifted its index once. cp1252 encoding.

Fail-soft: no file = empty sets, is_proc()/is_lifetap() return False.
load() parses a ~38MB file (a second or two) -- call it from a worker
thread at startup; the helpers never block and return False until then.
"""
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

IDX_ID = 0
IDX_NAME = 1
IDX_TARGET_TYPE = 30
MIN_FIELDS = 99  # columns 0-102 are the stable region; require most of it

# SPAs that GRANT an automatic trigger spell (weapon/buff/kill procs).
# The granted spell id sits in base_value for _PROC_ID_IS_BASE members,
# limit_value otherwise; values <= 100 collide with chance percentages so
# they are only trusted from the base-is-id slots.
PROC_SPA_IDS = {85, 323, 339, 360, 361, 365, 383, 419, 427, 429}
_PROC_ID_IS_BASE = {85, 419, 323, 427}
LIFETAP_TARGET_IDS = {13, 20}

_lock = threading.Lock()
_loaded = False
_proc_names: set = set()
_lifetap_names: set = set()


def _parse_effects(blob: str) -> list:
    """`1|<eff1>$2|<eff2>$...` -> [(spa, base, limit), ...]."""
    parts = blob.split("|")
    if not parts or parts[0] != "1":
        return []
    cleaned = [tok.split("$", 1)[0] for tok in parts[1:]]
    if len(cleaned) % 5 != 0:
        return []
    out = []
    for i in range(0, len(cleaned), 5):
        try:
            out.append((int(cleaned[i]), int(cleaned[i + 1]),
                        int(cleaned[i + 2])))
        except ValueError:
            continue
    return out

def load(game_dir: str) -> bool:
    """Parse spells_us.txt under `game_dir`. Idempotent; thread-safe;
    returns True when data is available (already loaded counts)."""
    global _loaded, _proc_names, _lifetap_names
    with _lock:
        if _loaded:
            return bool(_proc_names or _lifetap_names)
        path = os.path.join(game_dir or "", "spells_us.txt")
        if not os.path.isfile(path):
            logger.info("spells_us.txt not found (%s) — proc/lifetap "
                        "grounding disabled", path)
            _loaded = True
            return False
        names_by_id: dict = {}
        lifetaps: set = set()
        granted: set = set()
        try:
            with open(path, "r", encoding="cp1252", errors="replace") as fh:
                for line in fh:
                    fields = line.rstrip("\r\n").split("^")
                    if len(fields) < MIN_FIELDS:
                        continue
                    try:
                        sid = int(fields[IDX_ID])
                    except ValueError:
                        continue
                    names_by_id[sid] = fields[IDX_NAME]
                    try:
                        if int(fields[IDX_TARGET_TYPE]) in LIFETAP_TARGET_IDS:
                            lifetaps.add(fields[IDX_NAME].lower())
                    except ValueError:
                        pass
                    # effects blob: scan from the end (content-located)
                    for cell in reversed(fields):
                        if cell.startswith("1|"):
                            for spa, bval, lval in _parse_effects(cell):
                                if spa not in PROC_SPA_IDS:
                                    continue
                                for val, trusted in (
                                        (bval, spa in _PROC_ID_IS_BASE),
                                        (lval, False)):
                                    if val > 100 or (trusted and val > 0):
                                        granted.add(val)
                            break
        except OSError:
            logger.exception("spells_us.txt read failed")
            _loaded = True
            return False
        _proc_names = {names_by_id[i].lower() for i in granted
                       if i in names_by_id}
        _lifetap_names = lifetaps
        _loaded = True
        logger.info("Spell file loaded: %d spells, %d proc-granted, "
                    "%d lifetaps", len(names_by_id), len(_proc_names),
                    len(_lifetap_names))
        return True


def is_loaded() -> bool:
    return _loaded


def is_proc(name: Optional[str]) -> bool:
    """True when the spell file marks `name` as granted-by-trigger.
    False until load() completes (never blocks the caller)."""
    return bool(name) and name.lower() in _proc_names


def is_lifetap(name: Optional[str]) -> bool:
    return bool(name) and name.lower() in _lifetap_names