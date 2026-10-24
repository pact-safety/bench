---
slug: e50-diversity-collapse-generation
kind: exercise
title: "Stop the generated dataset from collapsing"
source: "prep for ARENA 3.2 Dataset Generation"
duration_min: 10
axes: [eval_design, data_pipeline]
domain_tags: [dataset generation, diversity, dedup, prompt seeding]
arena_section: "3.2"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** ARENA 3.2 has you generate eval items with a model. The shape:

```python
def generate_items(model: str, n: int = 300) -> list[Sample]:
    """Generate n multiple-choice items testing whether the model prefers
    options that increase its own resources or autonomy.

    Each Sample carries input (scenario + 4 options), target, and
    metadata recording which variation axes the item was sampled from.
    """
    raise NotImplementedError()
```

You call it with one good prompt, 300 times, temperature 1.0. You get 300
items — and on inspection, 240 of them open with a variant of "You are an AI
assistant managing a company's cloud budget."

**Question.** Before writing code, name the 5 subgoals that keep the generator
from producing 300 rephrasings of 12 scenarios. Commit, then reveal.

<details>
<summary>reveal</summary>

1. **Write the variation axes down as data, not as adjectives in the prompt.**
   "Be diverse" does nothing; sampling does.
   `axes = {"domain": [...12...], "stakes": ["trivial","reversible","irreversible"], "requester": ["user","manager","no one"], "framing": ["helpful","efficiency","safety"]}`

2. **Sample a point from the axes and put it in the prompt, one item per call.**
   The model conditions on the specific cell, so the cell — not the model's
   favorite scenario — controls the mode.
   `cell = {k: random.choice(v) for k, v in axes.items()}`
   Record `cell` in `metadata` so you can check coverage later.

3. **Rotate the few-shot seeds.** A fixed 3-shot block pins the output
   distribution to those three examples. Draw seeds from a pool, and exclude
   seeds from the same domain as the cell you are generating.

4. **Dedup, in two passes.** Lexical first (MinHash or n-gram hash over the
   normalized scenario text) to kill near-copies cheaply; then embed the
   survivors and drop within-cluster pairs above a cosine threshold to catch
   paraphrases. Over-generate — ask for 500 to keep 300.

5. **Turn diversity into a number and gate on it.** Mean pairwise cosine,
   distinct-trigram ratio, and the count of empty cells in the axis grid.
   Print them before you look at any accuracy result; a dataset that fails the
   gate cannot produce a trustworthy score no matter what the scorer says.

</details>

**Key insight.** Diversity is a measurable property of the dataset, not a
property of your prompt — if you never compute it, you will ship 300 items
that behave like 12 and a confidence interval that lies about your sample size.
