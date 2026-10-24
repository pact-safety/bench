# Bench UI style guide

The contract every UI change is checked against. It is deliberately short and
mechanical: a rule that can't be grepped for is a rule that gets ignored.

Companions: `docs/architecture/tokens.md` (the token vocabulary) and
`docs/THEMES.md` (how theming works). This file is the **law**; those two are
the reference.

---

## The five laws

1. **No literal visual values outside `:root`.** No hex, no `rgb(`, no `px`
   font-size, no `px` shadow, no font name — anywhere except a token
   definition. If the token doesn't exist, add it to `:root`; don't inline it.
2. **Shadows come from the ladder. There are exactly five.** Any `box-shadow`
   whose value is not `var(--shadow-1..5)` (or `var(--focus-ring)`, or
   `var(--inset-hi)`) is a violation.
3. **Gradients are named, decorative, and never behind text.** Only the
   `--grad-*` tokens and the pearl-void backdrop. No new `linear-gradient(` or
   `radial-gradient(` in a component rule, ever.
4. **Theme scopes redefine tokens only.** A `[data-theme="…"]` block may
   contain custom-property declarations and nothing else. No component
   selectors, no layout, no new rules. If a component needs to look different
   per theme, it reads a token that resolves differently per theme.
5. **Every motion is a token pair.** `transition` and `animation` use
   `var(--duration-*)` + `var(--ease-*)`. Every animation has a
   `prefers-reduced-motion` and `[data-reduce-motion]` off-switch.

---

## Law 2 — the shadow ladder

Five steps, redefined per theme, nothing else legal. Dark uses black drops;
hyperbolic uses violet lifts. Same ladder, same names, same intent.

```css
:root {
  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.25);                                  /* resting chip, raised input */
  --shadow-2: 0 1px 2px rgba(0, 0, 0, 0.35), 0 2px 8px rgba(0, 0, 0, 0.22);   /* card at rest */
  --shadow-3: 0 8px 24px rgba(0, 0, 0, 0.40);                                 /* card hover / lift */
  --shadow-4: 0 6px 18px rgba(0, 0, 0, 0.18);                                 /* popover, dropdown */
  --shadow-5: 0 12px 30px rgba(0, 0, 0, 0.28);                                /* modal, big floater */
}

:root[data-theme="hyperbolic"] {
  --shadow-1: 0 2px 8px rgba(150, 120, 170, 0.10);
  --shadow-2: 0 10px 30px rgba(150, 120, 170, 0.16);
  --shadow-3: 0 24px 60px rgba(120, 110, 160, 0.22);
  --shadow-4: 0 24px 60px rgba(120, 110, 160, 0.22);
  --shadow-5: 0 24px 60px rgba(120, 110, 160, 0.22);
}
```

Legacy names stay as aliases so nothing has to be renamed at once:

```css
:root {
  --shadow-sm: var(--shadow-1);   --shadow-md: var(--shadow-2);
  --shadow-lg: var(--shadow-3);   --shadow-popover: var(--shadow-4);
  --shadow-overlay: var(--shadow-5);
  --shadow-card: var(--shadow-2);
  --shadow-glass: var(--shadow-2); --shadow-float: var(--shadow-3);
}
```

**Do**

```css
.mira-turn { box-shadow: var(--shadow-2); }
.mira-turn:hover { box-shadow: var(--shadow-3); }
```

**Don't**

```css
.mira-turn { box-shadow: 0 4px 14px rgba(0,0,0,.18); }        /* literal */
.mira-turn { box-shadow: 0 10px 30px var(--plum-dim); }        /* token colour, invented geometry */
.mira-turn { box-shadow: var(--shadow-2), 0 0 0 1px #fff; }    /* ladder + a bonus layer */
```

Depth is a **step on the ladder, not a dial.** Going from rest to hover means
2 → 3. It never means "the same shadow but a bit bigger".

---

## Law 3 — gradients

Legal gradients, all already defined, all decorative:

| token | use |
|---|---|
| `--grad-spine` | the hourglass spine / vertical accent rules |
| `--grad-sand` | sand fill in progress + hourglass graphics |
| `--grad-frame` | gold frame edges on chamber chrome |
| the pearl-void `body::before` | the one ambient backdrop, hyperbolic only |

Anything else is a violation. In particular: no gradient buttons, no gradient
card fills, no gradient text, no gradient behind a transcript. If a surface
needs to feel lifted, it takes a glass fill token and a shadow step.

---

## Law 4 — theme scoping

This is the rule Claude Code breaks most often, so it is worth being blunt
about the shape of it.

**A theme is a palette swap, not a skin.** The component rule is written once,
theme-neutral, and reads tokens. The theme block only changes what those
tokens resolve to.

**Do** — one rule, two themes:

```css
/* component rule — theme-neutral, lives with the component */
.mira-rail {
  background: var(--panel-fill);
  backdrop-filter: var(--panel-blur);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-2);
}

/* dark default: the panel tokens are flat */
:root {
  --panel-fill:   var(--surface);
  --panel-blur:   none;
  --panel-border: var(--border);
}

/* hyperbolic: the same tokens turn to glass */
:root[data-theme="hyperbolic"] {
  --panel-fill:   var(--glass-fill);
  --panel-blur:   blur(var(--glass-blur));
  --panel-border: var(--glass-border);
}
```

**Don't** — a second copy of the component:

```css
.mira-rail { background: var(--surface); border: 1px solid var(--border); }

:root[data-theme="hyperbolic"] .mira-rail {   /* component rule inside a theme scope */
  background: rgba(255,255,255,.55);
  backdrop-filter: blur(18px);
  box-shadow: 0 10px 30px rgba(150,120,170,.16);
}
```

The second version is how the two themes drift apart: every future change to
`.mira-rail` has to be made twice, and one of them gets forgotten.

The glass indirection tokens (add these to `:root` if not present):

```css
:root {
  --panel-fill: var(--surface);
  --panel-fill-raised: var(--surface-2);
  --panel-fill-recessed: var(--surface);
  --panel-border: var(--border);
  --panel-blur: none;
  --panel-inset: none;
}
:root[data-theme="hyperbolic"] {
  --panel-fill: var(--glass-fill);
  --panel-fill-raised: var(--glass-fill-raised);
  --panel-fill-recessed: var(--glass-fill-recessed);
  --panel-border: var(--glass-border);
  --panel-blur: blur(var(--glass-blur));
  --panel-inset: var(--inset-hi);
}
```

**The legibility carve-out.** Work surfaces stay opaque in both themes: code
blocks, the compose editor, reading panes, and the Mira transcript body take
`--surface`/`--surface-2` directly, never `--panel-fill`. Glass is for chrome
and floating panels only. `[data-high-contrast]` sets `--panel-blur: none` and
`--panel-fill: var(--surface)`, which is why the indirection has to exist.

---

## Law 5 — motion

Full token set and the copy-paste keyframe library live in
`static/css/motion.css`. Rules:

- Durations: `--duration-instant` 60ms · `--duration-fast` 100ms ·
  `--duration-base` 150ms · `--duration-slow` 250ms · `--duration-slower` 400ms ·
  `--duration-ambient` 24s.
- Eases: `--ease-out` (enters), `--ease-emphasis` (state changes that matter),
  `--ease-in` (exits), `--ease-linear` (progress, spinners only).
- **Never animate `box-shadow`, `width`, `height`, `top/left`, or `filter`.**
  Animate `opacity` and `transform` only. Progress bars may animate
  `transform: scaleX()`, not `width`.
- Every `@keyframes` needs a matching off-switch. The global block in
  `motion.css` handles it — don't write per-component reduce-motion rules.
- Two ambient (infinite) animations are sanctioned in the whole app: the pearl
  void drift and the Mira voice orb pulse. A third needs a decision, not a
  commit.

---

## Component vocabulary

Before adding a component, check whether one of these covers it. Most "new
component" drift is a card with different padding.

| pattern | fill | border | radius | shadow | notes |
|---|---|---|---|---|---|
| Card / panel | `--panel-fill` | `--panel-border` | `--radius-card` | `--shadow-2`, hover `--shadow-3` | the default container |
| Work surface | `--surface-2` | `--border` | `--radius` | none | code, editor, transcript body — always opaque |
| List row | transparent, hover `--surface-overlay` | bottom hairline only | 0 | none | never a card |
| Button (primary) | `--accent` | none | `--radius` | none | press = `translateY(1px)` |
| Button (bordered) | transparent | `--border`, hover `--accent` | `--radius` | none | |
| Input | `--surface-2` | `--border` | `--radius-input` | focus `--focus-ring` | label always associated |
| Chip / badge | `--*-dim` | matching `--*-dim` | `--radius-pill` | none | mono, `--text-xs`, `--tracking-wider` |
| Popover | `--panel-fill-raised` | `--panel-border` | `--radius` | `--shadow-4` | |
| Modal / overlay | `--panel-fill-raised` | `--panel-border` | `--radius-card` | `--shadow-5` | |

Type: `--font-sans` for anything a person reads in sentences; `--font-mono` for
eyebrows, badges, metadata, timestamps, code, numbers in tables. Never mono for
prose, never sans for an eyebrow.

---

## Self-audit before opening a PR

Run `./tools/check_style.sh` and paste the output into the PR description. Then
confirm in words:

- [ ] `check_style.sh` passes with zero violations.
- [ ] Every new `box-shadow` is a bare `var(--shadow-N)`.
- [ ] No new `linear-gradient` / `radial-gradient` outside the `--grad-*` tokens.
- [ ] No component selector appears inside a `[data-theme=…]` block.
- [ ] Screenshotted in **both** themes; the diff between them is colour and
      translucency only, never layout.
- [ ] Every animation stops under `[data-reduce-motion]` and OS reduced motion.
- [ ] Work surfaces (code, editor, transcript body) are opaque in both themes.
- [ ] Checked with `[data-high-contrast]` on: no glass, no blur, focus rings visible.
