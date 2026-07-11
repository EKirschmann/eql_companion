# EQL Companion

A real-time AI companion for EverQuest Legends. It tails your combat log,
auto-detects your character, and shows a live HUD — DPS, session stats, a
streaming combat ledger — plus a chat companion that answers "what spells
should I learn / which AAs / where should I hunt" with your live context.

> Full documentation (architecture, extension points, model swapping, testing)
> lives in **`CLAUDE.md`**. This is the quick start.

## Run it

**Terminal 1 — backend** (FastAPI + WebSocket on :8000):
```powershell
conda activate eql-companion
cd G:\projects\eql_mods
uvicorn backend.main:app --reload
```

**Terminal 2 — frontend** (Next.js on :3000):
```powershell
cd G:\projects\eql_mods\frontend
npm run dev
```

Open **http://localhost:3000**. That's it — no profile setup. The backend finds
the most recent `eqlog_*.txt` in
`G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs`,
reads your character from the filename, and replays recent history.

**Tip**: type `/who` in-game once so the companion learns your level and class
from the log. Set your playstyle in the Vitals panel — the companion uses it.

## What you get

- **War Ledger** — live combat feed (hits, DoT ticks, casts, kills, XP with
  exact %, EQL upgrade-loot, coin) streaming within ~0.5s of the log line
- **Vitals & Session** — level, rolling 60s DPS, damage dealt/taken, hit rate,
  kills/deaths, XP gained, AA points, recent loot
- **Companion** — chat with an AI advisor that knows your class, level, zone,
  and recent activity (works without an Anthropic key via fallback formatting)

## Stack

FastAPI · SQLite · LangGraph (+ Claude, swappable via `.env`) · Next.js 14 ·
plain-CSS StoneGlass design system · WebSocket

## Status / caveats

- Parser validated against a real EQL log (2026-07-05). Re-run the coverage
  test in `CLAUDE.md` after game patches — log formats drift.
- Agent suggestion tools currently use built-in data; wiring the EQL MCP
  server for live wiki data is the next milestone (see `CLAUDE.md`).
- Gear suggestions deliberately come last on the roadmap.
