"""Event schemas for parsed EQL log lines.

Every parser match becomes one of these models. To add a new event type:
1. Add a subclass here with `type` set to a new string.
2. Add a regex + branch in parser.py that returns it.
3. (Optional) Handle it in state_tracker.py and/or persist it in main.py.
The WebSocket payload is `event.model_dump(mode="json")` — the frontend
switches on the `type` field.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class LogEvent(BaseModel):
    type: str = "generic"
    ts: datetime
    raw: str


class ZoneChange(LogEvent):
    type: str = "zone"
    zone: str


class MeleeOut(LogEvent):
    """You <verb> <target> for N points of damage."""
    type: str = "melee_out"
    verb: str
    target: str
    damage: int


class MeleeIn(LogEvent):
    """<attacker> <verbs> YOU for N points of damage."""
    type: str = "melee_in"
    attacker: str
    verb: str
    damage: int


class SpellDamageOut(LogEvent):
    """You hit <target> for N points of <kind> damage by <spell>."""
    type: str = "spell_out"
    target: str
    damage: int
    damage_kind: str
    spell: str


class SpellDamageIn(LogEvent):
    type: str = "spell_in"
    attacker: str
    damage: int
    damage_kind: str
    spell: str


class NonMeleeDamage(LogEvent):
    """<target> was hit by non-melee for N points of damage."""
    type: str = "non_melee"
    target: str
    damage: int


class CastBegin(LogEvent):
    type: str = "cast"
    spell: str


class CastInterrupted(LogEvent):
    type: str = "interrupt"


class CastFizzle(LogEvent):
    type: str = "fizzle"


class Kill(LogEvent):
    """You have slain X!"""
    type: str = "kill"
    target: str


class MyDeath(LogEvent):
    type: str = "death"
    killer: str


class OtherDeath(LogEvent):
    type: str = "other_death"
    victim: str
    killer: str


class ExpGain(LogEvent):
    type: str = "exp"
    party: bool = False
    percent: Optional[float] = None  # EQL logs the exact gain: "(1.107%)"


class DotDamage(LogEvent):
    """<target> has taken N damage from your <spell>."""
    type: str = "dot_out"
    target: str
    damage: int
    spell: str


class MissOut(LogEvent):
    """You try to <verb> <target>, but miss! (or target dodges/parries/...)"""
    type: str = "miss_out"
    target: str
    verb: str


class OtherCharInfo(LogEvent):
    """Another player's /who line — feeds the group roster (level + trio)."""
    type: str = "who_other"
    name: str
    level: int
    classes: str  # abbreviated, as the game prints it: "SHD/ROG/BER"


class PetLeader(LogEvent):
    """'/pet leader' response — definitive pet-to-owner mapping."""
    type: str = "pet_leader"
    pet: str
    owner: str


class AAListEntry(LogEvent):
    """'/alternateadv list' output row — the game prints one per OWNED RANK."""
    type: str = "aa_list"
    aa_id: int
    name: str


class AAListMeta(LogEvent):
    """Description / cost lines that follow an aa_list entry."""
    type: str = "aa_meta"
    desc: Optional[str] = None
    cost: Optional[int] = None


class OtherDamageOut(LogEvent):
    """Another player's (or pet's) hit on a mob — feeds group DPS. Never
    broadcast raw (busy zones would flood the WS); aggregated in encounters."""
    type: str = "other_out"
    attacker: str
    target: str
    damage: int
    source: str  # melee verb or spell name


class MissIn(LogEvent):
    """<attacker> tries to <verb> YOU, but misses!"""
    type: str = "miss_in"
    attacker: str
    verb: str


class Coin(LogEvent):
    """You receive 7 copper from the corpse."""
    type: str = "coin"
    amount: str


class LocUpdate(LogEvent):
    """Your Location is -1234.56, 567.89, 12.34  (printed when the player types /loc)"""
    type: str = "loc"
    x: float
    y: float
    z: float


class LevelUp(LogEvent):
    type: str = "level"
    level: int


class AAPoint(LogEvent):
    type: str = "aa"


class SkillUp(LogEvent):
    type: str = "skill"
    skill: str
    value: int


class Loot(LogEvent):
    type: str = "loot"
    item: str
    source: Optional[str] = None       # "the thaumaturgist's corpse"
    upgraded_to: Optional[str] = None  # EQL upgrade system: "... to create X +3"


class BuffFade(LogEvent):
    type: str = "buff_fade"
    spell: str


class HealReceived(LogEvent):
    type: str = "heal_in"
    amount: int


class HealOut(LogEvent):
    """You healed <target> (over time) for N hit points by <spell>."""
    type: str = "heal_out"
    target: str
    amount: int
    spell: str
    over_time: bool = False


class LocUpdate(LogEvent):
    """/loc output: 'Your Location is 384.16, -184.05, 3.75' (Y, X, Z)."""
    type: str = "loc"
    y: float
    x: float
    z: float


class CharacterInfo(LogEvent):
    """Parsed from a /who line matching our character:
    [13 Monk] Gentso (Iksar)  or  [65 Transcendent (Monk)] Gentso (Iksar)
    """
    type: str = "char_info"
    name: str
    level: int
    class_str: str
    race: Optional[str] = None
