---
slug: e17-ray-segment-as-linear-solve
kind: exercise
title: "Decompose ray-segment intersection into a linear solve"
source: "prep for ARENA 0.1 Ray Tracing"
duration_min: 12
axes: [algorithmic]
domain_tags: [linear algebra, rays, solve, decomposition]
arena_section: "0.1"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The blank-page function. Ray origin `O`, direction `D`;
segment endpoints `L1`, `L2`. Everything is stored 3-D with `z = 0`.

```python
def intersect_ray_1d(
    ray: Float[Tensor, "points=2 dim=3"],
    segment: Float[Tensor, "points=2 dim=3"],
) -> bool:
    """True iff the ray hits the segment.

    Ray points are (origin, direction). Ray extends forward only.
    """
    raise NotImplementedError()
```

**Question.** Before writing any code, name the 4–5 subgoals.

Write your list down first — the point is to compare decompositions,
not answers.

<details>
<summary>reveal</summary>

1. **Drop to 2-D and unpack the four points.** The `z` column is
   always 0, so it contributes a trivial equation. Two unknowns need
   exactly two equations.
   ```python
   O, D = ray[:, :2]
   L1, L2 = segment[:, :2]
   ```
2. **Write "they meet" as an equation.** A point on the ray is
   `O + uD` for `u >= 0`; a point on the segment is `L1 + v(L2 - L1)`
   for `0 <= v <= 1`. Setting them equal and moving unknowns left:
   `uD + v(L1 - L2) = L1 - O`.
3. **Read the matrix off that equation.** The unknowns are `[u, v]`,
   so the columns of `A` are their coefficients — `D` and `L1 - L2`.
   ```python
   A = torch.stack([D, L1 - L2], dim=1)   # (2, 2), columns not rows
   b = L1 - O                             # (2,)
   ```
4. **Solve, and treat "no solution" as a non-hit.** `A` is singular
   exactly when the ray and segment are parallel.
   ```python
   try:
       u, v = torch.linalg.solve(A, b)
   except RuntimeError:
       return False
   ```
5. **Apply the range conditions the docstring implied.** A solution
   exists for the infinite line; the *ray* and the *segment* are the
   restricted pieces.
   ```python
   return (u.item() >= 0) and (0.0 <= v.item() <= 1.0)
   ```

`dim=1` in subgoal 3 is the whole exercise. `torch.stack([D, L1 - L2],
dim=0)` builds the transpose, solves a different system, and returns
plausible floats.

</details>

**Key insight.** Any ARENA function shaped "do these two things meet"
becomes "does a solution exist in range": write the equality, move the
unknowns to one side, and the columns of `A` are the coefficients of
the unknowns in the order you're solving for them.
