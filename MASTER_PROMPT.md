# EQL Companion App — Master Prompt

**Status**: New companion webapp (separate from StoneGlass UI skin). Build full-stack: FastAPI backend + LangGraph AI agent + Gradio frontend (→ React later).

**Goal**: Build a practical, privacy-respecting AI companion tool for EQL that helps players decide what to learn/train and where to level next.

**User Journey**:
1. Create profile: Race, 3 classes (primary/secondary/tertiary), current level, playstyle.
2. Ask agent: "What spells should I learn?" → AI suggests prioritized list with reasons + synergies.
3. Ask: "What AAs next?" → AI recommends tiered (must-have passives first, actives later).
4. Ask: "Where to level?" → Current/next zones with difficulty + group size suggestions.
5. Ask: "What gear should I look for?" → Focus effects, procs, upgradeable pieces, zone drops.
6. (Future) Real-time context from logs: "I see you’re in Guk; here’s optimized advice for that zone."

**MVP (v1.0 ship)**: Profile creation + chat interface + spell/AA/zone/gear suggestions + source citations.
**Post-MVP**: Log watcher, gear planner, build scoring, macro suggestions, overlay, multi-character support, React frontend.

## Key EQL Facts (Always Reference These)
- **Multiclassing**: Primary class often race-influenced at creation. Secondary flexible; tertiary unlocks at level 10. Non-primary classes can be swapped (even mid-raid in some cases). Only one pet active at a time even with multiple pet classes. All classes level together until decisions lock in.
- **AAs**: Passive AAs available from level 1. Active AAs at appropriate levels. No hard cap. AAs persist across class loadouts/swaps. Handpicked for multiclass balance and fun. Tabs: General, Archetype, Class-specific.
- **Spells**: Many low-level spells autogranted. Use in-game "Actions → Spells" tab to see unknown spells by level. Scribing is straightforward. Cross-class synergies are powerful.
- **Leveling & Zones**: Smooth experience curve (no hell levels). Zones have 3 difficulty tiers (higher difficulty = better XP, rewards, loot). Instanced dungeons and raid content available. Housing exists.
- **Gear**: Wearable by any of your current active classes. Focus effects, procs, and the item upgrading system (+10 potential) are important. Pet-focused items exist for relevant classes.
- **Playstyle Considerations**: Always factor in solo vs group, DPS/tank/healer/support/pet roles, and class synergies when recommending anything.
- **Data Freshness**: EQL is a new/reimagined game (launched ~July 2026, pre-Kunark era with QoL). Use tools to fetch latest wiki/community data. Flag potential era drift if content references later expansions.

## Technical Stack (Decided)

**Backend**:
- FastAPI + Uvicorn (async, easy deployment).
- SQLite + SQLAlchemy (lightweight, no external DB needed; profiles, suggestion history).
- LangGraph + Claude API (reasoning-heavy agent with tool calling; supports multi-turn context).
- MCP integration: Call EQL MCP server (Node.js, runs separately) via HTTP or direct subprocess.

**AI Agent**:
- LangGraph workflow: user message → tools (MCP wiki search, class combos, AA/spell data) → reasoning → structured suggestions.
- Tools (via LangChain): `eql_wiki_search`, `get_class_aa_info`, `get_leveling_zones`, `get_gear_suggestions`, `get_class_combos`.
- Prompt: Step-by-step reasoning, multiclass synergy focus, source citations, personalized to profile.
- Context: Keep last 10 conversation turns + user profile in state; summarize if needed to avoid token bloat.

**Frontend (MVP)**: 
- Gradio (rapid iteration, no build step). Forms for profile, chat for suggestions, markdown display for sources.
- (Post-MVP) React + Next.js + Tailwind + WebSocket for live log updates + better UX.

**Logs (Post-MVP)**:
- Watchdog + regex parser for `eqlog_*.txt` (zone, spells, buffs, damage). Feed events to backend.
- Optional: Integrate EQLogParser if user has it; poll its API.

**Data Sources**:
- **Primary**: EQL MCP Server (wiki search, class combos, news) — run via Node.js, proxy HTTP calls from Python.
- **Fallback/Cache**: Direct MediaWiki API, EQProgression.com (AA/spell/zone data), community guides.
- **Caching**: Redis or in-memory dict with TTL (24h for wiki, 1h for dynamic data like leveling zones).

**Repo Structure** (starting):
```
eql_mods/  (renamed → eql-companion once StoneGlass moves)
├── backend/
│   ├── main.py              # FastAPI app: /profile, /suggest, /chat
│   ├── agent/
│   │   ├── prompts.py       # System + user prompt templates
│   │   ├── tools.py         # Tool definitions (MCP calls, data fetch)
│   │   ├── graph.py         # LangGraph workflow
│   │   └── state.py         # State schema (profile, history, context)
│   ├── models.py            # SQLAlchemy Profile, Suggestion models
│   ├── cache.py             # Caching layer (MCP results, wiki)
│   ├── mcp_client.py        # HTTP/subprocess wrapper for MCP server
│   └── config.py            # Settings (API keys, paths, model choice)
├── frontend/
│   └── gradio_app.py        # MVP Gradio UI (profile form + chat)
├── logs/                    # (Post-MVP)
│   └── watcher.py           # File monitor + parser
├── data/
│   └── companion.db         # SQLite (profiles, history)
├── .env                     # API keys, log path
├── requirements.txt         # Dependencies (fastapi, langraph, sqlalchemy, gradio, etc.)
├── README.md                # Quick start
└── CLAUDE.md                # Development guide
```

**Startup**:
1. MCP server: `node start` in MCP repo (Node.js, runs on :3000 or similar).
2. Backend: `uvicorn backend.main:app --reload` (FastAPI on :8000).
3. Frontend: `python frontend/gradio_app.py` (Gradio on :7860).
4. (Post-MVP) Add WebSocket bridge for live logs.

## AI Agent Design Rules
- **Reasoning Style**: Step-by-step, evidence-based. Always consider multiclass synergies. Prioritize practical lists with "why this" explanations.
- **Tool Use**: Call tools when data is missing, outdated, or for verification. Prefer fresh wiki/MCP data.
- **Output Format**: Structured sections (Spells, AAs, Leveling Spots, Gear) + overall reasoning + sources. Support both chat-style and dashboard-style responses.
- **Context Awareness**: Merge user profile + live log data (current zone, recent spells/activity) into every suggestion.
- **Safety/Accuracy**: Cite sources. Note uncertainties. Avoid overpowered or unverified claims. Flag if data might be from later eras.
- **Personalization**: Tailor heavily to exact class combo, level bracket, and playstyle. Offer alternatives (e.g., "For more solo focus..." or "Group-oriented variant...").

## Development Guidelines
- **Modularity**: Keep tools, prompts, graph, log parser, and UI separate and easy to extend.
- **Privacy/Local-First**: Run locally by default. Use user's own API keys. Minimize external calls where possible (cache aggressively).
- **Extensibility**: Design so new features (gear planner, macro suggestions, multi-character support, voice, overlay mode) can be added cleanly.
- **Code Quality**: Clean, well-commented Python. Use type hints. Handle errors gracefully. Make it easy to swap between Claude and OpenAI.
- **Testing**: Provide example runs and edge cases (different class combos, low vs high level, solo vs group).
- **Documentation**: Update README and prompts as features grow.

## Data Sources & Integration (Prioritize These)
1. **MCP Server** (https://github.com/Sergeantfirstclassvincetoxicumnegrum35/everquest-legends-mcp): Primary for wiki search (`eql_wiki_search`, `eql_wiki_page`), class combos, news, official sources. Run it separately and integrate via HTTP proxy or tool calls.
2. **Direct Wiki/MediaWiki API**: For EQL-specific wiki (search and page fetch).
3. **EQProgression.com** (especially /legends/ AA and spell sections): Structured class-specific data.
4. **eqlfaq.com** and community sources: Mechanics, multiclass rules, leveling guides.
5. **In-game + Logs**: Real-time zone, spell use, combat signals.
6. **Community**: YouTube guides, Reddit r/EQLegends, Discord for consensus on strong builds.

Cache results where appropriate. Implement refresh mechanisms.

## MVP Development (First Sprint)

**Phase 1: MCP Integration + Backend Scaffold** (do first):
1. Clone/run EQL MCP server locally.
2. Create `mcp_client.py`: HTTP wrapper to call MCP endpoints (`eql_wiki_search`, `eql_wiki_page`, etc.).
3. Create `backend/models.py`: SQLAlchemy Profile model (race, primary_class, secondary_class, tertiary_class, level, playstyle).
4. Create `backend/main.py`: FastAPI with `/profile` (POST/GET) and `/chat` (POST) endpoints.
5. Test: Can create a profile and store it.

**Phase 2: Agent Core** (next):
1. Create `agent/state.py`: LangGraph StateDict (profile, messages, suggestions, sources).
2. Create `agent/tools.py`: Spell suggestion tool (query MCP + claude reasoning).
3. Create `agent/prompts.py`: System prompt + spell-suggestion few-shot examples.
4. Create `agent/graph.py`: LangGraph workflow (user message → tools → suggestions + sources).
5. Test: `/chat` with "What spells should a Warrior/Bard/Wizard level 25 learn?" returns suggestions.

**Phase 3: Gradio Frontend** (parallel or after):
1. Create `frontend/gradio_app.py`: Forms for profile (race dropdowns, 3 class selects, level slider, playstyle radio).
2. Chat interface: User types question → calls backend `/chat` → displays suggestions markdown.
3. Test: Create profile, ask a question, see formatted suggestions.

**Phase 4: Expand Tools + Prompts** (after MVP):
1. Add AA suggestion tool (prioritize by level/role/archetype).
2. Add leveling zone tool (current/next zones with difficulty + group size).
3. Add gear suggestion tool (focus effects, procs, zone drops).
4. Tune prompts for multiclass synergies + source citations.
5. Test with various class combos (WAR/CLR/PAL, NEC/DRU/MNK, etc.).

**Post-MVP (not in v1.0)**:
- Log watcher + real-time context.
- React frontend + WebSocket.
- Gear/build planner, macro suggestions, multi-character support.
- Local LLM fallback.

## Development Rules

**Code Quality**:
- Type hints everywhere (Python 3.10+).
- Async/await for I/O (MCP calls, DB, HTTP).
- Error handling: Log gracefully, return user-friendly messages (never expose stack traces).
- Test edge cases: level 1 (no tertiary class), unusual combos, MCP timeouts.

**Data Accuracy**:
- Never invent EQL mechanics — always query MCP or cite known facts from CLAUDE.md.
- Always consider multiclass interactions (cross-class spell synergies, AA stacking, pet rules).
- Prioritize actionable, prioritized lists over walls of text.
- Cite sources (MCP page URL, EQProgression link, etc.).

**Architecture**:
- Modular: Tools, prompts, graph, DB, frontend cleanly separated.
- Stateless backend (state lives in SQLite + agent StateDict, not memory).
- Cache-friendly (MCP results cached, wiki searches deduplicated).
- Extensible: Add new tools without touching prompts; add new routes without touching tools.

**Privacy**:
- Local-first: Profiles and logs stay on disk.
- User controls API keys (in `.env`).
- No external calls beyond MCP (which user runs locally) and Claude API.

## Example Interaction

**User Profile**: Human Warrior / Bard / Wizard, level 25, Solo DPS focus.

**User**: "What spells should I learn?"

**Agent Response**:
```
**Top Priority (learn first)**:
1. Bard: Selo's Accelerando (Warrior synergy: run speed for kiting)
2. Warrior: Bloodrage (self-buff, +ATK)
3. Wizard: Frostbolt (burst DPS, cheap mana)

**Why**: Sells + Bloodrage = mobile self-buff; Frostbolt fills gaps when Warrior/Bard are cooldown.

**Cross-class synergies**:
- Wizard root spells enable Warrior tank moments
- Bard dex/att buffs scale all three classes

**Also available**: [list of good zone spells, clickie items, etc.]

**Sources**: MCP class database, EQL wiki, known player builds.
```

---

**How to Use This Prompt**:
When given a task, reference:
1. The **MVP Development** section (Phase 1–4) for what to build next.
2. The **Stack** section for technical decisions.
3. The **EQL Facts** for game mechanics.
4. The **Development Rules** for code quality.

Update this prompt as the project evolves. All future work references this spec.