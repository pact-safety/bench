---
slug: warmup-tree-traversal
title: Recursion — tree depth from nested dict
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, recursion]
domain_tags: []
competency_tags: [recursion]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Compute the maximum depth of a tree represented as a nested dict where
each node has `{"value": ..., "children": [...]}`. A leaf has empty
children. Depth 1 = single root.

## Starter

```
def max_depth(node):
    pass
```

## Solution

```
def max_depth(node):
    if not node["children"]:
        return 1
    return 1 + max(max_depth(c) for c in node["children"])
```

## Tests

```
leaf = {"value": 1, "children": []}
assert max_depth(leaf) == 1

tree = {
    "value": 1,
    "children": [
        {"value": 2, "children": [{"value": 4, "children": []}]},
        {"value": 3, "children": []},
    ],
}
assert max_depth(tree) == 3

print("OK")
```

## Key insight

`max` over an empty generator throws; the leaf case has to come first.
This is the recursion habit to keep warm: base case → reduction.
