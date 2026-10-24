# SETUP.md

macOS / Linux. Python 3.11+. Rustup for the Rust problems.

> **Self-hosters — local mode:** set `LIS_LOCAL_MODE=1` to run
> single-user with **auth disabled** (no Supabase/OAuth needed) — the app
> injects a fixed `local` user so every page just works. You still need a
> Postgres `DATABASE_URL` (a local Postgres is fine). As a safety
> interlock, `LIS_LOCAL_MODE` is *ignored* whenever `SUPABASE_JWT_SECRET`
> is set, so it can never disable auth on a real deployment. Leave it
> unset to run the full Supabase-auth setup below.

## Install

```sh
cd research-engineer-interview-prep

# Python venv + deps
python3 -m venv .venv
.venv/bin/pip install -e .
# Plus PyTorch + numpy for the ML problems. Either:
.venv/bin/pip install torch numpy
# ...or via the optional extra:
.venv/bin/pip install -e .[ml]

# Rust (optional; required for the Rust-write problems)
# https://rustup.rs/  -> default profile is fine
```

## Configure (environment)

The app reads config from the environment (loaded via `.env.local` if
present). Minimum to boot with data:

```sh
# Required: a Postgres connection string. Supabase's session pooler URL
# works; so does any local Postgres.
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Required for auth (Supabase project settings → API):
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_JWT_SECRET=<jwt secret>

# Optional — enables the LLM features (hints, review, mentor chat).
# Without it, those surfaces degrade gracefully to offline fallbacks.
ANTHROPIC_API_KEY=sk-ant-...
```

Migrations in `migrations_pg/` are applied idempotently at boot (set
`LIS_DISABLE_AUTO_MIGRATE=1` to skip). Set `LIS_ALLOWED_EMAILS` /
`LIS_ALLOWED_USER_IDS` to gate who can sign in.

## Run

```sh
.venv/bin/uvicorn app.main:app --port 8765
```

Open `http://127.0.0.1:8765/`. First start applies migrations and loads
all problems from `content/`; later starts do a cheap upsert-by-slug.

**Working on content or logic without a database?** `LIS_NO_DB=1` boots
the app against a strict no-DB sentinel (any query raises), which is what
the test suite uses — handy for validating that `content/` parses:

```sh
LIS_NO_DB=1 .venv/bin/python -c "import app.main"
```

## Reset state

State lives in Postgres, not a local file. To wipe attempts / review
state / sessions, truncate the relevant tables in your database (or drop
and recreate the schema and let the boot-time migrations rebuild it).
Problem content is reloaded from `content/` on every start, so it's never
lost by a reset.

## Tuning the scheduler

Edit `config.toml`, restart. The weights under `[scheduler]` control what
gets surfaced. The "why surfaced" expander on each problem card on the
home page shows the component breakdown.

## Adding a problem

Write a markdown file under `content/problems/<slug>.md`. Use any existing
problem as a template — `content/problems/f01-warmest-reading.md` is a
minimal example; `27-algo-validation-window.md` shows the full frontmatter.
Restart the server.

If the problem is Rust-write:
1. Set `rust_crate_dir: <name>` in the frontmatter.
2. Create `content/rust/<name>/` with a `Cargo.toml`, a placeholder
   `src/lib.rs`, and tests in `tests/integration.rs`.
3. The runner copies the crate to a tempdir on each submission and
   overwrites `src/lib.rs` with the submitted code.

## Troubleshooting

- **Redirected to `/login` on every page.** Either set `LIS_LOCAL_MODE=1`
  for single-user local mode, or (for the full auth setup) check the
  `SUPABASE_*` env vars are set and your email/user id is allowed.
- **`Hit the no-DB sentinel connection (LIS_NO_DB=1)`.** A real query ran
  under `LIS_NO_DB=1`. Provide `DATABASE_URL` and unset `LIS_NO_DB`.
- **Home is empty.** Check startup logs printed `[startup] loaded N
  problem files`. If N=0, inspect `content/problems/` for frontmatter
  syntax errors.
- **Rust submission says "cargo not found".** Install rustup; the runner
  shells out to `cargo` on your PATH.
- **Python submission fails with `ModuleNotFoundError: No module named
  'torch'`.** Install torch into the venv; the ML problems need it.
- **Page renders without styles.** Start uvicorn from the project
  directory — the static mount expects `static/css/` at the project root.
