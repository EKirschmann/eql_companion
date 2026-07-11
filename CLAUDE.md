# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# EQL Companion App — Real-Time Log-Aware Assistant

A real-time AI companion for EverQuest Legends that watches your combat logs, learns your character, and provides contextual advice on spells, AAs, and leveling zones. **Status: built and smoke-tested end-to-end (2026-07-05).**

**Architecture**: FastAPI backend + polling log tailer + LangGraph agent + Next.js frontend + WebSocket real-time updates.

**Character auto-detection**: the backend scans the log dir, picks the most recent `eqlog_<Name>_<server>.txt` (currently `eqlog_Gentso_rivervale.txt`), and derives name + server from the filename. No manual profile creation. Level/class are learned from `/who` lines — the FULL trio, abbreviations expanded. /who is authoritative (it always overwrites a saved trio) because loadout swaps write nothing else to the log; tell the user to type `/who` once after swapping classes or if level shows "?". If 2+ distinct cast spells are not castable by the saved trio (checked against each spell's own wiki page, cached 24h), `loadout_hint` appears in the snapshot and as a warning in the Vitals panel; cleared by /who or a manual trio edit.

---

## Quick Start

### Prerequisites
- Python 3.11+ (**conda env: `eql-companion`** — already created; deps in `requirements.txt`)
- Node.js 18+ (frontend deps already installed via `npm install` in `frontend/`)
- Anthropic API key in `.env` (`ANTHROPIC_API_KEY=...`) — **optional**: without credits the agent falls back to deterministic formatting
- EQL logs at: `G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs\eqlog_*.txt`

### Commands

**Terminal 1 — Backend (FastAPI + WebSocket on :8000)**:
```powershell
conda activate eql-companion
cd G:\projects\eql_mods
uvicorn backend.main:app --reload
```

**Terminal 2 — Frontend (Next.js on :3000)**:
```powershell
cd G:\projects\eql_mods\frontend
npm run dev
```

Then open **http://localhost:3000**. The MCP server is NOT required to run the app (agent tools currently use built-in data; MCP integration is a plugin point — see below).

---

## Architecture

### Backend Structure (actual files)

```
backend/
├── main.py                  # FastAPI app, REST + /ws WebSocket, lifespan starts the tailer
├── config.py                # pydantic-settings; log dir, LLM provider/model, DB URL
├── models.py                # SQLAlchemy: Character, ChatMessageRow, LogEventRow
├── state_tracker.py         # CharacterTracker — in-memory session state, DPS, ledger buffer
├── ws_manager.py            # WSManager — connection list + broadcast
├── cache.py                 # TTL cache (used when MCP/wiki tools come online)
├── mcp_client.py            # stdio JSON-RPC client for the EQL MCP server (wired)
├── game_data.py             # wiki→compact advisor context (spells/AAs), 24h cache
│
├── log_system/
│   ├── __init__.py          # re-exports parse_line, LogWatcher, discover_log_file
│   ├── events.py            # Pydantic event models (~20 types)
│   ├── parser.py            # ALL regex patterns live here — one table to patch
│   └── watcher.py           # polling tailer (0.4s), binary offsets, 1MB seed replay
│
├── map_system.py            # Atlas backend: map-file parsing + zone travel graph (BFS routing)
├── geometry_system.py       # "True walls": .s3d/.wld mesh extraction → 2D floors/walls JSON
│
└── agent/
    ├── state.py             # AgentState TypedDict (profile, messages, suggestions)
    ├── tools.py             # spell/AA/zone suggestion tools (built-in data for now)
    ├── advisor.py           # Advisor tab: wiki-grounded LLM counsel (strict JSON)
    ├── prompts.py           # system + task prompt templates
    └── graph.py             # LangGraph: gather → respond; _build_llm() = model seam

frontend/                    # Next.js 14 app router, TypeScript, plain CSS (no Tailwind)
├── app/
│   ├── layout.tsx           # fonts: Cinzel / IBM Plex Sans / IBM Plex Mono (next/font)
│   ├── globals.css          # StoneGlass design tokens — ALL styling lives here
│   └── page.tsx             # dashboard: header + 3-panel HUD grid
├── components/
│   ├── CharacterPanel.tsx   # level, DPS gauge, stat tiles, loot, per-mob hunting, playstyle
│   ├── AtlasPanel.tsx       # canvas zone map + route finder (center, default tab)
│   ├── CompanionPanel.tsx   # chat + suggestion groups (center, second tab)
│   ├── AdvisorPanel.tsx     # class-trio counsel: spells/AAs/horizon (center, third tab)
│   ├── WarLedger.tsx        # live combat feed — newest on top, 50 rows, "Mine only" filter
│   └── EncounterPanel.tsx   # last-5 pulls: per-mob dmg, arrows, ability+healing aggregate, group DPS, death recap
├── hooks/useWebSocket.ts    # auto-reconnecting WS hook
└── lib/                     # api.ts (fetch helpers, URLs), types.ts (shared shapes)

data/companion.db            # SQLite (characters, chat_messages, log_events)
```

**Design system note**: the frontend deliberately reuses the StoneGlass in-game
skin tokens (dark glass `rgba(18,21,26,.82)`, gold `#c8aa6e`, hairline
`rgba(200,170,110,.34)`, flat square-ended gauges, zero border-radius).
Semantic ledger colors: out-damage gold `#c8aa6e`, in-damage `#d4574a`, heal
`#1fb38c`, cast `#b07cc6` — all validated ≥3:1 contrast on the dark surface.
Old Gradio prototype was removed.

---

## Core Components

### 1. Log Watching & Parsing (`backend/log_system/`)

**Responsibility**: Tail `eqlog_*.txt`, parse events, hand them to `main.on_log_event`.

#### `watcher.py`
- **Polling tailer** (0.4s), not watchdog — reliable on all Windows filesystems
- Binary reads with byte offsets; partial lines buffered; handles truncation/rotation
- On startup, `seed()` replays the last 1MB of log history to establish zone/level/class and pre-fill the ledger (seed events don't count toward session stats)
- `discover_log_file()` picks the log: configured character's file, else most recent

#### `parser.py` — **verified against the real EQL log (2026-07-05, 765 events parsed)**
All patterns in one table at the top of the file. EQL-specific formats confirmed live:
```
You crush a dread bone for 19 points of damage.              → melee_out
A dread bone kicks YOU for 1 point of damage.                → melee_in
You try to crush a dread bone, but miss!                     → miss_out (hit-rate stat)
A dread bone tries to punch YOU, but misses!                 → miss_in
A dread bone has taken 32 damage from your Stinging Swarm.   → dot_out  (EQL DoT tick)
You gain experience! (1.107%)                                → exp with exact percent
You looted an X +2 from the Y's corpse to create an X +3     → loot (EQL upgrade system)
You receive 7 copper from the corpse.                        → coin
You begin casting Stinging Swarm.                            → cast
You have slain a dread bone!                                 → kill
[21 PAL/DRU/MNK] Gentso (Iksar) <Guild> ZONE: ...            → char_info (/who; abbrevs expand to Paladin/Druid/Monk)
```
Other players' hits ARE parsed (type `other_out`: melee/spell/dot with attacker) but never broadcast or ledgered — they only feed per-encounter group DPS. Pets fold into owners: `<Name> pet` convention plus definitive `"My leader is X"` lines (`/pet leader`) — own pets count as player damage (`Pet: <source>` rows), others' pets add to their owner's ally row. Non-events by design: mob-vs-mob, channel chat, flavor
text ("The darkness fades."). ~12% of a busy-zone log is our character — that's correct.

#### `events.py`
- Pydantic model per event type; `model_dump(mode="json")` is the WS payload
- Frontend switches on the `type` string — keep types stable

### 2. Character State (`state_tracker.py` + `models.py`)

**`CharacterTracker`** (in-memory, authoritative for the UI):
- Identity: name/server from filename; level/class/race from `/who` lines or user edits
- Session counters (live events only): damage dealt/taken, healing, kills, deaths,
  XP ticks + summed XP percent, AA points, skill-ups, hit-rate (hits vs misses), loot list
- Rolling 60s DPS window + `in_combat` flag (damage within 8s)
- `ledger`: last 300 events (the War Ledger feed)
- `recent_activity_summary()`: prose summary of notable events, injected into the agent prompt

**Database** (`models.py` — new-named tables; old Gradio-era `profiles`/`conversations` tables are dead, delete `data/companion.db` to purge):
- `characters`: one row per character; persists playstyle/class enrichment across restarts
- `chat_messages`: companion conversation history
- `log_events`: **milestones only** (zone/level/kill/death/aa/loot/skill) — per-hit spam never touches the DB

### 3. LangGraph Agent (`backend/agent/`)

**Responsibility**: Reason about character + log context, suggest actions.

#### `prompts.py`
- **System prompt**: Tells Claude/LLM the role + EQL facts
- **User prompts**: Templates for spell/AA/zone suggestions
- **Context injection**: Add character state + recent combat to every prompt

**Model swapping**: set `LLM_PROVIDER` + `MODEL` in `.env` — the single code seam
is `_build_llm()` in `graph.py` (full walkthrough in the "Model Swapping" section below).

**Extensibility**:
- Add new prompt templates for new suggestion types
- Add few-shot examples per model (OpenAI vs. Claude behave differently)

#### `tools.py`
- `get_spell_suggestions(profile, context)` — Returns prioritized spells
- `get_aa_suggestions(profile, context)` — Returns tiered AAs
- `get_leveling_zone_suggestions(profile, context)` — Returns zones
- `(future) get_gear_suggestions()` — Gear recs based on drops in logs

**Context parameter**: Can include recent combat, current zone, learned spells, etc.

**Extensibility**:
- Add new tools (e.g., `get_macro_suggestions`, `get_build_score`)
- Pass more context from logs (e.g., "last 10 mobs killed", "DPS over last minute")
- Tool outputs can be cached or memoized

#### `graph.py`
- LangGraph state machine: `process_user_input` → `route_to_tools` → `format_response`
- Each step is a node; edges define flow
- State contains profile + messages + suggestions

**Extensibility**:
- Add new nodes (e.g., `analyze_combat_logs`, `identify_weak_stats`)
- Add conditional routing (e.g., "if user asks about combat, analyze recent logs")
- Add memory management (e.g., summarize old conversations)

### 4. API + WebSocket (`main.py`, `ws_manager.py`)

**REST** (CORS open to `http://localhost:3000`):
- `GET /health` — `{status, watching: "<logfile>"}`
- `GET /api/character` — full tracker snapshot (see shape below)
- `PATCH /api/character` — set `playstyle` / `class_str` / `race` / `level` / `aa_available` / `spell_slots` manually
- `GET /api/characters` — every character with a log file (newest first) + active file
- `POST /api/character/select` `{file}` — retarget tailer/tracker to another log (per name+server DB profile)
- `GET /api/events?limit=100` — recent ledger rows (for initial page load)
- `GET /api/encounters?limit=50` — persisted fight history (event_type='encounter' milestones)
- `GET /api/chat/history?limit=40` — saved companion conversation
- `POST /api/chat` `{message}` — returns `{response, suggestions:{spells,aas,zones}}`
- `GET /api/map?zone=` — vector map (defaults to current zone): `{available, zone, lines, points, bounds}`
- `GET /api/zones` — travel-graph zone list (route search datalist)
- `GET /api/route?to=&frm=` — BFS zone path (`frm` defaults to current zone)
- `GET /api/geometry?zone=` — client-mined 2D wall/floor geometry with floor bands (cached in `data/geometry/`)
- `GET /api/geometry3d?zone=` — textured 3D submeshes (floors/ramps/walls/props; ceilings never shipped)
- `GET /api/texture/{short}/{name}` — zone texture PNGs exported during 3D extraction (`data/textures/`)
- `GET /api/advisor?refresh=` — structured counsel JSON (see Advisor section)
- `GET /api/spellbook` — parsed `/outputfile spellbook` export (owned spells; levels = castable by current trio, 255 = other loadouts)
- `GET /api/aas` — owned AA ranks parsed from `/alternateadv list` log output (one Ability line per rank; Cost/Description attached)
- `GET /api/ocr/status` · `POST /api/ocr/enabled {enabled}` · `POST /api/ocr/region {left,top,width,height}`
- `GET /api/ocr/preview` — one-shot capture+OCR of the region (calibration aid)
- `POST /api/ocr/overlay` — launches the on-screen region calibrator (tkinter box)
- `POST /api/overlay` — launches the always-on-top combat strip (`backend/overlay.py`; Scroll Lock ON = movable, OFF = click-through)

### Atlas (`backend/map_system.py` + `frontend/components/AtlasPanel.tsx`)

- **Data source**: vector map files (`L x1,y1,z1,x2,y2,z2,r,g,b` segments,
  `P ...,size,Label` points). Search order: the user's **Brewall pack**
  (`maps\Dark Brewall`, 1707 files incl. dungeon charts like befallen/guktop)
  first, stock `maps\` second — dirs in `config.py`. Base file plus `_1.._3`
  layers are merged; results `lru_cache`d. Filename fallback: squashed zone
  name ("South Karana"→southkarana) when not in `ZONE_FILES`.
- **Coordinate convention**: map files store (-locX, -locY); a `/loc` position
  plots at `(-x, -y)`, screen-y down.
- **Player position, two feeds** (both land in `tracker.position`):
  1. `/loc` log lines (`Your Location is Y, X, Z`) — manual, always works.
  2. **Screen OCR** (`backend/ocr_system.py`): if `eqgame.exe` is running and
     OCR is enabled, a 1s loop captures the configured screen region (mss),
     upscales 3x, OCRs with RapidOCR, and parses the in-game map's
     `X:/Y:/Z:/zone` readout. **RapidOCR, not Windows OCR** — the Windows
     engine silently drops short lines like "Z: 4" (verified). Passive screen
     reading only; never touches the game process. Region + enabled flag in
     `data/ocr_config.json`; calibrate via `backend/ocr_overlay.py` (draggable
     always-on-top gold box; game must be Windowed/Borderless). Controls live
     in the Atlas panel footer (status · OCR toggle · Calibrate).
- **Zone names**: `normalize_zone()` strips EQL instance suffixes
  ("Befallen 2 (Adaptive)" → "Befallen") and a leading "The ".
- **To add a zone**: put it in `ZONE_FILES` (long name → map file candidates); if the in-game name differs from the graph node (e.g. "The City of Guk" → "Upper Guk"), add it to `ZONE_ALIASES`
  and `ZONE_GRAPH` (adjacency for routing) in `map_system.py`. Unknown zones
  degrade to a "No chart" state; routing works even from chartless zones.
- **True walls mode**: the Atlas toggles Chart ↔ True walls. `geometry_system.py`
  parses the zone's own `.s3d` (PFS) archive and WLD `0x36` mesh fragments,
  classifies triangles by face normal (walls vs floors), bands floors from the
  upward-face z-histogram, and serves compact plot-space JSON. WLD axes are
  swapped vs `/loc` (wld_x=locY), so vertices plot at `(-wld_y, -wld_x)` —
  verified against live /loc samples + the Brewall Befallen chart (≤4 units).
  Floor selector: auto (nearest band to the hero's /loc z) / all / F1..Fn;
  chart labels stay overlaid. Chartless zones fit to geometry bounds.
- **3D mode** (`Atlas3D.tsx`, three.js): textured per-material submeshes with
  the game's own BMPs (converted to PNG, masked textures get palette-index-0
  alpha). Materials with render method 0 are invisible collision shells —
  dropped (they read as phantom ceilings otherwise). EQ winds triangles
  CLOCKWISE: classification negates the geometric normal and the payload
  re-emits CCW so three.js FrontSide culling gives the dollhouse look.
  Defaults per spec: ceilings never extracted, walls 50% opacity (slider),
  stairs/ramps + props on, no floor highlighting. Hero = green sphere at
  (locY, locX, z). Prop yaw applied; pitch/roll not yet (rare).
- **Rendering**: canvas, "gold ink on dark vellum" — file colors are blended
  toward the bone-gold ink (`inkColor()`), exits (`to X` labels) drawn as gold
  diamonds, player as a green dot (heal-green #1fb38c) with a soft ring, gliding (700ms ease-out) between position fixes. Pan = drag, zoom = wheel,
  the chart follows the hero at the current zoom; dragging releases the follow lock, Recenter re-locks (refits when no position is known). Dungeon charts mostly don't exist (classic behavior).

### Advisor (`backend/agent/advisor.py` + `backend/game_data.py` + `AdvisorPanel.tsx`)

Third center tab. Pipeline per consult: character context (class trio, level,
focus, zone, unspent AA points, spell slots) + OWNED STATE (spellbook export
`<Name>_<server>-*-Spellbook.txt` in the game dir + owned AA ranks from
`/alternateadv list` + recently-cast spells from the ledger) + compacted
EQL-wiki data → one LLM call → strict JSON (loadout that fills the spell
slots from owned spells / replace = supersession warnings / aa_now / aa_save
/ horizon = next 2 levels / locations / class_notes). Sync chips in the tab
show spellbook age + AA sync. The snapshot polls the spellbook file's mtime
and carries the AA sync stamp, so a fresh `/outputfile spellbook` or
`/alternateadv list` auto-triggers a new consult while the tab is open.
Vitals shows `sync_hints` — the exact command to type when the log is off
(`/log on`), the export is missing/stale (leveled since export or >24h), or
AAs are unsynced/newly earned.
Cached in-memory until the context signature changes or `?refresh=1` (the
Consult button).

- **Wiki grounding**: `game_data.build_wiki_context()` pulls each class's wiki
  page (per-level spell tables) + the "Alternate Advancement" page via the MCP
  server, compacts them to one-liners (≤20k chars), caches 24h. Failed fetches
  are NOT cached (retried next consult). Melee classes (Monk) have no Spells
  section on their page — expected, not a parser bug.
- **MCP server**: clone of everquest-legends-mcp v1.3+ at `MCP_SERVER_DIR`
  (upstream: ArtSabintsev/everquest-legends-mcp — the Sergeant… fork is stale).
  v1.3 `eql_builds_*` tools give STRUCTURED spells/AAs/skills/stances;
  `game_data.py` uses them for spell-class lookups, stance + skill-cap advisor
  sections, with wiki-page scraping as fallback. (Node ≥22;
  `npm install` builds `dist/`). The backend spawns it over stdio on demand
  (`mcp_client.py`, proper initialize handshake) and fails soft to ungrounded
  counsel when it's absent.
- **LLM**: whatever `_build_llm()` provides — currently LM Studio with
  qwen/qwen3-4b-2507. Start LM Studio's local server (Developer tab); set the
  model's context length ≥16k; enable JIT loading + idle auto-unload for
  load-on-demand. If the LLM call fails the endpoint returns a
  `source:"builtin"` fallback so the tab never breaks.
- **Class trio / AA points / spell slots**: not derivable from logs — set once
  in the tab's controls (`PATCH /api/character`, persisted to the characters
  table; SQLite columns are auto-migrated at startup). AA gains parsed from
  the log auto-increment `aa_available` afterward.
- Footer shows grounding: "wiki-grounded" vs "from memory" (approximate names).

**WebSocket `/ws`** (frontend auto-reconnects, sends "ping" keepalives):
```json
{ "type": "hello", "data": <snapshot> }            // on connect
{ "type": "events", "data": [ { "type": "melee_out", "ts": "...", "verb": "crush",
                                "target": "a dread bone", "damage": 19, ... }, ... ] }
                                                   // batched ~6 frames/sec (event_flush_loop)
{ "type": "state", "data": <snapshot> }            // throttled ≥1/s + every 3s
```

**Snapshot shape** (from `CharacterTracker.snapshot()`):
```json
{ "name": "Gentso", "server": "rivervale", "level": 13, "class_str": "Monk",
  "race": "Iksar", "playstyle": "solo_dps", "zone": "Befallen",
  "in_combat": true, "dps": 42.3, "session_max_dps": 87.1, "last_target": "a dread bone",
  "session": { "damage_dealt": 1234, "damage_taken": 210, "healing_received": 55,
               "kills": 16, "deaths": 0, "xp_ticks": 13, "xp_percent": 14.4,
               "aa_points": 0, "skill_ups": 2, "hit_rate": 62.9, "loots": ["..."] } }
```

### 5. Frontend (`frontend/` — Next.js 14, app router, TypeScript)

Single page: `/` — a three-panel HUD (Vitals & Session | Companion | War Ledger)
with a nameplate header (character, zone, link status). Chat lives inside the
Companion panel, not a separate route.

- **Styling**: hand-rolled CSS in `app/globals.css` — NO Tailwind. All colors are
  CSS custom properties mirroring StoneGlass. Ledger rows are colored via
  `data-kind` attributes ("out" | "in" | "heal" | "cast" | "milestone" | "dim").
- **Fonts** (next/font/google, self-hosted at build): Cinzel (display),
  IBM Plex Sans (UI), IBM Plex Mono (ledger + numerals).
- **Live data**: `hooks/useWebSocket.ts` auto-reconnects (2.5s backoff) and pins
  ledger scroll to bottom unless the user scrolled up.
- **New event type?** Add a case to `classify()` in `WarLedger.tsx` — unknown
  types fall back to a dim row showing the raw line, so nothing breaks.
- **Accessibility floor**: visible `:focus-visible` outlines, `prefers-reduced-motion`
  kills all animation, stat numbers wear ink color (identity comes from the
  colored tile rule, never color alone).

**Extensibility**:
- Add pages (e.g., `/gear-planner`) — app router auto-routes new folders
- Add dashboard widgets — subscribe to the same WS feed via props from `page.tsx`

---

## Data Flow

### Real-Time Combat Example

```
1. User plays EQL, kills a Goblin
2. EQL logs: "You hit Goblin for 42 points of damage."
3. Log watcher detects new line
4. Parser parses → CombatDamage event
5. Watcher emits via WebSocket to frontend
6. Frontend updates combat log widget in real-time
7. Agent analyzes: "User deals 120 DPS, recommend higher-damage spells"
8. Suggestion appears in dashboard or chat
```

### Chat Example

```
1. User types in chat: "What spells should I learn?"
2. Frontend sends POST /api/chat
3. Backend loads character state + recent log events
4. LangGraph agent processes request:
   a. Calls get_spell_suggestions(profile, recent_combat_context)
   b. Formats response with Claude
5. Returns suggestions + reasoning
6. Frontend displays in chat
```

---

## Configuration

### `.env` (all fields have working defaults in `backend/config.py`)
```
ANTHROPIC_API_KEY=sk-ant-...           # optional — agent falls back without it
LLM_PROVIDER=lmstudio                  # anthropic | openai | lmstudio | local
MODEL=qwen/qwen3-4b-2507               # must match the id LM Studio shows

MCP_ENABLED=true                       # EQL wiki grounding for the Advisor
MCP_SERVER_DIR=G:\projects\everquest-legends-mcp

DATABASE_URL=sqlite:///./data/companion.db

EQL_LOG_DIR=G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs
EQL_LOG_PATH=                          # full-path override (wins over dir scan)
EQL_CHARACTER_NAME=                    # prefer this character; else most recent log

FRONTEND_ORIGIN=http://localhost:3000  # CORS
```
Frontend URLs: set `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` in
`frontend/.env.local` only if the backend isn't on `localhost:8000`.

### Model Swapping — one seam: `_build_llm()` in `backend/agent/graph.py`

Already implemented as a provider switch:
```python
def _build_llm():
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI      # pip install langchain-openai
        return ChatOpenAI(model=settings.model)
    if settings.llm_provider == "lmstudio":
        from langchain_openai import ChatOpenAI      # OpenAI-compatible local server
        return ChatOpenAI(model=settings.model, base_url=settings.lmstudio_base_url,
                          api_key="lm-studio", temperature=0.3)
    if settings.llm_provider == "local":
        from langchain_ollama import ChatOllama      # pip install langchain-ollama
        return ChatOllama(model=settings.model)      # e.g. MODEL=llama3.1
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key)
```
Steps: (1) set `LLM_PROVIDER` + `MODEL` in `.env`, (2) `pip install` the matching
langchain provider package, (3) restart the backend. If the LLM call fails at
runtime (bad key, no credits, model down), `respond()` catches it and returns the
deterministic fallback formatting — the app never breaks on LLM problems.

---

## Extension Points (Plugins)

### Add a New Tool

**Example: Get macro suggestions**

1. Add to `backend/agent/tools.py`:
```python
async def get_macro_suggestions(profile: ProfileData, recent_spells: List[str]) -> List[SuggestionItem]:
    """Suggest spell rotation macros based on recent casts."""
    # Query MCP for spell synergies
    # Return prioritized macro suggestions
    pass
```

2. Register in `backend/agent/graph.py`:
```python
# In the routing logic, detect "macro" keyword
if "macro" in user_text:
    macro_suggestions = await get_macro_suggestions(profile, recent_spells)
    state["macro_suggestions"] = macro_suggestions
```

3. Format in `format_response()` to include macros in output.

### Add a New Event Type (worked example, matches real code)

**Example: track fall damage** (`You have taken 12 points of damage from falling.`)

1. `backend/log_system/events.py` — add the model:
```python
class FallDamage(LogEvent):
    type: str = "fall"
    damage: int
```
2. `backend/log_system/parser.py` — add the regex to the table and a branch in `parse_line`:
```python
RE_FALL = re.compile(r"^You have taken (\d+) points of damage from falling")
...
if fd := RE_FALL.match(msg):
    return ev.FallDamage(damage=int(fd.group(1)), **base)
```
3. Broadcasting is automatic — every parsed event is already sent over `/ws`.
4. (Optional) count it in `state_tracker.py` `apply()` and add to `snapshot()`.
5. (Optional) persist it: add `"fall"` to `PERSISTED_EVENTS` in `main.py`.
6. Frontend: add a `case "fall":` to `classify()` in `WarLedger.tsx`. Unknown
   types already render as dim raw-text rows, so skipping this step breaks nothing.

### Add a New Frontend Page

**Example: Gear planner**

1. Create `frontend/app/gear/page.tsx`
2. Add route in Next.js (auto-routed)
3. Fetch gear suggestions from backend API
4. Display interactive gear comparison
5. Add nav link to layout

---

## Testing

### Manual Backend Test (PowerShell)
```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/character
Invoke-RestMethod "http://localhost:8000/api/events?limit=10"
Invoke-RestMethod http://localhost:8000/api/chat -Method Post -ContentType "application/json" -Body '{"message": "What spells should I learn?"}'
```

### Parser Coverage Test (run after any EQL patch)
```powershell
conda activate eql-companion
python -c "import sys; sys.path.insert(0, r'G:\projects\eql_mods'); from backend.log_system.parser import parse_line; from collections import Counter; c=Counter(); [c.update([e.type]) for line in open(r'G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs\eqlog_Gentso_rivervale.txt', 'rb') if (e:=parse_line(line.decode('utf-8','replace'), 'Gentso'))]; print(c.most_common())"
```
Baseline (2026-07-05, 398KB log): 765 events; melee/miss/cast/dot/kill/exp/loot/coin/zone all present.
If a category drops to zero after a patch, the log format changed — fix `parser.py`.

### Simulated Combat (no game needed)
Append lines to the watched log file — the ledger updates within ~0.5s:
```powershell
Add-Content "G:\...\Logs\eqlog_Gentso_rivervale.txt" "[$(Get-Date -Format 'ddd MMM dd HH:mm:ss yyyy')] You crush a test dummy for 42 points of damage."
```

---

## Known Limitations

- ⚠️ Log parser is regex-based (fragile if EQL format changes; update patterns as needed)
- ⚠️ WebSocket doesn't persist across disconnects (add reconnect logic in frontend if needed)
- ⚠️ One ACTIVE character at a time — but the header dropdown switches between all logs in the folder (`/log on` in-game creates one)
- ⚠️ No gear suggestions (post-MVP)
- ⚠️ No macro editor (post-MVP)

---

## Development Workflow

1. **Read logs**: If adding a feature that needs log context, update `parser.py` + `events.py`
2. **Update character state**: If tracking new data, add to `CharacterState` model
3. **Add agent tool**: If companion needs to suggest something, add to `tools.py` + wire in `graph.py`
4. **Emit WebSocket event**: If frontend needs real-time update, broadcast from watcher
5. **Add frontend component**: Build React component that listens to WebSocket or calls backend API
6. **Test end-to-end**: Play EQL, watch events flow from logs → backend → frontend

---

## Common Tasks

### Change the LLM Model
1. Update `.env`: `LLM_MODEL=...` + `LLM_PROVIDER=...`
2. Update `backend/config.py` to instantiate the right client
3. Update `backend/agent/prompts.py` if model has different capabilities
4. Restart backend

### Add Support for New Event Type (e.g., Item Drops)
1. Add regex to `backend/log_system/parser.py`
2. Create `ItemDrop` class in `events.py`
3. Parse in `parser.py`
4. Emit in watcher
5. Store in database (optional)
6. Display in frontend

### Scale to Multiple Characters
1. Modify log watcher to monitor all `eqlog_*.txt` files
2. Maintain separate character state per log file
3. Add character selector to frontend
4. Route WebSocket events by character name

---

## Project Status

**Built & verified (2026-07-05)**:
- ✅ Log tailer + parser — validated against the real `eqlog_Gentso_rivervale.txt`
- ✅ Character auto-detection from filename; level/class via `/who` lines
- ✅ Session tracker: DPS (60s window), hit rate, XP %, kills/deaths, loot (incl. EQL upgrade-loot)
- ✅ WebSocket live feed + throttled state pushes
- ✅ LangGraph agent with live context (zone + recent activity) and LLM-failure fallback
- ✅ Next.js HUD (builds clean): Vitals panel, Companion chat, War Ledger
- ⬜ **Not yet done: end-to-end visual check in the browser while playing** — first thing to verify next session

**Next up (ordered)**:
1. Run both servers, play EQL, watch the ledger stream; tune ledger row wording/filtering (other_death may be spammy in busy zones — consider a toggle)
2. Real data in agent tools — replace the built-in spell/AA/zone stubs in `agent/tools.py`
   with MCP wiki queries (`mcp_client.py` exists but is NOT wired; MCP tool docs in git history / MASTER_PROMPT.md)
3. Gear suggestions tool (deliberately deferred to last per user)
4. ~~Multi-character~~ DONE (2026-07-06): header switcher over all `eqlog_*.txt`, file-keyed (same name can exist on two servers)
5. Buff timer widget (parse buff-fade flavor lines per spell — needs a lookup table)

**Known limitations**:
- Regex parser breaks silently if EQL changes log formats — run the coverage test after patches
- Level/class unknown until `/who` is typed in-game (UI shows a hint)
- Chat-agent suggestion tools still use built-in placeholder data, but chat
  context now includes the spellbook summary; the Advisor tab is fully
  grounded (wiki via MCP + owned spells/AAs)
- One active character at a time (header dropdown switches; per name+server profiles)
- Old `profiles`/`conversations` tables in companion.db are dead weight from the
  Gradio prototype; delete the DB file to clean (it regenerates)

---

## Notes

- **Git**: Not auto-committing. User commits when ready.
- **Token management**: Conversation history limited to last 10 turns; logs provide context instead
- **Privacy**: Logs and profiles stay local; no external uploads
- **Extensibility**: All major components (parser, agent, frontend) designed for plugins
