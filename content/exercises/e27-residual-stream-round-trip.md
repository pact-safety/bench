---
slug: e27-residual-stream-round-trip
kind: exercise
title: "Trace the residual stream through one block"
source: "prep for ARENA 1.1 Transformers from Scratch"
duration_min: 8
axes: [transformer_internals]
domain_tags: [residual stream, attention, mlp, layernorm]
arena_section: "1.1"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** GPT-2 small: `d_model=768`, `n_heads=12`, `d_head=64`,
`d_mlp=3072`. You run one forward pass with `batch=1`, `seq=6`, and
watch a single block go by, hook point by hook point.

**Question.** Give the shape at each of these hook points inside
`blocks.0`.

1. `hook_resid_pre`
2. `attn.hook_q`
3. `attn.hook_pattern`
4. `attn.hook_z`
5. `hook_attn_out`
6. `hook_resid_mid`
7. `mlp.hook_post`
8. `hook_mlp_out`
9. `hook_resid_post`

Write all nine down before opening the reveal.

<details>
<summary>reveal</summary>

1. `(1, 6, 768)` — the stream the block reads from.
2. `(1, 6, 12, 64)` — `hook_q`/`hook_k`/`hook_v` are all
   post-projection and still split by head. `12 * 64 == 768`.
3. `(1, 6, 6)` per head, so `(1, 12, 6, 6)` — the head axis sits at
   dim 1, and the last two axes are `(query_pos, key_pos)`.
4. `(1, 6, 12, 64)` — `z` is `pattern @ v`, so it is back in per-head
   value space. Still no `W_O`.
5. `(1, 6, 768)` — `W_O` maps each head's `d_head=64` back to
   `d_model` and **sums over heads**. This is the first shape in the
   block that is stream-shaped again.
6. `(1, 6, 768)` — `resid_mid = resid_pre + attn_out`.
7. `(1, 6, 3072)` — inside the MLP, after the nonlinearity, widened
   by 4x.
8. `(1, 6, 768)` — projected back down by `W_out`.
9. `(1, 6, 768)` — `resid_post = resid_mid + mlp_out`.

Note what LayerNorm did to the shapes: nothing. `ln1` and `ln2`
normalize in place at `(1, 6, 768)`.

</details>

**Key insight.** The residual stream is `(batch, seq, d_model)` at
every block boundary and never changes shape — attention and MLP both
detour into a different shape and come back. Anything you find at
`(batch, seq, 768)` can be added to the stream; anything at
`(batch, seq, 12, 64)` or `(batch, seq, 3072)` is mid-detour.
