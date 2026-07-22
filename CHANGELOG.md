# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## v1.12.0 — 2026-07-22

The overlay grows up (EQBuddy-inspired), and the companion learns what
a "session" is:

- **The overlay is now a session widget**, not just a damage meter.
  Four sections: COMBAT (the familiar ranked bars), SESSION (kills,
  deaths, XP% with XP/hr, coin with coin/hr, crits, hit rate), LOOT
  (recent drops + your best observed drop-rate mobs), and PROGRESS
  (level, an honest hours-to-ding estimate, session vs active time).
  With Scroll Lock on: click a section header to fold it, press c for
  a compact one-line strip, +/- to adjust opacity — position, opacity,
  and layout persist between launches. Click-through, the singleton
  guard, and auto-close on game exit are unchanged.
- **Honest per-hour rates**: XP/coin/kills per hour are computed
  against ACTIVE time (2-minute activity buckets) as well as elapsed —
  a 30-minute AFK no longer drags your rates down. Hours-to-level says
  "(max)" until you ding once in the session, then turns exact.
- **Session history**: the login banner now rolls the session over —
  the finished session's summary (kills, XP, coin, loot count, damage,
  max DPS, active hours) is archived, counters reset, and a new "Past
  sessions" table in the Vitals panel shows your recent sessions.
  Empty sessions are never recorded. What the app KNOWS (pet mappings,
  rosters, owned AAs) survives the rollover.
- **Screen-OCR position feed rescues misread coordinates**: classic
  letter/digit confusions (O/0, l/1, S/5, B/8) are corrected inside
  numbers — "X: -1O2" parses as -102, and a fully-misread "Z: -SO"
  after its label parses as -50 — frames that used to be dropped now
  land. Zone names are never altered.
- The main Consult now shows the same dimming veil over stale counsel
  that the gear consult has — no more wondering whether it heard you.
## v1.11.0 — 2026-07-21

Community-sourced upgrades (with thanks to kpxcoolx/eql-meter,
Velkenn/EQL-Effects-Finder, xaziaver/eql-weapon-inflection-analyzer,
terry-wilkerson/EQL-Loot-Filter-Manager, and rari/eqltools):

- **Exaltation tracking is now game-authoritative.** Your inventory
  export lists every socket on your gear (type included) — the app now
  reads them directly: stone types come from the game, "can socket
  into" requires a genuinely EMPTY socket of the right type, and since
  real exports show proc sockets on earrings and faces, the export
  overrides the old proc-goes-in-weapons assumption.
- **Loot filter awareness**: the app passively reads your LF_*.ini —
  merge notices now warn when an item is set to auto-sell or
  auto-merge, and /api/loot-filter summarizes your filter.
- **Smarter weapon advice**: 1H weapons show main-hand / off-hand
  white-DPS indices built on the real combat model — the main-hand
  damage bonus is a flat, delay-independent add (fast MH weapons beat
  their ratio) and the off-hand swings part-time with no bonus, so the
  best MH is often not the best OH.
- **Travel routes use rituals and translocators**: the route finder
  knows naval translocator dock cliques (Freeport–Butcherblock in one
  hop) and druid/wizard port rituals castable from anywhere —
  Rivervale to Erudin is now "cast Circle of Toxxulia, walk to Erudin"
  instead of nine zone lines.
- **Combat log accuracy**: rune absorption is tracked (new session
  stat), "magical skin absorbs the blow" counts as its own defense,
  self-inflicted damage (cannibalize, damage-shield ticks) counts as
  damage taken instead of polluting DPS, faction-cap lines parse,
  raid /who rows no longer misread the group number as your race, and
  other players' pets swinging as "Name`s warder" fold into their
  owner instead of vanishing.
- **Encounters**: each fight now shows its peak 3-second burst DPS,
  and a "copy" button produces a one-line shareable parse.
- Exaltation stones in the gear tab show where their base item drops
  on hover. A real-log regression fixture and
  `scripts/parser_coverage.py` make the after-patch parser check
  reproducible.
## v1.10.1 — 2026-07-21

Smarter merge notices and exaltation-aware weapon advice:

- **Merging worn pairs is no longer suggested blindly.** When both
  copies of an item are worn (ears/wrists/fingers), the merge notice
  shows the real trade in red — e.g. wearing two +4 bracers gives
  AC 20 / HP 18 while the merged +5 alone gives AC 11 / HP 10 — and
  says to keep both unless a better filler exists for the freed slot.
- **Weapon swaps respect exaltation stones.** Item lines in the
  consult now show which stones they host, and the advisor follows the
  real rules: stones move between your items for free, so they follow
  the better weapon instead of anchoring the worse one — but proc
  stones may only fire from the Primary slot, so a swap that would
  strand a proc off-hand now says "move its stone into your primary
  first" instead of silently wasting it.
## v1.10.0 — 2026-07-21

The knowledge release: the advisor now consults curated class guides,
item names grew where-to-get-it hover cards, and duplicate gear
surfaces merge opportunities.

- **Class guides** (`class_guides/*.md`, editable): every consult now
  reads curated guide files for your trio — a cross-class mechanics &
  meta file (combat-roll math, the two-highest-classes HP rule, healer/
  slower requirements, mote strategy), reference files for races,
  stances & invocations (including how invocation bonuses scale with
  your trio composition), and rituals, plus one file per class: deep
  community-sourced guides for Enchanter (Cavepig) and Necromancer
  (Haitsmelol/Necrotalk) and wiki-baseline files for the other 14.
  Update them freely after patches — see class_guides/README.md.
- **Item hover cards**: hover any item name in the Gear tab (slots,
  farm targets, merges, pet hand-overs) to see where it comes from —
  Drops From (zone + mob), Sold by, quests, and crafting, mined from
  the wiki's rendered item pages.
- **Merge opportunities**: owning two copies of the same equipment
  (bags/bank/worn) now lists them under the slot table with the
  predicted merge result from the wiki's progression model — equal
  ranks merge to exactly one rank up; a +0 into a +6 shows the tiny
  fractional gain honestly. Copies hosting exaltation stones are
  flagged first.
- **Honest survivability framing**: set your Max HP/Mana in the Vitals
  panel (the log never prints them) and gear advice frames HP swaps as
  percentages; with recent combat observed, it can say "+75 HP ≈ 2
  average incoming hits". Magnitude adjectives without data are now
  banned from gear counsel.
- **Log accuracy** (from the July patch notes, verified against real
  logs): heal crits are now parsed and counted (they only started
  logging on 7/7), and tier-suffixed spell names ("Lay on Hands VI")
  match correctly everywhere — proc labeling, lifetap detection, cast
  evidence.
- **Hunting keeps up with patches**: dev-revamped zones override the
  community sheet's stale bands — Crushbone now advertises 4-22 and
  Splitpaw 25-42, each tagged with the patch note.
- Reliability: item names that miss the wiki fuzzy-resolve via search
  + edit distance; wiki caches serve the last good data when a refresh
  fails; the OCR position feed gains a contrast boost for small text
  (thanks to DavisChappins/eql-tooltip for the techniques).
## v1.9.1 — 2026-07-21

The panels catch up with everything v1.9.0 started tracking:

- **Vitals & Session**: new "Coin earned" tile — a real session money
  total (corpse coin + group splits + vendor sales, shown as
  "3p 2g 6s 7c") that survives restarts — and a "Crits ✦" tile.
- **Session hunting table**: per-mob Coin and Drops columns — Drops is
  your observed drop rate (items dropped ÷ kills), so farming spots
  show their real yield; hovering a row still lists the items.
- **Encounter panel**: ability rows show per-ability crit counts
  ("12 ✦3") in the current fight, the pet section, and the last-5-
  fights aggregate; a "resisted" line lists which spells the foe
  resisted and how often; damage-shield damage appears as its own
  gold-accented row instead of hiding in the totals; and lifetap
  self-healing (synthesized in v1.9.0) shows in the Healing section.
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
