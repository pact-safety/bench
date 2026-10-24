---
slug: reverse-linked-list
title: Reverse a singly linked list
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [algo, fundamentals, linked_list]
domain_tags: [fundamentals]
competency_tags: [linked_list, pointer_manipulation]
jd_signal_tags: [fundamentals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

Reverse a singly linked list in place and return the new head. Nodes look
like:

```
class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next
```

```
def reverse_list(head: "Node | None") -> "Node | None"
```

Do it iteratively in O(n) time and O(1) extra space — rewire the `next`
pointers, don't build a new list.

## Starter

```
def reverse_list(head):
    # TODO
    pass
```

## Solution

```
def reverse_list(head):
    prev = None
    curr = head
    while curr is not None:
        nxt = curr.next    # stash the rest before we overwrite the link
        curr.next = prev   # flip this node's pointer backwards
        prev = curr        # advance the two walkers
        curr = nxt
    return prev            # prev is the old tail = the new head
```

## Tests

```
class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next

def to_list(head):
    out = []
    while head:
        out.append(head.val)
        head = head.next
    return out

def build(vals):
    head = None
    for v in reversed(vals):
        head = Node(v, head)
    return head

assert to_list(reverse_list(build([1, 2, 3, 4]))) == [4, 3, 2, 1]

# Single node reverses to itself.
assert to_list(reverse_list(build([9]))) == [9]

# Empty list.
assert reverse_list(None) is None

# Two nodes.
assert to_list(reverse_list(build([1, 2]))) == [2, 1]

print("OK")
```

## Key insight

Three pointers walk the list once: `prev` (the reversed part behind you),
`curr` (the node you're flipping), and a temporary `nxt` so you don't
lose the unvisited tail the instant you overwrite `curr.next`. When
`curr` falls off the end, `prev` is sitting on the old last node — the
new head.

## Pitfalls

- Overwriting `curr.next = prev` *before* saving `curr.next`: you orphan
  the rest of the list. Stash `nxt` first.
- Returning `head` (now the tail) or `curr` (now `None`) instead of
  `prev`. The new head is always `prev`.
- Off-by-one on the empty list: `prev` starts `None`, the loop never
  runs, and you correctly return `None`.
