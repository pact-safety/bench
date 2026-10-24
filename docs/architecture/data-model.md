# Data model

20-table Postgres schema in `migrations_pg/001_consolidated.sql`. UUID `user_id` everywhere, foreign-keyed to Supabase's `auth.users`. JSONB for free-form fields. The 2025 migration from SQLite was the project's biggest single change; the resulting schema is intentionally boring.

## Region and latency

The Supabase project lives in `aws-ap-southeast-1` (Singapore) to minimize round-trip from Chiang Mai. Earlier hosting in `us-east-1` (Virginia) was ~250ms RTT vs Singapore's ~50ms — a 5× speedup on every Postgres call. If you're hosting somewhere else, pick the region closest to you and update `.env.local`'s `DATABASE_URL`.

## Identity

- `auth.users` is Supabase-managed; you don't migrate it.
- `public.users` mirrors `auth.users.id` (UUID PK) and adds:
  - `settings_json` (JSONB) — the free-form bag for everything that doesn't deserve its own table (display_name, email, tz, a11y flags, preferred_voice, active_jd_id, onboarding_skipped, iac_profile)
  - Auto-populated by an `on_auth_user_created` trigger when GitHub OAuth creates the auth.users row.

## Core entity tables

| Table | What it stores |
|---|---|
| `problems` | Authored problems. Title, prompt, difficulty, type, EM mode, content_md, ref solution, test code, key insight, pitfalls. |
| `content_items` | Curated + user-added readings/videos/exercises. `kind`, `axes` (JSONB list), `source_kind` ('curated' or 'user'), `created_by_user_id` for external ones. |
| `attempts` | Practice submissions. Per-phase notes, final code, hints_used (JSONB), test_passed, confidence, time_per_phase. |
| `attempt_reviews` | LLM reviews of attempts. summary_md, per_phase (JSONB), overall_score, rubric_signals, voice_key. |
| `content_progress` | One row per (user_id, content_id). status, checked_at, rating, favorited, notes_md. |
| `review_state` | Per-(user, problem) recall scoring used by the scheduler. |
| `sessions` | Daily session aggregates. |
| `assessment_runs` + `assessment_responses` | The 12-question quiz state. |
| `jds` | Job descriptions. axis_weights (JSONB), signal_tags (JSONB), summary, iac_profile, iac_evidence_md, iac_fit_md. |
| `writings` | Drafts + published pieces. |
| `feedback` | The in-app feedback widget's persistent log. |
| `credentials` + `credential_assessments` | CV uploads + parses. |
| `reflections` | Hamming-mode generated prompt sets + the user's replies. |

## JSONB conventions

JSONB is the right call when:

- The shape is user-controlled (`settings_json`)
- The shape is small but variable (`hints_used = {"explore": 1, "plan": 2}`)
- The shape is a parsed-document result (`jds.axis_weights`, `jds.iac_profile`, `attempt_reviews.per_phase`)

Helpers in `app/repositories/_pg.py`:

- `jsonb(d)` → JSON-encodes a Python dict for parameter binding
- `uuid_str(value)` → coerces UUIDs to strings in dict_row results
- `naive_utc(dt)` → strips tzinfo from Postgres tz-aware timestamps so they compare to `datetime.utcnow()`

## Indexes

`migrations_pg/001_consolidated.sql` ships indexes on the high-traffic queries:

- `content_progress(user_id, checked_at)` — for "what did you finish today"
- `attempts(user_id, started_at)` — for the scheduler + reflect window
- `feedback(user_id, created_at DESC)` — for the inbox
- `attempts(problem_id)` — for the recall scoring lookup

## Content hash optimization

`content_items.content_hash` (added in `migrations_pg/002_content_hashes.sql`) — a `TEXT` column that stores a hash of the canonical content. The startup loader (`app/content_loader.py`) reads `content_repo.hashes_by_slug()` to skip unchanged TOML files. Restarts go from ~70s (full reload) to ~1s (no markdown changed).

## See also

- [Code tour](code-tour.md)
- [Setup](../development/setup.md)
