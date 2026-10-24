# SPEC.md

This document captures interpretation and design decisions made while
building v1. It complements the original brief — does not duplicate it.
Read the brief first.

## Scope as built

- 31 core problems (18 ML coding + ring buffer = 19, 8 debug, 4 algo).
  The brief enumerated 18 ML coding problems and separately requested
  "exactly 2 Rust-write problems in the core set." The 18 enumerated
  items include the greedy tokenizer (Rust-write). Adding the suggested
  ring-buffer KV-cache problem as a second Rust-write took the count to
  31; rather than drop a listed ML item, I logged the +1 overshoot in
  EXPERIMENT_LOG.md.
- 12 warmups (8 Python, 4 Rust). At the upper end of the 10–12 band.
- FastAPI + Jinja2 + HTMX + SQLite. No SPA, no build step, no Docker.
- Single implicit user with id=1; no auth.
- Schema hooks for v1.5 (sources, notes) — tables exist, repository
  classes exist with `NotImplementedError`, no UI.

## Data model decisions

- **SQLite with raw SQL via repositories.** Migration files numbered.
  No ORM. Migration runner tracks applied files in
  `schema_migrations`. Postgres port is mechanical: replace `sqlite3`
  driver, change `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL`,
  keep JSON-as-TEXT (Postgres has native JSON but TEXT works).
- **Problem content is markdown + frontmatter in `content/problems/`
  and `content/warmups/`.** Loaded into the DB on startup via upsert.
  DB is for *user state* (attempts, review_state). Problems are for
  git: versioning, diffing, blame all work.
- **`problem_revisions` table** retained from the brief for the future
  case where editing a problem invalidates prior attempts. Not written
  to in v1.
- **`is_warmup` column on `problems`** with an index. The scheduler
  query is `WHERE is_warmup = 0`. Keeps warmups invisible to scheduling
  without a separate table.
- **No `attempt.events` table** for fine-grained edit timestamps. The
  brief mentions `time_to_first_edit_seconds` and `edit_count`; in v1
  these are recorded only as totals on the attempt row, defaulting to
  null/zero. Wire the JS later if you want them.

## Scheduling decisions

- **Weighted scheduler, not SM-2.** SM-2's 1-day → 6-day → 14-day
  exponential intervals don't map to 30-60 minute drills at 1-3/day.
- **Six explicit weights in `config.toml`:** `days_since`,
  `low_confidence`, `over_time`, `used_reference`, `topic_gap`,
  `never_attempted`. All summed linearly. Tunable without code change.
- **Default weights chosen so:** a never-attempted problem outranks a
  recently-aced one but loses to a 3-weeks-stale lapsed one. The
  `never_attempted` weight (2.5) is the largest because cold problems
  are how you find the gaps.
- **Two constraints** applied during selection: at most one 60-min
  problem per session; surfaced set spans ≥ 2 of {ml_coding, debug,
  algo} when feasible. The span constraint is enforced lazily — only on
  the *last* slot, only if the higher-scoring candidate would leave
  the set single-category and an alternative exists.
- **`SessionStrategy` is an ABC.** Only `ReviewStrategy` is
  implemented. Stubs for `JDFocusedStrategy`, `ReadingStrategy`,
  `MixedStrategy` would slot in without rewriting the scheduler.

## Warmup separation

- **Warmups never enter the scheduled session.** They surface only via
  the explicit "warmup" link on the home page.
- **Warmup attempts are recorded** (history, future analytics) but
  excluded from `review_state` and from `due_score` calculation.
- **Pick algorithm:** least-recently-attempted warmup not seen in
  `warmup.recency_floor_days` (default 3); fallback to overall LRU if
  every warmup is within the floor.
- **Why this matters:** if warmups auto-surfaced, they would dominate
  daily time spent (they are short, easy, satisfying). The brief
  called this out as a procrastination surface. Opt-in click is the
  whole point.

## Test execution

- **Python runner:** subprocess-based, writes the submission +
  appended test code to a tempfile, runs with the server's Python
  interpreter, wall-clock-limited by `runner.python_timeout_seconds`.
  Torch is expected in the user's local environment.
- **Rust runner:** copies the per-problem crate template
  (`content/rust/<slug>/`) to a tempdir, overwrites `src/lib.rs` with
  the submission, runs `cargo test --quiet`. First run pays cargo
  compile time; subsequent runs hit cargo's local cache.
- **No sandboxing.** This is a local single-user app. The user is
  running their own code against their own machine. If multi-user is
  ever needed (v2+), the runner is the natural seam to insert
  isolation (Docker, gVisor, etc.).

## UI decisions

- **HTMX over SPA.** Submission posts via HTMX, swaps the result into
  a `#result` div. No client state, no JSON API.
- **Textarea editor by default.** CodeMirror 6 is feature-flagged off
  in `config.toml`. Tradeoff: textarea has zero load time, no syntax
  highlight, no autoindent beyond a 4-space tab handler. Most
  ML-coding answers are ~30 lines; the gain from a real editor is
  smaller than the cold-open cost of bundling CodeMirror. Re-evaluate
  after a week of textarea use.
- **No splash, no animations, no streaks, no badges.** The brief was
  explicit. The home view is: today's session, a small warmup link, a
  recent-attempts list. Nothing else.
- **`pre.md` for prompts.** Wrap-preserving but font-styled — preserves
  intent while keeping the visual line with the surrounding sans body.
  A real markdown renderer (mistune, markdown-it) is a v1.5 add if
  prompts ever contain inline code or links that matter visually.
- **Theme toggle** matches portfolio behavior: persists in localStorage,
  respects `prefers-color-scheme` on first load. Implemented via
  `data-theme="dark"` on `<html>`.

## Design tokens

See DESIGN_TOKENS.md. Tokens were extracted directly from the live
portfolio CSS at `https://libearden.dev/css/main.css`. The match is
close but not pixel-identical:

- **Match (tight):** color palette, dark/light parity, border-not-shadow
  card style, container max-width, typography scale.
- **Approximate:** font rendering — the portfolio loads Work Sans from
  Google Fonts; the app does not block on a remote fetch, so users
  without Work Sans installed get the next stack entry. Pragmatic
  tradeoff for sub-2s cold open.
- **Departures:** a richer monospace stack for code blocks (portfolio
  uses generic `monospace`); no `.hero` decorative background.

## Out of scope — confirmations

The brief listed exclusions; reaffirming the most likely "easy adds"
that were *not* built:

- LLM-graded review of submissions
- JD parsing or JD-aware ranking
- Reading-mode UI for the reserved `paper_*` problem_type values
- Streaks, badges, points
- Problem authoring UI (problems are edited as markdown in git)
- Multi-user
- API endpoints for clients that don't exist
- Application deadline tracker

## What v1.5 will likely want first

Based on what's reserved and what would compound the existing surface:

1. **Notes attached to attempts.** The `notes` table is reserved.
   Adding "post-attempt notes" gives the user a place to capture "I
   forgot X" — which then feeds back into prompt content as paper-aware
   prep evolves.
2. **`sources` ingestion** for paper-of-the-week style problems. The
   `paper_summary`/`paper_response` problem_type values are reserved.
   The data model already supports this; UI is the work.
3. **Confidence-weighted topic gap.** Currently a tag is "fresh" if
   *any* problem with it was attempted in 14 days. Better: fresh if
   you nailed it; stale if you lapsed.
4. **Per-attempt event log** (edit timestamps, paste detection). Would
   surface "you looked at the solution after 30 seconds" as a signal.

## What v2 will want

- LLM-graded solution review (judge model + rubric).
- JD ingestion → competency mapping → adaptive session.
- Mock interview mode with a time limit and no aux panels.
- Multi-user (the data model is ready; auth and isolation are the
  work).
