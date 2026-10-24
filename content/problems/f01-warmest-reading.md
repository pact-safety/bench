---
slug: warmest-reading
title: Warmest reading and when it happened
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [algo, fundamentals, arrays]
domain_tags: [fundamentals]
competency_tags: [linear_scan]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

You're handed a day's worth of temperature readings, one per hour, as a
list of numbers. Return a tuple `(value, index)` for the single warmest
reading — the highest value and the hour it occurred. If the same
maximum occurs more than once, return the *earliest* hour.

```
def warmest_reading(readings: list[float]) -> tuple[float, int]
```

If the list is empty, return `(None, -1)`.

## Starter

```
def warmest_reading(readings):
    # TODO
    pass
```

## Solution

```
def warmest_reading(readings):
    if not readings:
        return (None, -1)
    best_val = readings[0]
    best_idx = 0
    for i in range(1, len(readings)):
        if readings[i] > best_val:   # strict > keeps the earliest tie
            best_val = readings[i]
            best_idx = i
    return (best_val, best_idx)
```

## Tests

```
assert warmest_reading([60.0, 72.5, 68.0]) == (72.5, 1)

# Tie: earliest wins because of the strict `>`.
assert warmest_reading([80.0, 75.0, 80.0]) == (80.0, 0)

# Single element.
assert warmest_reading([50.0]) == (50.0, 0)

# Negatives are fine — no zero-init assumption.
assert warmest_reading([-5.0, -20.0, -1.0]) == (-1.0, 2)

# Empty.
assert warmest_reading([]) == (None, -1)

print("OK")
```

## Key insight

Track the best value *and* its index together in one linear pass. Seed
them from element 0 (not from `0` or `float("-inf")` blindly) so
negative-only inputs work and you never invent an index that isn't in
the list.

## Pitfalls

- Seeding `best_val = 0`: breaks on all-negative readings. Seed from the
  first element instead.
- Using `>=` in the comparison: that keeps the *latest* max, not the
  earliest. Use strict `>` for the earliest-tie rule.
- Forgetting the empty-list guard — indexing `readings[0]` would throw.
