"""User-tracked alert rules (tracked_rules.json) — EQBuddy-style watches.

Rules are deliberately SUBSTRING matches, not regex (per EQBuddy: users
should never need to escape anything). data/tracked_rules.json holds a
list of {"kind": "loot"|"kill"|"death"|"zone", "pattern": "text",
"enabled": true, "sound": true}; the file is created with a disabled
example on first load and re-read automatically when edited (mtime).
Matches surface as overlay banners (+ chime when sound is true) with a
5s per-rule cooldown; the seed replay never fires alerts (live only).
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

RULES_FILE = Path("data") / "tracked_rules.json"
_EXAMPLE = [{"kind": "loot", "pattern": "Kitchen Toolbelt",
             "enabled": False, "sound": True}]

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
                and r.get("pattern") and r.get("kind") in
                ("loot", "kill", "death", "zone")]
            _cache["mtime"] = mtime
    except Exception:
        logger.exception("tracked_rules.json load failed")
    return _cache["rules"]


def match(kind: str, text: str) -> list:
    """Enabled rules of `kind` whose pattern appears in `text`."""
    low = (text or "").lower()
    return [r for r in load_rules()
            if r["kind"] == kind and r["pattern"].lower() in low]