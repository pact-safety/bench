---
slug: climbing-ways
title: Count ways to climb (memoized recursion)
difficulty: easy
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, recursion, dynamic_programming]
domain_tags: [fundamentals]
competency_tags: [recursion, memoization]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

You're climbing a staircase of `n` steps. Each move you take either 1
step or 2 steps. Return the number of distinct ordered ways to reach the
top.

```
def climbing_ways(n: int) -> int
```

`climbing_ways(4)` is `5`: `1+1+1+1`, `1+1+2`, `1+2+1`, `2+1+1`, `2+2`.

Write it recursively, and memoize so `n` in the hundreds still returns
instantly (the naive recursion is exponential).

## Starter

```
def climbing_ways(n):
    # TODO
    pass
```

## Solution

```
def climbing_ways(n, memo=None):
    if memo is None:
        memo = {}
    if n < 0:
        return 0            # overshot the top — not a valid path
    if n == 0:
        return 1            # exactly at the top — one complete way
    if n in memo:
        return memo[n]
    memo[n] = climbing_ways(n - 1, memo) + climbing_ways(n - 2, memo)
    return memo[n]
```

## Tests

```
assert climbing_ways(0) == 1
assert climbing_ways(1) == 1
assert climbing_ways(2) == 2
assert climbing_ways(3) == 3
assert climbing_ways(4) == 5
assert climbing_ways(5) == 8      # Fibonacci shifted by one

# Memoization makes large n cheap and correct (no recursion-limit blowup
# from re-derivation, though very large n may still need iteration).
assert climbing_ways(30) == 1346269

print("OK")
```

## Key insight

The last move into step `n` is either a 1-step (from `n-1`) or a 2-step
(from `n-2`), so `ways(n) = ways(n-1) + ways(n-2)` — it's Fibonacci in
disguise. Memoizing collapses the exponential call tree to O(n): each
subproblem is solved once and reused.

## Pitfalls

- A *mutable default argument* (`def climbing_ways(n, memo={})`) is
  shared across calls and leaks state between independent invocations.
  Default to `None` and create the dict inside.
- Missing the `n < 0` guard: a 2-step from `n == 1` reaches `-1`, which
  must count as *zero* ways, not raise or recurse forever.
- Base case `n == 0 -> 1`, not `0`: landing exactly on the top is one
  valid completed path, and it's what makes the counts add up.
