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
    """You <verb> <target> for N points of damage. [(Critical) ...]"""
    type: str = "melee_out"
    verb: str
    target: str
    damage: int
    crit: bool = False


class MeleeIn(LogEvent):
    """<attacker> <verbs> YOU for N points of damage."""
    type: str = "melee_in"
    attacker: str
    verb: str
    damage: int
    crit: bool = False


class SpellDamageOut(LogEvent):
    """You hit <target> for N points of <kind> damage by <spell>."""
    type: str = "spell_out"
    target: str
    damage: int
    damage_kind: str
    spell: str
    crit: bool = False


class SpellDamageIn(LogEvent):
    type: str = "spell_in"
    attacker: str
    damage: int
    damage_kind: str
    spell: str
    crit: bool = False


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
    spell: Optional[str] = None  # "Your Force Snap spell is interrupted."


class CastFizzle(LogEvent):
    type: str = "fizzle"
    spell: Optional[str] = None  # "Your Cascade of Hail spell fizzles!"


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
    """<target> has taken N damage from your <spell> — or the casterless
    proc form "<target> has taken N damage by <spell>" (proc=True), which
    is OURS unless the target is a player, YOU, or our own pet."""
    type: str = "dot_out"
    target: str
    damage: int
    spell: str
    crit: bool = False
    proc: bool = False


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
    crit: bool = False


class PetInvHeader(LogEvent):
    """'Your pet has the following items equipped:' — starts a pet-gear burst."""
    type: str = "pet_inv_header"


class PetGearLine(LogEvent):
    """'Arms: Barbed Armplates +3' inside a /pet inventory check burst."""
    type: str = "pet_gear"
    slot: str
    item: str


class OtherHeal(LogEvent):
    """<Healer> healed <target>[ over time] for N [(M)] hit points by <Spell>."""
    type: str = "other_heal"
    healer: str
    target: str
    amount: int
    spell: str
    over_time: bool = False
    crit: bool = False  # heal crits log since the 2026-07-07 patch


class MissIn(LogEvent):
    """<attacker> tries to <verb> YOU, but misses / YOU block|dodge|...!"""
    type: str = "miss_in"
    attacker: str
    verb: str
    defense: str = "miss"      # miss | dodge | parry | block | riposte


class Coin(LogEvent):
    """Corpse coin, group split, vendor sale, or loot-window item sale."""
    type: str = "coin"
    amount: str
    split: bool = False              # "... as your split."
    vendor: Optional[str] = None     # "from Lanadin for the X(s)."
    item: Optional[str] = None       # the item a vendor sale was for
    from_item: bool = False          # "You received ... from that item."


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
    """Optionally carries the log's own running total ("You now have N
    ability points.") — authoritative for the unspent-points counter."""
    type: str = "aa"
    total: Optional[int] = None


class SkillUp(LogEvent):
    type: str = "skill"
    skill: str
    value: int


class Loot(LogEvent):
    type: str = "loot"
    item: str
    count: int = 1                     # "You looted 2 Spider Silk ..."
    source: Optional[str] = None       # "the thaumaturgist's corpse"
    upgraded_to: Optional[str] = None  # EQL upgrade system: "... to create X +3"
    sold: bool = False                 # loot-and-auto-sell variant
    sold_for: Optional[str] = None     # "4 platinum, 2 gold, 1 silver"
    stored: Optional[str] = None       # "... and stored it in your <depot>"


class BuffFade(LogEvent):
    type: str = "buff_fade"
    spell: str


class HealReceived(LogEvent):
    type: str = "heal_in"
    amount: int
    crit: bool = False


class HealOut(LogEvent):
    """You healed <target> (over time) for N hit points by <spell>."""
    type: str = "heal_out"
    target: str
    amount: int
    spell: str
    over_time: bool = False
    crit: bool = False


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

class DamageShieldOut(LogEvent):
    """<target> is burned by YOUR <kind> for N points of non-melee damage.
    Aux damage: counts toward totals/DPS but never swings or crit rates."""
    type: str = "ds_out"
    target: str
    kind: str
    damage: int


class Resist(LogEvent):
    """Out: '<target> resisted your <spell>!'; in: 'You resist <src>'s
    <spell>!'."""
    type: str = "resist"
    direction: str                 # "out" | "in"
    spell: str
    target: Optional[str] = None   # out: who resisted
    source: Optional[str] = None   # in: whose spell we shrugged off


class Faction(LogEvent):
    """Adjusted by <delta>, or capped: '... could not possibly get any
    better/worse.'"""
    type: str = "faction"
    faction: str
    delta: int
    capped: Optional[str] = None  # "better" | "worse" when at cap


class Rune(LogEvent):
    """You gain a rune for N points of absorption."""
    type: str = "rune"
    amount: int


class SelfHurt(LogEvent):
    """You hurt yourself for N points. (cannibalize / DS self-ticks —
    damage taken, never damage dealt)"""
    type: str = "self_hurt"
    damage: int


class RandomRoll(LogEvent):
    """'**Random: 0 to 100**' announce or '<Who> rolls 87 (0-100)'."""
    type: str = "roll"
    who: Optional[str] = None
    value: Optional[int] = None
    lo: Optional[int] = None
    hi: Optional[int] = None


class ItemMerge(LogEvent):
    """EQL upgrade crafting: 'merged two items ... create a new item: X'."""
    type: str = "merge"
    item: str


class Destroyed(LogEvent):
    """Advanced-loot destroy; the 'from that item' coin line follows it."""
    type: str = "destroyed"
    item: str
    count: int = 1


class MechanicTimer(LogEvent):
    """A raid-mechanic line matched the vendored trigger set (boss shout
    = Death Touch incoming, breath emote = AE cooldown, ...)."""
    type: str = "mechanic"
    name: str
    seconds: int


class SessionStart(LogEvent):
    """'Welcome to EverQuest Legends!' — the login banner. The one true
    session boundary: one log file holds weeks of play."""
    type: str = "session_start"


class PetAttack(LogEvent):
    """'<pet> told you, "Attacking X Master."' — printed ONLY to the
    owner's log, so it maps the pet with zero user action."""
    type: str = "pet_attack"
    pet: str
