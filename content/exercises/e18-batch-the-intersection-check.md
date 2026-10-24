---
slug: e18-batch-the-intersection-check
kind: exercise
title: "Decompose the batched intersection check"
source: "prep for ARENA 0.1 Ray Tracing"
duration_min: 12
axes: [algorithmic]
domain_tags: [batching, einops, broadcasting, rays, solve]
arena_section: "0.1"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Same geometry as the single-pair version, now with no
Python loop anywhere.

```python
def intersect_rays_1d(
    rays: Float[Tensor, "nrays 2 3"],
    segments: Float[Tensor, "nsegments 2 3"],
) -> Bool[Tensor, "nrays"]:
    """Entry i is True iff ray i hits at least one segment."""
    raise NotImplementedError()
```

**Question.** Before writing any code, name the 5 subgoals. Start from
the return type.

Commit to your list before revealing.

<details>
<summary>reveal</summary>

1. **Read the shape backwards from the return.** `Bool["nrays"]` with
   "at least one segment" in the docstring means an `.any()` over a
   segments axis, which means somewhere upstream you must hold a
   `(nrays, nsegments)` boolean grid. That grid is the real target.
2. **Build the pair grid, and drop the dead `z` column.**
   ```python
   nr, ns = rays.shape[0], segments.shape[0]
   rays = einops.repeat(rays[..., :2], "nr p d -> nr ns p d", ns=ns)
   segments = einops.repeat(segments[..., :2], "ns p d -> nr ns p d", nr=nr)
   ```
3. **Build `A` and `b` for every pair at once.** Same columns as the
   single-pair case; the batch axes ride along in front.
   ```python
   O, D = rays[..., 0, :], rays[..., 1, :]        # (nr, ns, 2) each
   L1, L2 = segments[..., 0, :], segments[..., 1, :]
   A = torch.stack([D, L1 - L2], dim=-1)          # (nr, ns, 2, 2)
   b = L1 - O                                     # (nr, ns, 2)
   ```
4. **Neutralize singular matrices before solving, not after.** One
   parallel pair anywhere raises and kills the whole batched solve, so
   detect and overwrite them, then remember which they were.
   ```python
   singular = A.det().abs() < 1e-8
   A[singular] = torch.eye(2)
   sol = torch.linalg.solve(A, b)                 # (nr, ns, 2)
   ```
5. **Apply the conditions, then collapse the segments axis.**
   ```python
   u, v = sol[..., 0], sol[..., 1]
   hit = (u >= 0) & (v >= 0) & (v <= 1) & ~singular
   return hit.any(dim=-1)                         # (nrays,)
   ```

Subgoal 4 is the step that has no single-pair analogue. In the loop
version you catch the exception per pair; batched, there is nothing to
catch per pair — you replace the bad matrices with something
invertible and mask their results out at the end.

</details>

**Key insight.** Any ARENA function whose docstring specifies an output
shape starts with subgoal 1 — read the shape backwards from the return.
`Bool["nrays"]` implies a reduction, the reduction implies a
`(nrays, nsegments)` grid, and the grid is what you build first.
