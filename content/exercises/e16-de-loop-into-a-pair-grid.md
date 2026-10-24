---
slug: e16-de-loop-into-a-pair-grid
kind: exercise
title: "Order the steps that replace a per-pair loop"
source: "prep for ARENA 0.1 Ray Tracing"
duration_min: 10
axes: [algorithmic]
domain_tags: [broadcasting, batching, indexing, rays]
arena_section: "0.1"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `rays` is `Float[Tensor, "nrays 2 3"]` and `segments` is
`Float[Tensor, "nsegments 2 3"]` (axis 1 = the two endpoints). For
each ray you want the index of the segment whose start point is
nearest to that ray's origin — one batched pass, no Python loop.
Target output: `Int[Tensor, "nrays"]`.

**Question.** Put these in the order that runs. One of them is a
distractor that must not appear.

```
A  diff = origins[:, None, :] - starts[None, :, :]
B  origins = rays[:, 0, :]
C  starts = segments[:, 0, :]
D  dist = diff.pow(2).sum(dim=-1).sqrt()
E  nearest = dist.argmin(dim=-1)
F  diff = origins - starts
```

Write your order down, and name the distractor, before revealing.

<details>
<summary>reveal</summary>

**Order: B, C, A, D, E.** (B and C swap freely — nothing forces
their relative order.) **F is the distractor.**

The constraints that force the rest:

- `A` needs both `origins` `(nrays, 3)` and `starts` `(nsegments, 3)`,
  so B and C come first.
- `A` is the only step that creates the pair grid: `(nrays, 1, 3)`
  against `(1, nsegments, 3)` broadcasts to
  `(nrays, nsegments, 3)`. Every later shape is downstream of it.
- `D` collapses the coordinate axis with `dim=-1`, giving
  `(nrays, nsegments)`.
- `E` collapses the segment axis with `dim=-1`, giving `(nrays,)` —
  the target shape.

**Why F is a trap rather than an error.** `origins - starts` is
`(nrays, 3)` against `(nsegments, 3)`. When `nrays != nsegments` it
raises, which is survivable. When they happen to be equal it
broadcasts fine and silently computes only the *diagonal* pairs —
ray `i` against segment `i` — and every downstream shape still looks
plausible.

</details>

**Key insight.** De-looping is one step: insert a `None` on each
operand at the axis the other one owns, making an
`(n, m, ...)` pair grid. Everything after that is choosing which axis
each reduction eats.
