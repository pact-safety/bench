---
slug: pair-sum
title: Pair that sums to a target
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, hashing]
domain_tags: [fundamentals]
competency_tags: [hash_map, complement_search]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

Given a list of integers and a target, return the *indices* of the two
distinct positions whose values add up to the target. Return them as a
tuple `(i, j)` with `i < j`. Assume exactly one such pair exists.

```
def pair_sum(nums: list[int], target: int) -> tuple[int, int]
```

Aim for a single pass — O(n) time, not the O(n²) double loop.

## Starter

```
def pair_sum(nums, target):
    # TODO
    pass
```

## Solution

```
def pair_sum(nums, target):
    # value we've already seen -> its index
    seen = {}
    for j, x in enumerate(nums):
        need = target - x
        if need in seen:
            return (seen[need], j)   # seen[need] came earlier, so i < j
        seen[x] = j
    return None  # promised one pair exists; None only if the contract breaks
```

## Tests

```
assert pair_sum([2, 7, 11, 15], 9) == (0, 1)

# The complement appears later — order of discovery still gives i < j.
assert pair_sum([3, 2, 4], 6) == (1, 2)

# Uses the same value twice at different indices.
assert pair_sum([3, 3], 6) == (0, 1)

# Negatives and a mid-list hit.
assert pair_sum([-1, 5, 3, -4], -5) == (0, 3)

print("OK")
```

## Key insight

Turn "find two numbers that sum to T" into "for each number, have I
already seen its complement `T - x`?" A hash map of value→index answers
that in O(1), so one pass suffices. Storing the index only *after*
checking guarantees you never pair an element with itself.

## Pitfalls

- Storing `seen[x] = j` *before* the `need in seen` check: on input like
  `[3, 3]` with the first `3`, you'd match your own index and return
  `(0, 0)`. Check first, then store.
- Returning `(j, seen[need])`: that can give `i > j`. Since `seen[need]`
  was inserted on an earlier iteration, it is the smaller index — put it
  first.
