---
slug: e28-split-into-heads
kind: exercise
title: "Subgoals for multi-head attention"
source: "prep for ARENA 1.1 Transformers from Scratch"
duration_min: 10
axes: [transformer_internals]
domain_tags: [attention, head, einsum, d_model]
arena_section: "1.1"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** An ARENA-shaped signature. `d_head = d_model // n_heads`,
so `n_heads * d_head == d_model`.

```python
def forward(self, resid_pre: Float[Tensor, "batch seq d_model"]
            ) -> Float[Tensor, "batch seq d_model"]:
    """
    Multi-head attention. Weights on self:
        W_Q, W_K, W_V : (n_heads, d_model, d_head)
        W_O           : (n_heads, d_head, d_model)
    Returns this block's attention contribution to the residual
    stream, shape (batch, seq, d_model).
    """
    raise NotImplementedError()
```

**Question.** Before writing any code, name the 5 subgoals. Don't
write the einsums yet — write the *labels*.

<details>
<summary>reveal</summary>

1. **Project the stream into per-head query/key/value space.**
   `q = einsum("b s m, h m d -> b s h d", resid_pre, self.W_Q)` — same
   for `k` and `v`.
2. **Score every query against every key, independently per head.**
   `scores = einsum("b q h d, b k h d -> b h q k", q, k) * d_head**-0.5`
3. **Mask, then normalize over the key axis.**
   `scores = self.apply_causal_mask(scores)` then
   `pattern = scores.softmax(dim=-1)` — `dim=-1` is `key_pos`.
4. **Take the weighted sum of values back into per-head space.**
   `z = einsum("b h q k, b k h d -> b q h d", pattern, v)`
5. **Merge the heads back to `d_model` with `W_O`.**
   `out = einsum("b q h d, h d m -> b q m", z, self.W_O)` — the `h`
   index is summed over, which is where the heads recombine.

What the `n_heads * d_head == d_model` constraint buys: steps 1–4 cost
the same FLOPs and the same parameter count as one head of width
`d_model`, but you get `n_heads` *independent* attention patterns
instead of one. The heads cannot talk to each other until step 5.

</details>

**Key insight.** Any ARENA function whose docstring specifies an
output shape starts with subgoal 1 — read the shape backwards from the
return. Here the return is `d_model`, so the last subgoal must be the
one that contracts away `h` and `d`.
