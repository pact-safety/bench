---
slug: algo-validation-window
title: Longest streak of consecutive validated training examples
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, sliding_window]
domain_tags: [training]
competency_tags: [sliding_window, two_pointer]
jd_signal_tags: [data_quality, training]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
references:
  - title: "Sliding-window pattern — variable window with a bounded violation count"
    why: "Frame the happy path first, then the variations; use complexity as a comparison input"
    phase: explore
  - title: "Clean Code — Ch. 3: Functions (small, single-purpose helpers)"
    book: "Robert C. Martin (Pearson, 2008)"
    why: "Keep the helper functions small once the loop structure is right; selective use"
    phase: implement
---

## Prompt

You're cleaning a training dataset. Each example has been processed by
a validation pipeline that emits a `quality_score` in `[0, 1]`. The
training team wants the *longest contiguous run* of examples whose
quality score is at least `threshold`, with at most `k` "soft failures"
allowed inside the window — a soft failure being an example with
score in `[soft_floor, threshold)`. A "hard failure" (score `< soft_floor`)
breaks the window.

```
def longest_validated_window(scores: list[float], threshold: float, soft_floor: float, k: int) -> tuple[int, int]
```

Return `(start_index, length)` of the longest such window. Ties: prefer
the *earliest* start. If no example qualifies, return `(0, 0)`.

## Starter

```
def longest_validated_window(scores, threshold, soft_floor, k):
    # TODO
    pass
```

## Solution

```
def longest_validated_window(scores, threshold, soft_floor, k):
    n = len(scores)
    if n == 0:
        return (0, 0)
    best_start = 0
    best_len = 0
    left = 0
    soft_count = 0
    for right in range(n):
        s = scores[right]
        if s < soft_floor:
            # Hard failure: window must skip this position entirely.
            left = right + 1
            soft_count = 0
            continue
        if s < threshold:
            soft_count += 1
        while soft_count > k:
            if scores[left] >= soft_floor and scores[left] < threshold:
                soft_count -= 1
            left += 1
        cur = right - left + 1
        if cur > best_len:
            best_len = cur
            best_start = left
    return (best_start, best_len)
```

## Tests

```
# All clean: window is everything.
out = longest_validated_window([0.9, 0.95, 0.99, 0.8], threshold=0.7, soft_floor=0.5, k=0)
assert out == (0, 4), out

# Hard failure breaks. The longest run is positions 0..1 and 3..5 (each length 2 or 3).
scores = [0.8, 0.9, 0.3, 0.95, 0.85, 0.9]
out = longest_validated_window(scores, threshold=0.7, soft_floor=0.5, k=0)
assert out == (3, 3), out

# Soft failures allowed: k=1 lets one [0.5, 0.7) into the window.
scores = [0.8, 0.6, 0.9, 0.6, 0.7]
out = longest_validated_window(scores, threshold=0.7, soft_floor=0.5, k=1)
# Best window: positions 0..2 (len 3, one soft at idx 1) tied with
# 2..4 (len 3, one soft at idx 3). Earliest wins.
assert out == (0, 3), out

# k=2 stretches it: the whole sequence is OK because all scores >= 0.5
# and only two soft failures total (idx 1 and 3).
out = longest_validated_window(scores, threshold=0.7, soft_floor=0.5, k=2)
assert out == (0, 5), out

# Empty
assert longest_validated_window([], 0.7, 0.5, 0) == (0, 0)

print("OK")
```

## Key insight

Standard sliding window with two failure types: hard failures jump
`left` past them and reset the soft counter; soft failures get
included up to `k` per window. The "earliest wins" tiebreak is what
the `>` (not `>=`) comparison gives you for free.

## Pitfalls

- Hard-failure handling: do *not* try to "shrink past" a hard failure
  the same way you shrink past soft failures. The window must
  completely exclude hard failures, so jump `left` to `right + 1`.
- Off-by-one on the tie break: use `>` so the earliest equal-length
  window is preserved. `>=` would replace it with later ones.
- The `soft_floor` is inclusive ([soft_floor, threshold)), while the
  hard floor is strict (< soft_floor). Match the test cases.
