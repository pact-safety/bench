---
slug: format-robustness-gap
title: Measuring a benchmark's prompt-format robustness
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [eval, eval_design]
domain_tags: [eval, safety]
competency_tags: [robustness, prompt_sensitivity, eval_validity]
jd_signal_tags: [eval_design, safety]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

A benchmark claims to measure a capability. But if a model's score swings
when you only reword the *prompt format* — not the underlying question —
the benchmark is partly measuring format-sensitivity, not the capability.
This is the validity problem at the heart of a lot of eval critique
(including sycophancy and demographic-framing work): the same item,
re-templated, shouldn't flip.

You ran every item under `K` equivalent prompt formats and recorded
whether the model got each item right under each format.

```
def robustness_report(results: list[list[bool]]) -> dict
```

`results[i]` is a list of `K` booleans — item `i`'s correctness under each
format (every row has the same length `K`). Return:

- `"per_format_acc"`: list of `K` accuracies (fraction of items correct
  under that format),
- `"robustness_gap"`: `max(per_format_acc) - min(per_format_acc)` — how
  much the headline score depends on format choice,
- `"unstable_items"`: how many items are correct under some formats but
  not all (their correctness flips with format).

Empty input → `per_format_acc=[]`, `robustness_gap=0.0`,
`unstable_items=0`.

## Starter

```
def robustness_report(results):
    # TODO
    pass
```

## Solution

```
def robustness_report(results):
    if not results:
        return {"per_format_acc": [], "robustness_gap": 0.0, "unstable_items": 0}
    n_items = len(results)
    k = len(results[0])
    # Accuracy per format = down the columns.
    per_format_acc = [
        sum(row[j] for row in results) / n_items
        for j in range(k)
    ]
    gap = max(per_format_acc) - min(per_format_acc)
    # An item is unstable if it's neither all-right nor all-wrong.
    unstable = sum(1 for row in results if 0 < sum(row) < k)
    return {
        "per_format_acc": per_format_acc,
        "robustness_gap": gap,
        "unstable_items": unstable,
    }
```

## Tests

```
# Two formats. Item 0 stable-correct; item 1 flips; item 2 stable-wrong.
results = [
    [True,  True],
    [True,  False],
    [False, False],
]
out = robustness_report(results)
assert out["per_format_acc"] == [2/3, 1/3], out
assert out["robustness_gap"] == 2/3 - 1/3, out
assert out["unstable_items"] == 1, out

# Perfectly robust: every format agrees on every item → gap 0, none unstable.
results = [[True, True, True], [False, False, False]]
out = robustness_report(results)
assert out["robustness_gap"] == 0.0
assert out["unstable_items"] == 0

# Every item flips on exactly one of two formats: high instability, and
# the two formats have identical marginal accuracy so the *gap* is 0 —
# showing gap alone can hide instability.
results = [[True, False], [False, True]]
out = robustness_report(results)
assert out["robustness_gap"] == 0.0
assert out["unstable_items"] == 2

# Empty.
assert robustness_report([]) == {"per_format_acc": [], "robustness_gap": 0.0, "unstable_items": 0}

print("OK")
```

## Key insight

Two complementary lenses on the same failure. The **robustness gap**
catches format choices that move the *aggregate* score — the thing a
leaderboard reports. **Unstable-item count** catches per-item churn even
when the aggregates happen to match (the last test: both formats score
50%, but *every* item is format-dependent). A benchmark you trust needs
both a small gap and few unstable items; reporting only accuracy under one
format hides both.

## Pitfalls

- Averaging across the wrong axis: accuracy is per *format* (down the
  columns), not per item (across the rows). Transposing them silently
  gives a meaningless "score."
- Using the gap as the only robustness metric — the last test case is the
  counterexample: identical marginals, total per-item instability.
- Counting an all-wrong item as "unstable." Unstable means it *changed*;
  `0 < sum(row) < k` excludes both all-right and all-wrong.
