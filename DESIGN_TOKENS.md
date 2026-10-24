# DESIGN_TOKENS.md

Tokens extracted from the live `libearden.dev` stylesheet (`/css/main.css`)
on 2026-05-12. The portfolio uses CSS custom properties scoped to `:root`
and `:root[dark]`. We adopt the same names where it makes sense, drop ones
this app does not need (badges, blog cards, footer widgets), and add a
small monospace track that the portfolio does not need but a code-drill
app does.

## Color — light (default)

| Token | Value | Role |
|---|---|---|
| `--brand-color` | `#533feb` | Primary action, link-hover, focus ring |
| `--accent-color` | `#00c8ff` | Secondary accent, tag highlights |
| `--background-color` | `#ffffff` | Page background |
| `--surface-color` | `#f7f8fc` | Card / section background |
| `--text-color` | `#1e2740` | Body text |
| `--text-alt-color` | `#6a6d76` | Muted text |
| `--heading-color` | `#1e2740` | Headings |
| `--border-color` | `#f0f0f0` | Card borders, hairlines |
| `--code-bg` | `#f3f3f3` | Inline code, pre |

## Color — dark (`:root[dark]`)

| Token | Value | Role |
|---|---|---|
| `--brand-color` | `#533feb` | Same — brand is theme-invariant |
| `--accent-color` | `#00c8ff` | Same |
| `--background-color` | `#0c101a` | Page background |
| `--background-alt-color` | `#080b12` | Footer / section alt |
| `--surface-color` | `#111520` | Card / section background |
| `--text-color` | `#9a9eab` | Body text |
| `--text-alt-color` | `#848690` | Muted text |
| `--heading-color` | `#f0f0f0` | Headings |
| `--border-color` | `#252629` | Card borders, hairlines |
| `--code-bg` | `#080b12` | Inline code, pre |

## Typography

- Body font stack: `"Work Sans", "Helvetica Neue", Helvetica, Arial, sans-serif`
- Monospace stack: `"JetBrains Mono", "SF Mono", Menlo, Consolas, monospace`
  (Work Sans does not ship a mono; portfolio uses generic `monospace` for
  `<pre>`. We add a richer mono stack because this app shows code by default.)
- Weights used: 400 (body), 500 (UI), 700 (headings)
- Body line-height: `1.6`
- Heading line-height: `1.2`
- Base size: `16px`; scale by 1.25 (modular)
  - `--font-size-sm: 0.875rem` (14px)
  - `--font-size-base: 1rem` (16px)
  - `--font-size-md: 1.125rem` (18px)
  - `--font-size-lg: 1.5rem` (24px)
  - `--font-size-xl: 2rem` (32px)

## Layout

- Container max-width: `1080px` (matches portfolio); narrows to `740px`
  on tablet (≤ 1024px).
- Horizontal page padding: `20px`.
- Card padding: `24px`.
- Section vertical rhythm: `48px` between major blocks.
- Radius: `8px` for cards, `6px` for buttons and inputs.

## Spacing scale

`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`,
`--space-5: 24px`, `--space-6: 32px`, `--space-7: 48px`, `--space-8: 64px`.

## Aesthetic notes

- Light/dark toggle on the portfolio respects `prefers-color-scheme` and
  persists in `localStorage` as `theme = "dark" | "light"`. We do the same.
- The portfolio is dense-but-airy: generous line-height, narrow content
  column, minimal chrome. We emulate that — no dashboards, no progress
  panels.
- Brand purple `#533feb` is the only loud color. Use it for the primary
  action (start session, submit, run tests) and the link-hover state.
  Avoid using it for backgrounds — the portfolio doesn't, and it gets
  shouty quickly.
- Cards have a hairline border (`--border-color`) rather than shadow.
  The portfolio uses a single 1px border instead of elevation; matches.

## Departures from the portfolio

1. **Monospace stack** — portfolio's generic `monospace, monospace` is
   fine for incidental code; this app spends its life inside `<pre>`,
   so a richer stack with JetBrains Mono / SF Mono is worth it.
2. **No hero gradient or particle background** — the portfolio's
   `.hero__bg` aside is decorative. The drill app's home view is a work
   surface, not a marketing page.
3. **No web font load** — portfolio pulls Work Sans from Google Fonts.
   Local-first app, sub-2s cold open: we declare Work Sans in the stack
   but do not block on a remote fetch. If the user has it installed
   (macOS doesn't by default), it renders; otherwise the system
   sans-serif fallback wins. Tradeoff: the visual match is approximate
   on a fresh machine, exact for users with Work Sans installed.
