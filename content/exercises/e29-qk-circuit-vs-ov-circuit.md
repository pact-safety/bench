---
slug: e29-qk-circuit-vs-ov-circuit
kind: exercise
title: "QK circuit vs OV circuit"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 9
axes: [mechanistic_interpretability, transformer_internals]
domain_tags: [qk circuit, ov circuit, attention, head]
arena_section: "1.2"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** One attention head in GPT-2 small. `d_model=768`,
`d_head=64`. Per head, `W_Q`, `W_K`, `W_V` are `(768, 64)` and `W_O`
is `(64, 768)`. Ignore biases and LayerNorm.

Scores are `x_dest @ W_Q @ W_K.T @ x_src.T`, and the head's output is
`x_src @ W_V @ W_O` weighted by the pattern.

**Question.** Answer four things:

1. What is the shape of the full QK matrix `W_Q @ W_K.T`?
2. What is the shape of the full OV matrix `W_V @ W_O`?
3. Both are `d_model → d_model` maps of rank at most 64. So what makes
   them different?
4. You want to know *which* token a head copies from. Which circuit do
   you read? You want to know *what* it copies. Which one then?

<details>
<summary>reveal</summary>

1. `(768, 768)` — `(768,64) @ (64,768)`.
2. `(768, 768)` — same outer shape, rank ≤ 64 for the same reason.
3. Where the output lands. The QK circuit consumes the residual stream
   at two positions and produces a **scalar score** per (dest, src)
   pair. Nothing it computes is ever added to the residual stream — it
   only decides *where* attention goes. The OV circuit consumes the
   residual stream at the source position and writes a `d_model`
   vector into the destination position's stream. It decides *what*
   gets moved, and it does so identically no matter which source
   position the pattern selected.
4. Which token → QK. What gets copied → OV. A previous-token head and
   an induction head can have near-identical OV circuits and be
   distinguished only by QK; a copying head and an anti-copying head
   can share a QK circuit and differ only in OV.

</details>

**Key insight.** QK reads two positions and writes a score; OV reads
one position and writes a vector. When an interpretability result
surprises you, ask which of the two you actually measured — patterns
are QK evidence, and they say nothing about what the head writes.
