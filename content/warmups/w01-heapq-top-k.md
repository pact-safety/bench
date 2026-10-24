---
slug: warmup-heapq-top-k
title: heapq — maintain top-k from a stream
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [heapq]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement a class `TopK(k)` that ingests a stream of `(score, item)`
pairs via `.add(score, item)` and exposes `.values()` returning the `k`
items with the highest scores so far, sorted descending. Use `heapq`.

## Starter

```
import heapq


class TopK:
    def __init__(self, k):
        pass

    def add(self, score, item):
        pass

    def values(self):
        pass
```

## Solution

```
import heapq


class TopK:
    def __init__(self, k):
        self.k = k
        self.heap = []  # min-heap of (score, item); root is smallest

    def add(self, score, item):
        if len(self.heap) < self.k:
            heapq.heappush(self.heap, (score, item))
        elif score > self.heap[0][0]:
            heapq.heapreplace(self.heap, (score, item))

    def values(self):
        return [item for score, item in sorted(self.heap, reverse=True)]
```

## Tests

```
tk = TopK(3)
for score, item in [(1, "a"), (5, "b"), (3, "c"), (4, "d"), (2, "e")]:
    tk.add(score, item)
assert tk.values() == ["b", "d", "c"], tk.values()

tk2 = TopK(2)
tk2.add(7, "x")
assert tk2.values() == ["x"]

print("OK")
```

## Key insight

A min-heap of size k: keep root = current k-th best; replace it when
a better score arrives. `heapreplace` is one operation instead of pop
+ push.
