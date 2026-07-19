"""EQL log line parser.

EQ log lines look like:
    [Sat Jul 05 11:30:00 2026] You have entered Rivervale.

All patterns live in this file so format drift after a game patch means
editing ONE table. Order in `parse_line` matters: specific formats
(spell-damage "by <spell>") are tried before generic melee.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.log_system import events as ev

TS_RE = re.compile(r"^\[(.+?)\] (.*)$")
TS_FMT = "%a %b %d %H:%M:%S %Y"

# Melee verbs (singular roots). "hits"/"slashes" are normalized before lookup.
MELEE_VERBS = {
    "slash", "hit", "crush", "pierce", "kick", "punch", "bash", "backstab",
    "bite", "claw", "maul", "gore", "sting", "strike", "slam", "smash", "rend",
}

RE_ZONE = re.compile(r"^You have entered (.+?)\.$")
RE_OUT_SPELL = re.compile(r"^You hit (.+?) for (\d+) points? of ([\w\s]+?) damage by (.+?)[.!]")
RE_IN_SPELL = re.compile(r"^(.+?) hit you for (\d+) points? of ([\w\s]+?) damage by (.+?)[.!]")
RE_OUT_MELEE = re.compile(r"^You (\w+) (.+?) for (\d+) points? of damage[.!]")
RE_IN_MELEE = re.compile(r"^(.+?) (\w+) YOU for (\d+) points? of damage[.!]")
RE_NON_MELEE = re.compile(r"^(.+?) was hit by non-melee for (\d+) points? of damage[.!]")
RE_CAST = re.compile(r"^You begin casting (.+?)\.")
RE_INTERRUPT = re.compile(r"^Your spell is interrupted\.")
RE_FIZZLE = re.compile(r"^Your spell fizzles!")
RE_KILL = re.compile(r"^You have slain (.+?)!")
RE_PET_INV_HEADER = re.compile(
    r"^Your pet (?:has the following items equipped:|does not have any "
    r"items equipped)")
# pet equip slots (fixed set — avoids matching stray "Word: value" lines)
_PET_SLOTS = ("Charm|Ear|Head|Face|Neck|Shoulders|Arms|Back|Wrist|Range|Hands|"
              "Primary|Secondary|Fingers|Chest|Legs|Feet|Waist|Ammo")
RE_PET_GEAR = re.compile(rf"^({_PET_SLOTS}): (.+)$")
RE_MY_DEATH = re.compile(r"^You have been slain by (.+?)!")
RE_OTHER_DEATH = re.compile(r"^(.+?) has been slain by (.+?)!")
RE_EXP = re.compile(r"^You gain (party )?experience!*(?:\s*\((\d+(?:\.\d+)?)%\))?")
RE_LEVEL = re.compile(r"^You have gained a level! Welcome to level (\d+)!")
RE_AA = re.compile(r"^You have gained an ability point!")
RE_SKILL = re.compile(r"^You have become better at (.+?)! \((\d+)\)")
RE_LOOT = re.compile(r"^--You have looted an? (.+?)\.--")
# EQL upgrade-loot: "You looted an X +2 from the Y's corpse to create an X +3"
RE_LOOT_UPGRADE = re.compile(
    r"^You looted an? (.+?) from (.+?)"
    r"(?: and sold it for (.+?))?(?: to create an? (.+?))?\.?$")
# EQL DoT ticks: "A dread bone has taken 32 damage from your Stinging Swarm."
RE_DOT = re.compile(r"^(.+?) has taken (\d+) damage from your (.+?)\.")
RE_MISS_OUT = re.compile(
    r"^You try to (\w+) (.+?), but (?:miss|.+? (?:dodges|parries|blocks|ripostes))!")
RE_MISS_IN = re.compile(
    r"^(.+?) tries to (\w+) YOU, but (?:misses|YOU (dodge|parry|block|riposte)s?)!")
RE_COIN = re.compile(r"^You receive (.+?) from the corpse")
# /loc output order is Y, X, Z
RE_LOC = re.compile(r"^Your Location is (-?[\d.]+), (-?[\d.]+), (-?[\d.]+)")
RE_BUFF_FADE = re.compile(r"^Your (.+?) spell has worn off")
RE_HEAL = re.compile(r"^You have been healed for (\d+) (?:hit )?points")
# "You healed Zizoo over time for 92 hit points by Blooming Heal."
RE_HEAL_OUT = re.compile(
    r"^You healed (.+?)( over time)? for (\d+)(?: \(\d+\))? hit points by (.+?)\.")
# "Bosh healed itself for 159 (210) hit points by Spirit Tap." — group
# members, pets, and mobs: the healer IS named; parens = pre-cap value
RE_OTHER_HEAL = re.compile(
    r"^([A-Z][\w`]*) healed (.+?)( over time)? for (\d+)(?: \(\d+\))? hit points by (.+?)\.")
# [13 Monk] Gentso (Iksar)   /   [65 Transcendent (Monk)] Gentso (Iksar) <Guild>
RE_WHO = re.compile(r"^\[(\d+) (.+?)\] (\w+) \((.+?)\)")
# "/pet leader": Gobaner says, 'My leader is Gentso.' — maps pets to owners
RE_PET_LEADER = re.compile(r"^([A-Z]\w+) says,? '\s*My leader is (\w+)")
# /alternateadv list output (one Ability line per owned rank)
RE_AA_LIST = re.compile(r"^Ability #(\d+): (.+)$")
RE_AA_COST = re.compile(r"^Cost per Level: (\d+)$")
RE_AA_DESC = re.compile(r"^Description: (.+)$")

# Other players' damage (group DPS). PC names are one capitalized word;
# NPCs carry articles/spaces so they fall through these attacker groups.
# "(?: pet)?": pets swing under "<Owner> pet" (e.g. "Officer Grush pet") —
# the tracker folds the character's own pet into player-side damage.
RE_OTHER_MELEE = re.compile(r"^([A-Z]\w+(?: pet)?) (\w+) (.+?) for (\d+) points? of damage[.!]")
RE_OTHER_DOT = re.compile(r"^(.+?) has taken (\d+) damage from (.+?) by ([A-Z]\w+(?: pet)?)\.")
RE_OTHER_SPELL = re.compile(
    r"^([A-Z]\w+(?: pet)?) hit (.+?) for (\d+) points? of ([\w\s]+?) damage by (.+?)[.!]")
NOT_PLAYERS = {"You", "Your", "It", "The", "That", "This", "Something", "Someone"}

FILENAME_RE = re.compile(r"eqlog_(?P<name>[^_]+)_(?P<server>.+)\.txt$", re.IGNORECASE)

# /who shows the trio as abbreviations: "[21 PAL/DRU/MNK] Gentso (Iksar)"
CLASS_ABBREV = {
    "WAR": "Warrior", "CLR": "Cleric", "PAL": "Paladin", "RNG": "Ranger",
    "SHD": "Shadow Knight", "DRU": "Druid", "MNK": "Monk", "BRD": "Bard",
    "ROG": "Rogue", "SHM": "Shaman", "NEC": "Necromancer", "WIZ": "Wizard",
    "MAG": "Magician", "ENC": "Enchanter", "BST": "Beastlord", "BER": "Berserker",
}


def expand_classes(class_str: str) -> str:
    """'PAL/DRU/MNK' -> 'Paladin/Druid/Monk'; full names pass through."""
    return "/".join(CLASS_ABBREV.get(part.strip().upper(), part.strip())
                    for part in class_str.split("/"))


def extract_character_from_filename(path: Path) -> tuple[Optional[str], Optional[str]]:
    """eqlog_Gentso_rivervale.txt -> ("Gentso", "rivervale")"""
    m = FILENAME_RE.search(path.name)
    if not m:
        return None, None
    return m.group("name"), m.group("server")


def _verb_root(verb: str) -> Optional[str]:
    v = verb.lower()
    if v in MELEE_VERBS:
        return v
    if v.endswith("es") and v[:-2] in MELEE_VERBS:
        return v[:-2]
    if v.endswith("s") and v[:-1] in MELEE_VERBS:
        return v[:-1]
    return None


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(" ".join(ts_str.split()), TS_FMT)
    except ValueError:
        return None


def parse_line(line: str, character_name: Optional[str] = None) -> Optional[ev.LogEvent]:
    """Parse a raw log line into an event, or None if unrecognized."""
    line = line.rstrip("\r\n")
    m = TS_RE.match(line)
    if not m:
        return None
    ts = _parse_ts(m.group(1))
    if ts is None:
        return None
    msg = m.group(2)
    base = {"ts": ts, "raw": msg}

    if z := RE_ZONE.match(msg):
        zone = z.group(1)
        # Skip "You have entered an area where levitation..." style notices
        if not zone.lower().startswith("an area"):
            return ev.ZoneChange(zone=zone, **base)
        return None

    if s := RE_OUT_SPELL.match(msg):
        return ev.SpellDamageOut(
            target=s.group(1), damage=int(s.group(2)),
            damage_kind=s.group(3).strip(), spell=s.group(4), **base)

    if s := RE_IN_SPELL.match(msg):
        return ev.SpellDamageIn(
            attacker=s.group(1), damage=int(s.group(2)),
            damage_kind=s.group(3).strip(), spell=s.group(4), **base)

    if c := RE_CAST.match(msg):
        return ev.CastBegin(spell=c.group(1), **base)
    if RE_INTERRUPT.match(msg):
        return ev.CastInterrupted(**base)
    if RE_FIZZLE.match(msg):
        return ev.CastFizzle(**base)

    if RE_PET_INV_HEADER.match(msg):
        return ev.PetInvHeader(**base)
    if pg := RE_PET_GEAR.match(msg):
        return ev.PetGearLine(slot=pg.group(1), item=pg.group(2).strip(), **base)
    if k := RE_KILL.match(msg):
        return ev.Kill(target=k.group(1), **base)
    if d := RE_MY_DEATH.match(msg):
        return ev.MyDeath(killer=d.group(1), **base)

    if x := RE_EXP.match(msg):
        pct = float(x.group(2)) if x.group(2) else None
        return ev.ExpGain(party=bool(x.group(1)), percent=pct, **base)
    if lv := RE_LEVEL.match(msg):
        return ev.LevelUp(level=int(lv.group(1)), **base)
    if RE_AA.match(msg):
        return ev.AAPoint(**base)
    if sk := RE_SKILL.match(msg):
        return ev.SkillUp(skill=sk.group(1), value=int(sk.group(2)), **base)
    if lo := RE_LOOT.match(msg):
        return ev.Loot(item=lo.group(1), **base)
    if lu := RE_LOOT_UPGRADE.match(msg):
        return ev.Loot(item=lu.group(1), source=lu.group(2),
                       sold=bool(lu.group(3)), sold_for=lu.group(3),
                       upgraded_to=lu.group(4), **base)
    if dt := RE_DOT.match(msg):
        return ev.DotDamage(target=dt.group(1), damage=int(dt.group(2)),
                            spell=dt.group(3), **base)
    if mo := RE_MISS_OUT.match(msg):
        return ev.MissOut(verb=mo.group(1), target=mo.group(2), **base)
    if mi := RE_MISS_IN.match(msg):
        return ev.MissIn(attacker=mi.group(1), verb=mi.group(2),
                         defense=mi.group(3) or "miss", **base)
    if co := RE_COIN.match(msg):
        return ev.Coin(amount=co.group(1), **base)
    if lc := RE_LOC.match(msg):
        return ev.LocUpdate(y=float(lc.group(1)), x=float(lc.group(2)),
                            z=float(lc.group(3)), **base)
    if bf := RE_BUFF_FADE.match(msg):
        return ev.BuffFade(spell=bf.group(1), **base)
    if h := RE_HEAL.match(msg):
        return ev.HealReceived(amount=int(h.group(1)), **base)
    if ho := RE_HEAL_OUT.match(msg):
        return ev.HealOut(target=ho.group(1), over_time=bool(ho.group(2)),
                          amount=int(ho.group(3)), spell=ho.group(4), **base)
    if oh := RE_OTHER_HEAL.match(msg):
        return ev.OtherHeal(healer=oh.group(1), target=oh.group(2),
                            over_time=bool(oh.group(3)), amount=int(oh.group(4)),
                            spell=oh.group(5), **base)

    if om := RE_OUT_MELEE.match(msg):
        verb = _verb_root(om.group(1))
        if verb:
            return ev.MeleeOut(verb=verb, target=om.group(2), damage=int(om.group(3)), **base)

    if im := RE_IN_MELEE.match(msg):
        verb = _verb_root(im.group(2))
        if verb:
            return ev.MeleeIn(attacker=im.group(1), verb=verb, damage=int(im.group(3)), **base)

    if nm := RE_NON_MELEE.match(msg):
        return ev.NonMeleeDamage(target=nm.group(1), damage=int(nm.group(2)), **base)

    if od := RE_OTHER_DEATH.match(msg):
        return ev.OtherDeath(victim=od.group(1), killer=od.group(2), **base)

    if pl := RE_PET_LEADER.match(msg):
        return ev.PetLeader(pet=pl.group(1), owner=pl.group(2), **base)
    if al := RE_AA_LIST.match(msg):
        return ev.AAListEntry(aa_id=int(al.group(1)), name=al.group(2).strip(), **base)
    if ac := RE_AA_COST.match(msg):
        return ev.AAListMeta(cost=int(ac.group(1)), **base)
    if ad := RE_AA_DESC.match(msg):
        return ev.AAListMeta(desc=ad.group(1), **base)

    if o := RE_OTHER_SPELL.match(msg):
        if o.group(1) not in NOT_PLAYERS:
            return ev.OtherDamageOut(
                attacker=o.group(1), target=o.group(2),
                damage=int(o.group(3)), source=o.group(5), **base)

    if o := RE_OTHER_MELEE.match(msg):
        root = _verb_root(o.group(2))
        if root and o.group(1) not in NOT_PLAYERS and o.group(3) != "YOU":
            return ev.OtherDamageOut(
                attacker=o.group(1), target=o.group(3),
                damage=int(o.group(4)), source=root, **base)

    if o := RE_OTHER_DOT.match(msg):
        return ev.OtherDamageOut(
            attacker=o.group(4), target=o.group(1),
            damage=int(o.group(2)), source=o.group(3), **base)

    if w := RE_WHO.match(msg):
        class_str = w.group(2)
        # "Transcendent (Monk)" -> "Monk"
        inner = re.search(r"\(([^)]+)\)", class_str)
        if inner:
            class_str = inner.group(1)
        if character_name and w.group(3).lower() == character_name.lower():
            return ev.CharacterInfo(
                name=w.group(3), level=int(w.group(1)),
                class_str=expand_classes(class_str), race=w.group(4), **base)
        # other players feed the group roster (keep the game's abbreviations)
        return ev.OtherCharInfo(name=w.group(3), level=int(w.group(1)),
                                classes=class_str, **base)

    return None
