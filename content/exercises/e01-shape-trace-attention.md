---
slug: e01-shape-trace-attention
kind: exercise
title: "Shape-trace through scaled dot-product attention"
source: "pairs with Vaswani §3.2.1"
duration_min: 8
axes: [transformer_internals]
domain_tags: [attention, head, scaled dot-product, softmax]
gpu_required: true
colab_url: "https://colab.research.google.com/github/LiBearden/research-engineer-interview-prep/blob/main/notebooks/exercises/e01-shape-trace-attention.ipynb"
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** You have `q`, `k`, `v` each of shape `(batch=2, seq=4, d_head=8)`.

**Question.** Walk through the four steps of scaled dot-product
attention, and predict the *shape* after each one.

1. `q @ k.transpose(-1, -2)` →  ?
2. divide by `sqrt(d_head)` →  ?
3. `softmax(scores, dim=-1)` →  ?
4. `weights @ v` →  ?

Write your guesses down before opening the reveal.

<details>
<summary>reveal</summary>

1. `(2, 4, 4)` — query–key compatibility matrix; each of the 4
   queries gets a score against each of the 4 keys.
2. `(2, 4, 4)` — scalar division doesn't change shape.
3. `(2, 4, 4)` — softmax over the last dim preserves shape.
4. `(2, 4, 8)` — `(2,4,4) @ (2,4,8)` →  `(2, 4, 8)`. The output's
   sequence-length matches `q`'s sequence-length; the feature dim
   matches `v`'s feature dim.

</details>

**Key insight.** The output's `seq` axis comes from `q` and the
`d_head` axis comes from `v`. If you ever see `out.shape ==
(B, k_seq, d_head)` instead of `(B, q_seq, d_head)`, you transposed
the wrong tensor.
