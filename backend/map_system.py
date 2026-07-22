"""Zone maps + travel routing.

Renders data from the game's own vector map files
(`<EQL>\\maps\\*.txt`, classic EQ format):
    L x1, y1, z1, x2, y2, z2, r, g, b      — line segment
    P x, y, z, r, g, b, size, Label_text   — labeled point

Map-space convention: file coords are already (-locX, -locY), i.e. a /loc
position plots at (-x, -y) with screen-y pointing down.

To support a zone the game names differently, add it to ZONE_FILES (map
lookup) and ZONE_GRAPH (routing). Unknown zones degrade to "no chart".
"""
import logging
import re
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# Zone long name (as logged by "You have entered X.") -> map file candidates.
ZONE_FILES: dict[str, list[str]] = {
    # Antonica — west
    "South Qeynos": ["qeynos"], "North Qeynos": ["qeynos2"],
    "Qeynos Hills": ["qeytoqrg"], "Surefall Glade": ["qrg"],
    "Qeynos Catacombs": ["qcat"],
    "West Karana": ["qey2hh1"], "North Karana": ["northkarana"],
    "South Karana": ["southkarana"], "East Karana": ["eastkarana"],
    "Lake Rathetear": ["lakerathe"], "Rathe Mountains": ["rathemtn"],
    "Arena": ["arena"], "Everfrost Peaks": ["everfrost"], "Everfrost": ["everfrost"],
    "Halas": ["halas"], "Blackburrow": ["blackburrow"],
    "Highpass Hold": ["highpass"], "High Keep": ["highkeep"],
    # Antonica — east
    "East Commonlands": ["ecommons", "commonlands"],
    "West Commonlands": ["commons", "commonlands"],
    "Kithicor Forest": ["kithicor"], "Rivervale": ["rivervale"],
    "Misty Thicket": ["misty", "mistythicket"],
    "Nektulos Forest": ["nektulos"],
    "Neriak Foreign Quarter": ["neriaka"], "Neriak Commons": ["neriakb"],
    "Neriak Third Gate": ["neriakc"],
    "Lavastorm Mountains": ["lavastorm"],
    "West Freeport": ["freportw", "freeportwest"],
    "East Freeport": ["freporte", "freeporteast"],
    "North Freeport": ["freportn"],
    "Northern Desert of Ro": ["nro", "northro"], "North Ro": ["nro", "northro"],
    "Oasis of Marr": ["oasis"],
    "Southern Desert of Ro": ["sro", "southro"], "South Ro": ["sro", "southro"],
    "Innothule Swamp": ["innothule", "innothuleb"], "Grobb": ["grobb"],
    "Upper Guk": ["guktop"], "Lower Guk": ["gukbottom"],
    "Feerrott": ["feerrott"], "Oggok": ["oggok"],
    "Gorge of King Xorbb": ["beholder"],
    # Faydwer
    "Greater Faydark": ["gfaydark"], "Lesser Faydark": ["lfaydark"],
    "Steamfont Mountains": ["steamfont", "steamfontmts"], "Ak'Anon": ["akanon"],
    "North Kaladim": ["kaladima"], "South Kaladim": ["kaladimb"],
    "Northern Felwithe": ["felwithea"], "Southern Felwithe": ["felwitheb"],
    "Dagnor's Cauldron": ["cauldron"], "Butcherblock Mountains": ["butcher"],
    # Odus
    "Erudin": ["erudnext"], "Erudin Palace": ["erudnint"],
    "Toxxulia Forest": ["tox", "toxxulia"], "Paineel": ["paineel"],
    "Kerra Isle": ["kerraridge"], "Erud's Crossing": ["erudsxing"],
    "Stonebrunt Mountains": ["stonebrunt"],
    # Boats / misc
    "Ocean of Tears": ["oot"],
    "Plane of Knowledge": ["poknowledge"],
    "Crescent Reach": ["crescent"],
    # Dungeons (charts come from custom packs like Brewall's; stock has none)
    "Befallen": ["befallen"],
    "Blackburrow": ["blackburrow"],
    "Upper Guk": ["guktop"],
    "Lower Guk": ["gukbottom"],
    "Solusek's Eye": ["soldunga"],
    "Nagafen's Lair": ["soldungb"],
    "Permafrost Keep": ["permafrost"],
    "Splitpaw Lair": ["paw"],
    "Runnyeye Citadel": ["runnyeye"],
    "Crushbone": ["crushbone"],
    "Castle Mistmoore": ["mistmoore"],
    "Estate of Unrest": ["unrest"],
    "Kedge Keep": ["kedge"],
    "Najena": ["najena"],
    "Cazic-Thule": ["cazicthule"],
}

# Travel graph (classic pre-Kunark connections). Keys/values use the same
# long names as ZONE_FILES. BFS gives the shortest zone-hop route.
ZONE_GRAPH: dict[str, list[str]] = {
    "Surefall Glade": ["Qeynos Hills"],
    "Qeynos Hills": ["Surefall Glade", "North Qeynos", "South Qeynos",
                     "Blackburrow", "West Karana"],
    "North Qeynos": ["South Qeynos", "Qeynos Hills"],
    "South Qeynos": ["North Qeynos", "Qeynos Hills", "Qeynos Catacombs",
                     "Erud's Crossing"],
    "Qeynos Catacombs": ["South Qeynos"],
    "Blackburrow": ["Qeynos Hills", "Everfrost Peaks"],
    "Everfrost Peaks": ["Blackburrow", "Halas", "Permafrost Keep"],
    "Halas": ["Everfrost Peaks"],
    "Permafrost Keep": ["Everfrost Peaks"],
    "West Karana": ["Qeynos Hills", "North Karana"],
    "North Karana": ["West Karana", "South Karana", "East Karana"],
    "South Karana": ["North Karana", "Lake Rathetear", "Splitpaw Lair"],
    "Splitpaw Lair": ["South Karana"],
    "East Karana": ["North Karana", "Highpass Hold", "Gorge of King Xorbb"],
    "Gorge of King Xorbb": ["East Karana", "Runnyeye Citadel"],
    "Runnyeye Citadel": ["Gorge of King Xorbb", "Misty Thicket"],
    "Highpass Hold": ["East Karana", "Kithicor Forest", "High Keep"],
    "High Keep": ["Highpass Hold"],
    "Kithicor Forest": ["Highpass Hold", "West Commonlands", "Rivervale"],
    "Rivervale": ["Kithicor Forest", "Misty Thicket"],
    "Misty Thicket": ["Rivervale", "Runnyeye Citadel"],
    "Lake Rathetear": ["South Karana", "Rathe Mountains", "Arena"],
    "Arena": ["Lake Rathetear"],
    "Rathe Mountains": ["Lake Rathetear", "Feerrott"],
    "Feerrott": ["Rathe Mountains", "Innothule Swamp", "Oggok", "Cazic-Thule"],
    "Oggok": ["Feerrott"],
    "Cazic-Thule": ["Feerrott"],
    "Innothule Swamp": ["Feerrott", "Southern Desert of Ro", "Grobb", "Upper Guk"],
    "Grobb": ["Innothule Swamp"],
    "Upper Guk": ["Innothule Swamp", "Lower Guk"],
    "Lower Guk": ["Upper Guk"],
    "Southern Desert of Ro": ["Innothule Swamp", "Oasis of Marr"],
    "Oasis of Marr": ["Southern Desert of Ro", "Northern Desert of Ro"],
    "Northern Desert of Ro": ["Oasis of Marr", "East Commonlands"],
    "East Commonlands": ["Northern Desert of Ro", "West Commonlands",
                         "West Freeport", "Nektulos Forest"],
    "West Commonlands": ["East Commonlands", "Kithicor Forest", "Befallen"],
    "Befallen": ["West Commonlands"],
    "West Freeport": ["East Commonlands", "East Freeport", "North Freeport"],
    "North Freeport": ["West Freeport", "East Freeport"],
    "East Freeport": ["West Freeport", "North Freeport", "Ocean of Tears"],
    "Nektulos Forest": ["East Commonlands", "Neriak Foreign Quarter",
                        "Lavastorm Mountains"],
    "Neriak Foreign Quarter": ["Nektulos Forest", "Neriak Commons"],
    "Neriak Commons": ["Neriak Foreign Quarter", "Neriak Third Gate"],
    "Neriak Third Gate": ["Neriak Commons"],
    "Lavastorm Mountains": ["Nektulos Forest", "Solusek's Eye",
                            "Nagafen's Lair", "Najena"],
    "Solusek's Eye": ["Lavastorm Mountains", "Nagafen's Lair"],
    "Nagafen's Lair": ["Lavastorm Mountains", "Solusek's Eye"],
    "Najena": ["Lavastorm Mountains"],
    "Ocean of Tears": ["East Freeport", "Butcherblock Mountains"],
    "Butcherblock Mountains": ["Ocean of Tears", "North Kaladim",
                               "Greater Faydark", "Dagnor's Cauldron"],
    "North Kaladim": ["Butcherblock Mountains", "South Kaladim"],
    "South Kaladim": ["North Kaladim"],
    "Greater Faydark": ["Butcherblock Mountains", "Lesser Faydark",
                        "Northern Felwithe", "Crushbone"],
    "Crushbone": ["Greater Faydark"],
    "Northern Felwithe": ["Greater Faydark", "Southern Felwithe"],
    "Southern Felwithe": ["Northern Felwithe"],
    "Lesser Faydark": ["Greater Faydark", "Steamfont Mountains",
                       "Castle Mistmoore"],
    "Castle Mistmoore": ["Lesser Faydark"],
    "Steamfont Mountains": ["Lesser Faydark", "Ak'Anon"],
    "Ak'Anon": ["Steamfont Mountains"],
    "Dagnor's Cauldron": ["Butcherblock Mountains", "Estate of Unrest",
                          "Kedge Keep"],
    "Estate of Unrest": ["Dagnor's Cauldron"],
    "Kedge Keep": ["Dagnor's Cauldron"],
    "Erud's Crossing": ["South Qeynos", "Erudin", "Kerra Isle"],
    "Erudin": ["Erud's Crossing", "Erudin Palace", "Toxxulia Forest"],
    "Erudin Palace": ["Erudin"],
    "Toxxulia Forest": ["Erudin", "Paineel", "Kerra Isle"],
    "Paineel": ["Toxxulia Forest"],
    "Kerra Isle": ["Toxxulia Forest", "Erud's Crossing"],
}

# Difficulty/instance suffixes -- "Befallen 2 (Adaptive)", "Befallen 4 (Refined)"
# etc. Every difficulty tier uses the same chart as the base zone.
RE_DIFFICULTY = re.compile(r"\s*\d*\s*\([a-z ]+\)\s*$", re.IGNORECASE)


def normalize_zone(name: str) -> str:
    """'Befallen 4 (Refined)' -> 'Befallen'; 'The Feerrott' -> 'Feerrott'."""
    n = RE_DIFFICULTY.sub("", name).strip()
    if n.lower().startswith("the "):
        n = n[4:]
    return n


# In-game names for zones whose graph/file keys use the colloquial name
# (the log says "You have entered The City of Guk.").
ZONE_ALIASES = {
    "city of guk": "Upper Guk",
    "guk": "Upper Guk",
    "ruins of old guk": "Lower Guk",
    "old guk": "Lower Guk",
    # EQL's in-game names vs the classic chart/graph keys
    "clan crushbone": "Crushbone",
    "clan runnyeye": "Runnyeye",
    "castle mistmoore": "Mistmoore Castle",
    "estate of unrest": "The Estate of Unrest",
}


def _canonical(name: str) -> Optional[str]:
    """Resolve a user/log zone name to a canonical graph/file key."""
    n = normalize_zone(name)
    lower = n.lower()
    if lower in ZONE_ALIASES:
        return ZONE_ALIASES[lower]
    for key in set(list(ZONE_FILES) + list(ZONE_GRAPH)):
        if key.lower() == lower:
            return key
    return None


def _maps_dirs() -> list[Path]:
    """Search order: custom pack (e.g. Brewall) first, stock maps second."""
    dirs = []
    for d in (settings.eql_maps_custom_dir, settings.eql_maps_dir):
        p = Path(d)
        if p.is_dir():
            dirs.append(p)
    return dirs


@lru_cache(maxsize=32)
def load_map(zone_name: str) -> Optional[dict]:
    """Load + parse map data for a zone (base file + _1.._3 label layers)."""
    key = _canonical(zone_name)
    candidates = list(ZONE_FILES.get(key or "", []))
    # Fallback: many packs name files by the squashed zone name
    squashed = re.sub(r"[^a-z0-9]", "", normalize_zone(zone_name).lower())
    if squashed and squashed not in candidates:
        candidates.append(squashed)

    base = None
    base_dir = None
    for d in _maps_dirs():
        for cand in candidates:
            if (d / f"{cand}.txt").exists():
                base, base_dir = cand, d
                break
        if base:
            break
    if base is None:
        return None

    lines: list[list[float]] = []
    points: list[dict] = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    files = [f"{base}.txt"] + [f"{base}_{i}.txt" for i in (1, 2, 3)]
    for fname in files:
        fpath = base_dir / fname
        if not fpath.exists():
            continue
        for raw in fpath.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            try:
                if raw.startswith("L "):
                    parts = [p.strip() for p in raw[2:].split(",")]
                    x1, y1, _, x2, y2, _ = (float(p) for p in parts[:6])
                    r, g, b = (int(float(p)) for p in parts[6:9])
                    lines.append([round(x1, 1), round(y1, 1),
                                  round(x2, 1), round(y2, 1), r, g, b])
                    min_x = min(min_x, x1, x2); max_x = max(max_x, x1, x2)
                    min_y = min(min_y, y1, y2); max_y = max(max_y, y1, y2)
                elif raw.startswith("P "):
                    parts = [p.strip() for p in raw[2:].split(",")]
                    x, y = float(parts[0]), float(parts[1])
                    size = int(float(parts[6]))
                    label = parts[7].replace("_", " ").strip()
                    points.append({"x": round(x, 1), "y": round(y, 1),
                                   "size": size, "label": label,
                                   "exit": label.lower().startswith("to ")})
                    min_x = min(min_x, x); max_x = max(max_x, x)
                    min_y = min(min_y, y); max_y = max(max_y, y)
            except (ValueError, IndexError):
                continue  # malformed line — skip

    if not lines and not points:
        return None
    return {
        "zone": key or normalize_zone(zone_name),
        "file": base,
        "lines": lines,
        "points": points,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    }


# EQL travel extras (data per rari/eqltools, CC0; sources: eqlwiki
# Travel_Guide + Translocators, P99 spell lines). Classic era only;
# zones absent from ZONE_GRAPH are skipped at runtime.
# Boats are replaced by NAVAL TRANSLOCATORS: each route is a dock
# CLIQUE, so any listed dock reaches any other in ONE hop.
TRANSLOCATOR_CLIQUES: list[list[str]] = [
    ["South Qeynos", "Erud's Crossing", "Erudin"],
    ["East Freeport", "Ocean of Tears", "Butcherblock Mountains"],
]
# Port RITUALS castable from any loadout once the class is leveled,
# modeled as a jump from anywhere to the destination zone.
PORT_SPELLS: dict[str, dict[str, str]] = {
    "druid": {
        "Butcherblock Mountains": "Circle of Butcher",
        "North Karana": "Circle of Karana",
        "Toxxulia Forest": "Circle of Toxxulia",
        "West Commonlands": "Circle of Commons",
        "Surefall Glade": "Circle of Surefall Glade",
        "Feerrott": "Circle of Feerrott",
        "Lavastorm Mountains": "Circle of Lavastorm",
        "Southern Desert of Ro": "Circle of Ro",
        "Steamfont Mountains": "Circle of Steamfont",
        "Misty Thicket": "Circle of Misty",
    },
    "wizard": {
        "Greater Faydark": "Fay Portal",
        "North Karana": "North Portal",
        "Toxxulia Forest": "Tox Portal",
        "Cazic-Thule": "Cazic Portal",
        "West Commonlands": "Common Portal",
        "Nektulos Forest": "Nek Portal",
        "Northern Desert of Ro": "Ro Portal",
        "West Karana": "West Portal",
    },
}


def find_route_ex(frm: str, to: str,
                  port_classes: tuple = ()) -> Optional[list[dict]]:
    """Labeled BFS over walk edges + translocator dock cliques + (when
    the trio can ritual-cast them) druid/wizard port jumps from any
    zone. Returns [{"zone", "via"}]; via is None for the start."""
    start, goal = _canonical(frm), _canonical(to)
    if (not start or not goal or start not in ZONE_GRAPH
            or goal not in ZONE_GRAPH):
        return None
    if start == goal:
        return [{"zone": start, "via": None}]
    port_jumps: dict[str, str] = {}
    for cls in port_classes:
        for z, spell in PORT_SPELLS.get(str(cls).lower(), {}).items():
            if z in ZONE_GRAPH and z not in port_jumps:
                port_jumps[z] = f"{cls} port ritual: {spell}"
    clique_of: dict[str, set] = {}
    for cl in TRANSLOCATOR_CLIQUES:
        present = [z for z in cl if z in ZONE_GRAPH]
        for z in present:
            clique_of.setdefault(z, set()).update(
                p for p in present if p != z)
    seen = {start}
    queue: deque[list[dict]] = deque([[{"zone": start, "via": None}]])
    while queue:
        path = queue.popleft()
        cur = path[-1]["zone"]
        neigh = [(n, "walk") for n in ZONE_GRAPH.get(cur, [])]
        neigh += [(n, "naval translocator")
                  for n in sorted(clique_of.get(cur, ()))]
        neigh += list(port_jumps.items())
        for n, via in neigh:
            if n in seen:
                continue
            step = {"zone": n, "via": via}
            if n == goal:
                return path + [step]
            seen.add(n)
            queue.append(path + [step])
    return None


def find_route(frm: str, to: str) -> Optional[list[str]]:
    """Shortest zone-hop path via BFS, or None."""
    start, goal = _canonical(frm), _canonical(to)
    if not start or not goal or start not in ZONE_GRAPH or goal not in ZONE_GRAPH:
        return None
    if start == goal:
        return [start]
    seen = {start}
    queue: deque[list[str]] = deque([[start]])
    while queue:
        path = queue.popleft()
        for neighbor in ZONE_GRAPH.get(path[-1], []):
            if neighbor in seen:
                continue
            if neighbor == goal:
                return path + [neighbor]
            seen.add(neighbor)
            queue.append(path + [neighbor])
    return None


def known_zones() -> list[str]:
    return sorted(ZONE_GRAPH.keys())
