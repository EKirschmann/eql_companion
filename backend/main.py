"""EQL Companion backend.

FastAPI app that:
- tails the EQL log, parses events, tracks character/session state
- broadcasts events + state over WebSocket (/ws)
- answers companion questions via the LangGraph agent (/api/chat)

Run: uvicorn backend.main:app --reload
"""
import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.agent.advisor import generate_advice, generate_gear_advice
from backend.agent.graph import get_agent
from backend.agent.state import AgentState, ProfileData
from backend.config import settings
from backend.game_data import hunting_candidates, spell_classes
from backend import session_state
from backend.geometry_system import geometry3d_for_zone, geometry_for_zone
from backend.log_system import LogWatcher, discover_log_file
from backend.log_system.parser import extract_character_from_filename, parse_line
from backend.log_system import events as ev
from backend.map_system import find_route, known_zones, load_map, normalize_zone
from backend.ocr_system import OcrWatcher, load_config as ocr_load_config, \
    ocr_region, parse_loc_text, save_config as ocr_save_config
from backend.models import Base, Character, ChatMessageRow, LogEventRow
from backend.spellbook import (clear_find_cache, exports_status,
                               load_export, load_spellbook)
from backend.state_tracker import CharacterTracker
from backend.ws_manager import ws_manager
from backend import spell_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# check_same_thread=False: milestone writes run in a worker thread (db_writer_loop)
Path("data").mkdir(exist_ok=True)  # sqlite cannot create the directory itself
engine = create_engine(
    settings.database_url, echo=False,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Lightweight migration: add new columns to pre-existing SQLite tables.
with engine.connect() as _conn:
    _cols = {r[1] for r in _conn.exec_driver_sql("PRAGMA table_info(characters)")}
    for _col, _typ in (("aa_available", "INTEGER"), ("spell_slots", "INTEGER"),
                       ("pet_slots", "INTEGER"), ("pet_classes", "TEXT"),
                       ("owned_aas", "TEXT"), ("aa_synced", "TEXT"),
                       ("pet_owners", "TEXT"), ("max_hp", "INTEGER"),
                       ("max_mana", "INTEGER")):
        if _col not in _cols:
            _conn.exec_driver_sql(f"ALTER TABLE characters ADD COLUMN {_col} {_typ}")
    _conn.commit()

# Persist these event types to the DB; per-hit spam stays in memory only.
PERSISTED_EVENTS = {"zone", "level", "kill", "death", "aa", "loot", "skill", "char_info"}
STATE_BROADCAST_MIN_INTERVAL = 1.0  # seconds
EVENT_FLUSH_INTERVAL = 0.15  # coalesce events into ~6 WS frames/sec
EVENT_BUFFER_MAX = 600       # cap the buffer during client-less catch-up bursts

tracker: Optional[CharacterTracker] = None
watcher: Optional[LogWatcher] = None
ocr_watcher: Optional[OcrWatcher] = None
_character_id: Optional[int] = None
_last_state_broadcast = 0.0
ADVICE_CACHE_FILE = Path("data/advice_cache.json")


def _sig_norm(sig: tuple) -> tuple:
    """Signatures survive a JSON roundtrip only as strings — normalize both
    sides of every comparison."""
    return tuple("" if x is None else str(x) for x in sig)


def _save_advice_cache() -> None:
    try:
        ADVICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ADVICE_CACHE_FILE.write_text(json.dumps({
            "advice": _advice_cache,
            "advice_sig": list(_advice_sig) if _advice_sig else None,
            "gear": _gear_cache,
            "gear_sig": list(_gear_sig) if _gear_sig else None,
        }), encoding="utf-8")
    except Exception:
        logger.exception("Advice-cache save failed")


def _load_advice_cache() -> None:
    global _advice_cache, _advice_sig, _gear_cache, _gear_sig
    try:
        d = json.loads(ADVICE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    _advice_cache = d.get("advice")
    _advice_sig = tuple(d["advice_sig"]) if d.get("advice_sig") else None
    _gear_cache = d.get("gear")
    _gear_sig = tuple(d["gear_sig"]) if d.get("gear_sig") else None


_advice_cache: Optional[dict] = None
_advice_sig: Optional[tuple] = None
_gear_cache: Optional[dict] = None
_gear_sig: Optional[tuple] = None
_watcher_task: Optional[asyncio.Task] = None
_last_persisted_aa: Optional[str] = None
_event_buffer: list = []
_db_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- log plumbing

def _load_character_enrichment() -> None:
    """Bind the tracker to its DB row and load persisted enrichment."""
    global _character_id
    db = SessionLocal()
    row = _sync_character_row(db)
    _character_id = row.id
    tracker.playstyle = row.playstyle
    tracker.class_str = row.class_str
    tracker.race = row.race
    tracker.aa_available = row.aa_available
    tracker.spell_slots = row.spell_slots
    tracker.pet_slots = row.pet_slots
    tracker.pet_classes = row.pet_classes
    tracker.max_hp = row.max_hp
    tracker.max_mana = row.max_mana
    if row.owned_aas:
        tracker.owned_aas = dict(row.owned_aas)
        if row.aa_synced:
            try:
                tracker._last_aa_seen = datetime.fromisoformat(row.aa_synced)
                tracker._aa_from_db = True
            except ValueError:
                pass
    if row.pet_owners:
        tracker.pet_owners = dict(row.pet_owners)
    global _last_persisted_aa
    _last_persisted_aa = row.aa_synced
    if row.level and not tracker.level:
        tracker.level = row.level
    db.close()


def _scan_log_characters() -> list:
    """Characters that have a log in the log dir (/log on in-game creates one)."""
    log_dir = Path(settings.eql_log_dir)
    out = []
    if not log_dir.exists():
        return out
    for p in sorted(log_dir.glob("eqlog_*.txt"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        name, server = extract_character_from_filename(p)
        if name:
            out.append({"name": name, "server": server, "file": p.name,
                        "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return out


async def switch_character(file_name: str) -> bool:
    """Retarget the tailer + tracker to another character's log file.
    Keyed by file (not name): the same name can exist on several servers."""
    global tracker, watcher, _watcher_task, _advice_cache, _advice_sig
    log_dir = Path(settings.eql_log_dir).resolve()
    path = (log_dir / Path(file_name).name).resolve()
    if path.parent != log_dir or not path.name.startswith("eqlog_") or not path.exists():
        return False
    found, _srv = extract_character_from_filename(path)
    if not found:
        return False
    if watcher:
        watcher.stop()
    if _watcher_task:
        _watcher_task.cancel()
    watcher = LogWatcher(path, on_log_event)
    tracker = CharacterTracker(watcher.character_name, watcher.server)
    tracker.spellbook_loader = load_spellbook
    tracker.has_log = True
    _load_character_enrichment()
    await watcher.seed()
    _watcher_task = asyncio.create_task(watcher.run())
    if ocr_watcher:
        ocr_watcher.tracker = tracker
    _advice_cache = _advice_sig = None
    asyncio.create_task(asyncio.to_thread(spell_file.load, settings.eql_game_dir))
    asyncio.create_task(_load_exalt_effects())
    await ws_manager.broadcast({"type": "state", "data": tracker.snapshot()})
    logger.info(f"Switched to {tracker.name} ({tracker.server})")
    return True


def _sync_character_row(db: Session) -> Character:
    """Get or create the Character row for the tracked character."""
    row = (db.query(Character)
           .filter(Character.name == tracker.name,
                   Character.server == tracker.server).first())
    if not row:
        row = Character(name=tracker.name, server=tracker.server)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


async def _check_cast(spell: str) -> None:
    """Loadout staleness check: two distinct cast spells outside the saved
    trio's wiki spell lists means the loadout probably changed in-game
    (swaps log nothing; only /who re-syncs the trio)."""
    try:
        if tracker.loadout_hint:
            return
        classes = [c.strip() for c in (tracker.class_str or "").split("/") if c.strip()]
        if not classes:
            return
        from backend.builds_data import spell_entry
        e = spell_entry(spell)
        if e and any(x.get("effectId") in (33, 71) for x in e.get("effects") or []):
            # pet summon: without a "/pet leader" mapping the pet's damage
            # credits an ally row instead of the player
            own = any(o.lower() == (tracker.name or "").lower()
                      for o in tracker.pet_owners.values())
            if not own:
                tracker.pet_hint = True
            return  # a summon is never a loadout-mismatch signal either
        from backend.game_data import is_travel_ritual
        if await is_travel_ritual(spell):
            return  # rituals (rings/circles/gate...) are castable by ANY
                    # class once learned — never a loadout signal
        book = load_spellbook(tracker.name, tracker.server)
        if book:
            scribed = ({s["name"] for s in book.get("castable", [])}
                       | set(book.get("other_loadouts") or []))
            if spell not in scribed:
                return  # not in the spellbook at all: an item/exaltation
                        # clicky casting someone else's spell, not a swap
        castable_by = await spell_classes(spell)
        if not castable_by or castable_by & set(classes):
            return  # trio can cast it, or we cannot judge (no page / wiki down)
        tracker.unknown_casts[spell] = ", ".join(sorted(castable_by))
        if len(tracker.unknown_casts) >= 2:
            names = "; ".join(f"{s} ({cls})" for s, cls
                              in list(tracker.unknown_casts.items())[:3])
            tracker.loadout_hint = (
                f"You're casting {names} — not castable by {tracker.class_str}. "
                "Loadout changed? Type /who in-game to re-sync.")
            await ws_manager.broadcast({"type": "state", "data": tracker.snapshot()})
    except Exception:
        logger.exception("Cast/loadout check failed")


async def _load_exalt_effects() -> None:
    """Effect names granted by owned exaltation stones (wiki-mined, cached)
    — the tracker labels matching damage lines "(exaltation)"."""
    try:
        from backend.game_data import item_line
        inv = load_export(tracker.name, tracker.server, "Inventory")
        names = set()
        for x in (inv or {}).get("exaltations") or []:
            bname = re.sub(r"\s*[(]Exaltation[)]$", "", x["name"]).strip()
            line = await item_line(bname)
            m = re.search(r"Effect: ([^(;|]+)", line or "")
            if m:
                names.add(m.group(1).strip().lower())
        # stones whose effect is ALSO a scribed spell (Drones of Doom etc.)
        # are AMBIGUOUS: the tracker labels them only when the client spell
        # file marks the effect proc-granted AND this session never saw a
        # cast of it (see CharacterTracker._fx_label)
        book = load_spellbook(tracker.name, tracker.server)
        scribed = set()
        if book:
            scribed = {s["name"].lower() for s in book.get("castable", [])}
            scribed |= {n.lower() for n in book.get("other_loadouts") or []}
        tracker.exalt_ambiguous = names & scribed
        tracker.exalt_effects = names - scribed
        if names:
            logger.info("Exaltation proc effects: %s (ambiguous: %s)",
                        ", ".join(sorted(tracker.exalt_effects)) or "none",
                        ", ".join(sorted(tracker.exalt_ambiguous)) or "none")
    except Exception:
        logger.exception("Exaltation-effect load failed")


async def on_log_event(event: ev.LogEvent, live: bool) -> None:
    tracker.apply(event, live)

    if not live:
        return

    if event.type in ("other_out", "aa_list", "aa_meta", "who_other",
                      "pet_inv_header", "pet_gear", "pet_attack"):
        return  # aggregated into tracker state; raw broadcast would flood the WS

    if event.type == "cast":
        asyncio.create_task(_check_cast(event.spell))

    # Persist milestones from a worker thread — an inline SQLite commit
    # (fsync) would stall the tailer/WS loop for milliseconds per kill.
    if event.type in PERSISTED_EVENTS and _character_id:
        try:
            _db_queue.put_nowait({
                "character_id": _character_id, "event_type": event.type,
                "payload": event.model_dump(mode="json"), "ts": event.ts,
                "zone": tracker.zone, "level": tracker.level,
                "class_str": tracker.class_str,
                "aa_available": tracker.aa_available,
            })
        except asyncio.QueueFull:
            logger.warning("DB queue full — dropping %s milestone", event.type)

    # Coalesced into batched WS frames by event_flush_loop.
    _event_buffer.append(event.model_dump(mode="json"))
    if len(_event_buffer) > EVENT_BUFFER_MAX:
        del _event_buffer[: len(_event_buffer) - EVENT_BUFFER_MAX]


def _persist_milestone(item: dict) -> None:
    """Runs in a worker thread — keeps SQLite fsyncs off the event loop."""
    db = SessionLocal()
    try:
        if item.get("kind") == "roster":
            row = db.get(Character, item["character_id"])
            if row:
                row.owned_aas = item["owned_aas"]
                row.aa_synced = item["aa_synced"]
                row.pet_owners = item["pet_owners"]
                db.commit()
            return
        db.add(LogEventRow(character_id=item["character_id"],
                           event_type=item["event_type"],
                           payload=item["payload"], ts=item["ts"]))
        row = db.get(Character, item["character_id"])
        if row:
            if item["zone"]:
                row.zone = item["zone"]
            if item["level"]:
                row.level = item["level"]
            if item["event_type"] == "aa" and item["aa_available"] is not None:
                row.aa_available = item["aa_available"]
            if item["class_str"]:
                row.class_str = item["class_str"]
        db.commit()
    finally:
        db.close()


async def db_writer_loop() -> None:
    while True:
        item = await _db_queue.get()
        try:
            await asyncio.to_thread(_persist_milestone, item)
        except Exception:
            logger.exception("Milestone persist failed")


async def _flush_events() -> None:
    """Send buffered events as ONE frame; piggyback a throttled state push."""
    global _last_state_broadcast
    if not _event_buffer:
        return
    if not ws_manager.connections:
        _event_buffer.clear()
        return
    batch = _event_buffer.copy()
    _event_buffer.clear()
    await ws_manager.broadcast({"type": "events", "data": batch})
    now = time.monotonic()
    if now - _last_state_broadcast >= STATE_BROADCAST_MIN_INTERVAL:
        _last_state_broadcast = now
        await ws_manager.broadcast({"type": "state", "data": tracker.snapshot()})


def _drain_roster_updates() -> None:
    """Persist AA/pet rosters when they change (they otherwise die with the
    process once the listing scrolls past the 1MB startup replay)."""
    global _last_persisted_aa
    if not tracker or not _character_id:
        return
    stamp = tracker._last_aa_seen.isoformat() if tracker._last_aa_seen else None
    if stamp == _last_persisted_aa and not tracker.pet_owners_dirty:
        return
    _last_persisted_aa = stamp
    tracker.pet_owners_dirty = False
    try:
        _db_queue.put_nowait({"kind": "roster", "character_id": _character_id,
                              "owned_aas": dict(tracker.owned_aas),
                              "aa_synced": stamp,
                              "pet_owners": dict(tracker.pet_owners)})
    except asyncio.QueueFull:
        logger.warning("DB queue full — roster persist skipped")


def _drain_finished_encounters() -> None:
    """Queue archived pulls for persistence (event_type='encounter')."""
    if not tracker or not tracker.pending_encounters:
        return
    views = list(tracker.pending_encounters)
    tracker.pending_encounters.clear()
    if not _character_id:
        return
    for view in views:
        try:
            _db_queue.put_nowait({
                "character_id": _character_id, "event_type": "encounter",
                "payload": view, "ts": datetime.fromisoformat(view["started"]),
                "zone": tracker.zone, "level": tracker.level,
                "class_str": tracker.class_str,
                "aa_available": tracker.aa_available,
            })
        except asyncio.QueueFull:
            logger.warning("DB queue full — dropping encounter record")


async def event_flush_loop() -> None:
    """~6 WS frames/sec regardless of combat intensity (was: 1 frame/swing)."""
    while True:
        await asyncio.sleep(EVENT_FLUSH_INTERVAL)
        try:
            _drain_roster_updates()
            _drain_finished_encounters()
            await _flush_events()
        except Exception:
            logger.exception("Event flush failed")


async def periodic_state_push():
    """Every 3s push state so DPS visibly decays to 0 out of combat, and
    snapshot the session to disk so restarts don't wipe it."""
    while True:
        await asyncio.sleep(3.0)
        if ws_manager.connections:
            await ws_manager.broadcast({"type": "state", "data": tracker.snapshot()})
        if watcher and getattr(tracker, "_dirty", True):
            tracker._dirty = False
            await asyncio.to_thread(session_state.save, tracker,
                                    str(watcher.path), watcher._offset)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tracker, watcher, ocr_watcher, _character_id, _watcher_task

    log_path = Path(settings.eql_log_path) if settings.eql_log_path else \
        discover_log_file(Path(settings.eql_log_dir), settings.eql_character_name)

    tasks: list[asyncio.Task] = []
    if log_path and log_path.exists():
        watcher = LogWatcher(log_path, on_log_event)
        tracker = CharacterTracker(watcher.character_name, watcher.server)
        tracker.spellbook_loader = load_spellbook
        tracker.has_log = True
        _load_character_enrichment()  # playstyle etc. survive restarts

        # session continuity: restore the last snapshot if it belongs to this
        # log file, then resume the tailer from the saved byte offset so the
        # downtime gap replays through the normal live path (counted once).
        restored = False
        st = session_state.load()
        if st and st.get("log_file") == str(log_path):
            try:
                size = log_path.stat().st_size
                off = int(st.get("offset") or 0)
                if 0 < off <= size:
                    session_state.restore(tracker, st)
                    watcher._offset = off
                    restored = True
                    logger.info("Session restored — replaying %d bytes of "
                                "downtime log", size - off)
            except Exception:
                logger.exception("Session restore failed — reseeding")
        if not restored:
            await watcher.seed()
        _watcher_task = asyncio.create_task(watcher.run())
        tasks.append(asyncio.create_task(periodic_state_push()))
        logger.info(f"Companion online for {tracker.name} ({tracker.server})")
    else:
        tracker = CharacterTracker(settings.eql_character_name, None)
        tracker.spellbook_loader = load_spellbook
        logger.warning(
            f"No EQL log found in {settings.eql_log_dir} — running without live data")

    _load_advice_cache()  # consults survive restarts
    tasks.append(asyncio.create_task(
        asyncio.to_thread(spell_file.load, settings.eql_game_dir)))
    tasks.append(asyncio.create_task(_load_exalt_effects()))
    ocr_watcher = OcrWatcher(tracker, ws_manager)
    tasks.append(asyncio.create_task(ocr_watcher.run()))
    tasks.append(asyncio.create_task(event_flush_loop()))
    tasks.append(asyncio.create_task(db_writer_loop()))

    yield

    if watcher:
        session_state.save(tracker, str(watcher.path), watcher._offset)
        watcher.stop()
    if _watcher_task:
        _watcher_task.cancel()
    ocr_watcher.stop()
    for t in tasks:
        t.cancel()


APP_VERSION = "1.10.0"  # bump together with frontend/lib/version.ts
GITHUB_REPO = "EKirschmann/eql_companion"

app = FastAPI(title="EQL Companion", version=APP_VERSION, lifespan=lifespan)

# Single-process mode: if the frontend has been static-exported (the exe /
# same-origin build), serve it from this same server. Mounted AFTER all
# /api and /ws routes are registered (done at import end).
def _mount_static_ui() -> None:
    from fastapi.staticfiles import StaticFiles
    ui = Path(__file__).resolve().parent.parent / "frontend" / "out"
    if ui.is_dir():
        app.mount("/", StaticFiles(directory=str(ui), html=True), name="ui")
        logger.info("Serving static UI from %s", ui)


app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------- API

class ChatRequest(BaseModel):
    message: str


class CharacterPatch(BaseModel):
    playstyle: Optional[str] = None
    class_str: Optional[str] = None
    race: Optional[str] = None
    level: Optional[int] = None
    aa_available: Optional[int] = None
    spell_slots: Optional[int] = None
    pet_slots: Optional[int] = None
    pet_classes: Optional[str] = None
    max_hp: Optional[int] = None    # user-reported from the in-game UI
    max_mana: Optional[int] = None


@app.get("/health")
async def health():
    growth = watcher.last_growth if watcher else None
    return {"status": "ok",
            "watching": watcher.path.name if watcher else None,
            "log_last_growth": growth.isoformat() if growth else None,
            "log_stalled_s": (round((datetime.now() - growth).total_seconds())
                              if growth else None)}


@app.get("/api/character")
async def get_character():
    return tracker.snapshot()


@app.patch("/api/character")
async def patch_character(patch: CharacterPatch, db: Session = Depends(get_db)):
    row = _sync_character_row(db)
    for field in ("playstyle", "class_str", "race", "level",
                  "aa_available", "spell_slots", "pet_slots", "pet_classes",
                  "max_hp", "max_mana"):
        value = getattr(patch, field)
        if value is not None:
            setattr(row, field, value)
            setattr(tracker, field, value)
    if patch.class_str is not None:  # manual trio edit resolves the mismatch hint
        tracker.unknown_casts.clear()
        tracker.loadout_hint = None
    if patch.pet_slots is not None:
        # setting a slot count means a (re)configured pet — drop any stale
        # equipped list; /pet inventory check repopulates it
        tracker.pet_inventory = {}
    db.commit()
    await ws_manager.broadcast({"type": "state", "data": tracker.snapshot()})
    return tracker.snapshot()


class CharacterSelect(BaseModel):
    file: str


@app.get("/api/characters")
async def list_characters():
    """Every character with a log file, newest first (/log on in-game creates one)."""
    return {"characters": _scan_log_characters(),
            "active_file": watcher.path.name if watcher else None}


@app.post("/api/character/select")
async def select_character(body: CharacterSelect):
    if not await switch_character(body.file):
        raise HTTPException(status_code=404,
                            detail=f"No log file {body.file} — type /log on in-game first")
    return tracker.snapshot()


@app.get("/api/aas")
async def get_owned_aas():
    """Owned AA ranks parsed from /alternateadv list output in the log."""
    return {"available": bool(tracker.owned_aas),
            "synced": tracker._last_aa_seen.isoformat() if tracker._last_aa_seen else None,
            "aas": [{"name": n, **v} for n, v in sorted(tracker.owned_aas.items())]}


@app.post("/api/aas/rescan")
async def rescan_aas():
    """Deep-scan the whole log for the most recent /alternateadv list burst
    (the startup replay only covers the last 1MB)."""
    if not watcher:
        raise HTTPException(status_code=400, detail="No log is being watched")

    def scan(path: Path):
        data = path.read_bytes()
        idx = data.rfind(b"] Ability #")
        if idx < 0:
            return None
        lo = max(0, data.rfind(b"\n", 0, max(0, idx - 300_000)) + 1)
        return data[lo:min(len(data), idx + 400_000)].split(b"\n")

    lines = await asyncio.to_thread(scan, watcher.path)
    if lines is None:
        return {"found": False,
                "reason": "No /alternateadv list output anywhere in the log"}
    for bline in lines:
        line = bline.decode("utf-8", "replace")
        if ("Ability #" not in line and "Description:" not in line
                and "Cost per Level:" not in line):
            continue
        e = parse_line(line, tracker.name)
        if e and e.type in ("aa_list", "aa_meta"):
            tracker.apply(e, live=False)
    return {"found": True,
            "synced": tracker._last_aa_seen.isoformat() if tracker._last_aa_seen else None,
            "distinct": len(tracker.owned_aas)}


@app.get("/api/exports")
async def get_exports():
    """Presence + freshness of every /outputfile export kind."""
    return exports_status(tracker.name, tracker.server)


@app.post("/api/exports/refresh")
async def refresh_exports():
    """Fresh directory scan — the 'check exports' button after running the
    in-game macro (/outputfile achievements|inventory|missingspells|spellbook)."""
    clear_find_cache()
    asyncio.create_task(_load_exalt_effects())
    return exports_status(tracker.name, tracker.server)


@app.get("/api/spellsets")
async def get_spellsets():
    """Saved in-game spell sets from the character's LO*.ini, ids decoded."""
    from backend import builds_data
    from backend.spellsets import find_loadout_ini, read_spell_sets
    path = find_loadout_ini(tracker.name, tracker.server)
    if not path:
        return {"available": False,
                "reason": "no <name>_<server>_LO*.ini in the game folder"}
    sets = await asyncio.to_thread(read_spell_sets, path)
    for s in sets:
        s["spells"] = [builds_data.spell_name(i) or f"#{i}"
                       for i in s.pop("spell_ids")]
    return {"available": True, "file": path.name, "sets": sets}


@app.post("/api/spellsets/generate")
async def generate_spellset(body: dict | None = None):
    """Write the advisor's Memorize-now list as an in-game spell set.
    One command in game then loads the whole bar: /memspellset <name>."""
    from backend import builds_data
    from backend.spellsets import find_loadout_ini, write_spell_set
    from backend.agent.advisor import _permanent_buffs, stack_gem_order
    from backend.game_data import _primary_effect as game_data_primary
    from backend.game_data import supersedes_for_slots
    source = ((body or {}).get("source") or "loadout").strip()
    default_name = "prebuffs" if source == "prebuffs" else "companion"
    name = ((body or {}).get("name") or default_name).strip()[:24]
    if _advice_cache is None:
        raise HTTPException(400, "no counsel cached — press Consult first")
    chosen = (body or {}).get("names")  # webapp checkbox selection
    if source == "prebuffs":
        # counsel picks + every owned permanent self-buff + timed buffs of
        # 20min or longer (Spirit Armor / Regeneration class) — dedupe, with
        # permanents first, then longest duration
        book = load_spellbook(tracker.name, tracker.server) or {}
        ctx_b = {"spellbook": book, "level": tracker.level}
        perm = _permanent_buffs(ctx_b)
        timed = []
        for s in book.get("castable", []):
            if tracker.level is not None and s["level"] > tracker.level:
                continue
            e = builds_data.spell_entry(s["name"])
            if not e or e.get("targetTypeId") not in (6, 51):
                continue  # beneficial self/ally only — no charms, no enemy DoTs
            pe = game_data_primary(e)
            if pe and pe[0] in (12, 13, 28):
                continue  # invisibility lines (incl. IVU): situational
            t = e.get("durationTicks") or 0
            if t > 0:  # any timed buff — longest first fills toward 14
                timed.append((t, s["name"]))
        timed.sort(reverse=True)
        llm_extra = [p.get("name") for p in _advice_cache.get("prebuffs") or []]
        ordered, seen = [], set()
        for n in perm + [n for _, n in timed] + llm_extra:
            if n and n not in seen:
                seen.add(n)
                ordered.append(n)
        # rank-family dedupe: Minor/Lesser/Greater prefixes and roman-numeral
        # suffixes are ranks of one line — keep the highest-level owned one.
        # (Effect comparison can't do this: the line's PRIMARY effect changes
        # between ranks, e.g. Minor Shielding leads with AC, Shielding with HP.)
        def rank_base(n: str) -> str:
            words = n.lower().split()
            while words and words[0] in ("minor", "lesser", "greater", "major"):
                words = words[1:]
            while words and words[-1] in ("i", "ii", "iii", "iv", "v"):
                words = words[:-1]
            return " ".join(words)

        lvl_of = {s["name"]: s["level"] for s in book.get("castable", [])}
        best: dict = {}
        for n in ordered:
            k = rank_base(n)
            if k not in best or (lvl_of.get(n, 0) > lvl_of.get(best[k], 0)):
                best[k] = n
        kept = [n for n in ordered if best.get(rank_base(n)) == n]
        # plus the effect-based gate for cross-name lines (Lesser Shielding
        # would also fall here when class sets align)
        picks = []
        for n in kept:
            superseded = False
            for other in kept:
                if other != n and await supersedes_for_slots(n, other):
                    superseded = True
                    break
            if not superseded:
                picks.append({"name": n})
        if not picks:
            raise HTTPException(400, "no pre-buffs found (spellbook export missing?)")
    elif chosen:
        picks = [{"name": n} for n in stack_gem_order([str(x) for x in chosen])]
    else:
        names = [p.get("name") for p in
                 ((_advice_cache.get("must_have") or [])
                  + (_advice_cache.get("should_have") or []))]
        picks = [{"name": n} for n in stack_gem_order([n for n in names if n])]
        if not picks:
            raise HTTPException(400, "the cached counsel has no loadout picks")
    path = find_loadout_ini(tracker.name, tracker.server)
    if not path:
        raise HTTPException(404, "no LO*.ini found in the game folder")
    ids, written, skipped = [], [], []
    for pck in picks:
        if len(ids) >= 14:
            break
        sid = builds_data.spell_id(pck.get("name"))
        if sid is None:
            skipped.append(pck.get("name"))
        else:
            ids.append(sid)
            written.append(pck.get("name"))
    if not ids:
        raise HTTPException(500, "could not resolve any spell ids "
                                 "(eqlbuilds snapshot missing?)")
    try:
        result = await asyncio.to_thread(write_spell_set, path, name, ids)
    except ValueError as e:
        raise HTTPException(500, str(e))
    return {**result, "written": written, "skipped": skipped,
            "memspellset": f"/memspellset {name}",
            "note": "The game reads this file at login — if the character "
                    "is logged in, camp to character select and back "
                    "before /memspellset (logging out overwrites the file)."}


@app.get("/api/spellbook")
async def get_spellbook():
    """Parsed /outputfile spellbook export for the active character."""
    book = load_spellbook(tracker.name, tracker.server)
    if not book:
        return {"available": False,
                "reason": "No spellbook export — type /outputfile spellbook in-game"}
    return {"available": True, **book}


@app.get("/api/events")
async def get_events(limit: int = 100):
    items = list(tracker.ledger)[-limit:]
    return {"events": items}


@app.get("/api/encounters")
async def get_encounters(limit: int = 50, db: Session = Depends(get_db)):
    """Persisted fight history for this character (newest first)."""
    if not _character_id:
        return {"encounters": []}
    rows = (db.query(LogEventRow)
            .filter(LogEventRow.character_id == _character_id,
                    LogEventRow.event_type == "encounter")
            .order_by(LogEventRow.id.desc()).limit(limit).all())
    return {"encounters": [r.payload for r in rows]}


def _parse_ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


@app.get("/api/update-check")
async def update_check():
    """Compare the running version against the newest GitHub tag. On-demand
    (the version badge in the header triggers it) — never automatic."""
    import ssl
    import urllib.request

    def _ctx():
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def fetch_api():
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=30",
            headers={"User-Agent": "eql-companion", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15, context=_ctx()) as r:
            return [str(t.get("name", "")).lstrip("v")
                    for t in json.loads(r.read())]

    def fetch_page():
        # no-API fallback: the public tags page. Unauthenticated API calls
        # are capped at 60/hour PER IP — guildmates behind shared IPs hit
        # 403s the plain website never imposes.
        req = urllib.request.Request(
            f"https://github.com/{GITHUB_REPO}/tags",
            headers={"User-Agent": "eql-companion"})
        with urllib.request.urlopen(req, timeout=15, context=_ctx()) as r:
            html = r.read().decode("utf-8", "replace")
        return [m.lstrip("v") for m in
                re.findall(rf"/{GITHUB_REPO}/releases/tag/v?([0-9.]+)", html)]
    latest = None
    err = None
    for fetch in (fetch_api, fetch_page):
        try:
            names = await asyncio.to_thread(fetch)
            latest = max((n for n in names if n), key=_parse_ver, default=None)
            if latest:
                break
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
    if latest is None:
        return {"current": APP_VERSION, "latest": None,
                "error": f"could not reach GitHub ({err or 'no tags found'})"}
    newer = latest is not None and _parse_ver(latest) > _parse_ver(APP_VERSION)
    return {"current": APP_VERSION, "latest": latest, "update_available": newer,
            "how": "close the companion and run update_companion.bat" if newer else None}


@app.post("/api/update/run")
async def run_update():
    """Launch the updater in its own console window (visible progress,
    survives the backend restarting under it). update_companion.bat routes
    git installs to git pull and ZIP installs to the Python downloader."""
    import subprocess
    bat = Path(__file__).resolve().parent.parent / "update_companion.bat"
    if not bat.exists():
        raise HTTPException(404, "update_companion.bat not found")
    subprocess.Popen(
        ["cmd", "/c", "start", "EQL Companion update", str(bat)],
        cwd=str(bat.parent),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return {"launched": True,
            "note": "Updating in a separate window — the app restarts "
                    "itself; refresh this page when the window says done."}


@app.get("/api/llm")
async def api_llm_get():
    from backend.llm_runtime import active, custom_model, openai_model
    options = [
        {"provider": "none", "model": "builtin",
         "label": "None — deterministic (no LLM)"},
        {"provider": "lmstudio", "model": settings.model,
         "label": f"Local — {settings.model}"},
        {"provider": "openai", "model": openai_model(),
         "label": f"OpenAI — {openai_model()}"},
    ]
    if settings.custom_base_url:
        options.append({"provider": "custom", "model": custom_model(),
                        "label": f"Custom — {custom_model()}"})
    return {
        "active": active(),
        "options": options,
        "openai_key_set": bool(settings.openai_api_key),
    }


@app.post("/api/llm")
async def api_llm_set(body: dict):
    """Switch the counsel model (Advisor tab). Clears the advice caches so
    the next consult regenerates with the newly selected model."""
    from backend.llm_runtime import active, set_active
    provider = (body.get("provider") or "").strip()
    if provider not in ("none", "lmstudio", "openai", "custom"):
        raise HTTPException(400, "provider must be none|lmstudio|openai|custom")
    global _advice_cache, _gear_cache
    set_active(provider, body.get("model"))
    _advice_cache = None
    _gear_cache = None
    _save_advice_cache()
    return {"active": active(), "openai_key_set": bool(settings.openai_api_key)}


@app.get("/api/hunting")
async def api_hunting(level: int | None = None):
    """In-era hunting zones bracketing the level, for the leveling chart.
    Deterministic (community Recommended-Levels table) — no LLM involved."""
    lv = level if level is not None else tracker.level
    if not lv:
        return {"level": None, "zones": []}
    try:
        zones = await hunting_candidates(int(lv))
    except Exception:
        zones = []
    return {"level": int(lv), "zones": zones}


@app.get("/api/advisor")
async def get_advisor(refresh: bool = False, cached: bool = False):
    """Structured counsel: spells, AA spending, horizon, zone picks.
    Cached until the character context changes or ?refresh=1.
    cached=1: return the cached counsel if fresh, else {"cached": false}
    WITHOUT running the LLM — the tab restores results on load with it."""
    global _advice_cache, _advice_sig
    book = load_spellbook(tracker.name, tracker.server)
    inv_sig = load_export(tracker.name, tracker.server, "Inventory")
    miss_sig = load_export(tracker.name, tracker.server, "MissingSpells")
    sig = (tracker.class_str, tracker.level, tracker.playstyle, tracker.zone,
           tracker.aa_available, tracker.spell_slots,
           book["updated"] if book else None, tracker._last_aa_seen,
           inv_sig["updated"] if inv_sig else None,
           miss_sig["updated"] if miss_sig else None)
    sig = _sig_norm(sig)
    if _advice_cache is not None and _advice_sig == sig and not refresh:
        return {**_advice_cache, "stale": False}
    if cached:
        # serve the last counsel even when the context moved on (zone/level/
        # exports) — marked stale so the tab can offer a reconsult instead
        # of forcing one
        if _advice_cache is not None:
            return {**_advice_cache, "stale": True}
        return {"cached": False}
    ctx = {
        "name": tracker.name, "race": tracker.race,
        "class_str": tracker.class_str, "level": tracker.level,
        "playstyle": tracker.playstyle, "zone": tracker.zone,
        "aa_available": tracker.aa_available, "spell_slots": tracker.spell_slots,
        "recent_activity": tracker.recent_activity_summary(),
        "recent_casts": tracker.recent_casts(),
        "spellbook": book,
        "owned_aas": tracker.owned_aas,
    }
    inv = load_export(tracker.name, tracker.server, "Inventory")
    if inv and inv.get("worn"):
        ctx["inventory_worn"] = inv["worn"]
    miss = load_export(tracker.name, tracker.server, "MissingSpells")
    if miss and tracker.level:
        ctx["missing_spells"] = [
            s for s in miss["castable"] if s["level"] <= tracker.level + 3][:25]
    advice = await generate_advice(ctx)
    # deterministic vendor list: missing spells are buyable (and scribable)
    # BEFORE their level — compact reminder, not LLM-generated
    lvl = tracker.level
    advice["purchase"] = sorted(
        ({"name": s["name"], "level": s["level"],
          "now": lvl is None or s["level"] <= lvl}
         for s in ctx.get("missing_spells") or []
         # near-level window only: low-level leftovers were skipped on purpose
         if lvl is None or s["level"] >= lvl - 2),
        key=lambda x: -x["level"])[:8]
    _advice_cache, _advice_sig = advice, sig
    _save_advice_cache()
    return advice


@app.get("/api/gear")
async def get_gear(refresh: bool = False, cached: bool = False):
    """Equipment counsel: best owned item per slot + farming targets.
    Slower than /api/advisor on first run (mines item pages from the wiki).
    cached=1: return the cached counsel if fresh, else {"cached": false}
    WITHOUT running the LLM — the tab uses it to restore results on load."""
    global _gear_cache, _gear_sig
    inv = load_export(tracker.name, tracker.server, "Inventory")
    sig = (tracker.class_str, tracker.level, tracker.race, tracker.pet_slots,
           tracker.max_hp, tracker.max_mana,
           tuple(sorted(tracker.pet_inventory.items())),
           inv["updated"] if inv else None)
    sig = _sig_norm(sig)
    if _gear_cache is not None and _gear_sig == sig and not refresh:
        return {**_gear_cache, "stale": False}
    if cached:
        if _gear_cache is not None:
            return {**_gear_cache, "stale": True}
        return {"cached": False}
    ctx = {"class_str": tracker.class_str, "level": tracker.level,
           "race": tracker.race, "playstyle": tracker.playstyle,
           "worn": (inv or {}).get("worn"),
           "inventory_items": (inv or {}).get("items"),
           "exaltations": (inv or {}).get("exaltations"),
           "pet_slots": tracker.pet_slots,
           "pet_classes": tracker.pet_classes,
           "pet_inventory": dict(tracker.pet_inventory),
           "max_hp": tracker.max_hp, "max_mana": tracker.max_mana,
           "combat": tracker.combat_profile()}
    advice = await generate_gear_advice(ctx)
    _gear_cache, _gear_sig = advice, sig
    _save_advice_cache()
    return advice


@app.get("/api/item-acquisition")
async def get_item_acquisition(name: str):
    """Where an item comes from (drops/vendors/quests/crafting) — feeds
    the gear-tab hover cards. Wiki-mined, cached."""
    from backend.game_data import item_acquisition
    return await item_acquisition(name)


@app.get("/api/map")
async def get_map(zone: Optional[str] = None):
    """Vector map data for a zone (defaults to the character's current zone)."""
    target = zone or tracker.zone
    if not target:
        return {"available": False, "zone": None,
                "reason": "No zone known yet — enter a zone or pass ?zone="}
    data = load_map(target)
    if data is None:
        return {"available": False, "zone": normalize_zone(target),
                "reason": "No chart exists for this place"}
    return {"available": True, **data}


@app.get("/api/geometry")
async def get_zone_geometry(zone: Optional[str] = None):
    """Client-mined 2D wall/floor geometry (defaults to the current zone).
    Extraction runs in a worker thread and caches to data/geometry/."""
    target = zone or tracker.zone
    if not target:
        return {"available": False, "zone": None,
                "reason": "No zone known yet — enter a zone or pass ?zone="}
    data = await asyncio.to_thread(geometry_for_zone, target)
    if data is None:
        return {"available": False, "zone": normalize_zone(target),
                "reason": "No client geometry for this place"}
    return data


@app.get("/api/geometry3d")
async def get_zone_geometry3d(zone: Optional[str] = None):
    """Full 3D triangle soup (floors/ramps/walls/props; ceilings excluded)."""
    target = zone or tracker.zone
    if not target:
        return {"available": False, "zone": None,
                "reason": "No zone known yet — enter a zone or pass ?zone="}
    data = await asyncio.to_thread(geometry3d_for_zone, target)
    if data is None:
        return {"available": False, "zone": normalize_zone(target),
                "reason": "No client geometry for this place"}
    return data


@app.get("/api/texture/{short}/{name}")
async def get_zone_texture(short: str, name: str):
    """Zone texture PNGs exported during 3D extraction."""
    import re as _re
    if not (_re.fullmatch(r"[a-z0-9_]+", short) and _re.fullmatch(r"[a-z0-9_.-]+", name)):
        raise HTTPException(status_code=400, detail="bad texture path")
    path = Path("data") / "textures" / short / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such texture")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/zones")
async def get_zones():
    """Zones known to the travel graph (for the route search box)."""
    return {"zones": known_zones()}


class OcrRegion(BaseModel):
    left: int
    top: int
    width: int
    height: int


class OcrEnabled(BaseModel):
    enabled: bool


@app.get("/api/ocr/status")
async def ocr_status():
    return ocr_watcher.status()


@app.post("/api/ocr/region")
async def ocr_set_region(region: OcrRegion):
    cfg = ocr_load_config()
    cfg.update(region.model_dump())
    ocr_save_config(cfg)
    return ocr_watcher.status()


@app.post("/api/ocr/enabled")
async def ocr_set_enabled(body: OcrEnabled):
    cfg = ocr_load_config()
    cfg["enabled"] = body.enabled
    ocr_save_config(cfg)
    return ocr_watcher.status()


@app.get("/api/ocr/preview")
async def ocr_preview():
    """One-shot capture + OCR of the configured region (for calibration)."""
    cfg = ocr_load_config()
    try:
        text = await ocr_region(cfg)
        return {"text": text, "parsed": parse_loc_text(text) if text else None}
    except Exception as e:
        return {"text": None, "parsed": None, "error": str(e)[:200]}


_overlay_proc = None


@app.post("/api/overlay")
async def toggle_combat_overlay():
    """Toggle the always-on-top combat strip (backend/overlay.py): one press
    launches it, the next press closes it — never a second copy."""
    global _overlay_proc
    import subprocess
    import sys as _sys
    if _overlay_proc is not None and _overlay_proc.poll() is None:
        _overlay_proc.terminate()
        try:
            _overlay_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _overlay_proc.kill()
        _overlay_proc = None
        return {"running": False}
    _overlay_proc = subprocess.Popen(
        [_sys.executable, "-m", "backend.overlay"],
        cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return {"running": True}


@app.get("/api/overlay")
async def overlay_status():
    return {"running": _overlay_proc is not None and _overlay_proc.poll() is None}


@app.post("/api/ocr/overlay")
async def ocr_launch_overlay():
    """Launch the on-screen calibration box (backend/ocr_overlay.py)."""
    import subprocess
    import sys as _sys
    subprocess.Popen(
        [_sys.executable, "-m", "backend.ocr_overlay"],
        cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return {"launched": True}


@app.get("/api/route")
async def get_route(to: str, frm: Optional[str] = None):
    """Shortest zone-hop route. `frm` defaults to the current zone."""
    start = frm or tracker.zone
    if not start:
        return {"path": None, "reason": "Current zone unknown"}
    path = find_route(start, to)
    if path is None:
        return {"path": None,
                "reason": f"No known route from {normalize_zone(start)} to {normalize_zone(to)}"}
    return {"path": path}


@app.get("/api/chat/history")
async def chat_history(limit: int = 40, db: Session = Depends(get_db)):
    if not _character_id:
        return {"messages": []}
    rows = (db.query(ChatMessageRow)
            .filter(ChatMessageRow.character_id == _character_id)
            .order_by(ChatMessageRow.id.desc()).limit(limit).all())
    return {"messages": [r.to_dict() for r in reversed(rows)]}


@app.post("/api/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    # Build profile from live tracker state
    classes = (tracker.class_str or "").split("/")
    classes += [None] * (3 - len(classes))
    profile: ProfileData = {
        "id": _character_id or 0,
        "race": tracker.race or "Unknown",
        "primary_class": (classes[0] or "Unknown").strip(),
        "secondary_class": (classes[1] or "").strip() or None,
        "tertiary_class": (classes[2] or "").strip() or None,
        "level": tracker.level or 1,
        "playstyle": tracker.playstyle or "balanced",
    }

    history = []
    if _character_id:
        rows = (db.query(ChatMessageRow)
                .filter(ChatMessageRow.character_id == _character_id)
                .order_by(ChatMessageRow.id.desc()).limit(10).all())
        history = [{"role": r.role, "content": r.content} for r in reversed(rows)]

    activity = tracker.recent_activity_summary()
    book = load_spellbook(tracker.name, tracker.server)
    if book:
        latest = ", ".join(s["name"] for s in book["castable"][-10:])
        activity += (f" Spellbook export: {len(book['castable'])} spells castable "
                     f"by the current trio (highest: {latest}).")

    state: AgentState = {
        "profile": profile,
        "messages": history + [{"role": "user", "content": request.message}],
        "current_zone": tracker.zone,
        "recent_activity": activity,
        "spell_suggestions": [], "aa_suggestions": [],
        "zone_suggestions": [], "gear_suggestions": [],
        "reasoning": None, "sources_cited": [], "error": None,
    }

    try:
        result = await get_agent().ainvoke(state)
    except Exception as e:
        logger.exception("Agent failed")
        raise HTTPException(status_code=500, detail=f"Companion error: {str(e)[:200]}")

    # Last assistant message is the reply (handles dicts and Message objects)
    reply = "The companion has nothing to say."
    for msg in reversed(result.get("messages", [])):
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", None)
        if role in ("assistant", "ai") and content:
            reply = content
            break

    if _character_id:
        db.add(ChatMessageRow(character_id=_character_id, role="user", content=request.message))
        db.add(ChatMessageRow(character_id=_character_id, role="assistant", content=reply))
        db.commit()

    return {
        "response": reply,
        "suggestions": {
            "spells": result.get("spell_suggestions", []),
            "aas": result.get("aa_suggestions", []),
            "zones": result.get("zone_suggestions", []),
        },
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "hello", "data": tracker.snapshot()})
        while True:
            await ws.receive_text()  # keepalive / ignore client messages
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)

_mount_static_ui()
