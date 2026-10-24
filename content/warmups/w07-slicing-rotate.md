---
slug: warmup-slicing-rotate
title: Slicing tricks — rotate, reverse, every-other
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [slicing]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement three one-liners that rotate, reverse, and stride a list.

```
def rotate_left(xs, k):    # rotate left by k (k may exceed len)
def reverse(xs):           # without using reversed() or [::-1]... ok use [::-1]
def every_other(xs):       # xs[0], xs[2], xs[4], ...
```

## Starter

```
def rotate_left(xs, k):
    pass


def reverse(xs):
    pass


def every_other(xs):
    pass
```

## Solution

```
def rotate_left(xs, k):
    if not xs:
        return list(xs)
    k %= len(xs)
    return xs[k:] + xs[:k]


def reverse(xs):
    return xs[::-1]


def every_other(xs):
    return xs[::2]
```

## Tests

```
assert rotate_left([1, 2, 3, 4, 5], 2) == [3, 4, 5, 1, 2]
assert rotate_left([1, 2, 3], 7) == [2, 3, 1]
assert rotate_left([], 3) == []
assert reverse([1, 2, 3]) == [3, 2, 1]
assert every_other([1, 2, 3, 4, 5]) == [1, 3, 5]
assert every_other([]) == []
print("OK")
```

## Key insight

`xs[k:] + xs[:k]` is the canonical left-rotate. `k %= len(xs)` handles
oversized k. Both `[::-1]` and `[::2]` are slice-with-stride; the
stride is the third argument.
