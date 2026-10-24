---
slug: e13-repeat-or-broadcast
kind: exercise
title: "Trace repeat against plain broadcasting"
source: "prep for ARENA 0.0 Prerequisites"
duration_min: 8
axes: [algorithmic]
domain_tags: [einops, repeat, broadcasting, shapes]
arena_section: "0.0"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `x = torch.arange(3)` — shape `(3,)`. `y = torch.arange(4)`
— shape `(4,)`.

**Question.** Predict the result shape of each line, or say it raises:

1. `x + y`
2. `x[:, None] + y[None, :]`
3. `einops.repeat(x, "a -> a b", b=4)`
4. `einops.repeat(x, "a -> a b", b=4) + y`
5. `x[:, None] + y` — how does this differ from (2)?

Write all five down before revealing.

<details>
<summary>reveal</summary>

1. **Raises.** Broadcasting aligns axes from the **right**: `3` against
   `4`. Neither is 1, so they're incompatible.
2. `(3, 4)`. The operands are `(3, 1)` and `(1, 4)`. Right-aligned:
   `1` vs `4` → stretch to 4; `3` vs `1` → stretch to 3.
3. `(3, 4)`. `b=4` is a new axis you named explicitly; `x`'s values run
   down it identically in each column.
4. `(3, 4)`. `(3, 4)` against `(4,)` right-aligns to `(3, 4)` vs
   `(1, 4)` — legal.
5. `(3, 4)`, identical to (2). A missing leading axis is treated as 1,
   so `y` of shape `(4,)` and `y[None, :]` of shape `(1, 4)` broadcast
   the same way. The explicit `None` is documentation, not behavior.

</details>

**Key insight.** Broadcasting is a right-aligned rule that stretches
size-1 axes and refuses everything else; `repeat` is you writing that
axis down by name. Reach for `repeat` when the axis has to exist for a
later pattern to refer to — not to make an arithmetic op typecheck.
