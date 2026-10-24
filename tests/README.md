# tests/

Two-tier test harness. Runs cheap by default so the agent can verify after every change.

## Tier 1 — unit (`tests/unit/`)

Pure-function tests. No DB, no network. The Anthropic SDK is mocked once in `conftest.py` so every LLM-touching service (hints, review, hamming, jds) is testable without burning real credits.

**Run all unit tests:** `./scripts/test.sh` — ~0.5s, 67 tests today

What's covered:
- `test_hints.py` — claude_hint shape (would have caught the `prompt_md` typo), tier escalation, fallback paths
- `test_scheduler.py` — Scorer components, `easy_first_bias` when no assessment
- `test_daily_flow.py` — priority order on Today's hero card
- `test_jds.py` — URL detection, HTML stripping, og:title heuristics, Greenhouse pattern
- `test_review.py` — Claude-graded attempt review, interview-mode rubric prompt
- `test_hamming.py` — weekly reflection generator + axis pass-rate aggregation
- `test_env.py` — .env loader (empty-value handling that bit us earlier)
- `test_auth.py` — PKCE primitives, JWT payload extraction

## Tier 2 — integration (`tests/integration/`)

Live `TestClient` against real Postgres. **Auto-skipped if `DATABASE_URL` isn't set.**

**Run unit + integration:** `./scripts/test.sh --integration` — ~5s when configured

Today covers:
- Unauthenticated `/` → 303 to `/login`
- `/login` renders
- `/auth/callback` without code → redirects with error
- `/static/*` serves
- `/auth/signin/github` redirects to Supabase with PKCE params + sets verifier cookie

Phase 5 will add a test-user fixture (`is_test=true` rows in `public.users`) so signed-in route tests stop being limited by the synthetic-JWT approach.

## When to run which

| What you did | Run |
|---|---|
| Touched a service / repo / model | `./scripts/test.sh` |
| Touched a route or template | `./scripts/test.sh` then sanity-check by browser |
| About to commit / ship | `./scripts/test.sh --integration` |
| Diagnosing a failing test | `./scripts/test.sh -v tests/unit/test_<name>.py::test_<one>` |

## Adding a test

Mirror `tests/unit/test_hints.py` for the pattern:
- Use the `mock_anthropic` fixture for any LLM-touching code
- Use `sample_problem` / `sample_attempt` fixtures for realistic dataclasses
- Keep each test under ~20 lines; one assertion focus per test
