"""Generate the custom textures for the 'Clean dark flat' modern skin.

Outputs into ../skin:
  modern_glass.tga  - 64x64 dark translucent panel background (subtle gradient)
  modern_atlas.tga  - 64x64 swatch atlas: accent / white-fill / dark-track / clear

Region map for modern_atlas (top-left coords, what EQUI_Modern.xml references):
  ACCENT  swatch cell (0,0)  -> inner sample (2,2,12,12)   color = ACCENT
  WHITE   swatch cell (16,0) -> inner sample (18,2,12,12)  gauge fill (tinted)
  TRACK   swatch cell (32,0) -> inner sample (34,2,12,12)  empty gauge track
  CLEAR   swatch cell (48,0) -> inner sample (50,2,12,12)  fully transparent
Border line slices come from the ACCENT cell:
  top/bottom = (2,2,12,1)   left/right = (2,2,1,12)   corner = (2,2,2,2)
"""
import os
from tga import write_tga, write_tga24, vgradient, solid, fill_rect

OUT = os.path.join(os.path.dirname(__file__), "..", "skin")
os.makedirs(OUT, exist_ok=True)

# ---- Palette (StoneGlass: dark glass + warm gold) ------------------------
# Design tokens from the project handoff (CLAUDE.md):
#   panel rgba(18,21,26,.82)  inset rgba(8,10,13,.72)  gold #c8aa6e
ACCENT = (200, 170, 110, 235)   # gold hairline border (#c8aa6e)
WHITE  = (255, 255, 255, 255)   # gauge fill base (FillTint multiplies this)
TRACK  = (8, 10, 13, 220)       # empty gauge track / inset, near-opaque dark
CLEAR  = (0, 0, 0, 0)           # transparent (square gauge ends, no lines)
GLASS_TOP = (24, 27, 33, 209)   # panel glass, slightly lighter at top
GLASS_BOT = (14, 16, 21, 209)   # panel glass, darker at bottom (~.82 alpha)

# ---- modern_glass.tga: vertical gradient ---------------------------------
W = H = 64
glass = []
for y in range(H):
    t = y / (H - 1)
    row = []
    px = tuple(round(a + (b - a) * t) for a, b in zip(GLASS_TOP, GLASS_BOT))
    for x in range(W):
        row.append(px)
    glass.append(row)
write_tga(os.path.join(OUT, "modern_glass.tga"), W, H, glass)

# ---- modern_atlas.tga: 16px swatch cells ---------------------------------
atlas = solid(64, 64, CLEAR)
fill_rect(atlas, 0,  0, 16, 16, ACCENT)
fill_rect(atlas, 16, 0, 16, 16, WHITE)
fill_rect(atlas, 32, 0, 16, 16, TRACK)
fill_rect(atlas, 48, 0, 16, 16, CLEAR)
write_tga(os.path.join(OUT, "modern_atlas.tga"), 64, 64, atlas)

# ---- Flat panel backgrounds (override stock noisy stone) -----------------
# Same filenames as stock so the engine swaps them for EVERY window using these
# templates (incl. windows we haven't hand-converted) -> global de-noise.
# 256x256 24bpp, subtle vertical gradient only. Kept distinct so window vs.
# inset vs. background layering still reads.
PANELS = {
    "wnd_bg_dark_rock.tga":  ((20, 23, 28), (14, 17, 21)),   # WDT_Inner / Transparent
    "wnd_bg_mid_rock.tga":   ((24, 28, 34), (17, 20, 26)),   # WDT_InsetStone / FakeInset
    "wnd_bg_light_rock.tga": ((32, 36, 43), (24, 28, 34)),   # WDT_Rounded / Def
}
for name, (top, bot) in PANELS.items():
    write_tga24(os.path.join(OUT, name), 256, 256, vgradient(256, 256, top, bot))

print("Wrote modern_glass.tga, modern_atlas.tga, and 3 flat panel backgrounds to",
      os.path.abspath(OUT))
