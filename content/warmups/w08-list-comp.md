---
slug: warmup-list-comp
title: List comprehensions / genexprs — flatten and filter
difficulty: easy
time_bucket: 5
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, python_idiom]
domain_tags: []
competency_tags: [comprehensions]
jd_signal_tags: []
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Given a list of lists of integers, return the sum of all positive
values across all sublists, computed in a single expression using a
generator expression.

```
def positive_sum(matrix):
    pass
```

## Starter

```
def positive_sum(matrix):
    pass
```

## Solution

```
def positive_sum(matrix):
    return sum(x for row in matrix for x in row if x > 0)
```

## Tests

```
assert positive_sum([[1, -2, 3], [-1, 4]]) == 8
assert positive_sum([]) == 0
assert positive_sum([[-1, -2]]) == 0
assert positive_sum([[0, 0, 1]]) == 1
print("OK")
```

## Key insight

In a comprehension, `for row in matrix for x in row` reads
left-to-right (outer to inner). The `if x > 0` filter applies to the
innermost loop. Use a generator (not a list) inside `sum()` so you
don't materialize.
