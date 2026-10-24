---
slug: depth-first-values
title: Depth-first values of a binary tree
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, binary_tree]
domain_tags: [fundamentals]
competency_tags: [tree_traversal, depth_first_search]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

Return the values of a binary tree in depth-first (pre-order) order:
each node before its children, left subtree fully before the right.
Nodes look like:

```
class Node:
    def __init__(self, val, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right
```

```
def depth_first_values(root: "Node | None") -> list
```

Return `[]` for an empty tree. Try both the recursive and the explicit-
stack iterative form — they're the two shapes every tree problem reuses.

## Starter

```
def depth_first_values(root):
    # TODO
    pass
```

## Solution

```
def depth_first_values(root):
    # Iterative, explicit stack. Push right before left so left pops
    # first — that reproduces pre-order left-to-right.
    if root is None:
        return []
    values = []
    stack = [root]
    while stack:
        node = stack.pop()
        values.append(node.val)
        if node.right is not None:
            stack.append(node.right)
        if node.left is not None:
            stack.append(node.left)
    return values

# Recursive equivalent, for reference:
# def depth_first_values(root):
#     if root is None:
#         return []
#     return ([root.val]
#             + depth_first_values(root.left)
#             + depth_first_values(root.right))
```

## Tests

```
class Node:
    def __init__(self, val, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

#        a
#       / \
#      b   c
#     / \   \
#    d   e   f
a = Node("a",
         Node("b", Node("d"), Node("e")),
         Node("c", None, Node("f")))
assert depth_first_values(a) == ["a", "b", "d", "e", "c", "f"]

# Single node.
assert depth_first_values(Node(1)) == [1]

# Left-leaning chain.
chain = Node(1, Node(2, Node(3)))
assert depth_first_values(chain) == [1, 2, 3]

# Empty tree.
assert depth_first_values(None) == []

print("OK")
```

## Key insight

Pre-order is "visit, then go left, then go right." Recursively that's a
one-liner. Iteratively you keep an explicit stack and — because a stack
is last-in-first-out — you push the *right* child first so the *left*
child is on top and gets processed next. That right-before-left ordering
is the whole trick.

## Pitfalls

- Iterative version pushing left before right: you'd get a right-first
  traversal. Push right first.
- Using a queue (`pop(0)`) instead of a stack (`pop()`): that's
  breadth-first, not depth-first.
- Forgetting the `None` guards before pushing children — appending
  `None` then calling `.val` on it later throws.
