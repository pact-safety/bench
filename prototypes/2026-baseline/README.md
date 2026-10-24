# 2026 baseline — UI/UX prototype set

**Question this prototype answers:** What should the bench feel like after the WS1 token layer lands but before we redesign IA + Today + grammar? Specifically, three structural decisions are in play and need a gut check before they propagate into ~30 templates:

- **Nav model** — palette-primary (Cmd+K is the discovery mechanism, visible nav is minimal) vs visible-rail (the current bench, every section visible up top) vs hybrid (3 grouped dropdowns + visible Cmd+K hint).
- **Density** — comfortable (default `--density: 1`) vs compact (`--density: 0.75` flips every density-aware component to tighter padding).
- **Today composition** — single-column relevant-now stack vs two-column primary+rail vs four-card grid.

## How to view

Static HTML. Run from the repo root:

```bash
python3 -m http.server 8765
```

Then open <http://localhost:8765/prototypes/2026-baseline/>. The pages pull the real `static/css/tokens.css` + `static/css/main.css`, so what you see is what the live app would look like with the proposed structural change.

## Surfaces

Three pages exercise the full system:

| Surface | What it tests |
|---|---|
| `today.html` | Dashboard density, day-navigation header, sectioned content stack |
| `problem.html` | Interactive HTMX swap (mocked), code blocks, badges, phase-based layout |
| `writings.html` | Prose surface in the `container--narrow` (720px) case |

Each page renders all three variants and switches between them via a `?variant=A|B|C` URL param. A floating bar at the bottom lets you flip without reloading.

## The variants (same across all three surfaces)

| Variant | Nav model | Density | Today composition |
|---|---|---|---|
| **A** | Palette-primary | Comfortable | Single-column relevant-now |
| **B** | Visible-rail (current) | Comfortable | Two-column primary + rail |
| **C** | Hybrid (3 grouped dropdowns + ⌘K hint) | Compact | Four-card grid |

Variants vary *structure*, not accent color. The amber is the same in all three. The dark surface is the same in all three. What's different is where things are and how dense they are.

## Decisions to capture

After picking, write the verdict here and the rationale in the next PR's body:

- **Nav model chosen:** _(fill in)_
- **Density chosen:** _(fill in)_
- **Today composition chosen:** _(fill in)_
- **Bits stolen from non-winning variants:** _(fill in)_

When the decisions are absorbed into the real templates, delete this directory. Prototypes are throwaway by design.
