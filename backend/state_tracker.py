"""In-memory character/session state built from the live event stream.

Seed events (log history replayed at startup) establish zone/level/class
and pre-fill the ledger buffer; only LIVE events count toward session
stats (kills, damage, DPS) so numbers reflect this play session.
"""
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from backend.log_system import events as ev
from backend.log_system.parser import CLASS_ABBREV

DPS_WINDOW_SECONDS = 60
COMBAT_TIMEOUT_SECONDS = 8
LEDGER_SIZE = 300

_FULL_TO_ABBR = {v.lower(): k for k, v in CLASS_ABBREV.items()}


def _abbrev_classes(class_str) -> str:
    """'Paladin/Druid/Monk' -> 'PAL/DRU/MNK' (unknown names pass through)."""
    if not class_str:
        return ""
    return "/".join(_FULL_TO_ABBR.get(p.strip().lower(), p.strip())
                    for p in str(class_str).split("/"))


def _foe_key(name: str) -> str:
    """Log lines capitalize the article at sentence start ("A dread bone
    kicks YOU") but not mid-sentence ("You crush a dread bone") -- fold the
    article case so one mob is one foe row. Named mobs (no article) pass
    through untouched. Note: the log carries no unique mob IDs, so two
    distinct mobs sharing a name still merge into one row by design."""
    for art in ("A ", "An ", "The "):
        if name.startswith(art):
            return art.lower() + name[len(art):]
    return name


class CharacterTracker:
    def __init__(self, name: Optional[str], server: Optional[str]):
        self.name = name or "Unknown"
        self.server = server or "unknown"
        # Enrichment (from who-lines / level-ups / DB / user edits)
        self.level: Optional[int] = None
        self.class_str: Optional[str] = None
        self.race: Optional[str] = None
        self.playstyle: Optional[str] = None
        self.aa_available: Optional[int] = None  # unspent AA points (user-set; +1 per gain)
        self.spell_slots: Optional[int] = None   # spell slots unlocked via AAs (user-set)
        self.zone: Optional[str] = None
        # Session counters (live events only)
        self.damage_dealt = 0
        self.damage_taken = 0
        self.healing_received = 0
        self.healing_done = 0
        self.kills = 0
        self.deaths = 0
        self.xp_ticks = 0
        self.xp_percent = 0.0   # summed from EQL's "(1.107%)" exp lines
        self.aa_points = 0
        self.skill_ups = 0
        self.swings_hit = 0     # melee accuracy
        self.swings_missed = 0
        self.loots: deque[str] = deque(maxlen=20)
        self.last_target: Optional[str] = None
        self.last_event_at: Optional[datetime] = None
        self.position: Optional[dict] = None  # from /loc lines
        self.session_max_dps: float = 0.0
        # Rolling buffers
        self._dmg_window: deque[tuple[datetime, int]] = deque()
        self.ledger: deque[dict] = deque(maxlen=LEDGER_SIZE)
        # Current/last encounter: per-ability damage breakdown. Persists after
        # combat ends; a new pull archives it into encounter_history.
        self.encounter: Optional[dict] = None
        self.encounter_history: deque[dict] = deque(maxlen=5)  # finished pulls, newest first
        # Loadout staleness: cast spells not castable by the saved trio
        self.unknown_casts: dict[str, str] = {}
        self.loadout_hint: Optional[str] = None
        # Death recap: frozen slice of incoming damage at the moment of death
        self.last_death: Optional[dict] = None
        # Per-mob session stats (kills, attributed xp, loot seen on corpses)
        self.mob_stats: dict[str, dict] = {}
        self._last_kill: Optional[tuple] = None  # (foe key, ts) for xp attribution
        # Finished pulls awaiting DB persistence (drained by the flush loop)
        self.pending_encounters: list[dict] = []
        # Injected by main: spellbook loader + whether a log file exists
        self.spellbook_loader = None
        self.has_log = False
        # Level + abbreviated trio per player seen in /who output
        self.who_roster: dict[str, dict] = {}
        # Pet name -> owner name, learned from "My leader is X" lines
        self.pet_owners: dict[str, str] = {}
        self.pet_owners_dirty = False  # flush loop persists when set
        self._aa_from_db = False       # roster restored from DB, not the log
        # Owned AA ranks from '/alternateadv list' (one line per rank)
        self.owned_aas: dict[str, dict] = {}
        self._last_aa_seen: Optional[datetime] = None
        self._last_aa_name: Optional[str] = None
        # set when a pet summon is cast but no pet maps to us — the pet's
        # damage lands in the ally rows until /pet leader is typed
        self.pet_hint = False

    def _touch_encounter(self, ts: datetime) -> None:
        if (self.encounter is None or
                (ts - self.encounter["last"]).total_seconds() > COMBAT_TIMEOUT_SECONDS):
            if self.encounter is not None:
                self.encounter_history.appendleft(self.encounter)
                self.pending_encounters.append(
                    self._encounter_view(self.encounter, live=False))
                del self.pending_encounters[:-10]
            self.encounter = {"started": ts, "last": ts, "target": None,
                              "total_out": 0, "total_in": 0, "abilities": {},
                              "foes": {}}
        else:
            self.encounter["last"] = ts

    def _encounter_heal(self, ts: datetime, label: str, amount: int) -> None:
        enc = self.encounter
        if (enc is None or
                (ts - enc["last"]).total_seconds() > COMBAT_TIMEOUT_SECONDS):
            return
        hl = enc.setdefault("heals", {}).setdefault(
            label, {"hits": 0, "total": 0})
        hl["hits"] += 1
        hl["total"] += amount

    def _encounter_ability(self, ts: datetime, name: str, kind: str, damage: int,
                           target: Optional[str] = None) -> None:
        self._touch_encounter(ts)
        enc = self.encounter
        ab = enc["abilities"].setdefault(name, {"kind": kind, "hits": 0, "total": 0})
        ab["hits"] += 1
        ab["total"] += damage
        enc["total_out"] += damage
        if target:
            enc["target"] = target
            self._encounter_foe(target, dealt=damage)

    def _encounter_foe(self, name: str, dealt: int = 0, taken: int = 0,
                       slain: bool = False) -> None:
        """Aggregate per-mob totals for the multi-mob pull display."""
        name = _foe_key(name)
        foe = self.encounter.setdefault("foes", {}).setdefault(
            name, {"dealt": 0, "taken": 0, "slain": False})
        foe["dealt"] += dealt
        foe["taken"] += taken
        if slain:
            foe["slain"] = True

    # ---- event ingestion -------------------------------------------------
    def apply(self, e: ev.LogEvent, live: bool) -> None:
        if isinstance(e, ev.ZoneChange):
            self.zone = e.zone
            self.position = None  # old coords are meaningless in a new zone
        elif isinstance(e, ev.LocUpdate) and live:
            self.position = {"x": e.x, "y": e.y, "z": e.z, "ts": e.ts.isoformat()}
        elif isinstance(e, ev.LevelUp):
            self.level = e.level
            # XP boxes + hunting XP are per-LEVEL: a ding resets them (kills,
            # loot, and damage stay session-wide)
            self.xp_ticks = 0
            self.xp_percent = 0.0
            for stats in self.mob_stats.values():
                stats["xp_percent"] = 0.0
        elif isinstance(e, ev.CharacterInfo):
            self.level = e.level
            if e.class_str:
                # /who reports the LIVE loadout (full trio) -- always trust it
                # over stale saved trios; loadout swaps write nothing else.
                self.class_str = e.class_str
                self.unknown_casts.clear()
                self.loadout_hint = None
            self.race = self.race or e.race
        elif isinstance(e, ev.OtherCharInfo):
            self.who_roster[e.name] = {"level": e.level, "classes": e.classes}
        elif isinstance(e, ev.PetLeader):
            if e.owner.lower() == (self.name or "").lower():
                self.pet_hint = False
            if self.pet_owners.get(e.pet) != e.owner:
                self.pet_owners[e.pet] = e.owner
                self.pet_owners_dirty = True
        elif isinstance(e, ev.AAListEntry):
            # ownership data, not session data: applies in seed replay too.
            # Skip listings OLDER than what we already hold (e.g. the seed
            # replays a burst that predates the DB-restored roster).
            if self._last_aa_seen is not None and e.ts < self._last_aa_seen:
                return_early = True
            else:
                return_early = False
            if not return_early:
                if (self._aa_from_db or self._last_aa_seen is None or
                        (e.ts - self._last_aa_seen).total_seconds() > 5):
                    # fresh listing (or a replay of the persisted one)
                    self.owned_aas.clear()
                    self._aa_from_db = False
                entry = self.owned_aas.setdefault(
                    e.name, {"id": e.aa_id, "ranks": 0, "cost": None, "desc": None})
                entry["ranks"] += 1
                self._last_aa_seen = e.ts
                self._last_aa_name = e.name
        elif isinstance(e, ev.AAListMeta):
            if (self._last_aa_name and self._last_aa_seen is not None and
                    0 <= (e.ts - self._last_aa_seen).total_seconds() <= 5):
                entry = self.owned_aas.get(self._last_aa_name)
                if entry:
                    if e.cost is not None:
                        entry["cost"] = e.cost
                    if e.desc and not entry["desc"]:
                        entry["desc"] = e.desc[:150]

        if live:
            self.last_event_at = e.ts
            if isinstance(e, (ev.MeleeOut, ev.SpellDamageOut, ev.DotDamage)):
                self.damage_dealt += e.damage
                self.last_target = e.target
                self._dmg_window.append((e.ts, e.damage))
                if isinstance(e, ev.MeleeOut):
                    self.swings_hit += 1
                    self._encounter_ability(e.ts, e.verb.capitalize(), "melee",
                                            e.damage, e.target)
                elif isinstance(e, ev.SpellDamageOut):
                    self._encounter_ability(e.ts, e.spell, "spell", e.damage, e.target)
                else:  # DotDamage
                    self._encounter_ability(e.ts, e.spell, "dot", e.damage, e.target)
            elif isinstance(e, ev.MissOut):
                self.swings_missed += 1
            elif isinstance(e, ev.OtherDamageOut):
                owner = self.pet_owners.get(e.attacker)
                if (e.attacker.lower() == f"{self.name} pet".lower()
                        or (owner and owner.lower() == self.name.lower())):
                    # OUR pet (by "<name> pet" convention, or a named summon
                    # mapped via a "My leader is" line): player-side damage.
                    self.damage_dealt += e.damage
                    self._dmg_window.append((e.ts, e.damage))
                    self._encounter_ability(e.ts, f"Pet: {e.source}", "pet",
                                            e.damage, e.target)
                else:
                    # Group DPS: credit other players/pets only while an
                    # encounter is live AND they hit one of OUR foes. Never
                    # extends the window (bystanders would keep it alive).
                    enc = self.encounter
                    if (enc is not None
                            and (e.ts - enc["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS
                            and _foe_key(e.target) in enc.get("foes", {})):
                        # another player's pet folds into its owner's row
                        who = owner or e.attacker
                        allies = enc.setdefault("allies", {})
                        allies[who] = allies.get(who, 0) + e.damage
            elif isinstance(e, (ev.MeleeIn, ev.SpellDamageIn)):
                self.damage_taken += e.damage
                self._touch_encounter(e.ts)
                self.encounter["total_in"] += e.damage
                self.encounter["in_hits"] = self.encounter.get("in_hits", 0) + 1
                self._encounter_foe(e.attacker, taken=e.damage)
            elif isinstance(e, ev.MissIn):
                # tanking view: which defense ate each incoming swing
                enc = self.encounter
                if (enc is not None and
                        (e.ts - enc["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS):
                    d = enc.setdefault("defense", {})
                    d[e.defense] = d.get(e.defense, 0) + 1
            elif isinstance(e, ev.HealReceived):
                self.healing_received += e.amount
            elif isinstance(e, ev.HealOut):
                self.healing_done += e.amount
                self._encounter_heal(e.ts, f"{e.spell} — You", e.amount)
            elif isinstance(e, ev.OtherHeal):
                if e.target.lower() == (self.name or "").lower():
                    self.healing_received += e.amount
                healer = self.pet_owners.get(e.healer, e.healer)
                self._encounter_heal(e.ts, f"{e.spell} — {healer}", e.amount)
            elif isinstance(e, ev.Kill):
                self.kills += 1
                mob = _foe_key(e.target)
                stats = self.mob_stats.setdefault(
                    mob, {"kills": 0, "xp_percent": 0.0, "loots": []})
                stats["kills"] += 1
                self._last_kill = (mob, e.ts)
                if self.encounter and (e.ts - self.encounter["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS:
                    self.encounter["last"] = e.ts
                    self._encounter_foe(e.target, slain=True)
            elif isinstance(e, ev.MyDeath):
                self.deaths += 1
                self.last_death = self._death_recap(e)
            elif isinstance(e, ev.ExpGain):
                self.xp_ticks += 1
                if e.percent:
                    self.xp_percent += e.percent
                    # attribute to the mob slain moments ago (heuristic window)
                    if (self._last_kill and
                            (e.ts - self._last_kill[1]).total_seconds() <= 6):
                        self.mob_stats[self._last_kill[0]]["xp_percent"] += e.percent
            elif isinstance(e, ev.AAPoint):
                self.aa_points += 1
                if self.aa_available is not None:
                    self.aa_available += 1
            elif isinstance(e, ev.SkillUp):
                self.skill_ups += 1
            elif isinstance(e, ev.Loot):
                label = f"{e.item} → {e.upgraded_to}" if e.upgraded_to else e.item
                if e.sold:
                    label += " (sold)"
                self.loots.appendleft(label)
                # loot lines name the corpse: exact per-mob attribution
                if e.source and "'s corpse" in e.source:
                    mob = _foe_key(e.source.split("'s corpse")[0].strip())
                    stats = self.mob_stats.setdefault(
                        mob, {"kills": 0, "xp_percent": 0.0, "loots": []})
                    if e.item not in stats["loots"] and len(stats["loots"]) < 8:
                        stats["loots"].append(e.item)

        if e.type not in ("other_out", "aa_list", "aa_meta", "who_other"):
            # other_out is too spammy; aa listing bursts are metadata
            self.ledger.append({**e.model_dump(mode="json"), "live": live})

    # ---- derived ----------------------------------------------------------
    def dps(self) -> float:
        cutoff = datetime.now() - timedelta(seconds=DPS_WINDOW_SECONDS)
        while self._dmg_window and self._dmg_window[0][0] < cutoff:
            self._dmg_window.popleft()
        if not self._dmg_window:
            return 0.0
        total = sum(d for _, d in self._dmg_window)
        span = (self._dmg_window[-1][0] - self._dmg_window[0][0]).total_seconds()
        value = total / max(span, 1.0)
        self.session_max_dps = max(self.session_max_dps, value)
        return round(value, 1)

    def in_combat(self) -> bool:
        if not self._dmg_window:
            return False
        return (datetime.now() - self._dmg_window[-1][0]).total_seconds() < COMBAT_TIMEOUT_SECONDS

    def _encounter_view(self, enc: dict, live: bool) -> dict:
        duration = max((enc["last"] - enc["started"]).total_seconds(), 1.0)
        abilities = [
            {
                "name": name,
                "kind": ab["kind"],
                "hits": ab["hits"],
                "total": ab["total"],
                "avg": round(ab["total"] / ab["hits"], 1),
                "dps": round(ab["total"] / duration, 1),
            }
            for name, ab in enc["abilities"].items()
        ]
        abilities.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        foes = [
            {"name": name, "damage": f["dealt"], "taken": f["taken"],
             "slain": f["slain"]}
            for name, f in enc.get("foes", {}).items()
        ]
        foes.sort(key=lambda f: (f["slain"], -f["damage"]))
        heals = [
            {"name": name, "kind": "heal", "hits": hl["hits"], "total": hl["total"],
             "avg": round(hl["total"] / hl["hits"], 1),
             "dps": round(hl["total"] / duration, 1)}
            for name, hl in enc.get("heals", {}).items()
        ]
        heals.sort(key=lambda a: a["total"], reverse=True)
        allies = []
        for name, dmg in enc.get("allies", {}).items():
            who = self.who_roster.get(name, {})
            allies.append({"name": name, "damage": dmg,
                           "dps": round(dmg / duration, 1),
                           "level": who.get("level"),
                           "classes": who.get("classes")})
        if allies and enc["total_out"] > 0:
            allies.append({"name": "You", "damage": enc["total_out"],
                           "dps": round(enc["total_out"] / duration, 1),
                           "level": self.level,
                           "classes": _abbrev_classes(self.class_str)})
        allies.sort(key=lambda a: a["damage"], reverse=True)
        active = live and (datetime.now() - enc["last"]).total_seconds() < COMBAT_TIMEOUT_SECONDS
        return {
            "active": active,
            "allies": allies,
            "started": enc["started"].isoformat(),
            "target": enc["target"],
            "foes": foes,
            "heals": heals,
            "total_healing": sum(h["total"] for h in heals),
            "duration": round(duration, 1),
            "total_damage": enc["total_out"],
            "damage_taken": enc["total_in"],
            "in_hits": enc.get("in_hits", 0),
            "defense": dict(enc.get("defense") or {}),
            "dps": round(enc["total_out"] / duration, 1),
            "abilities": abilities,
        }

    def encounter_snapshot(self) -> Optional[dict]:
        if not self.encounter:
            return None
        return self._encounter_view(self.encounter, live=True)

    def encounters_snapshot(self) -> list[dict]:
        """Current/last pull first, then previous pulls (5 total max)."""
        out = []
        if self.encounter:
            out.append(self._encounter_view(self.encounter, live=True))
        for enc in self.encounter_history:
            if len(out) >= 5:
                break
            out.append(self._encounter_view(enc, live=False))
        return out

    def ability_summary(self) -> dict:
        """Per-ability aggregate across the last 5 pulls — surfaces which
        abilities actually hit hardest over time, not just this fight."""
        encs = ([self.encounter] if self.encounter else []) + list(self.encounter_history)
        encs = encs[:5]
        if not encs:
            return {"encounters": 0, "duration": 0, "abilities": []}
        total_dur = sum(
            max((e["last"] - e["started"]).total_seconds(), 1.0) for e in encs)
        merged: dict[str, dict] = {}
        for e in encs:
            for name, ab in e["abilities"].items():
                m = merged.setdefault(name, {"kind": ab["kind"], "hits": 0, "total": 0})
                m["hits"] += ab["hits"]
                m["total"] += ab["total"]
        abilities = [
            {"name": n, "kind": m["kind"], "hits": m["hits"], "total": m["total"],
             "avg": round(m["total"] / m["hits"], 1),
             "dps": round(m["total"] / total_dur, 1)}
            for n, m in merged.items()
        ]
        abilities.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        merged_heals: dict[str, dict] = {}
        for e in encs:
            for name, hl in e.get("heals", {}).items():
                m = merged_heals.setdefault(name, {"hits": 0, "total": 0})
                m["hits"] += hl["hits"]
                m["total"] += hl["total"]
        heals = [
            {"name": n, "kind": "heal", "hits": m["hits"], "total": m["total"],
             "avg": round(m["total"] / m["hits"], 1),
             "dps": round(m["total"] / total_dur, 1)}
            for n, m in merged_heals.items()
        ]
        heals.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        return {"encounters": len(encs), "duration": round(total_dur, 1),
                "abilities": abilities, "heals": heals}

    def _death_recap(self, e: ev.MyDeath) -> dict:
        """The last 15s of incoming damage, frozen at the moment of death."""
        cutoff = e.ts - timedelta(seconds=15)
        hits: list[dict] = []
        for r in reversed(self.ledger):
            if r["type"] not in ("melee_in", "spell_in"):
                continue
            try:
                ts = datetime.fromisoformat(r["ts"])
            except (KeyError, ValueError, TypeError):
                continue
            if ts < cutoff:
                break
            hits.append({"attacker": r.get("attacker"),
                         "damage": r.get("damage", 0),
                         "source": r.get("spell") or r.get("verb") or "hit",
                         "ts": r["ts"]})
            if len(hits) >= 12:
                break
        hits.reverse()
        return {"ts": e.ts.isoformat(), "killer": e.killer,
                "total": sum(h["damage"] for h in hits), "hits": hits}

    def recent_casts(self, limit: int = 20) -> list:
        """Distinct spells recently cast, newest first (includes seed replay
        so the advisor sees the loadout in use even right after startup)."""
        seen: list = []
        for r in reversed(self.ledger):
            if r["type"] == "cast":
                s = r.get("spell")
                if s and s not in seen:
                    seen.append(s)
            if len(seen) >= limit:
                break
        return seen

    def recent_activity_summary(self, limit: int = 8) -> str:
        """Short prose summary of recent notable events, fed to the AI agent."""
        notable = [r for r in list(self.ledger)[-60:] if r["type"] in
                   ("zone", "kill", "death", "level", "aa", "loot", "cast")]
        if not notable:
            return "No recent notable activity."
        parts = []
        for r in notable[-limit:]:
            t = r["type"]
            if t == "zone":
                parts.append(f"entered {r['zone']}")
            elif t == "kill":
                parts.append(f"slew {r['target']}")
            elif t == "death":
                parts.append(f"was slain by {r['killer']}")
            elif t == "level":
                parts.append(f"reached level {r['level']}")
            elif t == "aa":
                parts.append("earned an AA point")
            elif t == "loot":
                parts.append(f"looted {r['item']}")
            elif t == "cast":
                parts.append(f"cast {r['spell']}")
        return "Recently: " + ", ".join(parts) + "."

    def _sync_hints(self, book: Optional[dict]) -> list:
        """In-game commands worth running, with why. Rendered in Vitals."""
        hints = []
        if not self.has_log:
            hints.append({"command": "/log on",
                          "reason": "No log file found — the companion is blind without one"})
        if self.pet_hint:
            hints.append({"command": "/pet leader",
                          "reason": "A summoned pet is unmapped — its damage is "
                                    "counting as an ally's, not yours"})
        if book is None:
            hints.append({"command": "/outputfile spellbook",
                          "reason": "No spellbook export found; the advisor cannot see owned spells"})
        else:
            stale = None
            try:
                exported = datetime.fromisoformat(book["updated"])
                for r in reversed(self.ledger):
                    if r["type"] == "level":
                        if datetime.fromisoformat(r["ts"]) > exported:
                            stale = "you have leveled since the last export"
                        break
            except (KeyError, ValueError, TypeError):
                pass
            if not stale and book.get("age_hours", 0) > 24:
                stale = f"the export is {round(book['age_hours'])}h old"
            if stale:
                hints.append({"command": "/outputfile spellbook",
                              "reason": f"Spellbook may be outdated — {stale}"})
        if self._last_aa_seen is None:
            hints.append({"command": "/alternateadv list",
                          "reason": "AA ranks unsynced; the advisor cannot see owned AAs"})
        else:
            for r in reversed(self.ledger):
                if r["type"] == "aa":
                    try:
                        if datetime.fromisoformat(r["ts"]) > self._last_aa_seen:
                            hints.append({
                                "command": "/alternateadv list",
                                "reason": "AA points earned since the last sync — re-list after spending them"})
                    except (KeyError, ValueError, TypeError):
                        pass
                    break
        return hints

    def snapshot(self) -> dict:
        book = None
        if self.spellbook_loader:
            try:
                book = self.spellbook_loader(self.name, self.server)
            except Exception:
                book = None
        return {
            "name": self.name,
            "server": self.server,
            "level": self.level,
            "class_str": self.class_str,
            "race": self.race,
            "playstyle": self.playstyle,
            "aa_available": self.aa_available,
            "spell_slots": self.spell_slots,
            "loadout_hint": self.loadout_hint,
            "owned_aas": {
                "distinct": len(self.owned_aas),
                "ranks": sum(v["ranks"] for v in self.owned_aas.values()),
                "synced": self._last_aa_seen.isoformat() if self._last_aa_seen else None,
            },
            "spellbook": {
                "file": book["file"], "updated": book["updated"],
                "age_hours": book["age_hours"],
                "count": len(book["castable"]),
            } if book else None,
            "sync_hints": self._sync_hints(book),
            "last_death": self.last_death,
            "mob_stats": sorted(
                ({"name": k, **v} for k, v in self.mob_stats.items()),
                key=lambda s: s["kills"], reverse=True)[:10],
            "zone": self.zone,
            "in_combat": self.in_combat(),
            "dps": self.dps(),
            "session_max_dps": round(self.session_max_dps, 1),
            "last_target": self.last_target,
            "position": self.position,
            "encounter": self.encounter_snapshot(),
            "encounters": self.encounters_snapshot(),
            "ability_summary": self.ability_summary(),
            "session": {
                "damage_dealt": self.damage_dealt,
                "damage_taken": self.damage_taken,
                "healing_received": self.healing_received,
                "healing_done": self.healing_done,
                "kills": self.kills,
                "deaths": self.deaths,
                "xp_ticks": self.xp_ticks,
                "xp_percent": round(self.xp_percent, 3),
                "aa_points": self.aa_points,
                "skill_ups": self.skill_ups,
                "hit_rate": round(
                    100 * self.swings_hit / max(self.swings_hit + self.swings_missed, 1), 1),
                "loots": list(self.loots),
            },
            "updated": datetime.now().isoformat(),
        }
