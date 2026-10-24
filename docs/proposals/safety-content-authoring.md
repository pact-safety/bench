# Proposal — safety-content authoring plan

Closes the **thesis gap** from the internal platform audit
(Dimension A): the AI-safety competency axes exist in the model but have
near-zero content, so a "safety fieldbuilding tool" can't actually assess or
train the competencies it exists to build. This is the plan to author that
content **before** spending on generation — per the operator's "plan it first"
call.

## What's empty today

From `app/services/assessment.py`:

- `ai_safety_fundamentals` — **0 assessment questions, 0 practice.**
- `mechanistic_interpretability` — **0 assessment questions**; practice is
  outsourced entirely to the external `mechinterp` / `arena_3` tracks.
- `ai_governance_strategy` — **0 assessment questions, 0 practice.**
- `eval_design` — has questions, but only **~1 authored practice problem**
  (`content/problems/13-sycophancy-eval-scoring.md`).

These three safety axes "default to 0 in `final_scores` until questions are
authored" (`assessment.py:47-48`). A safety-heavy JD surfaces them as gaps the
learner can't currently close inside bench.

## Design principle — differentiate content type by axis

The audit's mistake to avoid is "author N code problems per axis" uniformly.
The axes differ in how they can be practiced:

| Axis | Assessment Qs | Practice content type | Why |
|---|---|---|---|
| `eval_design` | +2–3 | **Original code problems w/ tests** | Highly code-able: scoring, aggregation, paired-comparison, contamination checks — all self-contained Python. |
| `ai_safety_fundamentals` | +3 | **Mixed: short applied problems + concept Qs** | Some is code-able (a reward-hacking detector, an oversight-scoring harness); some is conceptual (threat models, specification gaming) → assessment Qs + reflection. |
| `mechanistic_interpretability` | +3 | **Small self-contained code exercises + Qs**; deep work stays in the external track | Toy exercises run bench-native (logit lens on a tiny tensor, attention-pattern analysis, activation-patching arithmetic). Full circuit work needs notebooks/GPUs → already covered by the `mechinterp` external track. Don't duplicate it. |
| `ai_governance_strategy` | +3 | **Assessment Qs + reading-linked reflection prompts, NOT code** | Conceptual by nature. Forcing it into a Python problem would be fake. Serve via questions + a curated reading track + structured reflection. |

## Assessment-question spec (must match the real format)

Questions are Python literals in `app/services/assessment.py`, appended to
`Q_POOL`. Shape (`assessment.py:77-88`):

```python
Question(
    id="qNN-short-slug",            # sequential; keep ids unique
    prompt="A concrete scenario or judgment call…",
    axes=("mechanistic_interpretability",),   # 1–2 axes per Q
    options=(
        Option("Best answer.",        {"mechanistic_interpretability": 3}),
        Option("Partial / common-mistake answer.", {"mechanistic_interpretability": 1}),
        Option("Wrong-but-plausible.", {"mechanistic_interpretability": 0}),
        Option("I'm not sure.",        {"mechanistic_interpretability": 0}),  # required
    ),
)
```

Rules: exactly 4 options; weights `0–3` per touched axis; always include an
"I'm not sure" option scoring 0; questions should be **judgment/scenario**
based (like `q02-attention-shape`), not trivia. `assessment.py` is
**CODEOWNERS-adjacent load-bearing logic** — these land in a human-reviewed PR.

Target: **~11 new questions** (2–3 per empty axis + 2 more eval_design), enough
that the deterministic selector (`pick_next`) can touch every axis within the
5–10 question budget.

## Practice-problem spec (matches existing frontmatter)

Same schema as `content/problems/*.md` (see `f0*` and `13-sycophancy-eval-scoring`):
`slug, title, difficulty, time_bucket, problem_type, structural_tags,
domain_tags, competency_tags, jd_signal_tags, original: true, authored_by,
authored_date, version` + `## Prompt / Starter / Solution / Tests / Key insight
/ Pitfalls`. **Every solution must execute against its own test block before
it's kept** (the verification gate we used for the `f0*` fundamentals).

### First-tranche problem archetypes (proposed ~12)

**eval_design (4)** — paired-comparison scorer; eval-set contamination
detector; inter-rater agreement (Cohen's κ); robustness under prompt
perturbation.

**ai_safety_fundamentals (4)** — a reward-hacking / specification-gaming
detector over a trajectory log; an oversight-scoring harness (weak-supervisor
aggregation); a refusal/jailbreak classification scorer; a simple
constitutional-critique reducer.

**mechanistic_interpretability (4, small/self-contained)** — logit-lens
projection over a provided activation tensor; attention-pattern entropy /
induction-score computation; activation-patching effect arithmetic on given
tensors; feature-direction cosine analysis. (No model download; inputs are
provided arrays — runnable in the bench sandbox.)

`ai_governance_strategy` gets **no code problems** in tranche 1 — it gets
assessment questions + a curated reading track + reflection prompts (separate,
cheaper work).

## Integration with the adaptive assessment (the vision)

This is what makes the axes *load-bearing* for "your learning, your way":
assessment questions detect weakness on a safety axis → the scheduler weights
practice toward it → the learner attempts the new problems → re-assessment
shows movement. Authoring the questions and the practice **together** is what
closes that loop; doing only one half leaves the axis inert.

## Prerequisite spine

Tag the new problems into the on-ramp so they're reachable in order (addresses
the audit's "no prerequisite spine" finding): fundamentals (`f0*`) → ML
problems (`01–26`) → **safety practice (new)**. Give the safety problems
`depends_on`-style ordering via difficulty + a shared `structural_tag` so a
future path view can sequence them.

## Execution options (for the operator to pick after review)

- **A — First tranche via workflow:** ~11 assessment Qs + ~12 verified
  problems, split into two PRs (questions = human-review PR touching
  `assessment.py`; problems = content PR). Author→execute-tests→verify per
  problem. This is the "First tranche (~12)" scale.
- **B — Go big:** all axes filled + governance reading track + reflection
  prompts in one multi-PR pass.
- **C — Hand-author:** I write a batch per turn, no workflow.

## Constraints

- IP-clean: original authoring only; external material linked, not hosted
  (governance readings + deep interp stay as external tracks). See the repo's
  `original: true` convention.
- Assessment-question PRs are human-reviewed (load-bearing scoring logic).
- Respect the stack; no new heavy deps for the interp exercises (provided
  tensors, stdlib + numpy only).

## Open questions for the operator

1. **Governance depth:** is `ai_governance_strategy` best served by bench
   questions + readings, or should it lean on BlueDot's AGI-strategy course as
   the external track and bench only assess it? (Cheaper; avoids re-teaching.)
2. **Interp scope:** are small provided-tensor exercises useful, or should
   mech-interp stay entirely external (the `mechinterp` track) with bench only
   assessing conceptual understanding via questions?
3. **Answer sourcing for eval/safety questions:** anchor them to specific
   papers/benchmarks (with links) or keep them framework-agnostic?
