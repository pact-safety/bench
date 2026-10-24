# Templates and frontend

Server-rendered Jinja2 + HTMX. No SPA, no client-side state library. The whole frontend is ~30 templates + one ~3000-line CSS file + a small set of `<script>` blocks inline in the templates that need them.

## Templates

`templates/` is flat. Convention:

| File | Surface |
|---|---|
| `base.html` | Layout, nav, theme toggle, feedback widget |
| `home.html` | `/` Today page |
| `problem.html` | `/problem/<slug>` |
| `content.html` | `/content/<slug>` |
| `content_new.html` | `/library/add` form |
| `readiness.html` | `/readiness` |
| `voices.html` | `/voices` roster |
| `skills.html` | `/skills` per-axis breakdown |
| `library.html` | `/library` catalog |
| `settings.html` | `/settings` |
| `settings_reset.html` | `/settings/reset` confirmation |
| `jd_*.html` / `jds_index.html` | JD CRUD |
| `assess_*.html` | Assessment quiz |
| `credentials_*.html` | CV upload + review |
| `reflect.html` / `reflect_detail.html` | Reflect surface |
| `feedback_inbox.html` | `/feedback/inbox` |
| `writings*.html` | Writing CRUD |
| `_skill_chart.html` | Pentagon SVG include |

`base.html` defines:

- `{% block title %}` — overridden per page for the browser tab
- `{% block main_class %}` — empty default; per-page can set `container--narrow` (760px) for prose-heavy pages
- `{% block body %}` — page content

## Custom Jinja filters

Registered in `app/main.py`:

| Filter | Purpose |
|---|---|
| `markdown` | Mistune render of body text |
| `code` | Pygments-rendered code block |
| `pentagon_geometry` | Computes SVG coordinates for the skills pentagon |
| `jd_title` | Detects URL-shaped JD titles + derives a clean title (heals legacy data at render time) |

## CSS architecture

`static/css/main.css` is a single ~3000-line file. Organized by section:

- Custom properties (colors, spacing, typography) at the top
- A11y data-attribute overrides
- Typography, links, base
- Container, header, nav
- Component blocks (BEM-ish: `.next-action__title`, `.daily-progress__seg`, etc.)
- Per-surface blocks
- Media queries at the bottom

Theming is two CSS variable scopes: `:root` (light) and `:root[data-theme="dark"]` (dark). Dark mode is the platform default; the toggle persists to `localStorage["theme"]` + a brief inline script in `<head>` sets `data-theme="dark"` before paint to avoid flash.

## HTMX patterns

The platform uses HTMX for:

- Feedback widget POSTs (`hx-post="/feedback"`)
- `/hint/<slug>` per-phase hint fetches (swap into per-phase slots)
- `/submit/<slug>` problem submission (swap result into `#result`)

HTMX-specific behaviors layered on top:

- `htmx:confirm` → `run_tests` resubmit guard
- `htmx:configRequest` → re-sync feedback widget theme metadata at submit time
- `htmx:afterRequest` → success/failure rendering in the feedback widget

## Accessibility

- Three a11y toggles (reduce-motion, larger-text, high-contrast) drive `data-*` attributes on `<html>` set in `base.html` from `users.settings_json.a11y`.
- OS-level `prefers-reduced-motion` media query also respected.
- All form inputs have associated `<label>` elements.
- Focus rings: thicker + brand-color outline when high-contrast is on.
- ARIA live regions for hint slots and feedback widget status.

## See also

- [Code tour](code-tour.md)
- [Services](services.md)
