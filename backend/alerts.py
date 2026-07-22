"""User-tracked alert rules (tracked_rules.json) — EQBuddy-style watches.

Rules are deliberately SUBSTRING matches, not regex (per EQBuddy: users
should never need to escape anything). data/tracked_rules.json holds a
list of {"kind": k, "pattern": "text", "enabled": true, "sound": true}
where k is loot|kill|death|zone|tell|fade — pattern "*" matches
everything — plus the special kind "bighit" whose pattern is a NUMBER
(alert when a single hit taken meets it). The file is created with
disabled examples on first load and re-read automatically when edited
(mtime). Built-in alerts (summon, name mentioned in group/guild/raid
chat) fire without rules. Matches surface as overlay banners (+ chime
when sound is true) with a 5s per-rule cooldown; the seed replay never
fires alerts (live only).
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

RULES_FILE = Path("data") / "tracked_rules.json"
KINDS = ("loot", "kill", "death", "zone", "tell", "fade", "bighit")
_EXAMPLE = [
    {"kind": "loot", "pattern": "Kitchen Toolbelt",
     "enabled": False, "sound": True},
    {"kind": "tell", "pattern": "*", "enabled": False, "sound": True},
    {"kind": "fade", "pattern": "Mesmerize", "enabled": False, "sound": True},
    {"kind": "bighit", "pattern": "800", "enabled": False, "sound": True},
]

_cache = {"mtime": None, "rules": []}


def load_rules() -> list:
    try:
        if not RULES_FILE.is_file():
            RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            RULES_FILE.write_text(json.dumps(_EXAMPLE, indent=2),
                                  encoding="utf-8")
        mtime = os.path.getmtime(RULES_FILE)
        if _cache["mtime"] != mtime:
            raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            _cache["rules"] = [
                r for r in raw
                if isinstance(r, dict) and r.get("enabled", True)
                and r.get("pattern") and r.get("kind") in KINDS]
            _cache["mtime"] = mtime
    except Exception:
        logger.exception("tracked_rules.json load failed")
    return _cache["rules"]


def match(kind: str, text: str) -> list:
    """Enabled rules of `kind` whose pattern appears in `text`
    ("*" matches everything)."""
    low = (text or "").lower()
    return [r for r in load_rules()
            if r["kind"] == kind
            and (r["pattern"] == "*" or r["pattern"].lower() in low)]


def bighit_threshold():
    """Smallest enabled bighit rule value, or None."""
    best = None
    for r in load_rules():
        if r["kind"] != "bighit":
            continue
        try:
            v = int(str(r["pattern"]).strip())
        except ValueError:
            continue
        best = v if best is None else min(best, v)
    return best