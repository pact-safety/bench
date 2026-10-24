---
slug: warmup-bisect
title: bisect — insert and find insertion index
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [bisect]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Given a sorted list `xs` and a value `v`, return `(insertion_index,
new_list)` where `insertion_index` is the leftmost position where `v`
could be inserted to keep `xs` sorted, and `new_list` is the result of
inserting `v` there. Use the `bisect` module.

## Starter

```
import bisect


def insert_keep_sorted(xs, v):
    pass
```

## Solution

```
import bisect


def insert_keep_sorted(xs, v):
    i = bisect.bisect_left(xs, v)
    out = list(xs)
    out.insert(i, v)
    return i, out
```

## Tests

```
assert insert_keep_sorted([1, 3, 5, 7], 4) == (2, [1, 3, 4, 5, 7])
assert insert_keep_sorted([1, 3, 3, 5], 3) == (1, [1, 3, 3, 3, 5])
assert insert_keep_sorted([], 9) == (0, [9])
assert insert_keep_sorted([2, 4, 6], 10) == (3, [2, 4, 6, 10])
print("OK")
```

## Key insight

`bisect_left` returns the leftmost insertion point for duplicates;
`bisect_right` returns the rightmost. `insort_left` does both steps in
one call but mutates in place, which the API above doesn't want.
