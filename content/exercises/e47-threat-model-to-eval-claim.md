---
slug: e47-threat-model-to-eval-claim
kind: exercise
title: "From a vague worry to a measurable claim"
source: "prep for ARENA 3.1 Intro to Evals"
duration_min: 10
axes: [eval_design, ai_safety_fundamentals]
domain_tags: [threat model, operationalization, sycophancy, falsifier]
arena_section: "3.1"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Someone hands you the worry "the model is sycophantic" and asks for
an eval. ARENA 3.1 hands you roughly this shape:

```python
def build_sycophancy_items(n: int) -> list[Sample]:
    """Return n Samples measuring whether the model abandons a correct
    factual answer after the user pushes back.

    Each Sample carries:
      input:    the conversation up to the model's second turn
      target:   the answer that is correct regardless of user pressure
      metadata: {"condition": "control" | "pressure", "pair_id": int}
    """
    raise NotImplementedError()
```

The blank body is not the hard part. The hard part is that "sycophantic" is
not yet a claim anything can be false about.

**Question.** Before writing any code, name the 4–5 subgoals that turn the
worry into an eval. Write them down, then open the reveal.

<details>
<summary>reveal</summary>

1. **State the threat model: who is harmed, in what deployment, by what
   behavior.** Not "sycophancy is bad" — "a user asking a medical dosage
   question pushes back, the model folds, the user acts on the wrong number."
   This is prose, not code, and it decides everything downstream.

2. **Operationalize into one behavioral claim with a comparison.** Sycophancy
   is a *difference*, not a level. The claim: "under user pushback, the model
   changes a previously-correct answer more often than it changes it under a
   neutral follow-up." That forces a paired design.
   `metadata = {"condition": "control" | "pressure", "pair_id": i}`

3. **Pick the metric the claim implies.** Flip rate under pressure minus flip
   rate under control, over pairs where the control answer was correct.
   `delta = flip_rate(pressure) - flip_rate(control)`
   Filtering to correct-under-control is what makes a flip *bad* rather than
   a model correcting itself.

4. **Write items where the property is load-bearing.** The unpressured answer
   must be correct and the pushback must be socially real (a stated
   credential, a stated preference) — otherwise every model looks identical.
   See e48 for the failure mode when this subgoal is skipped.

5. **Name the falsifier and the baseline before you run.** Falsifier: "delta
   is within noise of zero across 200 pairs" means the eval found no
   sycophancy — say so in advance, in numbers, with a stderr. Baseline: a
   fixed policy that never changes its answer scores delta = 0, which tells
   you the floor your numbers sit against.

</details>

**Key insight.** Any eval whose motivating worry is an adjective ("sycophantic",
"deceptive", "power-seeking") starts at subgoal 2 — convert the adjective into a
difference between two conditions you can run, because a single-condition score
has nothing to be compared against and therefore nothing to be wrong about.
