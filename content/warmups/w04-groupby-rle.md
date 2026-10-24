---
slug: warmup-groupby-rle
title: itertools.groupby — run-length encoding
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [itertools]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Run-length encode a string. Return a list of `(char, count)` tuples.

## Starter

```
from itertools import groupby


def rle(s):
    pass
```

## Solution

```
from itertools import groupby


def rle(s):
    return [(c, sum(1 for _ in g)) for c, g in groupby(s)]
```

## Tests

```
assert rle("") == []
assert rle("a") == [("a", 1)]
assert rle("aaabbc") == [("a", 3), ("b", 2), ("c", 1)]
assert rle("abba") == [("a", 1), ("b", 2), ("a", 1)]
print("OK")
```

## Key insight

`groupby` groups *consecutive* equal elements — not all-equal. The
group itself is an iterator that you must consume to count it.
