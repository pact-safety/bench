# Proposal: Content engine v2 — same-day reading → paired exercise

**Status:** draft — awaiting operator review

**Author:** Claude (under operator delegation)

**Date:** 2026-06-19

**Predecessor:** Existing `/library` + scheduler + crosslink-after-attempt
surface; the WS4 right-rail integration on `/today`; the fieldbuilding
push that's queued behind OpenClaw + MATS Phase 2.

**Motivation:** the operator's framing 2026-06-18 — "we also need to get
some sort of content engine brought in, with exercises closely related
to papers read the same day. the whole thing needs to read as a
first-class fieldbuilding tool that engineers from other disciplines can
use to get ramped up to work at the frontier of AI safety."

## Problem

The bench has the components — `/library` curates evergreen reading,
the scheduler picks problems by axis-match, the crosslink surface
shows "what you read before this attempt" — but the **forward arrow is
missing**:

> *I just finished a reading. The bench knows the axes it touched. It
> should immediately surface "now try this" — a problem (or short
> exercise) that lets me apply what I just learned, today, while it's
> warm.*

Currently the operator finishes a reading and has to navigate to
`/today/next` or pick a problem manually. The axis signal exists in
both directions; only the reverse direction is wired.

For the fieldbuilding push specifically, this is the highest-leverage
piece: an ML/SWE engineer landing on the bench for the first time isn't
going to thread their own loop between *"read the layernorm paper"* and
*"now drill softmax-with-temperature."* The bench has to thread that
loop for them, **in the same session**, or the workflow doesn't take.

## Goal

Whenever the operator completes a content item, the bench surfaces a
**paired exercise** within seconds, on the same page (`/content/<slug>`)
AND on `/today`. Pairing is axis-tight (the exercise shares ≥2 axes
with the reading) and time-tight (same-day; the reading's axes haven't
faded). When no authored problem matches, the bench falls back to an
LLM-generated micro-exercise rather than failing silently.

## Scope

### v1 — same-day paired exercise (no LLM)

- New service `app/services/content_pairing.py` with:
  - `pair_for_content(content_item, recent_attempts, all_problems, now) → list[Problem]`
  - Ranks unattempted problems by axis-overlap + freshness + difficulty fit
  - Returns top 1-2 candidates; empty list when nothing matches well
- After a reading is marked complete (`POST /content/<id>/check`),
  the response includes a `paired_exercise` field consumed by:
  - A new banner on `/content/<slug>`: *"Now try this — paired exercise
    for what you just read"* with the problem title + one-click Start
  - A new rail card on `/today`: *"Practice — pair with today's reading"*
    when at least one reading was completed today and a problem matches
- Mark the pairing on the attempt row so the calibration data tracks
  *"attempts that came from a same-day reading pair"* separately from
  scheduler-picked attempts; useful for the post-launch quality bar
  ("are paired-exercise attempts more successful?")

### v2 — LLM-generated micro-exercises

Depends on v1 shipping + a few weeks of "no pair found" data so we
know how often the fallback fires.

- When `pair_for_content()` returns nothing, call Haiku with a short
  prompt: "given the reading's content_md + axes, generate a 5-10
  minute exercise that lets the operator apply this. Output JSON with
  title, prompt_md, axes, difficulty"
- Generated exercise is one-off (not persisted to the library) by
  default; the operator can promote it to a real authored problem
  via a button
- Spend-cap-gated (one cap-hit returns "no pair this time" gracefully)

### v3 — fieldbuilding curriculum defaults

Depends on v1 + the bench shipping publicly (Docker + open-source push,
queued behind MATS).

- Curated AISF / MATS / METR / ARENA / ARENA-adjacent readings as the
  default `content/readings/` library content (vs. the operator's
  current personal stack)
- Per-axis "first-N-readings" track: an ML engineer who joins the
  bench picks "I want to ramp into mech interp" → bench surfaces a
  curated 8-week curriculum of readings + paired exercises
- Fork-friendly: each `content/curricula/<name>.toml` declares a
  track; forks can ship their own (e.g. BlueDot-specific, MATS-cohort,
  etc.)

## Data model

### v1 additions

```sql
-- Migration 016_content_pairing.sql (CODEOWNERS — flagged human-only)
ALTER TABLE attempts
  ADD COLUMN paired_from_content_id BIGINT REFERENCES content_items(id),
  ADD COLUMN paired_from_completion_at TIMESTAMPTZ;
```

Both NULL on scheduler-picked attempts and on warmups. Only set when
the operator clicked into the problem from a paired-exercise banner.

### v2 additions (deferred)

```sql
-- Migration 017_llm_generated_exercises.sql
CREATE TABLE llm_exercises (
  id BIGSERIAL PK,
  user_id UUID NOT NULL,
  source_content_id BIGINT REFERENCES content_items(id),
  axes JSONB NOT NULL,
  difficulty TEXT,
  title TEXT NOT NULL,
  prompt_md TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  promoted_to_problem_slug TEXT  -- NULL until operator promotes
);
```

## Services

### v1: `app/services/content_pairing.py`

Pure functions over the loaded `Problem` list + content item + recent
attempts. No I/O.

- `axis_overlap(content_axes, problem_axes)` → int (count of shared axes)
- `is_fresh(problem, recent_attempts, days=14)` → bool (unattempted in last 14d)
- `difficulty_fit(problem, operator_skill_at_axis)` → float (0..1)
- `pair_for_content(content_item, recent_attempts, all_problems, now)`
  → list[Problem] (top 2 by `axis_overlap * 2 + difficulty_fit + freshness_bonus`)

Tuning weights are in `config.toml` so the operator can dial them
without a code change.

### v2: `app/services/exercise_gen.py` (new — when v2 lands)

- `generate_paired_exercise(content_item, user_id) → LLMExercise | None`
- Haiku call with spend-cap + offline-fallback pattern matching
  hints/review/jds
- Caches generated exercises by `(content_id, axes_hash)` so two
  operators on the same fork get one generation, not two

## UI surfaces

### v1

- **New section on `/content/<slug>`** below the existing rating +
  notes UI: a "Now try this" callout when a pair exists. Hidden when
  no pair found. Single CTA: "Start the exercise →" links to
  `/problem/<slug>?paired_from=<content_id>`.
- **New rail card on `/`** alongside the active-initiatives + signal +
  weak-axis cards: "Practice — pair with today's reading" surfaces
  when any reading was completed today and `pair_for_content` returns
  ≥1 candidate. Compact: one row per pair, click-through to the
  problem.
- **`?paired_from=<content_id>`** query param on the problem page is
  the trigger that sets `paired_from_content_id` on the attempt at
  submit time.

### v2 — LLM fallback

- Same surfaces; the callout copy changes when the suggestion is
  LLM-generated: "Generated paired exercise" with a small "iffy?
  promote to real problem" or "skip" affordance.

### v3 — curriculum surfaces

- New `/curricula` index page
- New `/curricula/<slug>` detail page (timeline + progress + the
  curated reading/exercise pairs in order)
- "Pick your ramp" widget on `/onboarding`

## Cost estimate

v1 has zero LLM cost — pure axis math.

v2 (LLM fallback): assuming ~5 "no pair" events per active operator
per week × 1500 input tokens (content_md snippet + system prompt) ×
~300 output tokens × $0.25 input + $1.25 output per 1M tokens (Haiku
4.5) = ~$0.001 per generation. **Negligible.** Even at 100 active
operators it's pennies. The spend cap exists for safety, not budget.

## Phasing & rough sizing

| Phase | What | Rough effort | Depends on |
|---|---|---|---|
| **v1** | Axis-pairing service + DB columns + two UI surfaces + tests | 1 PR · ~500 LoC + migration | Standalone. Can start after the EM rename + Docker scaffold land. |
| **v2** | LLM-generated micro-exercise fallback | 1 PR · ~400 LoC + spend-cap wiring | v1 + the no-pair rate is non-trivial |
| **v3** | Curriculum defaults + `/curricula` surface + fork-shipping | 2-3 PRs · ~1500 LoC across new content + new surfaces | v1 + public release (Docker + open-source) |

## When to start

After:
1. The EM/Formation rename (PR #357) lands — public branding has to be
   clean before the content pairing UI ships any new copy
2. The Docker / open-source push completes — the curriculum work in
   v3 is the part that makes the fieldbuilding story concrete; it
   shouldn't ship until the tool itself is forkable
3. MATS Phase 2 prep is done — this is your prep tool; don't disrupt
   the surface mid-prep

v1 specifically is the highest-leverage immediate piece. Once those
three precursors clear, v1 should be the next implementation push.

## Open questions

1. **Pair vs. propose multiple.** v1 returns top 1-2. Should the
   surface always show ONE pair (the highest-ranked) for decisiveness,
   or show 2-3 and let the operator pick? My default: one + a "see
   alternatives" disclosure. Decide during implementation.
2. **Time horizon for "same-day."** Strict (today, midnight to
   midnight) or rolling (last 12 hours)? Default: strict, but
   reading completed within the last 4 hours gets a heavier ranking
   bonus.
3. **What counts as completion** — `progress.status == 'completed'`
   only, or also "started but rated highly"? Default: completed only;
   `started` is too noisy.
4. **Pairing rate budget.** What's a reasonable target — every
   reading should have a pair surfaced 80% of the time? 50%? Drives
   v2's threshold for when to fall back to LLM generation.
