---
slug: e11-rearrange-pattern-binding
kind: exercise
title: "What each letter in a rearrange pattern binds to"
source: "prep for ARENA 0.0 Prerequisites"
duration_min: 8
axes: [algorithmic, transformer_internals]
domain_tags: [einops, rearrange, shapes, heads]
arena_section: "0.0"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `x` has shape `(2, 6, 32)` — batch 2, seq 6, `d_model` 32.
You want 4 attention heads. Two candidate patterns:

```python
a = rearrange(x, "b s (h d) -> b h s d", h=4)
c = rearrange(x, "b s (d h) -> b h s d", h=4)
```

**Question.** Three things:

1. What does each of `b`, `s`, `h`, `d` bind to in pattern `a`?
2. What are `a.shape` and `c.shape`?
3. Element `x[0, 0, 9]` — which `(h, d)` slot does it land in under `a`,
   and which under `c`?

Commit to all three before revealing.

<details>
<summary>reveal</summary>

1. `b=2` and `s=6` bind positionally to axes 0 and 1. `(h d)` says
   "axis 2 is really two axes multiplied together". You supply `h=4`,
   so einops solves `d = 32 / 4 = 8`. Every letter is a size, and
   parenthesised letters must multiply to the real axis length — `h=3`
   would raise, because 32 isn't divisible by 3.

2. Both are `(2, 4, 6, 8)`. The shapes are identical. That's the trap.

3. Order inside the parentheses is row-major: the **leftmost letter is
   the slowest-varying**. Under `(h d)`, flat index `9 = h*8 + d` gives
   `h=1, d=1`. Under `(d h)`, flat index `9 = d*4 + h` gives `d=2, h=1`
   — so it lands in `d=2` of head 1, a different slot.

`(h d)` is the correct split for a `d_model` laid out as four
contiguous 8-wide head blocks — which is how `W_Q` is stored.

</details>

**Key insight.** In a rearrange pattern every letter is an axis size,
and inside parentheses the leftmost letter varies slowest. Two patterns
can produce the same shape and still scramble your data differently —
shape agreement is not correctness.
