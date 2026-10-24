# Proposal: regression-testing coverage gaps

**Status:** draft — operator review needed

**Date:** 2026-05-25

**Triggered by:** validation walkthrough §9 — _"please scaffold robust regression testing for coverage"_

## Why this exists

The unit test suite is healthy (538 passing as of the 2026-05-25 push), but several regressions still made it to the operator in the past two weeks:

| Date | Bug | What slipped through |
|---|---|---|
| 2026-05-25 | Saturday pregen emitted a "complete no-show" reflection on a zero-attempt week | Activity-window logic was unit-tested for 30-day skip, but no test covered "active in 30d, quiet in 7d" |
| 2026-05-25 | `anthropic-fellows` + `generator-residency` showed as active on `/focus` despite being rejected ~30 days earlier | No content lint flags `status: active` initiatives whose `target_date` is in the past |
| 2026-05-24 | Backfill script `scripts/backfill_chat_outcomes.py` missing from production image (PR #255) | Dockerfile change was not exercised by `docker-smoke.yml` because the smoke only checks `import app.main` + `/__health` |
| 2026-05-24 | Backfill assumed `user_settings` table, actual schema is `public.users.settings_json` (PR #265) | No integration test runs the backfill against a real (or simulated) schema |
| 2026-05-23 | MCP server debug cycles (PRs #245→#249): session middleware bypass, lazy lambdas, mount order, lifespan task group, DNS rebinding | No automated test connects to `/mcp` and exercises the Streamable HTTP transport; bugs surfaced only via manual operator testing |

All five share a shape: the *unit* tests were green, but a layer above unit (image-build correctness, schema-against-actual-DB, integration with the SDK boundary, content drift over time) had no automated coverage.

This proposal audits the gap and lays out a phased plan. None of it touches the unit suite — that's working.

## Current coverage map

```
   ┌─────────────────────────────────────────────────────────────┐
   │  test.yml  →  pytest tests/unit/ -x                         │  ← every push/PR
   │  ✅ 538 tests, 8s, no DB, no network                         │
   │  Covers: pure-functional services, route handlers via       │
   │  TestClient, scheduler logic, repository contracts           │
   └─────────────────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────────────┐
   │  docker-smoke.yml  →  build image + import + /__health       │  ← PRs touching app code
   │  ✅ Catches missing files in image, import errors             │
   │  ❌ Doesn't exercise scripts/, doesn't hit any real route     │
   └─────────────────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────────────┐
   │  deploy.yml  →  fly deploy on push to main                  │  ← production
   │  ❌ No post-deploy smoke. If the image boots OK in CI but    │
   │     fails at runtime (auth flow, DB connection, MCP route),  │
   │     operator catches it manually                             │
   └─────────────────────────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────────────┐
   │  Manual: validation walkthrough docs/validation/*.md         │  ← operator, after major PRs
   │  ✅ Good: forces hand-on-keyboard verification                │
   │  ❌ Burdensome: ~15-20 minutes per push                        │
   └─────────────────────────────────────────────────────────────┘
```

There's a notable gap between "unit test passes" and "image still works in production." Three categories of regression are slipping through:

1. **Content drift** — initiative frontmatter, content/ files, reflect prompts. Pure-data, no test runner currently watches it.
2. **Image-level regressions** — files missing from the runtime stage, env vars not propagated, scripts not packaged. Docker-smoke catches the most obvious cases (import failure) but not script availability or `scripts/` running cleanly.
3. **Integration-boundary regressions** — MCP transport, real schema vs. test schema, Auth0 OAuth handshake. The unit suite uses mocks at these boundaries by design; bugs at the boundary itself are invisible.

## Phased proposal

Cheapest-first. Each phase is independently shippable and each closes one bug class above.

### Phase 1 — content lints (cheap, immediate value)

A new `tests/unit/test_content_lints.py` that loads every file under `content/` and asserts invariants:

**Initiative lints** (`content/initiatives/*.md`):

- `status == "active"` ⟹ `target_date is None or target_date >= today` — would have caught the rejected-applications drift
- `status == "done"` ⟹ `notes` contains a closure phrase (`"Closed"`, `"Shipped"`, `"Applied"`, `"Archived"`, or similar) — forces an explanatory note when archiving
- `priority in {0, 1, 2, 3}` — already enforced by loader, but assertion-as-doc is cheap
- `bench.surface in {"/", None}` — surface only the root for bench-resident initiatives
- Every file's `slug` matches its filename stem

**Reflect prompt lints** (`content/reflect_prompts.json`):

- Each prompt has `label` and `prompt` fields
- No two prompts share a `label` (collision would break the UI)
- Prompts referenced by the canned-fallback path in `hamming.py` exist

**Content schema** (`content/problems/*.md` etc.):

- All required frontmatter present
- `domain_tags` valid against the taxonomy
- `time_bucket in {5, 10, 15, 25, 45}` (existing scheduler invariants)

**Cost:** ~2 hours to write, ~50ms to run. Runs in `test.yml` for free.

**Wins:** catches content drift at PR time, no operator review burden.

**Open decision:** do we want lint failures to *block* PR merges, or just *warn*? I'd lean block for status-vs-target_date (data-quality regression) and warn for the rest (formatting). Operator preference?

### Phase 2 — script availability smoke

Extend `docker-smoke.yml` to verify every script under `scripts/` is importable and `--help` works inside the image. Catches PR #255 (missing `backfill_chat_outcomes.py` in image).

**Implementation sketch:**

```yaml
- name: Smoke 3 — every scripts/*.py is reachable and runs --help
  run: |
    docker run --rm \
      -e LIS_NO_DB=1 -e LIS_SKIP_STARTUP_LOAD=1 \
      lis-bench-smoke:test \
      sh -c 'for f in /app/scripts/*.py; do echo "== $f =="; python "$f" --help || exit 1; done'
```

**Cost:** ~10 min to write, +30s to the existing `docker-smoke` job.

**Wins:** zero false-positives (scripts that don't support `--help` get flagged in the same PR as the addition). Catches the entire "I added a script but forgot the Dockerfile COPY" class.

### Phase 3 — MCP transport integration test

A new `tests/integration/test_mcp_transport.py` (in the existing `tests/integration/` tree) that:

1. Boots the FastAPI app with `TestClient`
2. Negotiates a session against `/mcp` via the Streamable HTTP transport (or its httpx equivalent)
3. For each of the four MCP tools (`get_current_focus`, `get_initiative_state`, `list_open_threads`, `log_chat_outcome`), calls the tool with valid + invalid args and asserts the response shape

The four-tool surface is small and stable. The transport bugs (session middleware bypass, mount order, DNS rebinding) all manifest at this layer.

**Cost:** ~4 hours including familiarising with the MCP SDK's test patterns; ~1s per run.

**Wins:** the next time we touch `app/mcp_server.py`, a regression in the transport surfaces in CI instead of in the operator's terminal. Probably catches 4/5 of the recent debug cycles.

**Out of scope:** real Anthropic API calls, real Supabase. Mock at those boundaries (already wired in `tests/unit/test_mcp_server.py`).

### Phase 4 — full HTML route smoke

`tests/integration/test_html_smoke.py` loops over every registered route in `app.main.app.routes` and:

1. For unauthenticated routes: assert 200 and the page contains the expected page-title heading
2. For authenticated routes (using the existing `test_signed_in_routes.py` fixture pattern): assert 200 and the page renders without a Jinja `UndefinedError`

This is the cheapest way to catch "I changed a template variable in `focus.py` but missed it in `focus.html`" — Jinja's `StrictUndefined` (already enabled) raises at render time. A route-smoke test forces that render to happen.

**Cost:** ~3 hours.

**Wins:** broad coverage, catches the entire "template variable typo" class. Plus catches Jinja rendering regressions from CSS/HTML structural changes.

**Caveat:** would not catch the "complete no-show reflection" bug (that's logic, not template). Phases 1+2+3 + the existing unit suite still own the logic layer.

### Phase 5 — post-deploy smoke (only if Phases 1-4 prove insufficient)

After `deploy.yml` finishes, hit `https://bench.libearden.dev/__health` and `/about` from GitHub Actions; fail the deploy job (purely as signal — Fly will have already swapped) if either returns non-200.

**Why "only if needed":** post-deploy smokes are nice but don't change anything. The deploy already happened. The signal value is operator awareness; the bench has Sentry wired and the operator monitors Fly logs, so this is duplicative until proven otherwise.

**Cost:** ~30 min, ~5s per deploy.

## Visual / browser-level testing — deferred

Playwright/Selenium/visual-regression frameworks are not in scope for this proposal. Two reasons:

1. The bench is single-tenant alpha; the operator is the only user. Visual regressions surface within hours via the operator's own use of the platform.
2. The maintenance burden is real — flaky tests, browser version drift, screenshot baseline churn. The marginal value over Phase 4's HTML smoke is small for a UI this size.

If the bench ever opens up beyond the operator + invite-list, revisit.

## Recommended sequence + sizing

| Phase | Effort | Returns | Recommendation |
|---|---|---|---|
| 1. Content lints | ~2h | Catches content drift PRE-merge | **Ship first** — fastest signal, addresses the active rejected-applications class |
| 2. Script smoke | ~30min | Catches Dockerfile script omissions | **Ship second** — trivially additive to existing docker-smoke |
| 3. MCP integration | ~4h | Catches MCP transport regressions | **Ship third** — most recent debug cycles were here |
| 4. HTML route smoke | ~3h | Catches template/variable drift | **Operator decision** — meaningful coverage win, but the operator does manual validation on every push, so the marginal value is lower than for a multi-developer codebase |
| 5. Post-deploy smoke | ~30min | Catches "passed CI, broken in prod" | **Defer unless something slips through Phases 1-4** |

Total for Phases 1-3: ~7 hours of focused implementation, drops the operator's manual-validation burden noticeably without changing the local dev loop.

## Open decisions for operator

1. **Lint failures block or warn?** (Phase 1 — see above.) My recommendation: block for `status` ↔ `target_date` consistency; warn for the rest.
2. **Ship Phase 4 (HTML smoke) or skip?** The current validation-walkthrough cadence partially covers this. Honest assessment: Phase 4 is the most "tests for tests' sake" of the lot. If you want it, it's cheap; if you'd rather keep CI lean, the existing unit suite + Phases 1-3 are probably sufficient.
3. **Should Phase 3 (MCP integration) include the bearer-token auth path, or mock it out?** Adding real-token tests means CI needs a test token in secrets. I'd lean mock for unit-fast feedback; add an end-to-end auth smoke only if we see auth-layer regressions.

## Next steps if approved

1. File a Linear epic (`BEN-XX: regression coverage gaps`) referencing this doc
2. Sub-issues per phase (Phase 1 → 5)
3. PRs per phase, each independently shippable. Phase 1 lands first as the smallest + highest-signal change.
