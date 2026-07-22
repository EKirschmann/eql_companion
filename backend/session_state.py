"""Session persistence: the live session survives backend restarts.

A restart used to rebuild from a 1MB seed replay whose events deliberately
do not count toward session stats — wiping DPS records, kills, XP,
encounters, and the ledger. Instead the state-push loop snapshots the
tracker (plus the log byte offset) every few seconds; on startup, if the
snapshot matches the active log file, the tracker is restored and the
watcher resumes from the saved offset — lines written while the backend was
down replay through the normal live path (counted once, persisted once).
"""
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/session_state.json")

# Everything session-shaped on CharacterTracker. Skipped on purpose:
# _dmg_window (60s DPS window — stale after any restart), pending_encounters
# (drained to the DB every 150ms), spellbook_loader/has_log (injected),
# pet_owners_dirty/_aa_from_db (transient flags).
PERSIST_FIELDS = [
    "name", "server", "level", "class_str", "race", "playstyle",
    "aa_available", "spell_slots", "zone",
    "damage_dealt", "damage_taken", "healing_received", "healing_done",
    "kills", "deaths", "xp_ticks", "xp_percent", "aa_points", "skill_ups",
    "swings_hit", "swings_missed", "loots", "last_target", "last_event_at",
    "position", "session_max_dps", "ledger", "encounter",
    "encounter_history", "unknown_casts", "loadout_hint", "last_death",
    "mob_stats", "_last_kill", "_pending_xp", "_pending_coin",
    "who_roster", "pet_owners", "pet_inventory", "owned_aas",
    "spell_casts", "crits", "coin_copper", "rune_absorbed",
    "session_started", "_active_buckets", "_dinged", "loot_count",
    "pending_sessions",
    "_last_aa_seen", "_last_aa_name",
]
_DEQUES = {"loots": 20, "ledger": 300, "encounter_history": 5}


def _enc(o):
    if isinstance(o, datetime):
        return {"__dt__": o.isoformat()}
    if isinstance(o, (deque, tuple, set)):
        return list(o)
    raise TypeError(f"not JSON-serializable: {type(o)}")


def _hook(d: dict):
    if set(d) == {"__dt__"}:
        try:
            return datetime.fromisoformat(d["__dt__"])
        except ValueError:
            return d["__dt__"]
    return d


def save(tracker, log_file: str, offset: int) -> None:
    try:
        data = {
            "log_file": log_file,
            "offset": int(offset),
            "saved_at": datetime.now().isoformat(),
            "fields": {f: getattr(tracker, f, None) for f in PERSIST_FIELDS},
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, default=_enc), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        logger.exception("Session-state save failed")


def load() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"),
                          object_hook=_hook)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Session-state load failed — starting fresh")
        return None


def restore(tracker, data: dict) -> None:
    for f, v in (data.get("fields") or {}).items():
        if f in _DEQUES and v is not None:
            v = deque(v, maxlen=_DEQUES[f])
        elif f == "_last_kill" and v is not None:
            v = tuple(v)
        elif f in ("spell_casts", "_active_buckets") and v is not None:
            v = set(v)
        setattr(tracker, f, v)
