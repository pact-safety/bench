---
slug: connected-components
title: Count connected components
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, graph]
domain_tags: [fundamentals]
competency_tags: [graph_traversal, depth_first_search, visited_set]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

You're given an undirected graph as an adjacency mapping: each key is a
node, each value is the list of its neighbors. Return the number of
connected components — the count of separate "islands" of nodes.

```
def count_components(graph: dict) -> int
```

Example: `{0: [1], 1: [0], 2: []}` has two components — `{0, 1}` and
`{2}`.

## Starter

```
def count_components(graph):
    # TODO
    pass
```

## Solution

```
def count_components(graph):
    visited = set()
    count = 0
    for node in graph:
        if node in visited:
            continue
        # New, unvisited node → a component we haven't counted yet.
        count += 1
        # Flood-fill everything reachable from it so we don't recount.
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for nbr in graph[cur]:
                if nbr not in visited:
                    stack.append(nbr)
    return count
```

## Tests

```
assert count_components({0: [1], 1: [0], 2: []}) == 2

# One fully connected blob.
assert count_components({0: [1, 2], 1: [0, 2], 2: [0, 1]}) == 1

# All isolated.
assert count_components({0: [], 1: [], 2: [], 3: []}) == 4

# Empty graph.
assert count_components({}) == 0

# Two separate chains: 0-1-2 and 3-4.
g = {0: [1], 1: [0, 2], 2: [1], 3: [4], 4: [3]}
assert count_components(g) == 2

print("OK")
```

## Key insight

Walk every node once. The first time you land on an unvisited node, you
know it starts a component you haven't seen — increment the counter,
then flood-fill (DFS/BFS) to mark the entire component visited so its
other nodes don't trigger a second count. The visited-set is what keeps
one component from being counted many times.

## Pitfalls

- Incrementing the count inside the flood-fill instead of once per new
  start: you'd count every node, not every component.
- Skipping the `if cur in visited` re-check inside the loop: in an
  undirected graph a node gets pushed by each neighbor, so without the
  guard you revisit and can loop forever on a cycle.
- Iterating neighbors of a node not present as a key: a well-formed
  adjacency map lists every node as a key (even with an empty list) —
  validate that assumption on real input.
