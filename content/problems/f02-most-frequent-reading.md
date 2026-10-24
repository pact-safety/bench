---
slug: most-frequent-reading
title: Most frequent reading
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [algo, fundamentals, hashing]
domain_tags: [fundamentals]
competency_tags: [hash_map, counting]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

Given a list of sensor labels (strings), return the label that appears
most often. If several labels tie for the top count, return the one that
was *seen first* in the input.

```
def most_frequent(labels: list[str]) -> str | None
```

Return `None` for an empty list.

## Starter

```
def most_frequent(labels):
    # TODO
    pass
```

## Solution

```
def most_frequent(labels):
    counts = {}
    best = None
    best_count = 0
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
        # Update only on a strict increase, and only after this label's
        # own count grows — so the first label to *reach* the max wins.
        if counts[label] > best_count:
            best = label
            best_count = counts[label]
    return best
```

## Tests

```
assert most_frequent(["a", "b", "a", "c", "b", "a"]) == "a"

# Tie between "x" (2) and "y" (2): "x" reached count 2 first.
assert most_frequent(["x", "y", "x", "y"]) == "x"

# Single element.
assert most_frequent(["solo"]) == "solo"

# Empty.
assert most_frequent([]) is None

print("OK")
```

## Key insight

One pass, one hash map. The tie-break falls out for free: because you
only replace `best` on a *strict* `>`, whichever label first climbs to
the eventual maximum count holds the title — later labels that merely
match it never displace it.

## Pitfalls

- Building the full count map, then scanning it with `max(...)`: that
  loses first-seen order (dict iteration order is insertion order, but a
  later-inserted key can still tie), so you'd need extra bookkeeping. The
  single-pass strict-`>` update avoids it.
- `counts[label] += 1` on a missing key throws `KeyError`; use
  `.get(label, 0) + 1` (or `collections.Counter`).
