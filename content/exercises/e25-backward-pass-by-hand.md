---
slug: e25-backward-pass-by-hand
kind: exercise
title: "Run the backward pass over a four-node graph"
source: "prep for ARENA 0.4 Backpropagation"
duration_min: 10
axes: [training_mechanics, algorithmic]
domain_tags: [backprop, chain rule, computational graph, gradients]
arena_section: "0.4"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** A scalar graph. Note that `x` feeds **two** downstream nodes.

```python
x = 2.0
y = 3.0
a = x * y          # 6.0
b = a + x          # 8.0
L = b ** 2         # 64.0
```

**Question.** Walk the graph backwards from `L` and give `dL/db`,
`dL/da`, `dL/dy`, `dL/dx`. State the local derivative you used at each
edge.

Write all four down before opening the reveal.

<details>
<summary>reveal</summary>

Seed the output: `dL/dL = 1`.

1. **`L = b**2`** → local `dL/db = 2b = 16`. So `dL/db = 16`.
2. **`b = a + x`** → addition passes gradient through unchanged to both
   parents: local derivative `1` for each.
   - `dL/da = 16 * 1 = 16`
   - `x` gets a contribution of `16 * 1 = 16` — **hold it**, `x` isn't
     done yet.
3. **`a = x * y`** → multiplication routes each parent's gradient
   through the *other* operand.
   - `dL/dy = 16 * x = 16 * 2 = 32`
   - `x` gets a second contribution of `16 * y = 16 * 3 = 48`
4. **Sum `x`'s two paths.** `dL/dx = 48 + 16 = 64`.

Check it analytically: `L = (xy + x)² = x²(y+1)²`, so
`dL/dx = 2x(y+1)² = 2·2·16 = 64` and `dL/dy = 2x²(y+1) = 2·4·4 = 32`.
Both match.

The step people get wrong is 4. If you propagate `x`'s gradient the
moment the first path reaches it, you report `16` (or `48`, depending
on traversal order) — a plausible-looking number that is silently
wrong. This is why autograd needs a **reverse topological order**: a
node's gradient isn't final until every consumer of that node has been
processed.

</details>

**Key insight.** A node used in `k` places receives `k` incoming
gradients and they **sum** — that is the multivariate chain rule, and
it is the literal reason `.grad` accumulates with `+=` rather than `=`.
