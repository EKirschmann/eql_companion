import logging
from typing import Any, Dict, List
from backend.agent.state import SuggestionItem, ProfileData

logger = logging.getLogger(__name__)

# Mock spell data by class for MVP testing (when MCP is unavailable)
MOCK_SPELLS = {
    "Monk": ["Kick", "Flying Kick", "Sense of the Forest", "Tail Strike"],
    "Paladin": ["Holy Light", "Hammer Strike", "Protect", "Smite"],
    "Druid": ["Roots", "Heal", "Summon Companion", "Lifebloom"],
    "Warrior": ["Taunt", "Cleave", "Slam", "Rage"],
    "Bard": ["War Song", "Selo's Rhythm", "Healing Song", "Charm"],
    "Wizard": ["Frostbolt", "Magma Vein", "Root", "Teleport"],
    "Ranger": ["Stinging Swarm", "Arrows", "Camouflage", "Heal"],
    "Cleric": ["Holy Strike", "Greater Heal", "Cleanse", "Prayer"],
    "Rogue": ["Backstab", "Eviscerate", "Hide", "Poison Blade"],
}

MOCK_AAS = {
    "solo_dps": [
        {"name": "Damage Passive I", "tier": 1, "desc": "Increases damage output by 5%"},
        {"name": "Quick Strike", "tier": 2, "desc": "Active ability for burst damage"},
        {"name": "Evasion Stance", "tier": 3, "desc": "Improves survival when solo"},
    ],
    "group_dps": [
        {"name": "Coordinated Attack", "tier": 1, "desc": "Increases group synergy"},
        {"name": "Haste Aura", "tier": 2, "desc": "Passive buff to group attack speed"},
        {"name": "Rallying Cry", "tier": 3, "desc": "Active morale boost for group"},
    ],
    "tank": [
        {"name": "Defensive Stance", "tier": 1, "desc": "Reduces damage taken by 10%"},
        {"name": "Last Stand", "tier": 2, "desc": "Temporary damage reduction active"},
        {"name": "Taunt Mastery", "tier": 3, "desc": "Improves threat generation"},
    ],
    "healer": [
        {"name": "Mana Efficiency", "tier": 1, "desc": "Reduces spell mana cost by 8%"},
        {"name": "Heal Boost", "tier": 2, "desc": "Increases healing output by 12%"},
        {"name": "Cure Poison", "tier": 3, "desc": "Active ability to remove debuffs"},
    ],
    "support": [
        {"name": "Buff Duration", "tier": 1, "desc": "Buffs last 20% longer"},
        {"name": "Group Haste", "tier": 2, "desc": "Passive group attack speed buff"},
        {"name": "Debuff Mastery", "tier": 3, "desc": "Debuffs are more effective"},
    ],
    "pet_focused": [
        {"name": "Pet Damage", "tier": 1, "desc": "Increases pet damage by 15%"},
        {"name": "Pet Haste", "tier": 2, "desc": "Speeds up pet attack rate"},
        {"name": "Bond", "tier": 3, "desc": "Active ability to sync with pet"},
    ],
    "balanced": [
        {"name": "Versatility", "tier": 1, "desc": "Small boost to all damage types"},
        {"name": "Flexibility", "tier": 2, "desc": "Switch roles more effectively"},
        {"name": "Adaptation", "tier": 3, "desc": "Adapt to different combat scenarios"},
    ],
}

MOCK_ZONES = {
    "low": [
        {"name": "Crescent Reach", "difficulty": 1, "desc": "Starting zone, great for solo"},
        {"name": "Bixie Hive", "difficulty": 1, "desc": "Insect mobs, easy exp"},
    ],
    "mid": [
        {"name": "Hollowshade Moor", "difficulty": 2, "desc": "Undead mobs, moderate xp"},
        {"name": "Guk", "difficulty": 2, "desc": "Classic dungeon, good loot"},
    ],
    "high": [
        {"name": "Nagafen's Lair", "difficulty": 3, "desc": "Group content, excellent rewards"},
        {"name": "Ssraeshza Temple", "difficulty": 3, "desc": "High-level dungeon, epic loot"},
    ],
}


async def get_spell_suggestions(profile: ProfileData) -> List[SuggestionItem]:
    """
    Get spell suggestions for the player's class combo and level.

    Returns spell suggestions prioritized by playstyle fit and synergies.
    Uses mock data for MVP (MCP integration deferred).
    """
    suggestions: List[SuggestionItem] = []

    try:
        # Get spells for each class
        class_list = [profile["primary_class"], profile["secondary_class"]]
        if profile.get("tertiary_class"):
            class_list.append(profile["tertiary_class"])

        priority_map = {
            "solo_dps": ["damage", "control", "survival"],
            "group_dps": ["damage", "buffs", "debuffs"],
            "tank": ["survival", "aggro", "tanking"],
            "healer": ["healing", "survival", "buffs"],
            "support": ["buffs", "debuffs", "utility"],
            "pet_focused": ["pet", "buffs", "damage"],
            "balanced": ["damage", "survival", "utility"],
        }

        priorities = priority_map.get(profile["playstyle"], ["damage", "survival"])

        # Build suggestions from mock spells
        idx = 0
        for cls in class_list:
            spells = MOCK_SPELLS.get(cls, [])
            for spell in spells:
                if idx < 7:
                    suggestions.append(
                        {
                            "name": spell,
                            "category": "spell",
                            "priority": (idx % 3) + 1,
                            "reason": f"Core spell for {cls}, fits {profile['playstyle']} playstyle",
                            "synergies": [f"Synergizes with your {profile['primary_class']} class abilities"],
                            "source": f"EQL Wiki: {cls} Spells",
                        }
                    )
                    idx += 1

        return suggestions

    except Exception as e:
        logger.error(f"Error getting spell suggestions: {e}")
        return [
            {
                "name": "Sample Spell",
                "category": "spell",
                "priority": 2,
                "reason": "Good starter spell for your class combo",
                "synergies": ["Works with other damage spells"],
                "source": "EQL Wiki",
            }
        ]


async def get_aa_suggestions(profile: ProfileData) -> List[SuggestionItem]:
    """
    Get AA (Alternative Advancement) suggestions.

    Returns AAs prioritized by tier (must-have passives first, then actives).
    Uses mock data for MVP (MCP integration deferred).
    """
    suggestions: List[SuggestionItem] = []

    try:
        # Get AAs for playstyle
        playstyle = profile.get("playstyle", "balanced")
        mock_aas = MOCK_AAS.get(playstyle, MOCK_AAS["balanced"])

        for aa in mock_aas:
            suggestions.append(
                {
                    "name": aa["name"],
                    "category": "aa",
                    "priority": aa["tier"],
                    "reason": f"{aa['desc']}. Great for {playstyle}.",
                    "synergies": [f"Applies to {profile['primary_class']} tab", "Stacks with other passive boosts"],
                    "source": f"EQL Wiki: {aa['name']}",
                }
            )

        return suggestions

    except Exception as e:
        logger.error(f"Error getting AA suggestions: {e}")
        return [
            {
                "name": "Passive Boost I",
                "category": "aa",
                "priority": 1,
                "reason": "Foundational passive for your playstyle",
                "synergies": ["Stacks with class abilities"],
                "source": "EQL Wiki",
            }
        ]


async def get_leveling_zone_suggestions(profile: ProfileData) -> List[SuggestionItem]:
    """
    Get leveling zone suggestions for the player's current and next level range.

    Returns zones appropriate for their level, playstyle, and group size.
    Uses mock data for MVP (MCP integration deferred).
    """
    suggestions: List[SuggestionItem] = []

    try:
        level = profile["level"]

        # Determine difficulty tier
        if level < 20:
            zones = MOCK_ZONES["low"]
            tier_desc = "Early game"
        elif level < 50:
            zones = MOCK_ZONES["mid"]
            tier_desc = "Mid game"
        else:
            zones = MOCK_ZONES["high"]
            tier_desc = "Late game"

        playstyle = profile["playstyle"]
        fit_notes = {
            "solo_dps": "Solo-friendly camps with good respawn safety",
            "group_dps": "Group content with solid loot tables",
            "tank": "Challenging mobs for tanking practice",
            "healer": "Group dungeons where healing is needed",
            "support": "Group content for support role",
            "pet_focused": "Mobs that work well with pet damage",
            "balanced": "Versatile content for mixed playstyle",
        }

        # Build suggestions
        for idx, zone in enumerate(zones):
            if idx == 0:
                priority = 1
                note = "Current zone"
            else:
                priority = 2
                note = "Next progression"

            suggestions.append(
                {
                    "name": zone["name"],
                    "category": "zone",
                    "priority": priority,
                    "reason": f"{note} ({tier_desc}). {zone['desc']}",
                    "synergies": [
                        fit_notes.get(playstyle, "Good for leveling"),
                        f"Optimal for {profile['primary_class']} class",
                    ],
                    "source": f"EQL Wiki: {zone['name']}",
                }
            )

        return suggestions

    except Exception as e:
        logger.error(f"Error getting leveling zone suggestions: {e}")
        return [
            {
                "name": "Crescent Reach",
                "category": "zone",
                "priority": 1,
                "reason": "Safe starter zone with good exp",
                "synergies": ["Solo-friendly", "Good respawn safety"],
                "source": "EQL Wiki",
            }
        ]


# Placeholder for future gear suggestions tool (post-MVP)
async def get_gear_suggestions(profile: ProfileData) -> List[SuggestionItem]:
    """Get gear suggestions (post-MVP)."""
    return [
        {
            "name": "Gear suggestions coming soon",
            "category": "gear",
            "priority": 5,
            "reason": "Gear suggestion tool will be added post-MVP",
            "synergies": [],
            "source": "N/A",
        }
    ]
