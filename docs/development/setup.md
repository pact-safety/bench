# Setup and tests

For working on the platform itself.

## Local setup

```bash
git clone https://github.com/pact-safety/bench.git
cd bench
python -m venv .venv
.venv/bin/pip install -e ".[ml,dev,docs]"
```

You'll need:

- Python ≥ 3.11
- Anthropic API key (set `ANTHROPIC_API_KEY` in your shell rc)
- A Supabase project (for Postgres + auth via GitHub OAuth). See `.env.example`.

## Running the app

```bash
.venv/bin/uvicorn app.main:app --port 8765
```

Hot-reload is OFF by default (Jinja2 templates already auto-reload; Python changes require restart).

## Running tests

Two tiers.

**Unit** — no DB, no network. Run on every save.

```bash
.venv/bin/pytest tests/unit/
```

Speed: ~1.3s for 134 tests. The `mock_anthropic` fixture (in `tests/conftest.py`) replaces the Anthropic client with a programmable fake, so every LLM-touching service is unit-testable.

**Integration** — touches real Postgres + real Anthropic (if `ANTHROPIC_API_KEY` is set). Opt-in.

```bash
.venv/bin/pytest -m integration
```

Speed: ~90s for ~15 tests. Uses real test users created via the Supabase Admin API (see `tests/integration/_helpers.py`).

## Schema migrations

`migrations_pg/*.sql` — applied via `scripts/init_supabase_schema.py`. Idempotent; safe to re-run.

Adding a migration:

```bash
# Create the SQL file
echo "-- 003_add_thing.sql" > migrations_pg/003_add_thing.sql

# Apply
.venv/bin/python scripts/init_supabase_schema.py
```

## Docs site

```bash
.venv/bin/mkdocs serve            # preview at http://127.0.0.1:8000/
.venv/bin/mkdocs build            # static site to ./site/
```

The site mirrors what you're reading now. `mkdocs.yml` controls the nav + theme; `docs/` is the source.

## Common dev paths

| What you want to do | Where to look |
|---|---|
| Add a new endpoint | `app/main.py` (sectioned by surface) |
| Add a new entity / table | `migrations_pg/00X_*.sql` + `app/models.py` + `app/repositories/<entity>_repository.py` |
| Add a new LLM call | New file in `app/services/` matching the pattern in `hints.py` / `review.py` (Claude path + fallback) |
| Add a new template | `templates/<name>.html` extending `base.html` |
| Add a Jinja filter | `app/main.py` — register on `templates.env.filters` |
| Add a CSS rule | `static/css/main.css` (single-file by design; section it logically) |

## Branch / PR conventions

- Branch names: `lis-<N>-<short-descriptor>`
- PR title: `<scope>: <one-line summary> (LIS-<N>)`
- PR body: summary + test plan + tracking link to Linear
- Each PR maps 1:1 to a Linear issue when possible; bundle 3+ tiny fixes if they touch independent files
- Commit messages explain *why*, not just *what* — the code says what

## See also

- [Common tasks](common-tasks.md)
- [Contributing](contributing.md)
