---
slug: algo-eval-aggregation
title: Aggregate eval results by (model, dataset, prompt-variant)
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, hash_map, data_pipeline]
domain_tags: [eval]
competency_tags: [hash_map, aggregation]
jd_signal_tags: [eval, data_pipeline]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

You have a stream of eval result records. Each record is a dict with
keys `model`, `dataset`, `prompt_variant`, `score` (float), and
`tokens` (int). For each `(model, dataset, prompt_variant)` triple,
compute:

- `mean_score` (regular mean of the per-example scores)
- `total_tokens`
- `n`

Return a dict mapping each triple to a sub-dict of the three values.
Then implement a second function that, given that aggregation, returns
the `(dataset, prompt_variant)` triple where the **score gap** between
the best and worst model is largest, with the gap itself.

```
def aggregate(records: list[dict]) -> dict
def largest_model_gap(agg: dict) -> tuple[tuple[str, str], float]
```

Ties in the gap → pick the lexicographically smallest `(dataset,
prompt_variant)`. If fewer than 2 models per `(dataset, prompt_variant)`,
that key is not eligible.

## Starter

```
from collections import defaultdict


def aggregate(records):
    pass


def largest_model_gap(agg):
    pass
```

## Solution

```
from collections import defaultdict


def aggregate(records):
    sums = defaultdict(float)
    counts = defaultdict(int)
    tokens = defaultdict(int)
    for r in records:
        key = (r["model"], r["dataset"], r["prompt_variant"])
        sums[key] += r["score"]
        counts[key] += 1
        tokens[key] += r["tokens"]
    out = {}
    for k, c in counts.items():
        out[k] = {"mean_score": sums[k] / c, "total_tokens": tokens[k], "n": c}
    return out


def largest_model_gap(agg):
    by_dp = defaultdict(list)  # (dataset, prompt_variant) -> [(model, mean)]
    for (model, dataset, pv), stats in agg.items():
        by_dp[(dataset, pv)].append((model, stats["mean_score"]))
    best_key = None
    best_gap = float("-inf")
    for dp, lst in by_dp.items():
        if len(lst) < 2:
            continue
        means = [m for _, m in lst]
        gap = max(means) - min(means)
        if gap > best_gap or (gap == best_gap and (best_key is None or dp < best_key)):
            best_gap = gap
            best_key = dp
    return best_key, best_gap if best_key else (None, 0.0)
```

## Tests

```
records = [
    {"model": "A", "dataset": "mmlu", "prompt_variant": "cot", "score": 0.8, "tokens": 100},
    {"model": "A", "dataset": "mmlu", "prompt_variant": "cot", "score": 0.6, "tokens": 110},
    {"model": "B", "dataset": "mmlu", "prompt_variant": "cot", "score": 0.9, "tokens": 90},
    {"model": "C", "dataset": "mmlu", "prompt_variant": "cot", "score": 0.4, "tokens": 95},
    # Only one model on this combination — not eligible for gap.
    {"model": "A", "dataset": "mmlu", "prompt_variant": "zero_shot", "score": 0.5, "tokens": 40},
    # Two models, smaller gap
    {"model": "A", "dataset": "gsm8k", "prompt_variant": "cot", "score": 0.7, "tokens": 200},
    {"model": "B", "dataset": "gsm8k", "prompt_variant": "cot", "score": 0.75, "tokens": 210},
]

agg = aggregate(records)
key_a = ("A", "mmlu", "cot")
assert agg[key_a]["n"] == 2
assert abs(agg[key_a]["mean_score"] - 0.7) < 1e-9
assert agg[key_a]["total_tokens"] == 210

(dp, gap) = largest_model_gap(agg)
# Best gap is on mmlu/cot: B=0.9, A=0.7, C=0.4 -> gap 0.5
assert dp == ("mmlu", "cot"), dp
assert abs(gap - 0.5) < 1e-9, gap

print("OK")
```

## Key insight

Two passes through `defaultdict`s: one to aggregate per triple, one to
re-bucket by `(dataset, prompt_variant)` and reduce. Avoid the trap of
trying to compute the gap in a single pass — you need to see every
model's mean for a given dataset-variant before you can take max-min.

## Pitfalls

- The "fewer than 2 models" check is easy to forget; without it the gap
  is undefined (or 0 for a single-model entry, which spuriously wins
  when nothing else has data).
- Iterating `agg.items()` gives `(triple, stats)`. Unpacking the triple
  inline is cleaner than indexing.
- Lexicographic tie-break: `dp < best_key` on tuples does this for
  free; don't roll a custom comparator.
