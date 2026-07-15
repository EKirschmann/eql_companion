# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## v1.5.1 — 2026-07-14

- Fixed installs failing on Python 3.13: the OCR engine package now
  selects per Python version (rapidocr-onnxruntime up to 3.12, its
  successor rapidocr on 3.13+) — screen-OCR position tracking works on
  both. The installer also offers to install Python and Node.js for you
  via winget, and its window can no longer vanish before you read it.
- Downloads and one-click updates now track tagged releases, not
  in-development code.

## v1.5.0 — 2026-07-14

- **Update available, one click**: the app checks GitHub quietly (on load
  and every 6 hours) and shows an "Update available — vX.Y.Z" button next
  to the version; clicking it runs the updater in its own window. Updates
  no longer need git at all — ZIP installs update themselves via a
  built-in downloader that never touches your settings or data. Plus
  INSTALL.md: a plain-language install guide (no git, no command line).
- **Pet support, properly**: set your pet's equipment slot count in the
  Advisor and the gear consult builds it a loadout from spare bags/bank
  items (player keeps stat priority; at least one weapon). Pet abilities
  get their own encounter section; a mapped pet's kills and damage count
  as yours; a Vitals hint reminds you to /pet leader after summoning.
- **Encounter tables**: per-ability hit/cast counts (the Details-style x
  column); group heals show WHO healed; every fight shows a defense line.
- **Session hunting fixed**: XP attribution follows EQL's real line order
  (XP prints before its kill) — chain pulls no longer mis-credit; sorted
  by XP; per-level XP resets on ding; auto-sold loot shows "(sold)".
- **Advisor**: saved counsel restores after any restart (marked stale when
  your context moved on); exaltation moves respect class restrictions;
  keep-rows render dimmed; collapsed-ledger width goes to the encounter
  panel; vendor shopping list; loadout warnings ignore rituals and
  item-granted casts.

## v1.4.2 — 2026-07-14

- Collapsing the War Ledger in the normal layout now actually frees its
  column (slim vertical strip, like the Atlas/Advisor one) instead of
  leaving an empty panel.

## v1.4.1 — 2026-07-14

- The HUD is locked to the viewport on desktop: tall panels (encounter,
  advisor) scroll internally instead of stretching every column below the
  screen; the Atlas chart flexes to the available height.

## v1.4.0 — 2026-07-14

- **Combat dashboard**: hide the Atlas/Advisor panel and the encounter view
  reflows into side-by-side columns across the freed width; the War Ledger
  becomes a short strip and can collapse entirely; encounter text size is
  adjustable (A− / A+); the Companion chat tab is gone
- **Defense stats**: every fight now shows the tanking line — avoided %
  with dodge / parry / block / riposte / miss counts
- **Spell sets**: gems auto-ordered (DD, DoTs, AoE, heals from gem 8,
  utility, pets); pick-and-choose checkboxes (max 14) with a bigger,
  auto-backfilled nice-to-have list; the pre-buff set fills to 14 with
  permanents first then longest-duration buffs
- **Vendor shopping list**: near-level missing spells worth buying, marked
  "buy ahead" when above your level (spells scribe early)
- Loot lines that auto-sold show "(sold)"; loadout-change warnings no longer
  misfire on travel rituals or exaltation-granted casts; the overlay closes
  with the game and never doubles

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
