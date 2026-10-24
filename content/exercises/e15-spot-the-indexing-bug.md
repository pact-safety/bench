---
slug: e15-spot-the-indexing-bug
kind: exercise
title: "Spot the indexing bug in a ray helper"
source: "prep for ARENA 0.1 Ray Tracing"
duration_min: 8
axes: [debugging, algorithmic]
domain_tags: [indexing, ellipsis, shapes, rays]
arena_section: "0.1"
pedagogy: debug
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `rays` is `Float[Tensor, "nrays 2 3"]`: axis 1 selects
origin (0) or direction (1), axis 2 is `(x, y, z)`. The helper is
supposed to return every ray's origin.

**Symptom.** With 10 rays in, the caller gets shape `(2, 3)` instead
of `(10, 3)`. Nothing raises. On a single-ray test tensor of shape
`(1, 2, 3)` the function returned `(2, 3)` and the test passed.

```python
def get_origins(rays):
    """rays: Float[Tensor, "nrays 2 3"] -> Float[Tensor, "nrays 3"]"""
    return rays[0]
```

**Question.** What's the bug, what's the one-character-class fix, and
what would `rays[..., 0]` have given instead?

Answer before revealing.

<details>
<summary>reveal</summary>

**Bug.** A bare `rays[0]` always indexes **axis 0**. It returns the
first ray — both of its points — not the origin axis.

**Fix.** `rays[:, 0]`. The leading `:` says "keep axis 0 whole", so
the `0` lands on axis 1.

The three forms on this tensor:

| expression | shape | meaning |
|---|---|---|
| `rays[0]` | `(2, 3)` | ray 0, both points |
| `rays[:, 0]` | `(nrays, 3)` | origin of every ray |
| `rays[..., 0]` | `(nrays, 2)` | x-coordinate of every point |

`...` means "however many axes are needed", so `rays[..., 0]` always
indexes the **last** axis regardless of rank. That's why it's the form
that survives someone prepending a batch dimension — and why using it
where you meant axis 1 gives you x-coordinates and no error.

**What the symptom told you.** The output rank was right and only the
leading dim was wrong, which means an axis was consumed in the wrong
position — an indexing bug, not a math bug. The passing single-ray
test is the tell: with `nrays=1`, `rays[0]` and `rays[:, 0]` return the
same numbers in different shapes.

</details>

**Key insight.** `x[i]` indexes axis 0, `x[:, i]` axis 1, `x[..., i]`
the last axis — and a size-1 leading dimension makes the first two
agree, so tests written on one item can't distinguish them.
