# OmniPal design system (Omarchy style)

Single source of truth: `plugins/shared/*.js|*.qml`, symlinked into each plugin as `../shared/<name>` (enforced by `scripts/check_consistency.py`; `install.sh` links `plugins/shared` itself so the relative links resolve at runtime).
No QML file may contain a hex colour, a literal `Qt.rgba(<number>…)`, or `"monospace"` — enforced by `tests/test_design_tokens.py`.

## Runtime theme
Every root plugin (`id: root`) has a `FileView` that reads the current Omarchy theme palette:

1. `~/.local/state/omarchy/current/theme/colors.toml` (current omarchy, same path as omarchy `shell/Commons/Color.qml` and `bin/omarchy-theme-color`)
2. `~/.config/omarchy/current/theme/colors.toml` (legacy, tried on load failure)

The file is watched, so `omarchy-theme-set` re-skins OmniPal live. Missing keys fall back to tokyo-night
(`themes/tokyo-night/colors.toml`). Host `qs.Commons` `Color.background/foreground/accent` override the palette when present.

`root.theme` = `Tokens.build(Color, palette)` → semantic roles:
`bg surface surfaceAlt sunken scrim shadow line lineStrong text textStrong textMuted accent onAccent selection selectionFill hoverFill chipFill chipBorder ok warn danger info special highlight`.
`root.modeColors` = profile identity colours derived from the palette (windows=blue, mac=light_foreground, omarchy=green).
Child components (`OverviewCard`, `BlackHole`) take a `theme` property.

## Scales
| token | values | Omarchy origin |
|---|---|---|
| `radius` | none/sm/md 0, chip 2 | hyprland `rounding = 0` |
| `border` | hair 1, normal 2, focus 2 | hyprland `border_size = 2`, active border = accent |
| `space` | 2 4 6 10 14 20 28 | |
| `type` | 10 11 13 15 20 | |
| `motion` | fast 90, normal 140, slow 200 ms | |
| `font.mono` | JetBrainsMono Nerd Font | omarchy default font |

## Patterns
- Surfaces flat, no gradients; focused/selected = 2px accent border + `selectionFill`.
- Key-cap chips: `chipFill` + 1px `chipBorder`, radius `chip`; held modifier → 2px accent.
