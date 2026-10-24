---
slug: warmup-counter-defaultdict
title: Counter / defaultdict — count grouped occurrences
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [collections]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Given a list of `(category, word)` pairs, return a dict from category
to a list of `(word, count)` pairs sorted by count descending, then
word ascending.

```
def grouped_counts(pairs: list[tuple[str, str]]) -> dict[str, list[tuple[str, int]]]
```

## Starter

```
from collections import Counter, defaultdict


def grouped_counts(pairs):
    pass
```

## Solution

```
from collections import Counter, defaultdict


def grouped_counts(pairs):
    bucket = defaultdict(list)
    for cat, w in pairs:
        bucket[cat].append(w)
    return {
        cat: sorted(Counter(words).items(), key=lambda kv: (-kv[1], kv[0]))
        for cat, words in bucket.items()
    }
```

## Tests

```
pairs = [("a", "x"), ("a", "y"), ("a", "x"), ("b", "z"), ("a", "z"), ("b", "z")]
out = grouped_counts(pairs)
assert out["a"] == [("x", 2), ("y", 1), ("z", 1)]
assert out["b"] == [("z", 2)]
print("OK")
```

## Key insight

`defaultdict` is the right shape for "grouping by key into a list."
`Counter` is the right shape for counting. Stacking them is the
idiomatic two-line solution to grouped frequency problems.
