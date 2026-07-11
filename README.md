# EverQuest Legends — Modern UI Overhaul (`StoneGlass`)

A custom UI skin for EverQuest Legends in a **dark translucent glass + warm gold**
direction: dark semi-transparent panels, a thin gold hairline border, flat solid
gauges, and a tidied, more readable layout. Built **additively** — the stock
`uifiles\default` skin is never modified, and the shipped file set stays small so
client patches rarely affect it.

> Full project guide, design tokens, technical reference, and TODO live in
> **`CLAUDE.md`**. This README is the quick start.

## Layout

```
eql_mods/
├── skin/                 # THE skin (additive) — deploy source
│   ├── EQUI.xml          #   manifest copy + our modern include
│   ├── EQUI_Modern.xml   #   custom textures, gauge/border anims, glass templates
│   ├── EQUI_*.xml        #   restyled core HUD windows (Player, Target, Group, …)
│   ├── modern_glass.tga  #   dark glass panel background
│   └── modern_atlas.tga  #   gold / fill / track / clear swatches
├── reference/
│   ├── default-xml/      # pristine stock XMLs (diff base) + HTML design prototypes
│   └── modern-xml/       # Daybreak's shipped default_modern XMLs (ideas)
├── tools/                # _config / gen_textures / restyle / tga / deploy / restore
├── docs/_archive/        # abandoned full-copy approach (reference only)
└── backup/               # full stock backup (git-ignored, ~200MB)
```

## Workflow

1. **Retune look:** edit the palette in `tools/gen_textures.py` (glass/gold) and/or
   `tools/restyle.py` (bar tints).
2. **Regenerate:** `python tools/gen_textures.py` and
   `python tools/restyle.py EQUI_PlayerWindow.xml …` (reads pristine reference,
   writes `skin/`; idempotent).
3. **Deploy:** `pwsh tools/deploy.ps1`  → `…\uifiles\StoneGlass\`
4. **In-game:** `/loadskin StoneGlass` (revert with `/loadskin default`).
5. **Remove from disk:** `pwsh tools/restore.ps1`

## Status

- [x] Project scaffold, full stock backup, deploy tooling
- [x] Additive modern layer (glass/inset templates, flat gauge + gold-border anims, textures)
- [x] Core HUD restyled & deployed — Player, Target, ToT, Extended Target, Buffs,
      Songs, Casting, Spell gems, Hotbars, Group, Pet, EQ dock
- [ ] **In-game look review** (awaiting client availability on release)
- [ ] Flat/gold titlebar art (titled windows still show stock titlebar)
- [ ] Inventory window
- [ ] Layout / declutter pass (after visual direction confirmed in-engine)

## Engine constraints (known, by design)

- **Fonts** are fixed engine bitmaps (`<Font>1..5`) — no custom TTF from XML.
- **No smooth animation / cooldown sweeps** — only frame-cycled texture anims.
