# Contributing

Thanks for taking a look. A few things to know before you open an issue
or a pull request.

## How this repository works

This project is alpha-stage software with a single maintainer. Expect
rough edges, and expect things to change without much notice.

This public repository is a periodic export of a private development
repository. History is not carried over, and nobody develops directly
in this repo. If your pull request is accepted, the change is applied
in the private repository and shows up here in the next export. That
means your PR will be closed rather than merged, even when the change
is accepted.

Issues are welcome, and so are small, focused pull requests. If you're
planning something bigger, open an issue first so we can agree on the
approach before you spend time on it.

To report a security problem, follow [SECURITY.md](SECURITY.md). Please
don't open a public issue for it.

## Local setup

You need Python 3.11 or newer and a Postgres database. A Supabase
project or a plain local Postgres both work.

```sh
./scripts/setup.sh
```

The script checks your Python version and copies `.env.example` to
`.env` if you don't already have one. It installs dependencies with
`uv` if available, falling back to a `.venv` with pip. If
`DATABASE_URL` is set, it also applies the database migrations.
Otherwise, set `DATABASE_URL` in `.env` and run
`python scripts/apply_migrations.py` yourself.

To run the app locally without setting up GitHub OAuth:

```sh
DATABASE_URL=postgresql://... LIS_LOCAL_MODE=1 .venv/bin/uvicorn app.main:app --port 8765
```

Then open http://127.0.0.1:8765/. `LIS_LOCAL_MODE=1` bypasses sign-in
for single-user local use. `ANTHROPIC_API_KEY` is optional. Without it,
the LLM-backed features fall back to offline responses. See
[SETUP.md](SETUP.md) for the full environment setup (Supabase, auth,
API keys).

## Tests

Install the dev extra, then run the unit tests:

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/unit/
```

The unit tests take about a second and need no database or network.
When `DATABASE_URL` is empty, the test setup switches to a no-DB mode,
and the Anthropic client is replaced with a fake. `scripts/test.sh`
wraps the same command. `scripts/test.sh --integration` also runs the
integration tests, which need a real `DATABASE_URL` and will make real
API calls.

When fixing a bug, please write a failing test first, then the fix.

## Conventions

- **No SPA, no build step for the core app.** The frontend is
  server-rendered Jinja2 templates with HTMX and small amounts of
  inline vanilla JavaScript. Don't add a frontend framework or a CSS
  framework.
- **Visual values come from design tokens.** Colors, spacing, font
  sizes, radii, shadows, and motion values are defined once, in the
  `:root` block of `static/css/main.css` and in
  `static/css/tokens.css`. Use an existing token, or add one there,
  instead of writing a literal hex code or pixel value in a component.
  `docs/architecture/tokens.md` is the reference.
- **Reuse shared components.** Cards, lists, forms, buttons, status
  slots, and badges already have shared classes. Extend those rather
  than writing a one-off variant for a single page.
- **Accessibility must not regress.** The `<html>` element carries
  `data-reduce-motion`, `data-larger-text`, and `data-high-contrast`
  from the user's settings. New or restyled components must respond to
  all three. Also respect the OS-level `prefers-reduced-motion`, give
  every form input a `<label>`, keep focus rings visible, and use ARIA
  live regions for content that updates asynchronously (HTMX swaps and
  similar).
- **Comments explain why, not what.** Many existing comments record
  design decisions. Keep them intact when you refactor.
- **Match the surrounding code.** New routes should look like their
  sibling routes, and new repository classes should follow the shape of
  the existing ones in `app/repositories/`.
- **LLM calls respect per-user spend caps.** If you add a feature that
  calls a model, follow the pattern in the existing services: call
  `over_cap_for` from `app/services/spend_cap.py` before the request,
  call `record_usage_for` after it, and return the offline fallback
  when the cap is hit.

## License

By contributing, you agree that your contributions are licensed under
the [MIT License](LICENSE).
