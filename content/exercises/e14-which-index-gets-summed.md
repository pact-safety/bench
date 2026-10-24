---
slug: e14-which-index-gets-summed
kind: exercise
title: "Read an einsum string and name the summed index"
source: "prep for ARENA 0.0 Prerequisites"
duration_min: 8
axes: [algorithmic, transformer_internals]
domain_tags: [einsum, shapes, batching, matmul]
arena_section: "0.0"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `A` has shape `(2, 3, 4)`, `B` has shape `(2, 4, 5)`.

**Question.** For each string, give the output shape and name every
index that gets summed over:

1. `einsum("b i j, b j k -> b i k", A, B)`
2. `einsum("b i j, b i j -> b", A, A)`
3. `einsum("b i j -> b j", A)`
4. `einsum("b i j, b j k -> i k", A, B)`

Commit before revealing.

<details>
<summary>reveal</summary>

The rule: an index that appears in the inputs but **not** in the
output is summed over. An index appearing in both inputs and in the
output is aligned elementwise (a batch axis). An index in one input
and the output is free.

1. `(2, 3, 5)`. Summed: `j` (size 4). `b` appears on both sides, so
   it's a batch axis, not a contraction. This is `torch.bmm`.
2. `(2,)`. Summed: `i` and `j`. Elementwise product, then sum over
   both — a per-batch Frobenius inner product.
3. `(2, 4)`. Summed: `i`. One operand is legal; einsum with no
   contraction partner is a `reduce`.
4. `(3, 5)`. Summed: `j` **and** `b`. Dropping `b` from the output
   doesn't make it a batch axis anymore — it makes it a contraction,
   so you get the sum of the two per-batch matrix products. This is
   the one people get wrong.

`einops.einsum` spells the same thing with real names and spaces:
`einsum(A, B, "batch i j, batch j k -> batch i k")`.

</details>

**Key insight.** Read an einsum string right-to-left: whatever index is
missing from the output is being summed away. Batch axes stay batch
axes only because you wrote them on the output side.
