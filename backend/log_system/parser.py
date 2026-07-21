"""EQL log line parser.

EQ log lines look like:
    [Sat Jul 05 11:30:00 2026] You have entered Rivervale.

All patterns live in this file so format drift after a game patch means
editing ONE table. Order in `parse_line` matters: pet lines are
chat-shaped and precede the CHAT GUARD; the guard precedes all combat
matching (players quoting combat text would pollute the parse); specific
formats (spell-damage "by <spell>") come before generic melee. Trailing
combat tags STACK ("... damage. (Riposte) (Critical)") and are stripped
before matching — the crit flag rides on the damage event.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.log_system import events as ev

TS_RE = re.compile(r"^\[(.+?)\] (.*)$")
TS_FMT = "%a %b %d %H:%M:%S %Y"

# Melee verbs (singular roots). "hits"/"slashes" are normalized before
# lookup. frenzy phrases its target with a preposition ("You frenzy on a
# gnoll ...") — the damage regexes absorb the " on". cleave/smite/reave
# are real EQL verbs (cleave is an activated skill); shoot is the only
# log-marked ranged verb.
MELEE_VERBS = {
    "slash", "hit", "crush", "pierce", "kick", "punch", "bash", "backstab",
    "bite", "claw", "maul", "gore", "sting", "strike", "slam", "smash",
    "rend", "frenzy", "cleave", "smite", "reave", "shoot",
}

# PC names are one capitalized token; EQL allows backticks/apostrophes
# (Asaka L`Rei). NPCs carry articles/spaces so they fall through.
_PC = r"[A-Z][\w`']*"

# Stacked trailing combat annotations, peeled right-to-left — the loop
# only runs on lines containing " damage", keeping loot/chat parens intact.
RE_TAG = re.compile(r"^(.+)\s\(([A-Za-z][A-Za-z ]*)\)$")
CRIT_TAGS = ("Crippling Blow",)  # plus anything containing "Critical"

# Chat guard: speech lines never carry combat data, but players QUOTE it.
# Pet tells / "My leader is" ARE speech — matched before this.
RE_CHAT = re.compile(
    r"\b(?:say|says|tell|tells|told|shout|shouts|auction|auctions)\b"
    r"[^,]{0,60}, '")

RE_ZONE = re.compile(r"^You have entered (.+?)\.$")
RE_OUT_SPELL = re.compile(r"^You hit (.+?) for (\d+) points? of ([-\w\s]+?) damage by (.+?)[.!]")
RE_IN_SPELL = re.compile(r"^(.+?) hit you for (\d+) points? of ([-\w\s]+?) damage by (.+?)[.!]")
# plain non-melee nuke (no "by <spell>" tail)
RE_OUT_NM = re.compile(r"^You hit (.+?) for (\d+) points? of non-melee damage[.!]")
# incoming burst / damage shield on us: "YOU are burned by orc
# centurion's flames for 6 points of non-melee damage!"
RE_IN_NM = re.compile(
    r"^YOU are (\w+) by (?:(.+?)['`]s )?([\w\s]+?) for (\d+) points? of "
    r"non-melee damage[.!]")
# our damage shield: "Orc centurion is burned by YOUR flames for 5 ..."
RE_DS_OUT = re.compile(
    r"^(.+?) is (\w+) by YOUR (.+?) for (\d+) points? of non-melee damage")
RE_DS_OTHER = re.compile(
    rf"^(.+?) is (\w+) by ({_PC})['`]s (.+?) for (\d+) points? of non-melee damage")
RE_OUT_MELEE = re.compile(r"^You (\w+)(?: on)? (.+?) for (\d+) points? of damage[.!]")
RE_IN_MELEE = re.compile(r"^(.+?) (\w+)(?: on)? YOU for (\d+) points? of damage[.!]")
RE_NON_MELEE = re.compile(r"^(.+?) was hit by non-melee for (\d+) points? of damage[.!]")
RE_CAST = re.compile(r"^You begin (?:casting|singing) (.+?)\.")
RE_INTERRUPT = re.compile(r"^Your (?:(.+?) )?spell is interrupted\.")
RE_INTERRUPT2 = re.compile(r"^Your (?:casting|melody) has been interrupted!")
RE_FIZZLE = re.compile(r"^Your (?:(.+?) )?spell fizzles!")
RE_FIZZLE_BARD = re.compile(r"^You miss a note, bringing your song to a close!")
RE_RESIST_OUT = re.compile(r"^(.+?) resisted your (.+?)!$")
RE_RESIST_OUT2 = re.compile(r"^Your target resisted the (.+?) spell\.$")
RE_RESIST_IN = re.compile(r"^You resist (.+?)['`]s (.+?)!$")
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
RE_AA = re.compile(r"^You have gained an ability point!"
                   r"(?:\s+You now have (\d+) ability points?\.)?")
RE_SKILL = re.compile(r"^You have become better at (.+?)! \((\d+)\)")
# kept-in-inventory loot; the corpse name gives exact per-mob attribution
RE_LOOT = re.compile(r"^--You have looted (?:(\d+) |an? |the )?(.+?)(?: from (.+))?\.--")
# EQL auto-processed loot: sold / upgrade-merged / banked to a depot
RE_LOOT_UPGRADE = re.compile(
    r"^You looted (?:(\d+) |an? |the )?(.+?) from (.+?)"
    r"(?: and sold it for (.+?))?(?: to create (?:an? |the )?(.+?))?"
    r"(?: and stored it in your ([\w`' ]+))?\.?$")
RE_DESTROYED = re.compile(r"^You successfully destroyed (?:(\d+) )?(.+?)\.$")
RE_MERGE = re.compile(
    r"^You have successfully merged two items together to create a new "
    r"item:? (.+?)\.?$")
# EQL DoT ticks: "A dread bone has taken 32 damage from your Stinging Swarm."
RE_DOT = re.compile(r"^(.+?) has taken (\d+) damage from your (.+?)\.")
# incoming DoT tick: "You have taken 1 damage from Rabies by Gynok Moltor."
RE_DOT_IN = re.compile(r"^You have taken (\d+) damage from (.+?)(?: by (.+?))?[.!]$")
# casterless proc/poison tick: "An orc has taken 6 damage by Weak Poison."
RE_DOT_BY = re.compile(r"^(.+?) has taken (\d+) damage by (.+?)\.")
RE_MISS_OUT = re.compile(
    r"^You try to (\w+) (.+?), but (?:miss|.+? (?:dodges|parries|blocks|ripostes))!")
RE_MISS_IN = re.compile(
    r"^(.+?) tries to (\w+) YOU, but (?:misses|YOU (dodge|parry|block|riposte)s?)!")
RE_COIN = re.compile(r"^You receive (.+?) from the corpse")
RE_COIN_SPLIT = re.compile(r"^You receive (.+?) as your split")
RE_VENDOR_SALE = re.compile(r"^You receive (.+?) from (\S+) for the (.+?)\(s\)\.")
RE_COIN_ITEM = re.compile(r"^You received (.+?) from that item\.")
RE_FACTION = re.compile(
    r"^Your faction standing with (.+?) has been adjusted by (-?\d+)\.")
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
    rf"^({_PC}) healed (.+?)( over time)? for (\d+)(?: \(\d+\))? hit points by (.+?)\.")
# [13 Monk] Gentso (Iksar)   /   [65 Transcendent (Monk)] Gentso (Iksar) <Guild>
RE_WHO = re.compile(r"^\[(\d+) (.+?)\] (\w+) \((.+?)\)")
# "/pet leader": Gobaner says, 'My leader is Gentso.' — charm pets have
# multi-word mob names ("An abhorrent says, ...")
RE_PET_LEADER = re.compile(r"^(.+?) says,? '\s*My leader is (\w+)")
# the pet tells ONLY its master — zero-config pet mapping, fires on every
# /pet attack: "Jibekn told you, 'Attacking orc centurion Master.'"
RE_PET_ATTACK = re.compile(r"^(.+?) (?:tells|told) you, 'Attacking .+ Master\.'$")
# /alternateadv list output (one Ability line per owned rank)
RE_AA_LIST = re.compile(r"^Ability #(\d+): (.+)$")
RE_AA_COST = re.compile(r"^Cost per Level: (\d+)$")
RE_AA_DESC = re.compile(r"^Description: (.+)$")

# Other players' damage (group DPS). PC names are one capitalized word;
# NPCs carry articles/spaces so they fall through these attacker groups.
# "(?: pet)?": pets swing under "<Owner> pet" (e.g. "Officer Grush pet") —
# the tracker folds the character's own pet into player-side damage.
RE_OTHER_MELEE = re.compile(
    rf"^({_PC}(?: pet)?) (\w+)(?: on)? (.+?) for (\d+) points? of damage[.!]")
RE_OTHER_DOT = re.compile(
    rf"^(.+?) has taken (\d+) damage from (.+?) by ({_PC}(?: pet)?)\.")
RE_OTHER_SPELL = re.compile(
    rf"^({_PC}(?: pet)?) hit (.+?) for (\d+) points? of ([-\w\s]+?) damage by (.+?)[.!]")
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

    # strip stacked combat tags right-to-left; the raw ledger line keeps them
    body, tags = msg, []
    if " damage" in msg:
        while (t := RE_TAG.match(body)):
            body = t.group(1).rstrip()
            tags.append(t.group(2))
    crit = any("Critical" in t or t in CRIT_TAGS for t in tags)

    if z := RE_ZONE.match(body):
        zone = z.group(1)
        # Skip "You have entered an area where levitation..." style notices
        if not zone.lower().startswith("an area"):
            return ev.ZoneChange(zone=zone, **base)
        return None

    # pet lines are chat-shaped: match them BEFORE the chat guard
    if pa := RE_PET_ATTACK.match(body):
        return ev.PetAttack(pet=pa.group(1), **base)
    if pl := RE_PET_LEADER.match(body):
        return ev.PetLeader(pet=pl.group(1), owner=pl.group(2), **base)
    if RE_CHAT.search(body):
        return None  # speech — players quoting combat text stay out

    if s := RE_OUT_SPELL.match(body):
        return ev.SpellDamageOut(
            target=s.group(1), damage=int(s.group(2)),
            damage_kind=s.group(3).strip(), spell=s.group(4), crit=crit, **base)

    if s := RE_IN_SPELL.match(body):
        return ev.SpellDamageIn(
            attacker=s.group(1), damage=int(s.group(2)),
            damage_kind=s.group(3).strip(), spell=s.group(4), crit=crit, **base)

    if s := RE_OUT_NM.match(body):
        return ev.SpellDamageOut(
            target=s.group(1), damage=int(s.group(2)),
            damage_kind="non-melee", spell="non-melee", crit=crit, **base)

    if d := RE_DS_OUT.match(body):
        return ev.DamageShieldOut(target=d.group(1), kind=d.group(3),
                                  damage=int(d.group(4)), **base)
    if d := RE_DS_OTHER.match(body):
        if d.group(3) not in NOT_PLAYERS:
            return ev.OtherDamageOut(
                attacker=d.group(3), target=d.group(1),
                damage=int(d.group(5)), source=f"{d.group(4)} (DS)", **base)
        return None

    if s := RE_IN_NM.match(body):
        return ev.SpellDamageIn(
            attacker=s.group(2) or s.group(3), damage=int(s.group(4)),
            damage_kind="non-melee", spell=s.group(3), crit=crit, **base)

    if c := RE_CAST.match(body):
        return ev.CastBegin(spell=c.group(1), **base)
    if i := RE_INTERRUPT.match(body):
        return ev.CastInterrupted(spell=i.group(1), **base)
    if RE_INTERRUPT2.match(body):
        return ev.CastInterrupted(**base)
    if fz := RE_FIZZLE.match(body):
        return ev.CastFizzle(spell=fz.group(1), **base)
    if RE_FIZZLE_BARD.match(body):
        return ev.CastFizzle(**base)

    if r := RE_RESIST_IN.match(body):
        return ev.Resist(direction="in", source=r.group(1), spell=r.group(2), **base)
    if r := RE_RESIST_OUT2.match(body):
        return ev.Resist(direction="out", spell=r.group(1), **base)
    if r := RE_RESIST_OUT.match(body):
        return ev.Resist(direction="out", target=r.group(1), spell=r.group(2), **base)

    if RE_PET_INV_HEADER.match(body):
        return ev.PetInvHeader(**base)
    if pg := RE_PET_GEAR.match(body):
        return ev.PetGearLine(slot=pg.group(1), item=pg.group(2).strip(), **base)
    if k := RE_KILL.match(body):
        return ev.Kill(target=k.group(1), **base)
    if d := RE_MY_DEATH.match(body):
        return ev.MyDeath(killer=d.group(1), **base)

    if x := RE_EXP.match(body):
        pct = float(x.group(2)) if x.group(2) else None
        return ev.ExpGain(party=bool(x.group(1)), percent=pct, **base)
    if lv := RE_LEVEL.match(body):
        return ev.LevelUp(level=int(lv.group(1)), **base)
    if a := RE_AA.match(body):
        return ev.AAPoint(total=int(a.group(1)) if a.group(1) else None, **base)
    if sk := RE_SKILL.match(body):
        return ev.SkillUp(skill=sk.group(1), value=int(sk.group(2)), **base)
    if lo := RE_LOOT.match(body):
        return ev.Loot(item=lo.group(2), count=int(lo.group(1) or 1),
                       source=lo.group(3), **base)
    if lu := RE_LOOT_UPGRADE.match(body):
        return ev.Loot(item=lu.group(2), count=int(lu.group(1) or 1),
                       source=lu.group(3),
                       sold=bool(lu.group(4)), sold_for=lu.group(4),
                       upgraded_to=lu.group(5), stored=lu.group(6), **base)
    if ds := RE_DESTROYED.match(body):
        return ev.Destroyed(item=ds.group(2), count=int(ds.group(1) or 1), **base)
    if mg := RE_MERGE.match(body):
        return ev.ItemMerge(item=mg.group(1), **base)
    if dt := RE_DOT.match(body):
        return ev.DotDamage(target=dt.group(1), damage=int(dt.group(2)),
                            spell=dt.group(3), crit=crit, **base)
    if di := RE_DOT_IN.match(body):
        return ev.SpellDamageIn(
            attacker=di.group(3) or di.group(2), damage=int(di.group(1)),
            damage_kind="dot", spell=di.group(2), crit=crit, **base)
    if mo := RE_MISS_OUT.match(body):
        tgt = mo.group(2)
        if tgt.startswith("on "):
            tgt = tgt[3:]  # "You try to frenzy on a gnoll, but miss!"
        return ev.MissOut(verb=mo.group(1), target=tgt, **base)
    if mi := RE_MISS_IN.match(body):
        return ev.MissIn(attacker=mi.group(1), verb=mi.group(2),
                         defense=mi.group(3) or "miss", **base)
    if co := RE_VENDOR_SALE.match(body):
        return ev.Coin(amount=co.group(1), vendor=co.group(2),
                       item=co.group(3), **base)
    if co := RE_COIN.match(body):
        return ev.Coin(amount=co.group(1), **base)
    if co := RE_COIN_SPLIT.match(body):
        return ev.Coin(amount=co.group(1), split=True, **base)
    if co := RE_COIN_ITEM.match(body):
        return ev.Coin(amount=co.group(1), from_item=True, **base)
    if fa := RE_FACTION.match(body):
        return ev.Faction(faction=fa.group(1), delta=int(fa.group(2)), **base)
    if lc := RE_LOC.match(body):
        return ev.LocUpdate(y=float(lc.group(1)), x=float(lc.group(2)),
                            z=float(lc.group(3)), **base)
    if bf := RE_BUFF_FADE.match(body):
        return ev.BuffFade(spell=bf.group(1), **base)
    if h := RE_HEAL.match(body):
        return ev.HealReceived(amount=int(h.group(1)), **base)
    if ho := RE_HEAL_OUT.match(body):
        return ev.HealOut(target=ho.group(1), over_time=bool(ho.group(2)),
                          amount=int(ho.group(3)), spell=ho.group(4), **base)
    if oh := RE_OTHER_HEAL.match(body):
        return ev.OtherHeal(healer=oh.group(1), target=oh.group(2),
                            over_time=bool(oh.group(3)), amount=int(oh.group(4)),
                            spell=oh.group(5), **base)

    if om := RE_OUT_MELEE.match(body):
        verb = _verb_root(om.group(1))
        if verb:
            return ev.MeleeOut(verb=verb, target=om.group(2),
                               damage=int(om.group(3)), crit=crit, **base)

    if im := RE_IN_MELEE.match(body):
        verb = _verb_root(im.group(2))
        if verb:
            return ev.MeleeIn(attacker=im.group(1), verb=verb,
                              damage=int(im.group(3)), crit=crit, **base)

    if nm := RE_NON_MELEE.match(body):
        return ev.NonMeleeDamage(target=nm.group(1), damage=int(nm.group(2)), **base)

    if od := RE_OTHER_DEATH.match(body):
        return ev.OtherDeath(victim=od.group(1), killer=od.group(2), **base)

    if al := RE_AA_LIST.match(body):
        return ev.AAListEntry(aa_id=int(al.group(1)), name=al.group(2).strip(), **base)
    if ac := RE_AA_COST.match(body):
        return ev.AAListMeta(cost=int(ac.group(1)), **base)
    if ad := RE_AA_DESC.match(body):
        return ev.AAListMeta(desc=ad.group(1), **base)

    if o := RE_OTHER_SPELL.match(body):
        if o.group(1) not in NOT_PLAYERS:
            return ev.OtherDamageOut(
                attacker=o.group(1), target=o.group(2),
                damage=int(o.group(3)), source=o.group(5), crit=crit, **base)

    if o := RE_OTHER_MELEE.match(body):
        root = _verb_root(o.group(2))
        if root and o.group(1) not in NOT_PLAYERS and o.group(3) != "YOU":
            return ev.OtherDamageOut(
                attacker=o.group(1), target=o.group(3),
                damage=int(o.group(4)), source=root, crit=crit, **base)

    if o := RE_OTHER_DOT.match(body):
        return ev.OtherDamageOut(
            attacker=o.group(4), target=o.group(1),
            damage=int(o.group(2)), source=o.group(3), crit=crit, **base)

    # casterless proc/poison tick — LAST of the "has taken" family so the
    # attributed forms above always win
    if db_ := RE_DOT_BY.match(body):
        return ev.DotDamage(target=db_.group(1), damage=int(db_.group(2)),
                            spell=db_.group(3), proc=True, crit=crit, **base)

    if w := RE_WHO.match(body):
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