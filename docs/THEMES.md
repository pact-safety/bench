# Themes

Bench themes are **not a new system** — they reuse the existing
`data-theme` mechanism. A theme is ~9 primitive color values in a
`[data-theme="<name>"]` scope. Everything else in the app already reads
those primitives through aliases, so a new theme restyles the entire UI
without touching a single template or component rule.

The goal is personalization: a learner should be able to make the bench
feel like *their* space. Training is a long grind — the room you do it in
should feel like yours.

---

## How theming works

`static/css/tokens.css` defines the canonical **primitives** (shared with
libearden.dev). `static/css/main.css` aliases the older bench names onto
them (`--surface-color: var(--surface)`, `--brand-color: var(--accent)`,
…). Because every component rule references an alias or a primitive,
overriding the primitives is enough to retheme everything.

The 9 primitives a theme must define:

| token | role |
|---|---|
| `--bg` | page background |
| `--surface` | cards, panels |
| `--surface-2` | lifted surface — code blocks, raised chips |
| `--border` | hairlines, dividers |
| `--text` | primary text |
| `--text-muted` | secondary text, metadata |
| `--text-faint` | decorative only (ticks, disabled) |
| `--accent` | links, primary buttons, focus |
| `--accent-hover` | accent hover/active |

Current default (dark):

```css
--bg: #0A0B0D;  --surface: #131519;  --surface-2: #1A1D23;
--border: #262A31;
--text: #E7E9EC;  --text-muted: #8A909B;  --text-faint: #5A606B;
--accent: #E8B339;  --accent-hover: #F2C65C;
```

Theme state lives in `localStorage["theme"]`; a no-flash `<head>` script
in `templates/base.html` sets `data-theme` before first paint.

### ⚠️ Known blocker before arbitrary themes work

The theme layer is mid-migration. `main.css` documents dark as the plain
`:root` default with light as an override, but the codebase still carries
`:root[data-theme="dark"] …` rules, and the no-flash script only ever sets
`data-theme="dark"` (any other stored value is ignored). **Resolve that
before shipping a theme picker**, or a selected theme silently won't apply.
The fix is small and mechanical:

1. Pick one convention: `:root` = dark default, every other theme is a
   `[data-theme="X"]` override (including `light`).
2. Update the no-flash script to apply *any* stored theme name, not just
   `"dark"`.
3. Convert the remaining `:root[data-theme="dark"] …` rules to plain
   `:root` rules.

### Wiring a picker into personal settings

`users.settings_json` already carries the a11y toggles — add `theme` there
the same way, render a `<select>` on `/settings`, and have `base.html`
seed the no-flash script from the saved value (falling back to
localStorage so the choice survives before login).

---

## Theme: Hyperbolic Time Chamber

*The Room of Spirit and Time — an endless white void where one day is a
year. Sensory deprivation as a training environment. Blended with a
vaporwave palette: the blinding void, lit in neon.*

**Design reasoning.** The chamber's defining feature is a featureless,
horizonless white expanse under harsh sourceless light — so this is
deliberately a **light** theme, an inversion of bench's dark default
(you step out of the dark and into the white room). Surfaces are pure
white against a faintly violet-cast pearl void, so cards read as objects
floating in emptiness rather than panels on a page. The vaporwave
influence lands in the **accent** (deep orchid magenta) and the cool
violet cast running through the greys — neon restrained enough to stay
legible, rather than the full #FF6AD5 neon that fails contrast on white.

```css
:root[data-theme="hyperbolic"] {
  /* The void — pearl white with a faint violet cast */
  --bg:           #F7F5FA;
  --surface:      #FFFFFF;   /* blinding white — cards float in the void */
  --surface-2:    #EFEBF5;   /* lifted lavender tint — code blocks */
  --border:       #DCD5E8;   /* pale lavender hairline */

  /* Text — deep violet-charcoal, never pure black (softer, dreamlike) */
  --text:         #2A2438;
  --text-muted:   #6B6280;
  --text-faint:   #9A93AC;

  /* Vaporwave neon, dialed to stay readable on white */
  --accent:       #A62E8A;
  --accent-hover: #C4419F;
}
```

**Contrast** — measured, not estimated. Every floor is met:

| pair | ratio | floor |
|---|---|---|
| `--text` on `--bg` | 13.78:1 | 7.0 (AAA body) |
| `--text` on `--surface` | 14.92:1 | 7.0 (AAA body) |
| `--text` on `--surface-2` | 12.69:1 | 7.0 (AAA code) |
| `--text-muted` on `--bg` | 5.27:1 | 4.5 (AA body) |
| `--accent` on `--surface` | 6.21:1 | 4.5 (AA links) |
| `--accent` on `--bg` | 5.74:1 | 4.5 (AA links) |
| `--accent-hover` on `--surface` | 4.56:1 | 3.0 (hover) |

`--text-faint` (2.72:1) is decorative only — never use it for body copy.
Verify with the high-contrast toggle before shipping.

**Typography.** Keep the existing pairing (Inter body / Geist Mono
chrome) — no webfont additions. Vaporwave's retro-wide feel comes free
from the mono chrome plus `--tracking-widest` on eyebrows and badges,
not from importing a display face. (An all-mono theme reads authentically
retro but punishes long-form `/writings` prose.)

**Optional decorative extras** (only if you extend beyond the primitives):
a cyan `#22B8CF` as a secondary for charts/gradients, and a
magenta→cyan gradient reserved for hero/empty-state art. Don't put a
gradient behind text.

**Design-system extension (shipped).** This theme now carries the full
port of the claude.ai/design **"Bench Design System"** project, scoped
entirely inside `[data-theme="hyperbolic"]` (the dark default is
untouched): a signal color set (gold / mint / sky / plum, each with an
AA `-ink` and a soft `-dim`), semantic states re-hued for white, frosted
**glass panels** (translucent fill + backdrop-blur + violet lift shadows)
on floating surfaces, the **iridescent pearl-void** backdrop with a slow
drift, and rounder geometry (cards 20px). Guardrails: work surfaces
(code blocks) stay opaque for legibility; the drift stops under
reduce-motion (OS or bench toggle); the high-contrast toggle turns glass
opaque; two DS values were deepened after measurement (`--gold-ink`,
`--err`) because the DS checked them on pure white, not the pearl `--bg`.

---

## Prompt: generate a new bench theme

Paste this into a fresh session, replacing the brief.

```
Generate a color theme for "Li's Bench", a learning/training web app.

THEME BRIEF: <describe the vibe — a place, a film, a game, a mood,
an era. e.g. "the Hyperbolic Time Chamber from Dragon Ball Z, blended
with vaporwave" or "a 1970s NASA mission control room">

HARD CONTRACT — the output must be exactly one CSS block:

:root[data-theme="<kebab-name>"] {
  --bg:           #......;  /* page background */
  --surface:      #......;  /* cards, panels */
  --surface-2:    #......;  /* lifted surface — code blocks */
  --border:       #......;  /* hairlines, dividers */
  --text:         #......;  /* primary text */
  --text-muted:   #......;  /* secondary text, metadata */
  --text-faint:   #......;  /* decorative only */
  --accent:       #......;  /* links, primary buttons, focus */
  --accent-hover: #......;  /* accent hover/active */
}

RULES
- Exactly these 9 tokens. No extra tokens, no font imports, no
  component CSS, no gradients. Everything else in the app already
  derives from these.
- Accessibility is non-negotiable:
  * --text on --bg must be >= 7:1 (AAA body).
  * --text-muted on --bg must be >= 4.5:1 (AA body).
  * --accent on --surface must be >= 4.5:1 — it's used for links and
    buttons. Deepen a neon until it passes rather than dropping it.
  * --text-faint is decorative only and has no contrast floor.
- --surface and --surface-2 must be distinguishable from --bg and from
  each other, or cards and code blocks visually collapse.
- Commit to the theme's mood in the hues (a cast running through the
  greys), but keep saturation low enough on large surfaces that the UI
  stays comfortable for multi-hour sessions.

OUTPUT
1. The CSS block.
2. A 3-4 sentence design rationale: which real visual references drove
   the palette, and why light vs dark.
3. The three computed contrast ratios listed above, so they can be
   checked.
```

---

## Prompt: a new design system for the bench UI

**Read this first:** bench is server-rendered **Jinja + HTMX with one
hand-written `static/css/main.css`** — there is no React, no component
library, and no build step. Claude Design's usual output (React/Tailwind
components) **cannot be dropped into this app**. Use it for *visual
direction*, then port the decisions back as tokens and shared classes.
Do not let it introduce Tailwind, shadcn, or a framework — the minimal
terminal aesthetic is custom and a component library would fight it.

```
Design a visual system for "Li's Bench" — an adaptive AI-safety
fieldbuilding platform where engineers from other disciplines ramp
toward frontier safety research. Long sessions: reading, timed coding
drills, mentor chat, weekly reflection.

CONSTRAINTS (non-negotiable)
- Output is a DESIGN SPEC, not shippable component code: a token set,
  type scale, spacing scale, and the states for a small component
  vocabulary (card, list row, button, input, badge/tag, status slot).
- The implementation target is semantic server-rendered HTML styled by
  ONE hand-written CSS file. No Tailwind, no shadcn, no CSS framework,
  no build step, no client-state library.
- Dark is the default; the system must define light as well, and be
  extensible to arbitrary user themes that override only ~9 color
  primitives (bg, surface, surface-2, border, text, text-muted,
  text-faint, accent, accent-hover).
- Type pairing: a proportional sans for body/long-form prose, mono
  reserved for chrome (eyebrows, badges, metadata, code). Not all-mono.
- Must survive three a11y toggles: reduce-motion, larger-text,
  high-contrast. Focus rings always visible, thicker in high-contrast.

DELIVER
1. Token set with values for dark + light.
2. Type scale + spacing scale as stepped values, with intended usage.
3. The component vocabulary above, each with default/hover/focus/
   disabled/error states described in tokens (not hex).
4. Density: one knob for comfortable vs compact.
5. A short rationale for the aesthetic direction, and explicitly what
   you'd REMOVE from a typical dashboard UI to keep it calm enough for
   multi-hour study sessions.
```

---

## Adding a theme

1. Generate the block with the prompt above (or hand-write it).
2. Paste it into `static/css/main.css` alongside the other theme scopes.
3. Resolve the migration blocker above, then select it in `/settings`.

Themes are cosmetic only — they must never change layout, spacing, or
type, so every surface stays predictable across themes.
