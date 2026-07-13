# EQL Companion

A real-time companion app for **EverQuest Legends**. It tails your combat log
and gives you a live HUD in the browser — no game files touched, nothing
injected, purely passive.

**What you get**

- **Vitals & War Ledger** — live DPS, session stats, hit rate, XP, loot, a
  streaming combat feed, per-pull encounter breakdowns and group DPS
- **Atlas** — zone charts with a live position dot, zone-to-zone routing,
  "true walls" mined from the game's own map geometry, and a textured 3D
  dollhouse view with a follow camera
- **Advisor** — spell loadout, AA spending, upgrade warnings, gear-slot
  recommendations, exaltation tracking, and where-to-hunt picks — grounded in
  your actual spellbook/inventory exports and the EQL wiki, with every
  suggestion machine-verified (owned, level-legal, not superseded)
- **Overlay** — an optional always-on-top combat strip over the game

## Requirements

- **Windows 10/11** (log tailing works anywhere, but OCR position tracking
  and the overlay are Windows-only)
- **Python 3.11+**
- **Node.js 18+** (serves the web UI)
- EverQuest Legends with logging enabled (type `/log on` in game once)

**Optional — pick zero or one LLM for reasoned counsel:**

| Option | Needs | Notes |
|---|---|---|
| None (deterministic) | nothing | default-ready; mechanical but honest counsel, instant |
| LM Studio | a local model | free, private; ~26B MoE models work well |
| OpenAI | an API key | best quality; a consult is ~7k tokens |
| Custom endpoint | any OpenAI-compatible URL | Groq / OpenRouter / Gemini compat / LAN — free tiers work |

**Optional — EQL MCP server** ([ArtSabintsev/everquest-legends-mcp](https://github.com/ArtSabintsev/everquest-legends-mcp),
Node 22+) for structured spell/AA data. Without it the app fetches the wiki
over plain HTTP automatically — no Node beyond the UI is required.

## Setup

```
git clone https://github.com/EKirschmann/eql_companion
cd eql_companion
pip install -r requirements.txt
cd frontend && npm install && cd ..
copy .env.example .env
```

Edit `.env` and set `EQL_LOG_DIR` to your game's `Logs` folder (default:
`G:\Daybreak Game Company\Installed Games\EverQuest Legends\Logs`).

## Run

`start_companion.bat` — or two terminals:

```
uvicorn backend.main:app --reload     # backend on :8000
cd frontend && npm run dev            # UI on :3000
```

Open **http://localhost:3000**, then in game type:

| Command | Why |
|---|---|
| `/log on` | start writing the combat log (once per character) |
| `/who` | teaches the app your level + class trio |
| `/outputfile spellbook` · `inventory` · `missingspells` | grounds the Advisor in what you own |
| `/alternateadv list` | syncs your AA ranks |
| `/loc` | drops a position fix on the Atlas (or enable OCR tracking) |

Then press **check exports** and **Consult** in the Advisor tab.

## Notes

- Sessions survive backend restarts (state snapshots to `data/`)
- One active character at a time; the header dropdown switches between every
  `eqlog_*.txt` in the folder
- Everything stays local: logs, exports, and counsel never leave your machine
  unless you point the LLM at a hosted API
- `skin/` holds StoneGlass, an earlier (abandoned) in-game UI skin project —
  unrelated to the companion, kept for reference
- Full architecture and extension docs: `CLAUDE.md`
