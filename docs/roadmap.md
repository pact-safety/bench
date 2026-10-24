# Roadmap and decisions

What's been built, what's queued, what's deliberately deferred.

## Pilot priorities (2026-09-24)

> Bench is an early skill-acquisition tool for people transitioning into technical AI safety; try a practice session and share feedback.

### Supervised release pass — 2026-10-14

Scope remains a small invited pilot with no fixed launch date. ML4Good and
ARENA are the approved tracks; other curricula remain request-only. The release
criterion is a working first session and return visit: resource, practice,
review, reflection/rating, persisted account-isolated progress, and a clear next
action. Reading completion must not bypass competency gates; Mira remains a
question-led coach while exercise review retains its existing behavior.

Operating contract: start only open, eligible issues with concrete acceptance
criteria and satisfied dependencies; assign one owner; preserve unrelated work
and protected paths. Bugs require a failing regression before the fix. Check
focused tests, independent review, and browser behavior where relevant. Keep
prepared, merged, deployed, and live-verified evidence separate. Stop an item
after two unsuccessful cycles without material progress, or immediately on a
permission/protected-path blocker. Merge/deploy remain operator decisions;
close issues only after acceptance evidence and the required merged fix.

The initial audit baseline was `cb350914`, merged PR
#503.
Its deployment
succeeded. GitHub #502 and BEN-171 are closed/Done. Fresh public checks returned
`200 ok` from `/__health` and a login redirect from `/today`; authenticated
learner behavior is not established by those checks.

Inventory: 47 open GitHub issues and 48 unresolved Bench Linear issues (34
Backlog, 12 Triage, 2 Todo), with no open PRs at the start of this pass. The
Linear project filter alone misses most Bench issues. BEN-140 and BEN-141 both
represent #422's operator checklist; this is a duplicate candidate, not completed
security work. No issue closures were justified by the initial audit.

Ranked work: (1) #452/BEN-152, bound the default Mira transcript cache while
preserving fresh coaching reads; (2) fixture/browser checks for item persistence,
gates, isolation, feedback and desktop/mobile keyboard use; (3) authenticated
production verification for #306/BEN-106. Keep #408's existing content-pin work
untouched. #76/#77 remain device-blocked. #471/BEN-155 still needs evidence of
a healthy live week; the elapsed calendar gate alone does not satisfy it.

Fresh baseline checks: 122 focused tests pass across track content routes,
checkpoint gates, account isolation, daily resume, assessment integrity, atomic
coaching routes, feedback privacy and Connect detail state. This is mocked/unit
evidence, not a new live or PostgreSQL walkthrough. The hosted invited-user
walkthrough and operator runner/access review below remain release evidence
gaps. Initial first-batch estimate: 20–45 minutes agent work, 10–20 minutes
operator review, plus CI/environment waits; re-estimate after the batch. No
whole-release duration is committed before those gaps are resolved.

First batch released: #452/BEN-152 now expires default transcript-cache entries
after 30 seconds. A changed-row regression failed before the fix and passes
afterward; 45 focused Mira checks pass. Independent review found no actionable
issues and independently ran 23 repository/cache tests. Immediate local append
invalidation and fresh coaching reads remain intact. Operator-authorized PR #504
merged as `488e9f6`; all PR/main checks and deployment `38503507354` passed.
Fly release 216 reports that commit, the running machine passes health, the live
repository-file hash matches tested source, and public health returns `200 ok`.
#452 is closed and BEN-152 Done. Cached reads can still lag another worker by
up to 30 seconds. Strict documentation build passes.

Fresh learner QA: 143 focused tests pass. Chromium fixture pages at 1280px and
390px, with real CSS/reader/autosave scripts and accessibility settings enabled,
show no horizontal overflow or unlabeled visible inputs. Keyboard reader focus,
reflection focus return, rating selection and local draft recovery pass. Fixtures
replace the shell and external reader content and omit persistence endpoints;
they do not prove hosted or PostgreSQL behavior. QA reproduced a nonblocking
continuity defect: the shared ML4Good “Essence of Linear Algebra series” resource
can return section 12's learner to section 11. Preserve shared item identity and
notes when repairing originating-section context; no data loss was demonstrated.
The selected-section repair is tracked in #505/BEN-172: prefer a matching unlocked
selection while preserving the existing fallback and all prerequisite gates.
Three regressions failed before the fix; 100 focused tests and 48 independent
review tests passed afterward. Actual-context browser fixtures for sections 11
and 12 passed at 1280/390px, including stopping point, return URL, shared reflection
and overflow checks. Operator-approved PR #506 merged as `18a9fe2`; all PR/main
checks and deployment `38509031364` passed. Fly release 217 reports that commit,
the deployed file matches tested source, and public health returns `200 ok`.
#505 is closed and BEN-172 Done. Explicit clicked-link
origin when different from the saved selection remains outside this narrow fix.

Fresh disposable PostgreSQL verification: all 50 integration tests pass. A
targeted temporary-table check also confirms two fixture learners independently
retain ratings/reflections on the same shared item across completion/unread and
repository reload. The localhost-only container was removed afterward. No real
learner records were written. This adds database evidence, not a hosted browser
walkthrough or proof of adversarial execution isolation.

Runner/access review: submitted exercises retain the application's OS identity,
filesystem and network access despite environment filtering; the documented
subprocess runner is not a full isolation boundary. No exploit was executed.
Production configuration-presence checks found one environment-allowlisted ID,
no explicit admin list, and an assessment signing key. The admin fallback is
consistent with single-operator configuration, not proof of unintended admin
access; separate admin configuration must be reviewed before broadening the
environment allowlist. Protected access/deployment surfaces are unchanged.
Operator acceptance or remediation of runner isolation remains required before
claiming the pilot is ready for additional learners.

The unfinished execution boundary is now an explicit release gate in
#507
/ BEN-173 (`human-only`, `complexity:l`). The completed #421/BEN-139 audit and
environment-scrubbing PR #431 did not deliver full isolation or record risk
acceptance; #431 explicitly retained this prerequisite before non-owner alpha
execution. Runtime choice and protected Docker/Fly/CI scope need operator
direction before implementation. No exploits or protected edits were performed.

Hosted read-only verification has a further constraint: Today may persist settings
through decay handling, and the default open feedback inbox may synchronize linked
issue closures into feedback status. Neither is safe to visit under a strict
no-real-learner-writes instruction. #306 remains open for user-guided observation
or a separately authorized dedicated test identity; local fixture results do not
satisfy its production visual acceptance criteria.

The real local application was also exercised with disposable PostgreSQL and one
synthetic local-mode learner: activate ML4Good, save/reload item reflection and
rating, complete the resource without passing a checkpoint, save/reload a stopping
point and uncertain practice answer, return from Today, and submit feedback into
the review inbox. Direct fixture database inspection confirmed persistence and
the empty checkpoint-pass list. Full-shell tracks/detail/item checks at 1280/390px
had no overflow and keyboard rating selection worked. Server and container were
removed afterward. External browser requests and all external API keys were
disabled; this does not establish external-source/CDN/HTMX-widget behavior,
two-account browser isolation, scored assessment, runner isolation, or hosted
authenticated behavior. A reproduced narrow-screen feedback-inbox overflow is
tracked separately as #508; it does not change the runner release gate.

The #508/BEN-174 inbox fix wraps long resource paths and action forms while
preserving shared styles used by other surfaces. A 390px browser overflow
assertion failed before the fix. Both 390px and 1280px full-app regressions pass
afterward with accessibility preferences, visible keyboard focus and real
backlog/archive/reopen persistence. Sixty feedback unit tests, token-reference
checks and independent review pass. This batch is prepared, not merged or live;
its fixture writes were confined to a disposable local database.

This sequence takes priority over the historical queues below. The
[root roadmap](https://github.com/pact-safety/bench/blob/main/ROADMAP.md) retains feature detail.
The immediate product
is the hosted, invited flow; there is no Bench CLI. Public source and
public signup are separate milestones.

**Validation (PR #473, merged as `cf5c636`):** both onboarding fixes
have failing-before/passing-after regression coverage. The full unit suite
passes with local ML extras: 1,195 passed, 2 skipped, 1 known expected
failure. A fresh Python 3.11 / PyJWT 2.15 environment without ML extras
passes 1,168 tests, with 29 skips and the same expected failure, after
correcting noncanonical dummy JWT signatures in test fixtures. Authentication
code is unchanged. A fresh local PostgreSQL walkthrough found another first-use
blocker: onboarding tip forms nested inside the exercise form left the
run-tests button without a form owner. The follow-up repair separates tip
dismissal forms from page forms and has failing-before/passing-after browser
coverage. Local checks passed for tip progression/dismissal, plan unlocking,
hidden-test failure, a corrected passing attempt, saved progress, and structured
feedback in the inbox. These used a disposable database and disabled external
API keys; hosted login, paid review, and a human pilot remain unverified.

**Recovery (2026-09-24):** the earlier PR #473 deployment failed because
Supabase's pooler rejected the configured tenant/user; PR #474's deploy job
succeeded but initially had the same unhealthy startup. After the Supabase
project was restored, a read-only database query succeeded, Fly completed
startup on `5f1db5c`, and the public `/__health` endpoint returned HTTP 200 `ok`.
No credential rotation, deployment configuration change, or manual machine
restart was needed. The hosted human walkthrough and delayed-retention
validation remain separate unfinished work.

The initial audit
used older local commit `5841dd8`; its findings must not erase mechanisms
that shipped in the 41 intervening commits, including recitation spacing.

### Now — repair and verify the first 30 minutes

- [x] **Implemented and unit-tested:** preserve explicitly eligible
  onboarding warmups through scheduler filtering, and correct the daily-mode
  recommendation threshold from raw `2` to normalized `2/3`. Default warmup
  exclusion and user-selected daily modes remain covered by regressions.
- [x] Merge the scheduler and recommendation fixes (PR #473).
- [x] Implement and locally verify first-use tip form ownership with a
  PostgreSQL database: tip dismissal, failed and corrected attempts, saved
  progress, the no-API review state, and feedback capture.
- [x] Merge the follow-up form repair (PR #474, `5f1db5c`), with all checks green.
- [x] Resolve database startup availability after Supabase project restoration:
  database query, Fly startup health, and public health verified on `5f1db5c`.
- [ ] Verify onboarding → `paired-eval-position-debias` → tests/review →
  journal with a fresh invited user in a guided 30-minute session. Record
  friction, failures, assistance used, and whether the next action is clear.
- [ ] **Operator-owned prerequisite before expanding the pilot:** review
  runner inherited environment and access boundaries. Protected
  auth/security/deployment changes stay with the operator. Public signup
  requires stronger execution isolation.

### Individual track learning items — 2026-09-26

BEN-171 connects approved ML4Good
and ARENA resources to the existing content library. Each distinct source within
a track has a stable item page, a learning type, and its own per-learner rating,
favorite, reflection, and completion state. Repeated links share an item;
existing ARENA preparation items and runnable checkpoints retain their identities.
The library filters by track, learning type, and topic. Locked resources explain
prerequisites, while curricula pending audit remain unavailable.

Today and track resource links open individual content pages. The track page is
an outline; section practice checks and saved work have dedicated pages. Resource
completion leads back to the appropriate section check and never grants a
checkpoint pass or exam exemption. Existing section indices, questions, progress,
and saved answers stay intact. Atlas retains the inline reader on its item page;
other providers use an explicit original-source link. External-source descriptions
are not treated as full articles for paper-pass or recitation grading.

Scope: catalog entries such as a playlist or a multi-part tutorial remain one
resource unless the curriculum explicitly supplies separate URLs. Splitting those
into smaller authored learning units is a separate content audit. Validation:
1,888 unit tests plus two focused item-rendering checks, 65 frontend/lifecycle
checks, strict docs, and desktop/mobile browser checks.

### Atlas reading inside the lesson — 2026-09-25

BEN-170 keeps approved Atlas chapter
resources in a lazy, sandboxed reading panel beside the track section. Hide the
source to reflect and reopen it without losing its current subsection or scroll
position. Notes and explanations use the existing account-scoped browser draft
recovery. Today links retain the track context; other resource providers retain
an explicit original-source link.

The operator approved the narrow Atlas-only frame policy. Source links are
validated against the catalog provider, with no arbitrary URL fetching. The
original source remains available when embedding fails. Source position is not
restored after a full page reload or switching resources; saved stopping points
remain the durable way to resume. Validation includes 1,848 local unit tests,
63 frontend/lifecycle checks, and actual Atlas navigation on desktop/mobile.

### Track learner-flow repair — 2026-09-25

BEN-169 replaces Atlas checks
that incorrectly reused exercise-review prompts with authored, versioned
curriculum questions. Existing answers remain available as earlier work;
revised questions require a new response. Exercise review is unchanged.
ML4Good recommends an Atlas reading block before technical exercises without
renumbering saved sections. Notes precede a readable prerequisite outline and
one next-action card. Only ML4Good and ARENA are available during the audit;
other tracks accept deduplicated requests in the existing feedback inbox.
Missing practical assessments block completion rather than granting a pass.

Local validation: 1,687 unit tests passed (2 existing skips, 1 known expected
failure), including 12 new rendering regressions. Disposable Chromium checks
covered 390px/1440px layouts and accessibility toggles. Three request-concurrency
Postgres tests are included in CI; no local database was available.

The research-informed assessment pilot adds typed or dictated explanations
and fresh application to Atlas Capabilities and ARENA prerequisites. Both
formats use the same versioned rubric. Dictation requires learner confirmation
of the transcript; typing remains available. A human operator quotes evidence
and scores each criterion. The provisional cutoff is 80% overall and at least
3/4 on every essential criterion. This unproctored pilot is not certification
or a validated threshold. ARENA also requires owned passing practical work.

Pending, assisted, outdated, and unsuccessful responses do not grant exemptions.
Approved results advance the next action, readings, and prerequisite outline,
with “tested out” counts separate from completed practice. Submission tokens,
locked account writes, and account-bound server signatures protect evidence; errors
retain response drafts and review ratings. The operator review queue is linked
from Tracks. Existing exercise review and Mira's answer-free coaching remain
unchanged; no model grades these assessments.

Pilot validation: 1,802 unit tests passed (2 existing skips, 1 known expected
failure), 58 frontend/lifecycle tests passed, and nine PostgreSQL regressions
are included in CI. Browser previews covered 390px/1440px and accessibility
toggles. Build and strict documentation checks passed. The optional Svelte
type-check still reports the same nine errors on unchanged main.

The supplied learning research informs optional oral explanation and a fresh
application task, not fixed modality percentages or credit for listening.
Calibrating rubrics with independently scored examples, delayed retention,
worked-example fading, and own-voice replay remain future work. BEN-155's
retrieve-first scheduling gate remains **2026-10-01 after 15:38 UTC**.

The 47 remaining GitHub issues were reviewed against their acceptance criteria:
16 separate open-bench epics, 4 learner study tasks, 7 operator/hardware/timing
items, 7 partial or unverified deliveries, and 13 outstanding implementations.
No additional full closures were justified. Detailed disposition is recorded
in the Linear project and the existing Obsidian curriculum handoff.

### Audit closeout — 2026-09-25

BEN-167 derives assessment coverage
from saved responses: an unassessed axis is unknown, while a measured zero
remains a score. Results, charts, recommendations, and comparison screens use
that distinction. Readiness hours are explicitly illustrative fixed-assumption
scenarios; practice does not automatically recalibrate the assessment snapshot.
Available exercises can supply the next assessed focus when the weakest axis
has no remaining exercise. New assessment questions and a validated learning-rate
model remain separate work.

BEN-168 closes remaining continuity
repairs: sent/received contact entries imply their direction; historical writing
sources resolve accessible reading slugs; concurrent Mira submissions save each
coaching step once and preserve conflicting drafts and selected work. Intentional
new sessions carry a stable retry identity. Mira still uses finite coaching
questions and supplies no answers; exercise review is unchanged.

Feedback promotion commits a claim before creating a GitHub issue. An uncertain
outcome blocks another automatic create and lets an admin verify/link an existing
issue. This prevents repeated attempts; it does not promise exactly-once delivery
across GitHub and Postgres. A claimed report with no remote issue remains in the
inbox for operator review. Markdown exports use separate per-user directories;
legacy shared files are retained, not treated as a current aggregate queue.

Local verification: 1,634 Python unit tests pass (2 skips, 1 known expected
failure), all 56 frontend/lifecycle checks pass, and the production build passes.

PR #495
merged as `3f9126c`. CI passed 1,607 Python tests without optional ML extras
(29 skips, 1 known expected failure), all 14 browser tests including 38 real-
Postgres regressions, frontend/lifecycle, build, container smoke, security, and
style checks. Independent review is complete.
Deployment 36096842209
succeeded; read-only verification confirmed all 21 changed runtime files match
the tested release. Human pilot feedback, protected runner-boundary review,
voice mentoring, new assessment content, and broader calibration are not implied
by these engineering checks. BEN-155 remains gated until **2026-10-01 after
15:38 UTC**; no timing-gated learning experiment is pulled forward.

### Connect follow-up consistency — 2026-09-25

BEN-166 keeps private notes in
history without resetting touchpoint or reply state. List and detail views
use the same actual-touchpoint rule, even beyond the visible history window;
same-day entries have deterministic ordering. Confirmation dialogs treat
contact names as text, cancellation prevents submission, and archiving retains
history. Regression coverage includes account boundaries, long note histories,
same-day direction changes, invalid requests, and browser confirmations.

Assessment coverage and the remaining continuity repairs are covered by the
audit closeout above.

### Bounded and recoverable imports — 2026-09-25

BEN-165 covers bounded URL
capture and archive imports, replacement-aware quotas, and atomic note/chunk
storage. Re-importing an unchanged archive repairs incomplete notes; distinct
folder paths retain distinct notes. Import failures explain how to retry, and
the KB page distinguishes searchable notes from Mira’s current coaching preview.
Validation includes malformed archives, transport boundaries, concurrent quota
checks, rollback/retry, and a browser import/re-import journey.

Connect ordering and confirmation fixes shipped in PR #493. The audit closeout
above covers assessment evidence and remaining continuity repairs.

### Account isolation and work recovery — 2026-09-25

BEN-164 tracks the first repair
batch from the platform audit: account-scoped content and assessments,
server-validated assessment progression, explicit MCP account configuration,
and preserving exercise and writing drafts through failed saves. Deadline
submissions retain a retryable snapshot; writing status changes save the current
title and body together. Existing exercise review remains unchanged.

Regression coverage includes disposable-Postgres ownership/concurrency checks
and browser failure-recovery gates. Broader ingestion recovery and URL restrictions, Connect
semantics, and assessment calibration remain separate follow-up batches.

### Navigation and Mira coaching audit — 2026-09-25

BEN-160
tracks the implemented next-step labels, native navigation disclosures,
keyboard-accessible palette, and calmer Today/track organization. The primary
action stays visible; broader alternatives and dashboard details start collapsed.
This is a usability change to assess with the learner, not a claim of clinical
ADHD efficacy.

BEN-161
tracks the implemented Mira text preview: finite prompts for framing, attempting,
checking, and reflecting; learner notes stay in Bench, with no AI-provider
request or correctness verdict. Older conversations remain read-only and the
legacy unrestricted generation endpoint is disabled. Matching unfinished
sessions resume, tab-scoped drafts survive failed saves, exact persisted text
acknowledges drafts, and fresh transcript reads avoid stale coaching steps.
The no-answer constraint applies to Mira; existing exercise hints and review
remain unchanged. Voice and external AI critique await explicit user choice.

BEN-162 covers the accompanying
feedback-flow usability and administrative-review improvements.

Local validation: 1,365 unit tests passed, 24 frontend tests passed, and all
11 feedback-script lifecycle tests passed. Browser QA covered navigation,
section links, draft continuity, and the focused learner journey. The production
frontend build passed. A clean dependency install still reports nine Svelte
configuration/island type-check errors; an isolated archive of baseline
`3244a825` with its own clean install reproduces identical diagnostics.
Release is pending; the linked issues record current status.
BEN-155's **2026-10-01 after 15:38 UTC** gate is unchanged.

### Track practice flow — implemented (2026-09-25)

BEN-158
is the user-approved batch for session resume, checkpoint answers/feedback and
failed-check correctness, a review companion, curriculum-first onboarding and
discovery, and choosing the next eligible section. Reuse existing track state
and shared UI; preserve progress, prerequisite gates, and accessibility.
Implementation and local validation are complete: 1,273 unit tests passed
(2 skipped, 1 known expected failure), plus browser QA with an in-memory test
user. Self-review and saving answers stay local; optional AI critique awaits
the operator’s choice. BEN-158 records current review and release status.
BEN-155's global retrieve-first change remains separate and gated until
**2026-10-01 after 15:38 UTC** at the earliest.

### ML4Good prework track (2026-09-25)

- [x] BEN-157: implement the shared
  **ML4Good Technical Prework (Fall 2026)** track from the
  [Hong Kong 2026 guide](https://docs.google.com/document/d/1hwZ7FPMxE2qQEDtXYZ-IGsnKNFKzrVW7/edit#heading=h.1muxhwej888n).
  Initial content-only release: PyTorch Colab and Basics 0–7, einops/tensors,
  shared Atlas chapters 1–4, philosophy and playlist. Math/Python refreshers
  initially appeared only in notes; BEN-159 below makes them usable track work.
  Independent review found no issues; 36 focused tests and one actual-catalogue
  route/list/activation smoke test passed.
  Release status and follow-up are tracked in BEN-157 and PR #477.

### ML4Good continuity — implemented, awaiting CI and release (2026-09-25)

BEN-159 follows up on the missing
math preparation and the generic reading cards that did not change with an
active track. Implementation is complete locally; CI and release are pending.

- Preserve the original 11 core section indexes and progress. Add seven
  independently selectable refreshers: linear algebra foundations and
  extensions, probability/statistics, calculus, Python basics, classes/Zen,
  and bonus OOP/PEP 8. Restored source references live alongside the relevant
  sections, including PyTorch examples and einops/einsum help.
- Keep core completion separate from supplemental progress. The source's
  essential mathematical capabilities remain explicit; selective refresher
  completion does not imply that the underlying capabilities are optional.
- Carry active-track readings, videos, exercises, and supplemental resources
  into Today and Library, with saved-session continuation. Starting a writing
  draft from today's reading retains the track section and stopping-point
  context instead of using an unrelated general reading.
- Local browser QA passed math selection, save/resume, and Atlas/playlist
  cards. Full-suite validation and release evidence remain to be recorded;
  this entry does not claim the changes are live.

### Next — retained skill and a small pilot

- [x] **Merged and deployed (BEN-154, PR #475 / `9eee399`):** persist per-problem +1/+7/+30
  return dates in existing user settings and surface due problems before fresh
  picks. A due-day unaided pass advances the interval; early/same-day unaided
  repeats preserve it. Assisted passes and failed returns reset to +1 without
  treating assisted success as retained skill. Existing track and due-recitation
  priorities are preserved.
- [x] Merge and verify the problem-return release in the hosted app (PR #475).
- [ ] Gather delayed unaided results. An assisted pass alone does not show retention.
  Recitation spacing already ships in BEN-135: per-concept +1/+7/+30 days,
  miss → +1 day, and due recitation in daily flow. Extend rather than duplicate it.
- [ ] Preserve the existing curriculum sequence: BEN-154
  implements passed work becoming due again first (merged and deployed); BEN-155
  adds retrieve-first after BEN-154 has been live for a week, no earlier than
  **2026-10-01 after 15:38 UTC**;
  BEN-156 adds an unlocked mixed
  set third. BEN-154 is Done; BEN-155 and BEN-156 remain Backlog;
  BEN-155 retains its blocking relationship to BEN-154. Their current project
  membership is unchanged. The active plan is mirrored in
  Research Engineer Interview Prep,
  which is separate from the open-bench research-orchestration project.
- [ ] After the access/execution prerequisite and fresh-user walkthrough
  pass, invite 3–5 pilot users; resolve blocking friction before growing to
  10. Collect structured feedback through the existing widget and inbox.
- [ ] Set up paired baseline/delayed unaided results and counts of invited,
  started, completed, and returned learners. Report assistance and missing
  follow-ups separately; these observations do not establish causal efficacy.
- [ ] Prepare a sanitized public-source cut with fresh history, content-rights
  review, and a code-license decision (MIT recommended). Verify a truthful
  Postgres/pgvector/bootstrap quickstart from a clean checkout; no-DB smoke
  mode is not a functional local product.

Estimates are **engineering days**, with delayed-reassessment observation
and pilot recruitment time additional:

| Work | Estimate |
|---|---|
| Execution and access boundaries | 2–5 days |
| Onboarding repairs and polish | 0.5–1.5 days |
| First-session flow | 1–2 days |
| Persisted problem review schedule and reassessment | 2–4 days |
| Measurement setup | 1–2 days |
| Public-source cut | 1–3 days |

### Later — evidence-led expansion

- [ ] Explore opt-in aggregate reporting with suppression below five
  distinct learners per reported group; make no absolute anonymity promise.
- [ ] Explore a fellowship cohort, shared progress, and a monthly 15-minute
  written check-in in groups of 4–6; validate demand before building it.
- [ ] Consider Mangrove export/link-out conditional on a partnership.
  Individually consented matching is separate from aggregate reporting.
- [ ] Assemble grant evidence from paired baseline/delayed results and
  participation counts, with limitations. Budget, organizational case, and
  why-now remain separate application work. Evaluate a fiscal sponsor
  before an independent entity, subject to actual needs.

These unchecked items record unfinished work and intentions, not current
capabilities or implementation commitments for the longer-term ideas.

## Phases

The platform's been built in phases tracked under LIS-281.

| Phase | State | What it included |
|---|---|---|
| 1: Supabase + Postgres schema | ✅ | 20-table consolidated migration, UUID FKs to auth.users, JSONB everywhere |
| 2: Feedback import | ✅ | Historical SQLite rows migrated; live widget persists to Postgres |
| 3: GitHub OAuth (PKCE) | ✅ | Server-managed code_verifier cookie, auth-gate middleware, /auth/me |
| 4: Postgres data layer | ✅ | 13 repos, ~50 callsites refactored, UUID throughout |
| 5: Test-user separation | ✅ | Real test users via Supabase Admin API; 14 integration tests |
| 6: Onboarding polish | ✅ | Skip path, easy-first ramp, surface ramp indicator |
| 7: Deploy bench.libearden.dev | Deployed; invited walkthrough pending | PR #503 deployment succeeded on `cb350914`; public health rechecked 2026-10-14 |

## Features shipped (recent)

- **Daily progress strip + Up-next hero** (LIS-274 chain)
- **Hash-based startup skip** — 70s → 1s restart when content unchanged
- **In-process cache** with read-through + invalidate-on-write
- **External reading capture** (`/library/add` with Claude-powered URL parse) — LIS-294
- **JD + CV IAC profile + alignment view** — LIS-295
- **Run_tests resubmit guard** — LIS-291
- **Reflect skeleton loader** — LIS-290
- **Readiness timeline evaluation** — LIS-296
- **Mentor voices registry** — LIS-297

## Queued

| Issue | Scope | Priority |
|---|---|---|
| LIS-285 | Slot done-tracker over-marks completion (audit-trail bug) | Med — needs repro data |
| LIS-284 | Unify tag taxonomy between problems and content_items | Med — Library discovery |
| LIS-292 | `/library/add` submit failure investigation | Low — possibly browser-side |
| Reflect-voice routing | Route hamming.py through the voice registry | Low |
| Reflect-IAC integration | Pull JD/CV IAC into reflect prompt context | Low |
| Multi-JD readiness aggregate | "What to focus on this week given all your JDs" | Low |
| Acceleration mode | Research-replication content + extra daily slots | Big |
| Calibrated hours-per-axis-point | Replace heuristic with attempt-derived value | Big, needs a validated outcome study; no fixed attempt-count guarantee |

## Security posture

| Concern | Status |
|---|---|
| GitHub OAuth via Supabase (PKCE, ES256 JWT) | ✅ shipped |
| CSP headers + form-action lockdown | ✅ shipped |
| Access allowlist (`LIS_ALLOWED_USER_IDS`) | ✅ shipped — single-tenant gate |
| Bearer-token MCP server auth | ✅ shipped (PR #243 / #246) |
| **Row-Level Security on every table** | ✅ shipped (migration 010 / PR #254-ish) — defense-in-depth against direct PostgREST or anon-key paths; bench's `postgres`-role connection bypasses |
| OAuth 2.1 shim for claude.ai web | parked (issue #244) |

## Parking lot — explicit deferrals

Ideas captured here so they don't sit in the operator's head. Each entry has a **revisit trigger** — the condition that should pull it back onto the active queue.

### Expand `/writings` into a long-form drafting pipeline

The current `/writings` route is a draft list. The expansion adds: kanban-style pipeline (idea → outline → draft → ready → published), split-pane Markdown editor with live GFM preview, clean export for Substack / LW / AF / personal, audit-trailed Sonnet structure/clarity passes that **never write substance**.

Full design in [`docs/proposals/writing-pipeline.md`](./proposals/writing-pipeline.md); spec lives at GH #258. Operator logged it **Low / phased** on purpose.

**Why parked.** Phase 1 alone is a 1500-2000 LOC build with a real UI surface (the kanban board). That's 1-2 weeks competing directly with the capstone arXiv deadline (LIS-186, 2026-07-15). The writing habit itself can start now in any Markdown editor — the bench's pipeline is an accelerant for a habit, not a prerequisite to it.

**Revisit when.** Capstone is off the critical path AND the operator notices "where's my draft, what stage was it in, how do I export it" is actually slowing weekly writing cadence.

**Hard constraint:** the Sonnet guardrail (never writes substance) is non-negotiable. Build it into the API surface (no "generate draft" endpoint exists), the prompt (clarity-pass refuses to fill `[TODO]`s), and the UI (sidebar suggestions, never inline edits, explicit Apply/Discard).

### `/connecting` — networking tracker with warmth monitor

Bi-directional networking surface. Tracks outreach + replies per contact, classifies by type (peer / mentor / field / initiative), surfaces a "warmth" signal so connections don't go cold without the operator watching them all. Default view is an action queue (only cooling/cold/new, most-overdue-first) — anti-obsession is a hard requirement.

Full design in [`docs/proposals/connecting-route.md`](./proposals/connecting-route.md); spec lives at GH #256. Operator logged it **Low** on purpose.

**Why parked.** Capstone arXiv submission deadline (LIS-186) is **2026-07-15**. Building `/connecting` before that trades the capstone for a tool, and the tool itself is meant to be low-cognitive-overhead, not a build project that consumes cognition.

**Revisit when.** Capstone is off the critical path (post-arXiv, after 2026-07-15). Pick up MVP scope (per the proposal's recommendation, **without** Linear mirror initially) when there's spare bandwidth.



### `/lab` — eval-design playground

A `/lab` route where the operator specs a small alignment-shaped eval (e.g., "does Sonnet detect deceptive Llama-2-7B outputs given prompt template X?"), the bench runs it through the existing Anthropic API integration (plus optionally a small open-source model via Modal), and produces a notebook entry — hypothesis / method / raw results / interpretation. Each notebook is operator-flagged public-or-private; public ones become shareable portfolio artifacts at `/lab/notebook/{slug}`.

**Why interesting.** Designing small evals *is* the JD task for METR / Apollo / Anthropic Interp / Redwood. A `/lab` notebook that records hypothesis → method → results → takeaway is a directly shareable artifact of that skill. Three or four good notebooks IS an application portfolio.

**Why parked.** Bench-building is at risk of swallowing the time meant for interview prep itself. The current make-it-legible wave (BEN-74 through BEN-77, plus the BEN-79 → BEN-82 focus/journal/MCP stack) is finishing the platform as a portfolio artifact. Adding `/lab` re-opens it as a project for another 3–4 weeks. Distinguishing parked from "no" matters: this idea is the right shape, just not the right week.

**Revisit when.** Either (a) the operator finds themselves wanting to design an eval and reaches for the wrong tool, OR (b) the make-it-legible wave fully lands and the operator wants to commit a multi-week build before applications open. Revisit no later than 2 weeks from filing.

**Not parked variants.** "Lab as Jupyter-in-the-bench" (notebook hosting) and "lab as content-authoring playground" — both rejected on first pass. The eval-design framing is the only one worth doing.

### "Open in Cursor" buttons

Skipped. Reviewers don't have Cursor installed; the operator is already in Cursor. Revisit only if the public-corpus repo (#196) ships and a public-facing "try it" flow becomes desirable — in which case the right answer is GitHub Codespaces ("Open in Codespaces" button), not Cursor.

### Email-forward inbound for news / readings

A real inbox (`content@bench.libearden.dev` via Resend/Postmark inbound webhook) that turns forwarded newsletter emails into draft `content/readings/` items. Defer until the RSS news-feed engine (Phase 1 of the content-generation engine, separate sub-issue) proves the news feed is actually used.

**Revisit when.** RSS news feed is shipped and operator finds themselves manually creating `content/readings/*.md` from emails ≥3 times.

## Design decisions worth knowing

**Anti-sycophancy is structural, not stylistic.** Reviews and reflect prompts are *required* to identify specific gaps in JSON. The system prompts call out generic "keep up the great work" as the explicit failure mode.

**Single-tab UX.** The Today page has ONE next thing. The platform refuses to fan out into 12 "what should I do" widgets. If you want to break out, the library is one click.

**Hints cap at structural scaffolding.** Tier 3 is the end of the ladder. After that, you look at the reference solution and trace why — and that lookup is logged, affecting scheduler scoring.

**JSONB over per-field columns.** Settings, hints_used, axis_weights, parsed_json, iac_profile — JSONB. Pragma: the shape is small + user-controlled + we can index when it matters.

**No SPA.** Server-rendered Jinja2 + HTMX for the small handful of partial swaps. Faster to develop, faster to debug, lower client-side complexity.

**LLM-or-fallback, never LLM-only.** Every Claude-flavored service has an offline path. Routes never branch on `ANTHROPIC_API_KEY` — that's the service's responsibility.

## See also

- LIS-281 phase tracker on Linear (canonical)
- [Architecture: code tour](architecture/code-tour.md)
