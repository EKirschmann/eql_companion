# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repository.

# EQL Companion — Real-Time Log-Aware Assistant

A real-time companion for EverQuest Legends: tails the combat log, tracks the
character, and provides a live HUD (vitals, war ledger, encounters), an Atlas
(charts / mined geometry / textured 3D), and a wiki-grounded Advisor (spells,
AAs, gear, hunting spots). Passive by design — it never touches game files or
memory. User setup lives in **README.md**; this file is architecture,
invariants, and conventions.

**Stack**: FastAPI backend + polling log tailer + Next.js 14 frontend (app
router, TypeScript, hand-rolled CSS) + WebSocket live feed + optional LLM.

## Running for development

`start_companion.bat dev` — or by hand:

```
uvicorn backend.main:app --reload      # backend :8000 (from the repo root)
cd frontend && npm run dev             # UI :3000
```

END USERS run production mode (`start_companion.bat` with no args): uvicorn
WITHOUT --reload + `next start` serving the build from `.next-prod`
(~350MB lighter, no file watchers). Production builds use a SEPARATE dist
dir (`NEXT_DIST_DIR=.next-prod`), so a running dev server and a prod build
can no longer corrupt each other.

- `--reload` restarts on .py changes and re-reads `.env`; editing `.env`
  alone does NOT trigger a reload — touch a backend file or restart.
- Typecheck with `npx tsc --noEmit` (from frontend/).
- The backend needs the configured `EQL_GAME_DIR` (see `.env.example`);
  without a log file it runs in a degraded no-data mode.

## Backend map

```
backend/
├── main.py              # FastAPI app, REST + /ws, lifespan, flush loops, caches
├── config.py            # pydantic-settings; EQL_GAME_DIR derives Logs/ + maps/
├── llm_runtime.py       # runtime-switchable LLM (none|lmstudio|openai|custom|...)
├── session_state.py     # tracker snapshot/restore — sessions survive restarts
├── wiki_http.py         # no-Node wiki fallback (MediaWiki api.php -> text)
├── mcp_client.py        # stdio client for the EQL MCP server (+ HTTP fallbacks)
├── builds_data.py       # direct reader of the eqlbuilds snapshot (levels, ids)
├── spellsets.py         # read/WRITE the game's LO*.ini saved spell sets
├── game_data.py         # wiki/builds grounding, verification helpers, ZEM table
├── spellbook.py         # /outputfile export parsing (spellbook/inventory/...)
├── state_tracker.py     # CharacterTracker — session state, DPS, ledger, encounters
├── ws_manager.py        # WS connection list + broadcast
├── models.py            # SQLAlchemy: characters, chat_messages, log_events
├── map_system.py        # Atlas charts: map-file parsing + zone travel graph
├── geometry_system.py   # .s3d/.wld mesh extraction (2D floors/walls + 3D)
├── ocr_system.py        # screen OCR position feed (RapidOCR; Windows)
├── overlay.py           # always-on-top combat strip (tkinter; Windows)
├── log_system/          # events.py (pydantic), parser.py (ALL regex), watcher.py
└── agent/               # advisor.py (LLM counsel + gates + builtin mode),
                         # graph.py (chat), prompts.py, tools.py, state.py
```

Frontend: `app/page.tsx` (3-panel HUD), `components/` (CharacterPanel,
AtlasPanel + Atlas3D, CompanionPanel, AdvisorPanel, WarLedger,
EncounterPanel), `hooks/useWebSocket.ts`, `lib/api.ts` + `lib/types.ts`.
All styling is CSS custom properties in `app/globals.css` — **no Tailwind**.

## Log pipeline (the spine of everything)

- **watcher.py**: polling tailer (0.4s), binary reads with byte offsets.
  On startup it either restores the previous session (below) or replays the
  last 1MB as *uncounted* seed events to establish zone/level/ledger.
- **parser.py**: every regex lives in one table at the top. Verified against
  real EQL logs — melee/miss both directions, EQL DoT ticks ("has taken X
  damage from your Y"), exp percent lines, upgrade-loot, coin, casts, kills,
  `/who` char_info (class abbreviations expand; the trio is authoritative),
  `/loc`, AA list bursts, pet ownership ("My leader is X").
- Other players' hits parse as `other_out` but are never broadcast — they
  only feed per-encounter group DPS. Own pets fold into the player
  ("Pet: <source>" rows, incl. pet DoTs via the "by <caster>" form);
  others' pets fold into their owner's ally row. Pets need a "/pet leader"
  mapping — casting a pet summon with none raises a Vitals hint.
- XP attribution is FORWARD-ONLY: EQL prints "You gain experience!"
  BEFORE its kill line, so XP holds as pending and is claimed by the next
  kill (own, mapped pet, or ally "has been slain by X") within 3s.
  Backward attribution mis-credited every tick during chain pulls.
  Per-mob XP and the XP box reset on level-up.
- Heals name their healer ("Bosh healed itself for 159 (210) hit points
  by Spirit Tap") — encounter heal rows key "Spell — Healer". Incoming
  avoidance parses per defense verb (block/dodge/parry/riposte/miss) into
  the per-fight defense line. Loot-and-auto-sell lines tag "(sold)".
- Exaltation procs share the spell-damage line shape; effects granted by
  owned stones (wiki-mined into tracker.exalt_effects at startup/export
  refresh/character switch) label ability rows "(exaltation)" — MINUS any
  effect that is also a scribed spell (a cast and a proc are
  indistinguishable; mislabeling real casts is the worse error).
- **Adding an event type**: model in `events.py` → regex + branch in
  `parser.py` → (optional) count in `state_tracker.apply()` → (optional) add
  to `PERSISTED_EVENTS` in main.py → `case` in WarLedger `classify()`.
  Unknown types render as dim raw rows, so nothing breaks if you skip the UI.
- **Parser coverage test** (run after any EQL patch): parse your full log and
  count event types; a category dropping to zero means the format changed.

## Session persistence (survives restarts)

`session_state.py` snapshots the tracker (counters, ledger, encounters,
mob stats, rosters, owned AAs) plus the log byte offset to
`data/session_state.json` every 3s and on shutdown. On startup, if the
snapshot matches the active log file, the tracker restores and the watcher
resumes from the saved offset — downtime lines replay through the normal
live path (counted once, persisted once). The 60s DPS window is deliberately
not restored. Advisor/gear consults persist to `data/advice_cache.json`
(signatures normalized to strings — see `_sig_norm` in main.py).

## REST + WS surface

WS `/ws`: `hello` (snapshot) on connect, `events` batches (~6 frames/s),
throttled `state` pushes. REST highlights (see main.py for all):

- `GET /api/character` (snapshot) · `PATCH /api/character` (trio/level/AA/slots)
- `GET /api/characters` + `POST /api/character/select` — multi-log switching
- `GET /api/events|encounters|chat/history` · `POST /api/chat`
- `GET /api/advisor` / `GET /api/gear` — LLM consults; `?refresh=1` forces,
  `?cached=1` returns the cache instantly or `{"cached": false}` WITHOUT
  running the LLM (the tab restores results on load; consults are
  button-press only, never automatic)
- `GET/POST /api/llm` — runtime model switch; clears both consult caches
- `GET /api/hunting` — deterministic leveling-zone candidates (Gantt chart)
- `GET /api/spellbook|aas|exports` · `POST /api/exports/refresh|aas/rescan`
- `GET /api/spellsets` · `POST /api/spellsets/generate` — read the game's
  saved spell sets / write the counsel as one (source=loadout|prebuffs,
  optional names[] from the UI checkboxes; gems auto-stacked DD, DoT, AoE,
  heals from gem 8, utility, pets; loadout set "companion", buff set
  "prebuffs"; one-time .companion-backup beside the LO*.ini)
- `GET /api/update-check` (badge click + 6-hourly poll; API with plain
  tags-page fallback) · `POST /api/update/run` (spawns the updater in its
  own console window)
- `GET /api/map|zones|route|geometry|geometry3d|texture/{short}/{name}`
- `POST /api/overlay` — toggle (launches or kills; `GET` reports state)
- `GET/POST /api/ocr/*` — screen-OCR position feed config

## Atlas invariants (hard-won — do not "fix")

- Map files store (-locX, -locY): a `/loc` position plots at `(-x, -y)`.
- WLD axes are swapped vs `/loc` (wld_x = locY): geometry vertices plot at
  `(-wld_y, -wld_x)`; the 3D hero sits at (locY, locX, z).
- **EQ winds triangles CLOCKWISE**: classification negates the geometric
  normal and the 3D payload re-emits CCW for three.js FrontSide culling.
- Materials with render method 0 are invisible collision shells — dropped
  (they read as phantom ceilings). Ceilings are never extracted.
- 3D camera: follow mode translates camera + orbit target by the hero's
  delta (user angle/zoom preserved); panning off-target releases the lock.
- Zone names: `normalize_zone()` strips EQL instance suffixes ("Befallen 4
  (Refined)" → "Befallen"). New zone = `ZONE_FILES` (+ `ZONE_ALIASES`,
  `ZONE_GRAPH` adjacency) in map_system.py.
- Position feeds: `/loc` lines always; optional screen OCR (RapidOCR — the
  Windows OCR engine silently drops short lines like "Z: 4").

## Advisor — "the LLM proposes, structured data disposes"

The house pattern: **every LLM suggestion is machine-verified before
display**; failing entries are dropped and logged, never shown. The gates
(game_data.py + advisor.py):

- Loadout picks must be OWNED and at/below the character's level; the
  spellbook is split into "usable now" vs "scribed for later" in the prompt.
- Travel magic (SPAs 26/83/88/104 + name patterns) is stripped — rings/
  circles/zephyrs/gate/succor are RITUALS in EQL, never memorized.
- Resurrection lines (SPA 81) are dead slots for solo focuses.
- `supersedes_for_slots`: same primary effect + sign + target + identical
  class set, higher magnitude (NONCOMPARABLE_SPAS {32,33,85,113}; zero-base
  rank-1 records fall back past id-10 charisma spacers). Owned picks
  superseded by another owned usable spell are dropped.
- Long-duration buffs route to a separate `prebuffs` section.
- **Locations are gated against the community Recommended-Levels table**:
  the raw WIKITEXT is parsed (the rendered page collapses empty cells) from
  in-era sections only (Antonica/Odus/Faydwer + Planes of Fear/Hate/Sky —
  Kunark/Velious never parsed). The 2026-07 redesign carries per-level
  QUALITY circles (efficient/ok/poor/special), explicit level ranges, and
  a zone Type column: candidates rank efficient > ok > stretch, cities
  exclude themselves by Type (efficient-marked rows exempt — the sheet is
  mid-edit), bands merge range+marks when they disagree, and the prompt
  says to strongly prefer EFFICIENT zones. At most ONE stretch pick
  survives; deterministic backfill if the model under-picks. Same data
  feeds `GET /api/hunting` and the Leveling-chart Gantt.
- **Permanent buffs** (self-target + zero durationTicks, minus
  travel/summon/pet/FD/res SPAs) are listed in the prompt with a
  never-say-"refresh" instruction — Instrument of Nife-class buffs last
  until death.
- Deterministic extras: a vendor "purchase" list (near-level missing
  spells, buy-ahead marked), nice_to_have backfilled with owned
  non-superseded alternatives when the LLM lists few, and cached counsel
  restores after ANY restart via `?cached=1` — marked `stale` when the
  context moved on instead of being discarded. Consults are button-press
  ONLY, never automatic.
- Tiered loadout: must_have / should_have fill the spell slots exactly;
  nice_to_have offers swaps. Spell levels annotated from the spellbook.

**Owned state** comes from `/outputfile` exports parsed in spellbook.py
(`<Name>_<server>-...-<Kind>.txt` in the game dir): Spellbook, MissingSpells,
Inventory, Achievements — plus owned AA ranks from `/alternateadv list` log
bursts. Sync chips + `sync_hints` tell the user the exact command when
something is missing/stale. Bump the version int in the export cache key
whenever the Inventory parse changes.

## Gear advisor

- The slot table ALWAYS shows the full 24-slot EQL roster (CANON_SLOTS):
  two generic **Any Slots** (any equippable item, stats live), paired
  Ear/Wrist/Fingers, Ammo, Held — **no Charm or Power Source in EQL**.
  Unaddressed slots backfill as keep/empty rows (`_full_slot_table`).
- Wiki item stats are BASE (+0) values; +N upgrade ranks scale enormously
  and are undocumented — items with a higher worn rank are never "beaten"
  by base-stat comparisons, and STATS UNKNOWN items are never replaced.
- Gear is usable if ANY ONE of the trio can use it (`[USABLE]` pre-tags;
  wiki Race: lines are stale classic-era data and are stripped).
- A 2H primary recommendation deterministically drops the secondary rec.
- Exaltations parse from `<Loc>-SlotN` socket sub-rows with host tracking.
  Sockets are TYPED — focus/clicky/worn/proc (taxonomy per
  eqlegendstools.com); each stone's type is inferred from its base item's
  Effect line, proc stones fit weapon sockets only, and moves are only
  recommended between same-type sockets ("unknown" stays honest). Stones
  keep their base item's CLASS list: trio-unusable stones are tagged bank
  fodder and any move rec for them is machine-dropped.
- **Pet loadout**: `pet_slots` (user-set per character, next to AA points/
  Spell slots) caps a pet_gear list — bags/bank items only, at least one
  weapon, player keeps stat priority, exaltation hosts excluded. The
  workflow: unload pet gear to bags -> /outputfile inventory -> check
  exports -> consult gear. Slot-table rows whose recommendation IS the
  worn item render dimmed (status, not suggestions).

## LLM runtime (backend/llm_runtime.py)

- Providers: `none` (deterministic) | `lmstudio` | `openai` | `custom` (any
  OpenAI-compatible base URL) | `anthropic` | `local` (Ollama). Switch at
  runtime via the Advisor tab / `POST /api/llm`; persists to
  `data/llm_config.json`; switching clears consult caches.
- `none` never builds a chat model — advisor/gear branch to
  `_builtin_counsel` / `_builtin_gear`: effect-categorized loadout
  (damage/heal/control/buff via spell records), exact supersession warnings,
  horizon from scribed-ahead + purchasable, AA cost ranking, hunting picks,
  gear rank-upgrade detection. Also the automatic fallback when any LLM
  call FAILS — the tab never breaks.
- LM Studio only: `_lmstudio_budget` sizes max_tokens to the loaded context
  window (prevents cryptic 400 overflows; thinking models burn reasoning
  tokens against the completion budget). Frontier models get no knobs —
  o-series/gpt-5.x reject temperature.
- Chat (agent/graph.py) uses the same `get_llm()` seam.

## Wiki grounding

`builds_data.py` reads the eqlbuilds.com dataset snapshot that ships inside
the MCP clone (dist/data/eqlbuilds — CI-refreshed): per-class spell lists
with EXACT unlock levels, AA ranks/costs, skills. When present it feeds the
advisor's spell/AA context directly (no scraping), backs `spell_record`
when the MCP server can't answer, and decides pet-line supersession (pet
SPAs 33/71 carry no magnitude — unlock level IS strength). No clone = every
helper returns None and callers fall back.

`mcp_client.py` prefers the EQL MCP server (structured `eql_builds_*`
spells/AAs/skills/stances; clone of ArtSabintsev/everquest-legends-mcp,
Node 22+, `MCP_SERVER_DIR`) and **falls back to plain HTTP** (wiki_http.py,
MediaWiki api.php → text in the same line-per-cell shape) when it is absent
— adopters need no Node beyond the UI. Page/context caches are 1-24h;
failed fetches are not cached. Melee classes have no Spells section on
their wiki page — expected, not a parser bug.

## Configuration (.env — see .env.example for the annotated version)

`EQL_GAME_DIR` is the one path most installs must set; `Logs/`, `maps/`, and
the Brewall custom-map dir derive from it. LLM fields: `LLM_PROVIDER`,
`MODEL` (local id), `OPENAI_API_KEY`/`OPENAI_MODEL`, `CUSTOM_BASE_URL`/
`CUSTOM_API_KEY`/`CUSTOM_MODEL`, `ANTHROPIC_API_KEY`. `MCP_SERVER_DIR`
empty = wiki over HTTP. Key changes need a backend restart; the provider/
model selection itself is runtime-switchable in the UI.

## Frontend conventions

- **StoneGlass design tokens** (inherited from an earlier in-game skin
  project): dark glass `rgba(18,21,26,.82)`, gold `#c8aa6e`, hairline
  `rgba(200,170,110,.34)`, flat square-ended gauges, zero border-radius.
  Semantic colors: out-damage gold, in-damage `#d4574a`, heal `#1fb38c`,
  cast `#b07cc6` — all ≥3:1 contrast on the dark surface.
- Fonts: Cinzel (display), IBM Plex Sans (UI), IBM Plex Mono (numerals).
- Ledger rows color via `data-kind`; dim/disabled table rows via `data-dim`.
- Accessibility floor: `:focus-visible` outlines, `prefers-reduced-motion`
  kills animation, color never carries meaning alone.
- WS hook auto-reconnects (2.5s); ledger pins to bottom unless the user
  scrolled up; events batch through `page.tsx`.
- **Layout modes** (all persisted in localStorage): the center
  Atlas/Advisor panel collapses ("◂ hide") into a combat dashboard —
  encounter sections reflow into CSS multi-columns across the freed width,
  the ledger becomes a short strip; the War Ledger collapses in EITHER
  mode (its freed column goes to the encounter panel, which then also
  reflows); encounter text scales via A−/A+ (CSS zoom); the whole HUD is
  viewport-locked >=1200px (panels scroll internally, never the page).
  The Companion chat tab was removed.
- The Encounter panel shows per-ability hit counts (×), a defense line,
  healer-attributed heal rows, and a separate Pet section when a mapped
  pet contributes. The overlay (backend/overlay.py) is a Details-style
  meter: ranked class-colored bars to raid size, Damage|DPS modes,
  this-fight|last-5 segments, named-mutex singleton, self-closes when
  eqgame.exe exits.

## Testing

- **Parser coverage** (after any EQL patch): iterate your real log through
  `parse_line`, `Counter` the event types — a vanished category means the
  log format changed; fix `parser.py`.
- **Simulated combat** (no game needed): append a line to the watched log —
  `[<timestamp>] You crush a test dummy for 42 points of damage.` — the
  ledger updates within ~0.5s. Tag synthetic rows unmistakably ("test
  dummy") so cleanup can target them precisely.
- Manual API checks: `/health`, `/api/character`, `/api/advisor?cached=1`.
- Backend tests import `backend.*` — run from the repo root with the
  project's Python environment.

## Known limitations

- Regex parser breaks silently if EQL changes log formats (run the coverage
  test after patches).
- Level/class unknown until `/who` is typed in-game; loadout swaps write
  nothing to the log (cast-mismatch detection hints at `/who`).
- One ACTIVE character at a time (header dropdown switches).
- OCR position + overlay are Windows-only. Dungeon vector charts mostly
  do not exist (classic behavior) — True-walls / 3D modes cover them.
- The chat agent (backend/agent/graph.py) still exists server-side but has
  no tab — the Advisor is the grounded path.
- The community hunting sheet is mid-edit: Type/range/circle data can
  disagree (parser merges and tolerates); ZEM multipliers still
  unpublished.

## Releasing

Bump `APP_VERSION` in backend/main.py AND frontend/lib/version.ts (same
string), add a CHANGELOG.md section, commit, then `git tag vX.Y.Z` and push
with `--tags`. Untagged pushes are invisible to users: the in-app check
(badge click + 6-hourly poll; API with tags-page fallback for rate-limited
IPs) compares against the newest tag, and update_companion.py downloads
THAT TAG's ZIP (git clones pull main instead). The updater preserves
.env/data/node_modules/.next*, side-files changes to running scripts as
*.new, uses certifi for TLS (never disables verification), and rebuilds
the frontend into .next-prod. Install path is git-free: releases-page ZIP
-> install_companion.bat (offers Python/Node via winget, PATH-refreshes
in-window, cmd /k so the window never vanishes) — see INSTALL.md.

## Notes for assistants

- Git: never commit `.env` (real keys) or `data/` (runtime state) — both
  gitignored. Commit when the user asks.
- Before ANY destructive SQL against `data/companion.db`: SELECT the exact
  predicate first, eyeball the rows, delete by id list — never by pattern.
- The verification-gate pattern is the house style: when adding an
  LLM-driven feature, pair it with a deterministic verifier and a
  deterministic fallback so the UI never depends on model correctness.
