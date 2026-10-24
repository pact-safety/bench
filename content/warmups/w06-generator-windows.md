---
slug: warmup-generator-windows
title: Generators — sliding window iterator
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [generators]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement a generator function `windowed(iterable, n)` that yields
tuples of `n` consecutive items. If the iterable has fewer than `n`
items, yield nothing. Must work on any iterable, including generators
(single-pass).

## Starter

```
from collections import deque


def windowed(it, n):
    pass
```

## Solution

```
from collections import deque


def windowed(it, n):
    if n <= 0:
        return
    buf = deque(maxlen=n)
    for x in it:
        buf.append(x)
        if len(buf) == n:
            yield tuple(buf)
```

## Tests

```
assert list(windowed([1, 2, 3, 4], 2)) == [(1, 2), (2, 3), (3, 4)]
assert list(windowed([1, 2], 3)) == []
assert list(windowed(range(5), 1)) == [(0,), (1,), (2,), (3,), (4,)]

def gen():
    yield from range(4)

assert list(windowed(gen(), 3)) == [(0, 1, 2), (1, 2, 3)]
print("OK")
```

## Key insight

`deque(maxlen=n)` auto-evicts the oldest item on `append` — exactly
the sliding semantics. Wrap in `tuple()` on yield so consumers can't
mutate the live deque.
