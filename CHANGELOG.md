# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## v1.9.0 — 2026-07-21

Big combat-log accuracy release: the parser now recognizes a large set
of real EQL line formats it previously dropped (found by studying two
excellent community projects — EQBuddy and eql-log-reader), pets map
themselves with zero setup, and the game's own spell file grounds proc
and lifetap detection.

- **Damage numbers are more complete.** Newly parsed: incoming DoT
  ticks (damage you take from dots was invisible before), plain and
  incoming non-melee nukes, damage shields in all three directions
  (yours counts toward damage/DPS but never inflates swing accuracy),
  and casterless proc/poison ticks. One real log had 38,000+ damage
  shield hits that were simply missing.
- **Crits are tracked.** Trailing tags — "(Critical)", stacked
  "(Riposte) (Critical)", "(Crippling Blow)" — are recognized, counted
  per session and per ability, and marked with ✦ in the War Ledger.
- **More of the world parses**: named spell fizzles and interrupts
  (bard forms too), resists in both directions (shown per fight),
  faction hits, item merges, advanced-loot destroys, group coin
  splits, vendor sales, multi-stack auto-sells, banked-to-depot loot,
  and Berserker frenzy / cleave / smite / reave / shoot verbs. The
  "You now have N ability points" total now drives the unspent-AA
  counter authoritatively.
- **Chat can no longer pollute combat stats**: speech lines are
  excluded before combat matching, so players quoting combat text in
  /say or /tell don't register as damage.
- **Pets map themselves.** The pet's own "Attacking X Master." tell
  (printed only to your log) registers it automatically — no /pet
  leader needed (it still works). Charm handling: a "pet" that turns
  on you un-maps instantly; slain pets un-map.
- **The game's spell file grounds the tricky calls** (spells_us.txt,
  read from the game folder — nothing installed): exaltation effects
  that are also scribed spells now label "(exaltation)" when the data
  says proc-granted and you never cast them; and lifetap self-healing
  is synthesized — your own taps log no heal line at all, so that
  healing never counted before.
- **Fairer XP and coin attribution**: corpse coin now converts to
  copper and credits the mob like XP does; rewards that print AFTER a
  kill (looting the corpse later, trailing party XP) fall back to that
  kill instead of being dropped. Per-mob stats now track coin and
  drop counts.
- Log reading hardened: correct cp1252 decoding (accented names no
  longer risk breaking parses), a log-staleness signal on /health, and
  the game folder is auto-discovered from the Daybreak registry entry
  when the configured path doesn't exist.
## v1.8.0 — 2026-07-21

- **Gear advice now uses REAL +N stats.** The wiki's Item Level slider
  formula (eqlwiki computes upgraded stats client-side from the base
  item) is ported into the app and verified to match the site
  bit-for-bit: primary stats gain ~10% of base per level (+1/level for
  small values), weapon damage gains floor(base×N/10), haste/regen +1
  per level, weight drops, and items with 2+ stats grow the emergent
  "SV VOID: +N" resist. Every owned item in the gear consult is shown
  at its actual owned rank ("[stats at +4]"), so comparisons are
  honest both ways — a higher +N no longer auto-wins, and a strong +0
  drop can rightfully beat a worn +2.
- Deterministic mode (LLM "none", and the fallback when a model call
  fails) got real cross-item recommendations: besides same-item
  higher-rank detection it now suggests a bags/bank item when it is
  strictly better than the worn one — equal or higher on every scaled
  stat, higher on at least one — slot- and class-checked.
- **Pet hand-overs are verified before display.** The consult now
  shows the model the pet's currently-held items WITH their scaled
  stats (they aren't in your inventory export, so they were previously
  compared as bare names), asks it to name what each hand-over
  replaces, and a new deterministic gate drops any suggestion that is
  strictly worse than something the pet already holds — no more
  "replace the 19 AC breastplate with a 17 AC coat".
- Exaltations: stones whose base item carries a **Focus Effect**
  (a separate wiki field that our parser missed — it even renders
  glued onto the Race line) now show that effect and type as focus
  stones with correct "can socket into" rules, instead of
  "no listed effect (stat stone?)".
- Gear tab layout: Pet gear now sits directly under the player slot
  table, with Exaltations after it.
- Pet mechanics corrected per the definitive spec (since v1.7.0):
  pet gear is a flat bag of N generic slots — no invented Head/Arms
  rows; every pet is base Warrior plus a secondary class by pet type
  (set via the new "pet 2nd class" dropdown); it can equip gear usable
  by its two classes or any of your trio (Attunable only, never
  No-Drop); the slot count auto-computes from your class combo and
  stays overridable; gear persists through death and re-summon.
- Quieter logs: wiki pages that don't exist (the HTTP fallback covers
  them) no longer warn on every consult.
## v1.7.0 — 2026-07-19

- Fixed the launcher serving a stale (older-version) interface in
  production mode: start_companion.bat now rebuilds the UI automatically
  whenever the source changed since the last build.
- Pet tracking: reads /pet inventory check to know the pet's real loadout;
  a mapped pet shows as its own "(pet)" row in group DPS with its abilities
  tracked; gear consult fills the pet's empty slots and respects the slot
  count you set; an emptied pet is recognized and cleared.
- Exaltations: "can socket into" now uses the real class/slot rules
  (eqlwiki) — proc stones need a shared class with the target weapon, etc.
- AA counsel drops already-owned/maxed ranks (rank recovered from data
  since the log omits it); gear recs are slot- and class-checked.
- Groundwork for a dependency-free single executable (deterministic, no-OCR
  build; single-process serving).

## v1.6.1 — 2026-07-17

- Hunting recommendations follow the community's redesigned
  Recommended-Levels table: per-level efficiency ratings (efficient /
  doable / not recommended), explicit level ranges, and zone types.
  The advisor now strongly prefers zones the community rates EFFICIENT at
  your level, cities are excluded by their own Type column, and the
  leveling chart reflects the rated bands (gaps included).
- Encounter parse labels exaltation proc damage "(exaltation)" — except
  effects that are also scribed spells, which stay attributed to your
  casting.

## v1.6.0 — 2026-07-15

- **Much lighter on your PC**: the interface now runs as a production
  build (~350MB less RAM, no file watchers) and the backend drops its
  dev-mode reloader; the installer/updater build the interface once
  (about a minute). Developers: `start_companion.bat dev` keeps the old
  hot-reload behavior.
- OCR position tracking skips its neural-net pass entirely when the
  captured pixels haven't changed — standing still or sitting in menus
  now costs (almost) no CPU.
- Session snapshots write only when something actually happened.

## v1.5.3 — 2026-07-14

- Fixed "CERTIFICATE_VERIFY_FAILED" when checking or downloading updates:
  Python now validates GitHub with the bundled certifi certificate store
  (some Windows Pythons and antivirus HTTPS-scanning break the default
  one). If you are already stuck on it: run `pip install certifi` once,
  or download the ZIP in your browser — then updates work normally.
- Update checks fall back to the plain GitHub website when the API is
  rate-limited (shared IPs), and error messages show the real cause.

## v1.5.2 — 2026-07-14

- OCR on Python 3.13 actually works now: the rapidocr v2 engine needs the
  onnxruntime package installed separately (CPU package — no graphics
  card requirement) and it was missing from the requirements. Update and
  the calibrator's "onnxruntime is not installed" error goes away.

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
