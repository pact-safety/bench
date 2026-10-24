---
slug: e30-hook-z-index
kind: exercise
title: "Ablate one head at hook_z"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 7
axes: [mechanistic_interpretability, debugging]
domain_tags: [transformerlens, hookpoint, hook_z, ablation]
arena_section: "1.2"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** GPT-2 small, `batch=1`, `seq=6`, `n_heads=12`,
`d_head=64`. You want to zero-ablate head 7 of layer 0 — remove that
head's entire contribution to the residual stream, leaving the other
eleven heads untouched.

```python
def ablate_head(z, hook):
    ____
    return z

logits = model.run_with_hooks(
    tokens,
    fwd_hooks=[("blocks.0.attn.hook_z", ablate_head)],
)
```

**Question.** What single line replaces `____`, and what would each
plausible wrong version do instead? Commit to an answer first.

<details>
<summary>reveal</summary>

```python
z[:, :, 7, :] = 0.0
```

`hook_z` holds `pattern @ v` — shape
`(batch, seq, n_heads, d_head)` = `(1, 6, 12, 64)`. The head axis is
dim **2**, which is why the ablation needs three leading slices.

The wrong versions, and what they actually do:

- `z[:, 7] = 0.0` — zeroes sequence position 7 across all 12 heads.
  With `seq=6` this raises `IndexError`, which is the lucky case; with
  a longer prompt it silently ablates a token instead of a head.
- `z[7] = 0.0` — indexes the batch axis. `IndexError` at `batch=1`.
- `z[:, :, :, 7] = 0.0` — zeroes one of the 64 `d_head` channels in
  every head. Almost no effect, and no error.

Ablating at `hook_z` rather than `hook_pattern` or `hook_v` is
deliberate: `z` is the last point where heads are still separate, so
zeroing it removes exactly head 7's summand from `W_O`'s sum. One step
later, at `hook_attn_out`, the heads have already been added together
and there is no head axis left to index.

The name is mechanical: `blocks.{layer}.attn.hook_z`, and
`utils.get_act_name("z", 0)` builds the same string.

</details>

**Key insight.** Before indexing any TransformerLens activation, say
its shape out loud. `hook_z`/`hook_q`/`hook_k`/`hook_v` are
`(batch, seq, head, d_head)`; `hook_pattern` is
`(batch, head, query, key)` — the head axis moves.
