# Design tokens

The bench's visual surface is a configuration layer, not an engineering task. Every color, spacing, type size, line-height, radius, border, shadow, and motion value comes from a CSS custom property (a "token"). Restyling the whole app means editing the `:root` block at the top of `static/css/main.css` — not hunting through templates or component blocks.

The rule: **never hardcode a visual value.** If I'm about to type a hex code, a px or rem value, or a font name anywhere except the token definitions, I stop. Either the right token exists and I use it, or I add it.

## Where tokens live

Two files. Order matters — `tokens.css` loads first.

- **`static/css/tokens.css`** — the small, shared vocabulary I use on both this site and `libearden.dev`. Color base (`--bg`, `--surface`, `--surface-2`, `--border`, `--text`, `--text-muted`, `--text-faint`), accent (`--accent`, `--accent-hover`, `--accent-dim`), fonts (`--font-sans`, `--font-mono`), the canonical `--radius` (6px), and the prose vs. wide max-widths. I do not add new variables to this file; visual additions specific to the bench belong in `main.css`.
- **`static/css/main.css`** — the bench's `:root` block on top of the shared layer. Adds bench-specific aliases (e.g. `--surface-color: var(--bg)`), the full type and spacing scales, semantic state colors, shadows, radii, motion, and surface overlays. This is what I edit when I restyle.

The bench is dark-only as of 2026-05-27 (after the portfolio-alignment push). All values live in `:root`. If light theme is restored later, mirror everything theme-dependent in `:root[data-theme="light"]`.

## Vocabulary

### Color

Surface and text resolve to the shared tokens. The bench-side aliases (`--surface-color`, `--text-color`, etc.) exist only so I don't have to grep-edit every legacy rule; new code references `--bg`, `--surface`, `--text` directly when it can.

| Token | Purpose |
|---|---|
| `--bg` | Page background |
| `--surface` | Card / panel surface |
| `--surface-2` | Lifted surface — code blocks, dropdowns, input backgrounds |
| `--border` | Default border |
| `--text` | Primary text |
| `--text-muted` | Secondary text |
| `--text-faint` | Tertiary / disabled |
| `--accent` | Amber — the single accent color |
| `--accent-hover` | Lighter amber for hover and active |
| `--accent-dim` | ~15% amber — faint fills, focus ring, dim borders |

Semantic state colors are bench-specific (defined in `main.css`'s `:root`). Each has a `-dim` companion at ~15% alpha for backgrounds and faint borders.

| Token | Purpose |
|---|---|
| `--ok` / `--ok-dim` | Success / pass verdicts |
| `--warn` / `--warn-dim` | Partial / caution |
| `--err` / `--err-dim` | Failure / danger |
| `--info` / `--info-dim` | Neutral status, info banners |

Surface overlays — very-low-opacity white tints I use for row hovers and faint stripes on dark surfaces.

| Token | Use |
|---|---|
| `--surface-overlay-faint` | ~2% white — faintest stripe |
| `--surface-overlay` | ~3% white — default row hover |
| `--surface-overlay-strong` | ~4% white — stronger row hover |

### Type

One stepped type scale. I do not introduce font-size literals; if I need a size that isn't on the scale, I either pick the nearest step or extend the scale.

| Token | Size | Typical use |
|---|---|---|
| `--text-2xs` | 10px (0.625rem) | SVG tick marks, smallest microcopy |
| `--text-xs` | 12px (0.75rem) | Chips, metadata, eyebrows |
| `--text-sm` | 14px (0.875rem) | Secondary text, UI labels |
| `--text-base` | 16px (1rem) | Body |
| `--text-md` | 17px (1.0625rem) | `h3`, lead paragraphs |
| `--text-lg` | 20px (1.25rem) | Minor section heads |
| `--text-xl` | 24px (1.5rem) | `h2`, interview timer |
| `--text-2xl` | 28px (1.75rem) | Larger section heads |
| `--text-3xl` | 32px (2rem) | `h1` default |
| `--text-4xl` | 36px (2.25rem) | Larger page titles |
| `--text-5xl` | 40px (2.5rem) | Hero scale (sparingly) |

Shared geometry and emphasis: `--border-thin` (1px) for fine component outlines; `--weight-semibold` (600) for emphasized headings and disclosure titles.

Line heights: `--leading-tight` (1.25, headings), `--leading-snug` (1.4, dense rows), `--leading-normal` (1.6, body).

Letter spacing: `--tracking-tight` (`-0.015em`, large display), `--tracking-normal` (0), `--tracking-wide` (0.04em, small caps), `--tracking-wider` (0.08em, microcopy), `--tracking-widest` (0.12em, eyebrows).

Font pairing — the rule that keeps the bench from reading "all-mono terminal" (which punishes anything longer than a paragraph):

- `--font-sans` (Inter) — headings, body, button labels, prose
- `--font-mono` (Geist Mono) — eyebrows, tag chips, badges, metadata strings, timestamps, code, SVG ticks

The minimal/terminal feel comes from mono *chrome* plus restrained color and spacing, not from monospacing the prose.

### Spacing

| Token | Value |
|---|---|
| `--space-0-5` | 2px |
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-5` | 24px |
| `--space-6` | 32px |
| `--space-7` | 48px |
| `--space-8` | 64px |

Every margin, padding, and gap references the scale. Density is one knob: `--density` is a multiplier (default 1, comfortable). A density-aware component computes its padding as `calc(var(--space-N) * var(--density))`. `html[data-density="compact"]` flips the knob to 0.75 across every density-aware surface.

### Radius

| Token | Value | Use |
|---|---|---|
| `--radius-sm` | 2px | Hairline rounding on dense rows |
| `--radius-md` | 4px | Inputs (when not using the standard radius) |
| `--radius` | 6px | Cards, buttons, panels — the portfolio scale |
| `--radius-pill` | 999px | Avatars, alpha pill, count badge |

Legacy aliases `--radius-card` and `--radius-input` resolve to `--radius`. Don't introduce new aliases.

### Shadows

The shared in-page source panel uses `--resource-reader-height` (`70vh`) for its reading viewport. Its width follows the available content width, with no fixed minimum that would overflow a mobile screen.

| Token | Use |
|---|---|
| `--shadow-sm` | Subtle elevation — chips, raised inputs |
| `--shadow-md` | Default card lift (also aliased as `--shadow-card`) |
| `--shadow-lg` | Hover lift on cards |
| `--shadow-popover` | Profile dropdown, small panels |
| `--shadow-overlay` | Modals, big floaters (feedback panel) |
| `--focus-ring` | The 3px amber-dim ring on all interactive elements |

### Motion

| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 100ms | Color / border-color hovers |
| `--duration-base` | 150ms | Transform, opacity, box-shadow |
| `--duration-slow` | 250ms | Wider fades, layout-affecting transitions |
| `--ease-out` | standard ease-out | Default for state changes |
| `--ease-emphasis` | a more pronounced curve | Emphasis animations (pentagon entry, etc.) |

`html[data-reduce-motion="1"]` and the system-level `prefers-reduced-motion: reduce` both collapse durations to ~0 across the app — components don't need to do anything special to participate.

## Accessibility invariants

Tokens drive a11y too; the three toggles map to data-attributes on `<html>` populated from `users.settings_json.a11y`:

- `data-reduce-motion="1"` — kills animation/transition durations
- `data-larger-text="1"` — bumps the root font to 19px (~19% larger; aligns with WCAG "large text")
- `data-high-contrast="1"` — pushes primary text to pure white, thickens focus rings, and overrides border tokens to higher-contrast values

Components don't need bespoke variants for these — they ride the token overrides. If I add a new component and it doesn't respond to one of the three toggles, the component is wrong, not the toggle.

## Adding a token

1. Confirm no existing token covers it. If the value is a one-off, that's usually a signal I should be using a scale step, not adding a new token.
2. Add it to the `:root` block in `main.css`, in the section it belongs to (color / type / spacing / radius / shadow / motion).
3. Add a row to this page describing it and its typical use.
4. Reference it in the rule that needed it.

If the token is genuinely shared with `libearden.dev` (rare — the existing shared set is small and stable), it goes in `tokens.css` instead and the same change has to land in the portfolio repo. This is heavy enough that the bias is to keep the addition bench-side.

## What doesn't go in tokens

- Geometric values that aren't visual: `border-radius: 50%` for a circle, `min-width: 18px` for a counter badge. These are structural, not stylistic.
- Counts (`1fr`, `repeat(5, …)`, `flex: 1`).
- SVG-specific font sizes in px (chart tick labels, badge inscriptions) — they don't compose with the root rem the way component text does. Comment them so the intent is obvious.
