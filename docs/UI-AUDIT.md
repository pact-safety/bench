# UI audit — hyperbolic theme, 2026-08-10

Twelve defects found by reading seventeen screenshots of the running app.
Each entry: what's wrong, the evidence, the law it breaks (see
`STYLEGUIDE.md`), and the fix. Fixes are implemented in
`static/css/hyperbolic-fixes.css` — land that file, then work this list to
confirm each one is actually resolved in the browser.

Ordered by leverage. The first three account for most of what makes the
theme look unfinished.

---

## D1 — Native controls are painted in dark mode  ★ root cause of 3 defects

**Evidence.** `/content/new`: every axis checkbox renders as a solid black
square. `/connecting/{id}`: the date input renders as a near-black fill with
white text, on a white card. `/mira`: the transcript scrollbar is a solid
black bar down the middle of the page.

**Cause.** The dark default sets `color-scheme: dark` (or inherits it), and
the hyperbolic scope never overrides it. The browser therefore paints every
UA-drawn control — checkbox, radio, date picker, scrollbar, select arrow —
with its dark-mode palette, regardless of your CSS.

**Fix.** One declaration in the theme scope:
`color-scheme: light; accent-color: var(--accent);`
This is a token-level fix, so it belongs in the theme block and violates
nothing. Verify all three surfaces after landing it.

---

## D2 — The header has its own gradient, and it doesn't match the void

**Evidence.** Every screenshot. The nav bar runs a horizontal pink → mint
gradient; the page below runs the pearl-void radials. They meet at a hard
horizontal seam about 100px down, visible across the full width.

**Law broken.** Law 3 — the only sanctioned gradients are the `--grad-*`
tokens and the pearl-void backdrop. The header gradient is neither.

**Fix.** The header is chrome sitting *in front of* the void: give it
`--panel-fill-recessed` plus `backdrop-filter`, no gradient of its own. The
void then reads continuously behind it and the seam disappears.

---

## D3 — Content sits directly on the raw gradient

**Evidence.** `/content/new`, `/connecting`, `/focus`, `/news`, `/writings`:
body copy, labels, and form fields sit on the void with no surface beneath
them. On `/content/new` the right third of the page is an unbroken peach
wash with nothing on it, while the form's left edge sits over the lavender
band — so identical inputs read as different colours depending on where
they land on the page.

**Law broken.** Law 3's "never behind text", and the glass hierarchy: the
void is *atmosphere*, panels are what content sits on.

**Fix, in two parts.**
1. Add a scrim to the void stack — a `rgba(255,255,255,0.55)` layer over the
   radials, so even bare text has an even field behind it. The iridescence
   survives; the saturation stops competing with type.
2. Give the page's main column a glass panel (`--panel-fill` +
   `--panel-blur` + `--panel-border` + `--shadow-2`). Content should never be
   a direct child of the void.

---

## D4 — Form fields are translucent, so they tint with the background

**Evidence.** `/content/new`: the Title, Duration, and Notes fields render as
pale lavender/pink washes that shift hue across the page. The Notes textarea
is visibly pinker than the Title input above it.

**Law broken.** The legibility carve-out — work surfaces stay opaque.
An input the user types into is a work surface.

**Fix.** `--input-bg: var(--surface)` — opaque white — in the theme scope.
Inputs keep the pale border and the 14px radius; they stop being windows.

---

## D5 — The dark theme's amber leaks into the active nav underline

**Evidence.** Every screenshot: the active nav item (Today / Connect /
Ingest) carries an **orange-amber** underline while every other accented
element on the page — links, buttons, eyebrows, the wordmark — is magenta.

**Cause.** A hardcoded amber, or a rule referencing the dark accent
directly rather than `var(--accent)`.

**Fix.** `var(--accent)`. The style gate's hex check catches this class of
bug once it runs.

---

## D6 — The "+ New conversation" button is a gold gradient

**Evidence.** `/mira`, conversation rail. A gold → orange gradient fill on
the primary button of a magenta-accent page. It is the only gold element in
the entire app.

**Law broken.** Law 3 (unsanctioned gradient) and, separately, accent
consistency.

**Fix.** Solid `var(--accent)`, matching every other primary button
("Log it", "Activate", "Save draft", "Generate this week's prompts").

---

## D7 — The Mira transcript is clipped and overlaps the composer

**Evidence.** `/mira`: the last visible line — "distinguishes this from the
obvious alternative?" — is cut horizontally mid-glyph, with the composer
box drawn over it. The scroll container's height doesn't resolve against
its parent.

**Cause.** Classic flex/grid overflow: a scrollable child inside a flex
column needs `min-height: 0` (or `min-block-size: 0`) or it refuses to
shrink and spills under its sibling.

**Fix.** `min-height: 0` on the transcript's flex parent, `overflow-y: auto`
on the transcript, and let the composer be a fixed-height sibling. Also
`scroll-padding-block-end` so the newest turn isn't tucked under the
composer's shadow.

---

## D8 — The content column is not centred

**Evidence.** `/content/new` at a ~1650px viewport: content spans roughly
x=418 to x=1138, centre ≈778, while the viewport centre is ≈880. About
100px left of centre. Same on `/library` and `/news`.

**Cause.** A max-width container without `margin-inline: auto`, or an
asymmetric padding that only compensates for a scrollbar on one side.

**Fix.** `margin-inline: auto` on the container and `scrollbar-gutter:
stable both-edges` on the scroll root, so the layout doesn't shift when a
scrollbar appears.

---

## D9 — Pages with little content are 70% empty gradient

**Evidence.** `/focus` (one initiative row), `/connecting` (one contact),
`/writings` (one draft). Content occupies the top quarter; the rest is
wallpaper.

**Not a bug in the theme** — it's what an empty state looks like when the
theme is loud. Two fixes, both cheap: the scrim in D3 calms the empty
region, and these routes need real empty-state content (what this page is
for, what to do first) rather than a bare list with one row.

---

## D10 — Card borders are inconsistent

**Evidence.** `/aim`: the "Where you stand" card has a **magenta** 1px
border. Every other card in the app has the pale lavender hairline. Nothing
about that card is selected or in an error state.

**Fix.** `var(--panel-border)`. Accent borders mean "selected" or
"highlighted" — if the card is meant to be featured, it should say so with a
shadow step, not by borrowing the selection colour.

---

## D11 — Two different card radii on the same page

**Evidence.** `/mira`: the conversation rail's active item and the panels
use ~14px; the outer panels use ~20px; the tab strip's chips are pills. On
`/library` the content rows are square-cornered while their container is
20px.

**Fix.** `--radius-card` (20px) for panels, `--radius` (14px) for controls
and inner blocks, `--radius-pill` for chips and badges. No third value.

---

## D12 — "SOON" badges read as active tabs

**Evidence.** `/mira` sub-nav: "KB SOON" and "Voice SOON" sit at the same
visual weight as Chat / Agenda / Memory / Evals, so they look clickable.

**Fix.** Disabled treatment on the parent tab — `--text-faint`,
`cursor: not-allowed`, `aria-disabled="true"` — with the badge in
`--surface-2`. A user should be able to tell what's live without clicking.

---

## Verifying the fix

Screenshot these five routes in the hyperbolic theme, before and after:
`/mira`, `/content/new`, `/aim`, `/connecting/{id}`, `/focus`. Then flip to
the dark theme and screenshot the same five — the dark theme must be
**pixel-identical to its current state**, since every fix here is either a
token redefinition inside the hyperbolic scope or a layout bug that was
wrong in both themes (D7, D8).
