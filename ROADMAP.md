# ROADMAP.md

Phased plan for additional features beyond v1. Each item placed by
size, dependency, and whether earlier data is needed to make it worth
building.

**Current priority (2026-09-25):** the hosted invited pilot, with
BEN-169 repairing authored track
checks, prerequisite visibility, reading-first orientation, and the audited
ML4Good/ARENA catalog. A human-reviewed written/dictated test-out pilot now
covers Atlas Capabilities and ARENA prerequisites; broader calibration remains
future work.
See [Pilot priorities](docs/roadmap.md#pilot-priorities-2026-09-24) for the
active now/next/later sequence, validation limits, and estimates. The feature history below
remains reference material; its order does not override pilot prerequisites.

LLM features assume `ANTHROPIC_API_KEY` is in the environment. Default
model choices: `claude-haiku-4-5-20251001` for cheap per-attempt work,
`claude-sonnet-4-6` for content generation and judging, `claude-opus-4-7`
where reasoning quality matters more than cost.

## Methodology — the five phases as the spine

The problem-solving spine is a five-phase rhythm for working under
uncertainty (a widely-taught structure; we claim no ownership of it):

> **Explore → Brainstorm → Plan → Implement → Verify**

This is not a feature — it is the *user experience spine*. Starting in
v1.5, the problem page is restructured around the five phases. Every
existing roadmap item that touches the user's flow gets re-framed
around the phases:

- **#5 hint ladder** becomes phase-aware hints.
- **#7 approach feedback** receives semantic phase content instead of
  raw keystrokes.
- **#8 skill graph** slices by *phase × topic*, not just topic.
- **#2 spaced-repetition scheduler** weights against phase weakness
  too, not just topic weakness.
- **#4 docs links** become per-phase: Explore-time references,
  Plan-time references, etc.

The phase scaffolding is tailored per problem context:
- Individual algo practice (untimed, learning-oriented)
- Algo interview simulation (timed, live-signal-oriented)
- Design interviews / design documents

Each Li's Bench problem will eventually carry per-phase scaffolding
informed by the appropriate variant. v1.5 establishes the structural
support; v2/v3 layer on adaptive content.

---

## v1.0.1 — polish (immediate, landed)

Small fixes that don't need a milestone.

- ✅ **Markdown rendering in prompts** (#1) — mistune integration with
  custom HighlightRenderer.
- ✅ **Theme toggle context** (#3) — sun/moon icon plus a "light" /
  "dark" label reflecting the current state.
- ✅ **Rename to Li's Bench** (#9) — `<title>`, brand, favicon (🛠),
  README note. Repo directory keeps the descriptive name.
- ✅ **Soft syntax highlighting in rendered code blocks** —
  Pygments + a Slack-style four-token CSS palette (keywords, strings,
  comments, numbers). No IDE rainbow. Same palette in light and dark.

## v1.5 — phase spine, onboarding, ergonomics

Originally planned: notes attached to attempts, paper-source
ingestion, reading-mode UI, CodeMirror feature flag. **The new top
item — phase-structured problem flow — is the foundation everything
else builds on.** Order matters: ship the phases first so all subsequent
attempts produce phase-content that v2/v3 LLM features can use as
training data.

### 1) Phase-structured problem flow ✅ landed

Restructure the problem page into five explicit, ordered sections.
Each section is a self-contained text area; the editor (Implement)
is one of them. Time-on-task is recorded per section.

**Schema additions** on `attempts`:
```
explore_notes        TEXT
brainstorm_notes     TEXT
plan_notes           TEXT
verify_notes         TEXT
time_per_phase_json  TEXT   -- {"explore": 120, "brainstorm": 90, ...}
```

**UI changes:**
- Five collapsible sections in order: Explore, Brainstorm, Plan,
  Implement, Verify.
- Each has a prompt header that adapts to the problem type (algo /
  ML coding / debug / design) — e.g., Explore for algo asks for
  I/O contract + edge cases; Explore for debug asks for the symptom
  fingerprint and what it *isn't*; Explore for design asks for
  goals/non-goals + constraints.
- **Soft Plan gate** (configurable in `config.toml` and in user
  settings): the Implement section is read-only until the Plan
  section has more than N characters of content. Default N = 80.
  Easy bypass for warmups; problem-level override allowed.
- A small "current phase" indicator in the header. Switching sections
  records a phase-transition timestamp.

**Per-problem authoring:**
Each problem grows phase-specific prompt fragments in the
frontmatter:
```yaml
em:
  explore_prompt: |
    Pin the I/O contract. What's the shape of `q, k, v`?
    What's "causal" doing operationally?
  brainstorm_prompt: |
    Two-three approaches. Cost each in time/space. Pick the
    one that maps cleanest to the PyTorch primitives you'll use.
  plan_prompt: |
    What's your invariant? Where does the scale go? How will
    you build the mask?
  verify_prompt: |
    What's your minimum test? What's the boundary case
    (single-token sequence? all-masked? mixed batch)?
```
Fragments are author-curated. Falls back to a generic per-type
prompt if a problem doesn't specify.

**Why the Plan gate matters.** Planning before coding is widely the
phase with the strongest correlation to interview and work outcomes. A small UX nudge
that forces *any* Plan content before coding builds the habit. The
gate is soft (configurable, bypassable) — not coercion, just
friction in the right direction.

**Scope:** ~2-3 days for the structural work + one-off auth pass
on phase prompt fragments for the 31 core problems (~3-4 hours
batched).

### 2) Adaptive initial assessment + onboarding ✅ landed (with stat pentagon)

5-10 multiple-choice questions, re-takeable. Seeds the skill graph
and the scheduler with a coarse-grained competency baseline before
the user has any attempt history.

**Question pool** (pre-authored, ~15-20 questions covering all
skill axes):
- Transformer internals (attention, multi-head reshape, KV cache)
- Training mechanics (grad accumulation, mixed precision, eval mode)
- Sampling / decoding (top-p, beam, temperature, length norm)
- Eval design (sycophancy framing, paired comparisons, robustness)
- Debugging patterns (causal-mask flips, softmax-then-CE, Bessel,
  detach in residuals)
- Tokenization (BPE merges, greedy match, vocab edge cases)
- Algorithmic patterns (when to reach for which DS)
- Rust fluency (read-only? read-and-modify? write-from-blank?)

Each question is multiple-choice with 4 answers. Answers are
weighted on a 0-3 competency scale per skill axis. Many questions
touch more than one axis.

**Adaptive question selection:**
Deterministic decision tree, not LLM-driven. Picks the next
question that maximizes information gain about an *untouched* axis.
First question is fixed (broad calibration: production ML
experience). Stops at 5-10 questions or when every axis has at
least one signal.

**Data model:**
```
assessment_runs
  id, user_id, started_at, completed_at
assessment_responses
  run_id, question_id, answer_index, axis_scores_json
```
Latest completed run feeds the skill graph and the scheduler.

**LLM optional (v2):** Sonnet generates a personalized "where to
start" paragraph based on the response pattern. Until then, a
deterministic templated summary ("you reported weakness on
sampling and tokenization; suggested first session:
top-p-sampling and bpe-merges").

**Re-take:** explicit link from the home page footer and from a
new `/settings` page. Each retake is its own run; we keep history.

**Onboarding flow (first-load):**
1. Welcome screen explaining what Li's Bench is in two paragraphs.
2. Brief on the five phases (one screen, with a link to
   the methodology doc).
3. Initial assessment (5-10 questions).
4. Result screen with: rough skill graph, suggested first
   problem, button to start.

After completion, the standard home page becomes the landing.
Returning users skip the welcome but can re-take from `/settings`.

**Scope:** ~3 days (question authoring is the bulk; UI is small;
no LLM in v1 of this).

**Landed details (2026-05-12):**
- 15 multiple-choice questions across 10 axes, deterministic adaptive
  selection (info-gain heuristic), min 5 / max 10 questions, early
  exit once every axis is touched after the minimum.
- The 10 axes consolidate into **5 stats** for visualization:
  TRANSFORMER (transformer_internals + numerical_stability), TRAINING
  (training_mechanics + debugging), DECODING (sampling_decoding +
  tokenization), EVAL/DATA (eval_design + data_pipeline), SYSTEMS
  (algorithmic + rust_fluency).
- **Stat pentagon (SVG radar)** replaces the original bar chart on the
  home page, the assessment result page, and the settings page.
  Server-side SVG, no JS, theme-aware, color-tier coding per stat
  badge. See `app/services/skill_stats.py` +
  `templates/_skill_chart.html`.
- Onboarding flow: welcome → phases intro → assessment → result with
  suggested first problem. Skippable; skip flag stored in
  `users.settings_json.onboarding_skipped`.
- Retake from `/settings`.

### 3) Soft syntax highlighting in the editor

The CodeMirror 6 flag is already in `config.toml`. v1.5 work:
- Bundle CodeMirror 6 + Python + Rust language modes as static
  assets (no build step — ship pre-bundled files in `static/cm/`).
- Match the same soft 4-token palette already used for rendered
  code blocks.
- Wire behind the flag; default-on for v1.5.
- Tab-to-indent already works in CodeMirror; remove the textarea
  handler when CM is active.

**Scope:** ~1 day.

### 4) Per-phase docs links (#4) ✅ infra landed; backfill ongoing

A `references:` array in markdown frontmatter, with optional
`phase:` to target a specific phase:
```yaml
references:
  - title: "Attention Is All You Need (Vaswani et al., §3.2.1)"
    url: "https://arxiv.org/abs/1706.03762"
    why: "scaled dot-product attention definition"
    phase: plan
  - title: "PyTorch nn.LayerNorm — biased variance note"
    url: "https://pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html"
    why: "the unbiased=False detail"
    phase: implement
  - title: "Programming Rust 2e, Ch. 4 — Ownership and Moves"
    url: ""   # local PDF — page-anchored reference, not URL
    page: 79
    why: "borrow checker fundamentals for the &str signature"
    phase: explore
```
Surfaces inside the relevant phase section. Local PDF references
get a `page:` field with a path/page anchor; v1.5 surfaces them as
text (page number + book title), v2 could deep-link if a local PDF
viewer is added.

**Recommended canon for the existing 31 problems**, pulled from the
user's reading stack (attached 2026-05-12):
- **The Rust Book** (Klabnik/Nichols) — borrow checker, lifetimes,
  iterator chains — links from Rust warmups and the 2 Rust-write
  core problems.
- **Programming Rust 2nd Ed** (Blandy/Orendorff/Tindall) — deeper
  reference for the same crowd, especially error handling and
  trait machinery.
- **Clean Code** (Martin) — *selectively* for naming/small-function
  arguments in the Implement-phase guidance. Skip the more
  controversial chapters.
- **Machine Learning with PyTorch and Scikit-Learn** (Raschka/Liu/
  Mirjalili) — full coverage for the ML coding section:
  attention/MHA → transformer chapter; LayerNorm/RMSNorm → norm
  chapter; sampling → generation chapter.
- **The Art of Doing Science and Engineering** (Hamming) — *not*
  per-problem; surfaces in v2 reflection mode (see below). Doesn't
  belong on individual problem pages.

Authoring approach: a one-shot script
`scripts/suggest_refs.py` calls Sonnet with each problem's content
and proposes 2-3 references with `why:` and `phase:` annotations.
Human reviews, edits, commits. **~4-6 hours** for the 31 core
problems batched.

**Landed (2026-05-12):**
- Frontmatter `references:` block parses; persisted in
  `problems.references_json` (migration 005).
- Per-problem panel on problem page, grouped by phase via
  `app/services/references.py`.
- Backfilled 5 problems as examples covering the user's reading
  stack: scaled-dot-product-attention, layernorm-from-scratch,
  greedy-tokenizer-rust, ring-buffer-rust, algo-validation-window.
  The remaining 26 are an authoring sprint.

### 5) Credentials upload + skill-gap evaluation (new)

The intuition: the quiz tells us what the user *says* they know; their
CV, transcripts, and diplomas tell us where their credentials suggest
they should be. The gap between the two is the signal — both
directions matter (over-credentialed-but-rusty *and*
under-credentialed-but-self-taught).

**Placement.** After the assessment, as an optional second step in
onboarding (with a "skip — add later from /settings" path). Putting
it after the quiz means we have the user-reported baseline to
contrast against; putting it before makes the quiz feel gated.

**Privacy.** CVs/transcripts carry PII. Files stay on disk under
`data/credentials/<user_id>/<run_id>/`, never leave the machine
except as text sent to Claude for analysis (with caching disabled
for that call). A clear in-UI note: "your file content is sent to
Claude via Anthropic's API for one analysis call, then discarded
server-side."

**Phases.**

*Phase 1 — Upload + storage + extraction (no LLM yet)*
- Multipart upload form (PDF, DOCX, TXT, common image types).
- Server-side storage with a per-user timestamped directory.
- Per-format text extraction:
  - PDF: `pypdf` (already common in our stack-adjacent code).
  - DOCX: `python-docx`.
  - TXT: read as-is.
  - Image: `pytesseract` is heavy; defer — accept "image OCR not
    yet supported" message for now. User can convert to PDF.
- Schema (new migration 006):
  ```
  credential_runs (id, user_id, started_at, completed_at, status_text)
  credential_files (id, run_id, filename, content_type, byte_size, extracted_text, sha256, uploaded_at)
  credential_assessments (id, run_id, inferred_axis_scores_json,
      gap_axis_scores_json, summary_md, curriculum_json, created_at)
  ```
- `credential_files.extracted_text` holds the extracted text for
  later LLM input. `inferred_axis_scores_json` and `summary_md`
  are populated in Phase 2.
- UI: `/onboarding/credentials` upload screen + a
  `/credentials/<run_id>` review page that shows extracted text
  before triggering analysis.

*Phase 2 — LLM analysis + skill-gap rendering*
- Call Claude Sonnet 4.6 with a structured prompt:
  - System: "You are a credentials-to-competency evaluator for AI
    research-engineering roles. Output JSON only."
  - User: extracted text + the 10-axis definitions.
  - Expected response schema: `{inferred_axis_scores: {axis: 0..1},
    rationale: {axis: "..."}, summary: "..."}`.
- Use prompt caching on the axis-definition system prefix; the
  variable part is the user's documents.
- Store the response on `credential_assessments`.
- Render: side-by-side pentagons (credentials vs. assessment) with
  per-axis arrows showing the gap direction and magnitude. For
  the top 3 gap axes, recommend 2-3 problems each from the
  corpus (reusing `assess_service.suggested_slugs_for_axis`).

*Phase 3 — Tailored curriculum (sequencing)*
- The pure "recommend N problems" list is fine in Phase 2.
- Phase 3 sequences them: easier-first within an axis, scaffolds
  prerequisites, and tags the resulting set as a saved curriculum
  the scheduler can prioritize for the next N days.
- A new `curricula` table:
  ```
  curricula (id, user_id, source, source_run_id, name,
      problem_ids_json, created_at, completed_at)
  ```
  `source = 'credentials'` or `'manual'`. The scheduler grows a
  new strategy `CurriculumStrategy` that surfaces problems from
  the active curriculum first.

**Scope.** Phase 1 is ~1.5 days. Phase 2 is ~2 days (LLM service +
side-by-side rendering). Phase 3 is ~2 days (curriculum modeling +
scheduler strategy). All three together are a real two-week sprint
including authoring + visual polish; recommend shipping them
sequentially with the user reviewing each phase.

**Open design question.** Whether the inferred-from-credentials
score is rendered as a *second* pentagon (clean comparison, more
chrome) or overlaid on the same pentagon as a translucent "expected"
polygon outline. The overlay reads denser but takes one glance;
side-by-side reads cleaner but takes more vertical real estate.
I'll mock both and let you pick before implementing Phase 2.

### 6) Multi-modal Today (curriculum learning flow)

**Shape change.** "Today" stops being just-scheduled-problems and
becomes a daily learning sequence with four ordered modes:

1. **Readings** — one chapter or paper section, checkable when done.
2. **Watch / Listen** — a short video or podcast tied to the day's topic.
3. **Practice** — small guided exercises that apply the reading.
4. **Compose** — the existing scheduled code-compose / debug / algo
   problems.

Each section is presentable empty (placeholder copy with intent) so
the architecture is visible before content lands. Compose is already
live; Readings / Watch / Practice are authored content + scheduling.

**Schema (new migration 007).** A unified `content_items` table
that any mode can populate; problems remain as-is for now but
become a special case of content_items in a later refactor:

```
content_items
  id              INTEGER PK
  kind            TEXT       -- 'reading' | 'video' | 'podcast' | 'exercise'
  slug            TEXT UNIQUE
  title           TEXT
  source          TEXT       -- book title, podcast feed, paper URL
  url             TEXT       -- external link (paper, YouTube, RSS item)
  duration_min    INTEGER    -- estimated time
  axes_json       TEXT       -- which of the 10 skill axes it touches
  prerequisites_json TEXT    -- IDs of prior content_items
  content_md      TEXT       -- markdown body (excerpt, summary, exercise prompt)
  authored_by     TEXT
  authored_date   TEXT
  version         INTEGER
content_progress
  user_id   INTEGER
  content_id INTEGER
  status    TEXT  -- 'unread' | 'in_progress' | 'completed'
  checked_at TEXT
  notes_md  TEXT
  PRIMARY KEY (user_id, content_id)
```

Content is authored as markdown files in
`content/{readings,videos,exercises}/<slug>.md`, parsed the same way
as problems. The existing `Problem` and the new `ContentItem` share
the structural pattern.

**Scheduler.** A `DailyCurriculumStrategy` builds a Today by picking
one item per mode whose axes match the user's weakest stat (from
the assessment + recent attempts). Falls back to "least recently
attempted within axis" when no obvious gap match.

**Authoring** is the heavy lift. v0 ships the schema, the home-page
slots (already done — placeholders are in place), the scheduler, and
a starter set authored from the user's reading stack:

| Reading | Source | Axes |
|---|---|---|
| The Rust Book Ch.4 — Ownership and Moves | Klabnik/Nichols | rust_fluency |
| The Rust Book Ch.9 — Error Handling | Klabnik/Nichols | rust_fluency |
| Programming Rust Ch.5 — References | Blandy et al. | rust_fluency |
| ML with PyTorch — Transformer chapter | Raschka et al. | transformer_internals |
| ML with PyTorch — Normalization | Raschka et al. | transformer_internals, numerical_stability |
| Attention Is All You Need §3.2.1 | Vaswani et al. | transformer_internals |
| LayerNorm paper (Ba et al.) | Ba/Kiros/Hinton | numerical_stability |
| Sycophancy eval methodology (capstone draft) | user's capstone | eval_design |
| Hamming Ch.1 — "Foundations" | Hamming | (cross-cutting; reflection) |

(That's 8-9 readings as a starter batch; ~1 paragraph of summary +
the canonical link + axes tags each. ~4 hours batched.)

**Video / podcast** content is harder — we don't author it, we curate.
v0 surfaces 1-3 videos per axis (e.g., Karpathy's "Let's build GPT,"
3Blue1Brown's transformer series, Anthropic interpretability talks,
Latent Space podcast episodes for breadth). Curation as a one-off
script that hits a hand-maintained YAML.

**Exercises** are the trickiest authoring surface — they should be
shorter than compose problems but longer than warmups, and they
should pair tightly with a reading. v0 authoring rate is ~1 exercise
per 2 readings.

**Phases.**

*Phase A — Shape only (✅ landed).* Today restructured into
four sections; thoughtful empty states; nav restructured with Today /
Skills / Library / Settings.

*Phase B — Content schema + scheduler (✅ landed).* `content_items`
+ `content_progress` tables (migration 006), `ContentRepository`,
content loader for `content/{readings,videos,podcasts,exercises}/`,
`pick_daily()` picker that prefers items aligned with the user's
weakest assessment axes. `/content/<slug>` view with markdown body
and mark-complete action. The home page now surfaces a real reading
+ video/podcast per day from the picker; Practice stays
empty-stated until exercises author.

*Phase C — Starter content batch (✅ landed, 20 items).* Authored:

Readings (8):
- Vaswani §3.2.1 (attention)
- Rust Book ch. 4 (ownership)
- LayerNorm paper (Ba et al.)
- Karpathy "A Recipe for Training Neural Networks" (training + debugging)
- Rust Book ch. 10 (generics, traits, lifetimes)
- Programming Rust 2e ch. 5 (references)
- ML with PyTorch ch. 16 (transformers)
- Sennrich BPE paper

Videos (3): Karpathy GPT, 3B1B attention, Karpathy tokenizer.

Podcasts (1): Latent Space on evals.

Exercises (8): shape-trace, where-does-mask-go, Rust move semantics,
Rust signature choice, spot-LN-bug, when-RMSNorm, BPE merge
prediction, training-loop ordering bug.

**Axis coverage** after the second sprint (2026-05-13): transformer_internals
(9), training_mechanics (5), rust_fluency (5), data_pipeline (4),
numerical_stability (3), tokenization (3), algorithmic (3), debugging
(2), sampling_decoding (1), eval_design (1).

Phase C extension (✅ landed): authored r09 (The Pile), r10 (SemDeDup),
r11 (Hamming Ch.1-2), r12 (two-pointer patterns), v04 (Karpathy
makemore), e09 (sliding window trace), e10 (spot the dedup bug).
data_pipeline and algorithmic axes are no longer at 0.

Remaining backlog: more sampling/decoding depth, more eval-design
depth (Apollo Research write-ups, METR evals).

**Rating-aware picker (✅ landed).** `pick_daily()` now blends three
signals into a single score:
- Weak-axis overlap (existing): +1 per matching axis.
- Average historical rating across the item's axes, centered on 3:
  5★ axis = +0.4; 1★ axis = -0.4.
- Duration as a milli-tiebreak (shorter preferred).

`ContentRepository.axis_ratings_for_user()` aggregates ratings from
completed content per axis. Effect: once you start rating things,
the picker preferentially surfaces content from axes you've signaled
enjoyment of, and avoids axes you've rated low — *even when those
axes are nominally "weak"* and would otherwise be prioritized.
"Don't surface content the user already rejected" wins over
"surface what closes the gap" by a calibrated margin.

*Phase D — Curation polish.* Defer until usage signals which axes
need more breadth.

*Phase E — Exercise authoring (✅ landed).* 6 exercises authored as
markdown with native `<details>` answer-reveals:
- 2 on attention (paired with Vaswani §3.2.1)
- 2 on Rust ownership (paired with Rust Book ch. 4)
- 2 on LayerNorm (paired with the Ba et al. paper)

Render via the existing `/content/<slug>` flow; mark-complete works
the same as readings/videos. Markdown renderer flipped to
`escape=False` so authored `<details>` blocks pass through; safe
because all rendered content is author-controlled.

*Phase F — Progress feeds scheduler (✅ landed).* The weighted
scheduler grew a new `content_aligned` component:
- `problem_axes(problem)` maps a problem's tags + problem_type to
  the 10-axis assessment space.
- `_recent_content_axes(uid)` returns the set of axes touched by
  content items the user completed within the last
  `content_aligned_recency_days` (default 3).
- `Scorer.score()` adds `content_aligned = weight × min(overlap, 3) / 3`
  when there is overlap. Saturates at 3 overlapping axes so a single
  topic can't dominate.
- Default `weight_content_aligned = 1.5` in `config.toml`.

UX: the why-surfaced expander on each problem card now shows the
content-aligned line when relevant — making the connection between
"I read the attention paper" and "the attention problem is on top
today" explicit. Verified end-to-end with a mock user who completes
r01 (Vaswani §3.2.1) and sees both `scaled-dot-product-attention`
and `debug-causal-mask` get a +0.5 boost.

*Phase E — Exercise authoring.* 5-8 small applied exercises pairing
with readings. ~1 day.

*Phase F — Mode-aware progress.* Check-off UI on readings/videos;
progress feeds a new `content_completed` axis component in the
scheduler so the user's compose problems start aligning with what
they read that day.

### 7) Originally-planned v1.5 items (still on)

- Notes attached to attempts (`notes` table exists)
- Paper-source ingestion (`sources` table exists)
- Reading-mode UI (reserved `paper_*` problem_types)

These follow the phase-spine and onboarding work; they benefit from
the same restructuring.

---

## v2 — adaptive + LLM-mediated

### 1) Phase-aware hint ladder (was #5, reframed) ✅ infra landed; authored hints pending

**Landed:** every phase on a non-interview problem page now has a
"Stuck? Get a nudge" button. Click sends current phase notes (or code
for Implement) to `POST /hint/<slug>` with a per-phase count; Haiku
4.5 returns a tiered hint (1 nudge → 2 direction → 3 scaffolding)
that swaps into the slot below the textarea. Tier escalation is
monotone — request 3 resolves to "you're at the end of the ladder."
Fallback path (no API key / model error) returns generic
process-focused nudges per phase.

`attempts.hints_used_json` records `{phase: count}` per submitted
attempt. The scheduler reads `max_tier_reached` and adds a
`weight_used_hints` component (default 0.6, mirrors `used_reference`)
scaled by tier/3, so a tier-1 hint barely budges the score while a
tier-3 hint penalizes ~full.

**Still TODO:** author per-problem hints inline in the `.md`
frontmatter so the LLM has a reference ladder to anchor to (the
roadmap example in the next section). Until then every hint is
LLM-generated from prompt + user notes.

Replaces the current "look at solution / pitfalls" toggle for users
who opt into hint mode.

**Authored content per problem:**
```markdown
## Hints

### Explore
1. nudge: "What are the shapes? Write them down."

### Plan
1. nudge: "What's invariant when you transpose?"
2. direction: "Where does the scale factor go in your equation?"

### Implement
1. nudge: "PyTorch's softmax has a `dim` arg."
2. direction: "Mask before softmax, not after."
3. scaffolding: "`scores = scores.masked_fill(mask, float('-inf'))`"

### Verify
1. nudge: "What's the test for causality?"
```

**Trigger logic** is phase-aware: hints unlock per the phase the
user is currently in, with time thresholds (50% / 20% / 10% of the
problem's time budget). User can always click ahead of the timer.

**LLM fallback (Haiku):** when authored hints are exhausted or
absent, Claude receives: prompt, user's current notes for that
phase, user's code (if Implement), and hints already shown.
Returns one additional non-revealing hint.

**Scheduler interaction:** `looked_at_hint_phase_N` becomes a per-
phase weight in the due_score. Higher tier = bigger boost.

**Cost:** authoring ~3-4 hints/problem × 4 phases × 31 problems is
the heavy lift. ~1 week batched.

### 2) Skill-aware scheduling (was #2)

Now phase-aware:

- Per-tag, per-phase rolling pass rate (last 5 attempts).
- New scheduler component `weight_difficulty_match` rewards
  problems that match the user's current floor per (tag, phase).
- Cold-start uses the **initial assessment** as the seed instead of
  generic defaults — directly addresses the "where do I start?"
  question.
- Cap the floor-matching weight so `never_attempted` still wins
  some of the time; prevents plateau.

**~2 days** once assessment data exists.

### 3) LLM-graded solution review (✅ landed)

After submit, Sonnet 4.5 receives the problem + the user's phase
notes + final code + reference solution + test pass/fail, and returns
a structured per-phase critique. Three sentences per engaged phase —
one specific strength, one specific gap, one open question — plus a
two-sentence summary and an overall confidence score.

System prompt explicitly anti-sycophancy: "If notes are thin, say so
directly. If the code is buggy, name the specific bug, not 'could be
improved.'"

Skipped silently when `ANTHROPIC_API_KEY` isn't set; the result panel
shows a small note instead. Reviews persist on
`attempt_reviews` (migration 008); revisitable at
`/attempt/<id>/review`.

Sample render (synthetic): see
`data/snapshots/review-test/review-claude--dark.png`.

### 4) Phase-aware approach feedback (was #7, reframed)

Replaces the keystroke-analysis framing entirely. Sonnet receives:
- Problem prompt and phase prompts
- User's Explore / Brainstorm / Plan / Verify notes
- Final code
- Reference solution + test result
- Time spent per phase

Returns a phase-by-phase report: one strength, one gap, one
question per phase. Aggregates per phase × topic into the skill
graph data.

**Cost:** Sonnet per attempt is ~$0.01-0.03. At 3 attempts/day =
~$1-3/month. Acceptable for a solo tool.

### 5) Reflection / Hamming mode ✅ landed

A weekly review surface, separate from the per-problem flow. Pulls
the last 7 days of attempts, runs them through Sonnet with a
prompt informed by Hamming's "The Art of Doing Science and
Engineering" — what are you avoiding, what's compounding, what's
the biggest problem in your stack right now? Output: a short
prompt-set the user answers in writing. Stored under the existing
`notes` table.

This is where Hamming sits in the product — not on individual
problem pages.

### 6) JD-aware adaptive ranking (✅ landed)

Paste a JD; Claude (or a keyword fallback) parses it into:
- per-axis weights across the 10 assessment axes,
- a list of `signal_tags` from a curated taxonomy
  (interpretability, evals, sycophancy, rlhf, alignment, transformer,
  rust, inference, agents, robustness, …).

The user activates one JD at a time (`users.settings_json.active_jd_id`).
While active, the scheduler grows a `jd_aligned` weighted component
that blends:
- 60% axis match (the JD's axis weights × the problem's axes), and
- 40% tag match (the JD's signal_tags ∩ the problem's
  `jd_signal_tags` already authored on every problem).

A `Focused on …` banner appears on the home page; the compose card
order shifts to surface what the role wants. Verified end-to-end
with a synthetic Anthropic interpretability JD: the scheduler
correctly prioritized `multi-head-attention-reshape` (jd_aligned 1.50)
over other compose problems.

Routes: `/jds` (paste + list), `/jds/<id>` (detail with axis
emphasis chart + signal tags), `POST /jds/<id>/activate`, `POST
/jds/clear-active`, `POST /jds/<id>/archive`. Linked from
`/settings`.

---

## v3 — visualization + advanced LLM

### 1) Skill graph (was #8, now phase-aware)

Heatmap with two axes:
- Rows: distinct `competency_tags` from the corpus
- Columns: phases (Explore, Brainstorm, Plan, Implement, Verify)

Cell color = rolling pass quality × phase quality from LLM review
(v2 above). Saturation = recency / sample size.

Server-side SVG (or styled `<table>` with CSS Grid) — stays no-SPA.

**Onboarding seeds the first version of this graph.** Even with
zero attempts, the assessment produces a coarse heatmap; that's
how the user gets immediate "where am I?" feedback.

**LLM-generated summary (Sonnet, optional):** sends the
tag-phase-quality matrix and returns a 3-paragraph summary of
strongest area, biggest gap, suggested focus.

**Gate full display until N ≥ 15 real attempts** (assessment-only
data is shown with a "based on self-assessment" caveat).

**~3-4 days**, depending on viz fidelity.

### 2) Interview mode (✅ landed)

A timed, no-aux-pane variant of the problem flow. Engaged via
`?mode=interview` on any non-warmup problem. What changes:

- All aids hidden: reference solution, pitfalls, key insight, and
  per-phase docs links are completely removed from the page. A
  small dashed note explains they'll surface on the result page.
- Prominent countdown timer in the problem head, ticking down from
  the problem's `time_bucket`. Fires alert banners at 50% / 20% /
  10% remaining and at zero (no auto-submit — the user submits
  deliberately).
- phase scaffolding stays — phases are how the candidate
  *thinks*, not aids.
- New `interview_mode_bool` column on `attempts` so post-hoc analysis
  can separate practice from interview attempts.

The review service branches on `attempt.interview_mode`:
- Practice attempts use the original system prompt.
- Interview attempts use a stricter Algo-Interviews rubric prompt
  that's harder on calibration and additionally returns six
  structured signals: assumption_clarification, multiple_approaches,
  complexity_stated, plan_before_code, code_quality, verification.
  Each signal is rendered as a tier-colored cell in the result panel,
  visible at a glance.

Entry points: a `try in interview mode →` link below every scheduled
problem card on Today, plus a top-of-page CTA on regular problem
pages.

**Optional voice-to-text** for narration is deferred to v3.

### 3) Voice / multimodal review

Two distinct surfaces; both share the same audio-capture + Whisper
transcription plumbing.

**3a) Voice reflection on content (priority).** A 🎙 button on
every `/content/<slug>` page that records audio and transcribes it
into the existing `notes_md` reflection field. Use case: walking
with the bench, listening to a podcast, dictating thoughts on a
paper without typing. Pairs naturally with the Hamming weekly
reflection — voice notes accumulate into the dataset Sonnet
summarizes on Sunday.

Implementation: Web Audio API → record locally → POST to
`/content/<id>/voice-reflect` → server forwards bytes to Whisper
(`whisper-1`) → returns transcript → user can edit before save.
Storage stays the same column (`content_progress.notes_md`).

Roughly **~6 hr build** (audio capture is the most surface area;
the server side is a single Anthropic call).

**3b) Voice mode for interview / exercise.** Sonnet receives the
voice-transcribed narration + code + phase notes and grades against
the algo-interview rubric: clarifying questions asked, brute-force-
first considered, complexity stated, trade-offs surfaced, edge
cases verified.

Builds on 3a — same recorder, different endpoint, different
grading prompt. The interviewer side ALSO needs streaming
transcription so the user sees their own narration land in real
time (otherwise it feels like talking into a void). Whisper has
streaming support but the API ergonomics differ; ~1 day for the
streaming UX vs ~2 hr for batch.

**Storage** for both: a new `voice_recordings` table with
`(id, user_id, source_kind, source_id, audio_url, transcript_md,
created_at)` — audio_url points at Supabase Storage. We don't keep
the audio bytes in Postgres.

### 4) Process-trajectory capture (was the original #7)

The keystroke-analysis idea isn't gone — it's just lower priority
than phase content. In v3 we add fine-grained event capture (paste
detection, edit clusters, idle periods) layered onto the phase
content, giving the LLM review even more signal.

---

## Cross-cutting items

### Phase authoring

Each new feature in v1.5+ requires problem-level phase authoring:
phase prompts, hint ladders, reference links. Plan for this as a
**recurring content sprint** — ~half a day per release.

### LLM infrastructure

- `app/services/llm.py` — single Anthropic client.
- **Prompt caching** for the problem-content prefix when calling
  per attempt (review, hints, post-submit feedback) — saves cost.
- Model picks: Haiku 4.5 for hints (latency matters, quality bar
  lower), Sonnet 4.6 for graded review and phase feedback (default),
  Opus 4.7 only for the optional skill-graph summary.

### Telemetry to instrument

- Plan-gate: bypass rate, average chars before gate opens.
- Per-phase time distribution. Outliers (zero-time Brainstorm,
  no-Verify) are tell-tale habits to surface to the user.
- Hint ladder: distribution of tier stopped at, pass rate with
  hints on vs off.
- Onboarding: completion rate, retake frequency, time-to-first-
  solved-problem.

### Branding

If "Li's Bench" sticks, reserve a clean domain
(`lis.bench` or `bench.libearden.dev`) ahead of any hosted version
in v3+.

---

## Items not in any phase

- **Mobile-first redesign.** Laptop-primary, tablet OK, mobile
  graceful-degrade. Current responsive CSS suffices.
- **Problem-authoring UI.** Markdown + git is the contract.
- **Streaks / gamification.** Still no.
- **Themes / narrative framing (captured idea, unscheduled).**
  User-configurable themes so a learner can make the bench feel like
  their own — beyond light/dark, a chosen aesthetic and optional
  narrative overlay for their journey. Motivating example: staging a
  career transition as themed "sagas" (à la one operator running their
  OpenClaw agents as Dragon Ball characters). Fits the north-star
  personalization pillar ("adapts to the individual") — a low-stakes
  way to increase belonging/retention. Scope TBD: at minimum a theme
  picker in `/settings` layered on the existing token system
  (`static/css/main.css`); narrative framing (renaming phases/tracks/
  milestones into a chosen motif) is a later, larger layer.
- **Public sharing of solutions.** Out of scope for an internal
  tool.
- **Real-time multiplayer / pair sessions.** Out of scope.

---

## v2 — UI Redux (deferred from in-cycle feedback)

The v1 surface is intentionally a single linear scroll on every
page. That worked while the platform was small — but the user
flagged it explicitly: *"the completely linear/infiniscroll
interface isn't super useful on all of the pages, but we can
footnote that for a v2 ui redux"*. This phase collects the
information-architecture work that's been accumulating.

### 1) Skills page full redux (from feedback #3)

The current Skills page renders the stat pentagon, an axis
breakdown table, and a long timeline of attempts in one column.
After enough attempts it becomes a wall. Redesign targets:

- **Pentagon as the hero, not the table.** Move the per-axis
  ratings + per-axis history into a tabbed or accordion structure
  under the pentagon — one axis at a time, default open on the
  weakest.
- **"Strengths / Gaps / Plateaus" framing.** Skills isn't just
  current state — it's trajectory. Surface 7-day deltas next to
  raw confidence. Plateau = no movement in N days on an axis with
  attempted problems.
- **Attempt density timeline.** A small calendar-heatmap-style
  strip (GitHub contribution graph energy) showing days with
  attempts, color-keyed by axis. Replaces the linear attempt log.
- **Compare against JD.** When a JD is uploaded, overlay its
  axis weights on the pentagon (different stroke). Already half
  built via the JD-aware scheduler.

### 2) Linear/infiniscroll → information architecture pass

The user's meta-note covers more than Skills. Pages that today
read as one long column and should be reshaped:

- **Today.** Sections (Reading / Listening / Practicing /
  Composing / Writing) are correct but stack vertically forever.
  Consider a 2-column above-the-fold (today's queue + journal
  preview) with secondary sections below.
- **Library.** Three lists (content, cores, warmups) plus
  favorites plus filter chips is a lot of vertical scroll. A
  two-pane layout — filters/facets on the left rail, results
  on the right — would shorten the page to ~one viewport.
- **Problem page.** Five phases stacked is correct, but the
  References + Approach + Submit sections after the editor turn
  the page into a 3000px scroll. Consider sticky right-rail nav
  jumping between phases.
- **Feedback inbox.** Now has Open/Backlog/Closed tabs (landed),
  which is the small version of this work for one page.

Common pattern: replace "scroll until you find it" with "tab,
filter, or rail until you find it."

### 3) Writing editor formatting + AI/Substack integrations (from feedback #1)

Today's `/writings/<id>` is a plain textarea. Lift to a richer
editor that fits the alignment-forum / substack drafting flow:

- **Formatting toolbar.** Bold/italic/code, headings, link,
  blockquote, ordered/unordered lists. Server-side markdown
  already renders these — surface them in the input.
- **Substack export.** "Publish to Substack" action that pushes
  the markdown to the user's connected Substack via API. Needs
  OAuth + a connections page in Settings.
- **AI editor companion.** A right-rail panel that, with the
  user's CV + JD + recent attempts in scope, can:
  - critique structure ("the third paragraph buries the lede"),
  - flag claims that need a citation,
  - suggest related Pile/SemDeDup/etc. references from the
    user's already-read material,
  - tailor tone to the venue (alignment forum vs substack).
- **Alignment Forum readiness check.** A scoring rubric (claims
  precision, citation density, novelty vs. prior post) that
  runs against AF norms. Output: "this is ready" vs. "this is
  a draft" + the specific gaps.

### 4) Linear integration for feedback (from feedback #4 part 2)

Today's feedback inbox is local-only and has already been wiped
twice by `--reset` regressions in `scripts/snapshot.py` and
`scripts/mock_user.py`. The destructive warnings are in place
but the durability story is still bad. Lift the source of truth
to Linear:

- **Project: `Li's Bench Feedback`** under the existing
  Linear workspace. Each feedback row becomes a Linear
  issue on create. Status maps: open → Todo, backlog → Backlog,
  archived → Done, dismissed → Canceled.
- **Sync direction.** Bi-directional. Writes go to Linear via
  the MCP. Reads pull from Linear at session start and cache
  locally for offline use.
- **Inbox.md** mirror becomes derived state, regenerated from
  Linear, not from SQLite.

This kills the data-loss class outright and gives the user a
single triage queue across Claude sessions, mobile, and the web
client.

### 6) Observability: Sentry ✅ landed (paused on the rest)

Sentry SDK wired in `app/observability.py`, initialized from
`app/main.py` before the `FastAPI()` instance so middleware
auto-wraps. `SENTRY_DSN` lives in `.env.local`; soft-fails if blank.
Production-ish defaults: `send_default_pii=False`,
`max_request_body_size="never"`, traces sampled at 10% in non-local
environments. Release tag pulled from `pyproject.toml`. Self-test
endpoint at `/__sentry/test` (registered only when the SDK
initialized) raises a `RuntimeError` so the user can verify events
hit their Sentry inbox.

**Deliberately deferred:** Better Stack, PostHog, Resend, Supabase /
multi-user auth. All four serve a deployed-multi-user product
shape — the tool is still local single-user. Add them as part of
the deploy-to-`libearden.dev/bench` work, not before.

### 7) External content ingestion ✅ landed

The "all-in-one platform" gap the user named: incorporate
DeepLearning.ai videos, BlueDot readings, Coursera lectures, etc.
into the same daily rotation as authored content.

`/library/add` form takes title, kind, source (curated dropdown +
"Other" free-text), URL, duration, axes (checkbox grid against the
10 assessment axes), and optional markdown notes. Slug auto-derived
from the title with an `x-` prefix and uniqueness suffix; URL is
validated for `http(s)` only. Stored in `content_items` with
`source_kind='user'` and `created_by_user_id`. Migration `017`.

Surfaces uniformly with authored content: daily picker, ratings,
reflections, cross-links, library list. Visually flagged via
`.badge--external` (brand-tinted pill) on library rows and the
content detail header. Startup `content_loader` only touches
`source_kind='authored'` rows so user-added items survive restarts.

**Not in v1:** auto-fetching content from gated platforms (each LMS
is its own scraping problem), calendar integration (multi-day
work), auto-progress tracking from external LMS APIs.

### 5) Skills + content + writings cross-linking ✅ partial

**Landed:**
- Per-content page: "What you attempted after this" footer — attempts
  started within 7 days of marking the content complete, intersected
  on skill axes. Sorted oldest → newest so the user sees the arc.
- Per-attempt page: "What you read before this" footer — symmetric:
  content completed in the 7 days before the attempt, axis-overlap
  required. Shows ratings and time delta.

Inference is time-window + axis-overlap; the headers phrase it
honestly ("within 7 days") so false positives don't read as claims of
explicit citation.

**Still TODO:** the writings sidebar auto-suggest from last-week
activity. `source_refs_json` already exists on writings; the
seeded-draft creation path populates it but there's no live picker
yet for users adding refs to a draft they're already editing.
