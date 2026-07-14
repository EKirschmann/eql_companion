# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## v1.3.1 — 2026-07-14

- **Pre-buff spell set**: a second write button on the Pre-buffs section
  creates a "prebuffs" in-game set (permanent buffs first) — /memspellset
  prebuffs, buff up, then /memspellset companion for combat.
- **The advisor now knows which buffs are permanent** (self-target,
  zero-duration in the spell data — Instrument of Nife, Shielding line,
  Banshee Aura…) and is instructed never to suggest "refreshing" them.
- Spell-set write confirmations stay on screen until the next consult.

## v1.3.0 — 2026-07-14

- **Write in-game spell sets**: a button next to "Memorize now" writes the
  advisor's picks (priority order = gem order) straight into the game's
  saved spell sets as "companion" — then one command in game loads the whole
  bar: `/memspellset companion`. Existing sets are never touched and a
  one-time backup of the file is kept. Note: the game reads this file at
  login, so camp to character select and back before using the command.
- Saved sets are readable via /api/spellsets with spell ids decoded to names.

## v1.2.0 — 2026-07-14

- **Details-style damage meter overlay**: ranked class-colored bars over the
  game (like the WoW Details! addon) — bar length shows share of the leader,
  each row shows damage (or DPS) and percent of the group total, up to raid
  size. Two modes (Damage | DPS — click the title) and two segments (this
  fight | last 5 fights — click the right side of the header) while Scroll
  Lock is ON; click-through as always when it's OFF.

## v1.1.0 — 2026-07-14

- **Update checker**: click the version badge in the header to compare your
  install against the latest release; `update_companion.bat` pulls it.
- **Deterministic spell/AA grounding**: the advisor reads the eqlbuilds.com
  dataset snapshot directly (exact unlock levels, AA rank costs) instead of
  scraping wiki tables; spell verification works even without the MCP server.
- **Pet fix**: summoned-pet lines are compared by unlock level — the advisor
  can no longer recommend a lower-level pet than you own (necromancer bug).
- **Typed exaltation sockets**: focus / clicky / worn / proc (taxonomy per
  eqlegendstools.com); socket-move advice is constrained to same-type
  sockets, and proc stones to weapon slots.
- MCP data source repointed to the up-to-date ArtSabintsev repository.

## v1.0.0 — 2026-07-13

First shared release.

- Live HUD: vitals, War Ledger, encounter history with group/raid breakdowns
- Atlas: Brewall charts with live position (/loc + optional screen OCR with
  a guided setup), true-wall mined geometry, textured 3D with follow camera
- Advisor: wiki-grounded spell loadout tiers, AA counsel, upgrade warnings,
  hunting spots gated to the in-era community level table + leveling chart
- Gear: full 24-slot roster (both Any Slots), exaltation tracking, farming
  targets; machine-verified against your actual exports
- Counsel models: none (deterministic) / LM Studio / OpenAI / any
  OpenAI-compatible endpoint — switchable at runtime
- Sessions survive backend restarts; guided installer (`install_companion.bat`)
