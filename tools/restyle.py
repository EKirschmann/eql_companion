"""Restyle a stock EQ window XML into the 'Clean dark flat' modern look.

Reads from reference/default-xml, writes to skin/. Three transforms:
  1. Gauge/border animation names -> flat modern equivalents.
  2. Window draw templates -> glass / inset glass.
  3. FillTint / LinesFillTint RGB values -> modern palette (only inside
     those tint blocks, so labels and other colors are untouched).

Usage:  python restyle.py EQUI_PlayerWindow.xml EQUI_TargetWindow.xml ...
Idempotent: safe to re-run; reads the pristine reference each time.
"""
import os
import re
import sys

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "reference", "default-xml")
DST = os.path.join(HERE, "..", "skin")

# 1. Animation name swaps (stock -> modern)
ANIM_SWAPS = {
    "A_GaugeBackground": "A_ModGaugeBg",
    "A_GaugeFill": "A_ModGaugeFill",
    "A_GaugeEndCapLeft": "A_ModClear",
    "A_GaugeEndCapRight": "A_ModClear",
    "A_GaugeLines": "A_ModClear",
    "A_GaugeLinesFill": "A_ModClear",
    "A_TargetGaugeBackground": "A_ModGaugeBg",
    "A_TargetGaugeFill": "A_ModGaugeFill",
    "A_TargetGaugeEndCapLeft": "A_ModClear",
    "A_TargetGaugeEndCapRight": "A_ModClear",
    "A_TargetGaugeLines": "A_ModClear",
    "A_TargetGaugeLinesFill": "A_ModClear",
}

# 2. Draw template swaps
TEMPLATE_SWAPS = {
    "WDT_Rounded": "WDT_ModernGlass",
    "WDT_FakeInset": "WDT_ModernGlass",
    "WDT_InsetStone": "WDT_ModernInset",
}

# 3. Palette remap: stock (r,g,b) -> StoneGlass (r,g,b)
#    Bar-fill tints from the project handoff (CLAUDE.md design tokens).
PALETTE = {
    (150, 0, 0): (184, 54, 43),     # HP red
    (220, 0, 0): (184, 54, 43),     # group HP red
    (0, 100, 200): (58, 127, 196),  # mana blue
    (0, 128, 255): (58, 127, 196),  # group mana blue
    (247, 222, 0): (224, 181, 58),  # endurance amber
    (240, 240, 0): (224, 181, 58),  # group stamina amber
    (100, 100, 0): (150, 130, 60),  # ETW stamina (kept subdued)
    (51, 150, 51): (74, 155, 90),   # pet / AA green
    (51, 192, 51): (74, 155, 90),   # group pet green
    (220, 150, 0): (200, 162, 74),  # exp gold
    (130, 0, 130): (155, 89, 182),  # cast purple
    (170, 0, 170): (155, 89, 182),  # casting-window purple
    (132, 132, 165): (139, 143, 176),  # slate timers
    (0, 200, 140): (31, 179, 140),  # ToT teal
    # AA tick-lines (0,80,220) intentionally left unchanged.
}

TINT_RE = re.compile(
    r"(<(?:FillTint|LinesFillTint)>\s*)"
    r"<R>(\d+)</R>(\s*)<G>(\d+)</G>(\s*)<B>(\d+)</B>",
    re.S,
)


def remap_tint(m):
    pre, r, s1, g, s2, b = m.group(1), int(m.group(2)), m.group(3), int(m.group(4)), m.group(5), int(m.group(6))
    nr, ng, nb = PALETTE.get((r, g, b), (r, g, b))
    return f"{pre}<R>{nr}</R>{s1}<G>{ng}</G>{s2}<B>{nb}</B>"


def restyle(text):
    for old, new in ANIM_SWAPS.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    for old, new in TEMPLATE_SWAPS.items():
        text = text.replace(f"<DrawTemplate>{old}</DrawTemplate>",
                            f"<DrawTemplate>{new}</DrawTemplate>")
    text = TINT_RE.sub(remap_tint, text)
    return text


def main(names):
    for name in names:
        with open(os.path.join(SRC, name), "r", encoding="latin-1") as f:
            text = f.read()
        out = restyle(text)
        with open(os.path.join(DST, name), "w", encoding="latin-1", newline="") as f:
            f.write(out)
        print(f"restyled {name}")


if __name__ == "__main__":
    main(sys.argv[1:])
