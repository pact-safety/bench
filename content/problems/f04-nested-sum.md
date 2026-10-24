---
slug: nested-sum
title: Sum of an arbitrarily nested list
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, recursion]
domain_tags: [fundamentals]
competency_tags: [recursion, tree_shaped_data]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

You're given a list that may contain integers or other lists, nested to
any depth. Return the sum of every integer anywhere inside it.

```
def nested_sum(items: list) -> int
```

Example: `nested_sum([1, [2, [3, 4]], 5])` is `15`.

## Starter

```
def nested_sum(items):
    # TODO
    pass
```

## Solution

```
def nested_sum(items):
    total = 0
    for item in items:
        if isinstance(item, list):
            total += nested_sum(item)   # recurse into the sublist
        else:
            total += item
    return total
```

## Tests

```
assert nested_sum([1, 2, 3]) == 6

assert nested_sum([1, [2, [3, 4]], 5]) == 15

# Empty list, and empty sublists, contribute 0.
assert nested_sum([]) == 0
assert nested_sum([[], [[]], []]) == 0

# Deep single chain.
assert nested_sum([[[[[7]]]]]) == 7

# Negatives.
assert nested_sum([10, [-3, [-7]]]) == 0

print("OK")
```

## Key insight

The data is tree-shaped, so the code is too: for each element, either
it's a leaf (an int — add it) or a branch (a list — recurse and add what
comes back). The base case is implicit — an empty list runs the loop
zero times and returns the `0` accumulator.

## Pitfalls

- Testing `type(item) == list` instead of `isinstance(item, list)`:
  fine here, but `isinstance` is the idiomatic, subclass-safe check.
- Trying to flatten first, then sum: works, but it allocates a whole new
  list. Summing during the walk is simpler and uses only call-stack space.
- Forgetting that the recursive call *returns* a value you must add —
  calling `nested_sum(item)` and discarding it silently drops sublists.
