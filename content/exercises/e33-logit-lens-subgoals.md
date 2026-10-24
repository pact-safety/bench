---
slug: e33-logit-lens-subgoals
kind: exercise
title: "Subgoals for direct logit attribution"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 10
axes: [mechanistic_interpretability]
domain_tags: [logit lens, direct logit attribution, unembedding, layernorm]
arena_section: "1.2"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** An ARENA-shaped signature. You have a stack of residual
stream vectors — one per layer, say, or one per attention head — and
you want each one's contribution to the logit difference between two
answer tokens.

```python
def logit_diff_of_stack(
    stack: Float[Tensor, "component batch d_model"],  # at the final position
    cache: ActivationCache,
    correct_token: int,
    wrong_token: int,
) -> Float[Tensor, "component"]:
    """
    How much each component pushes toward `correct_token` over
    `wrong_token`, in logits. Averaged over batch.
    """
    raise NotImplementedError()
```

**Question.** Before writing any code, name the 4 subgoals.

<details>
<summary>reveal</summary>

1. **Turn the two tokens into one direction in residual space.**
   `direction = model.W_U[:, correct_token] - model.W_U[:, wrong_token]`
   — `W_U` is `(d_model, d_vocab)`, so `direction` is `(d_model,)`.
2. **Apply the final LayerNorm to the stack.**
   `scaled = cache.apply_ln_to_stack(stack, layer=-1, pos_slice=-1)`
   — the logits come from `ln_final(resid) @ W_U`, not from `resid @
   W_U`. Skipping this is the single most common DLA bug; it leaves
   every attribution off by the same per-prompt scale factor, so the
   *ranking* looks plausible and the *magnitudes* are wrong.
3. **Project each component onto the direction.**
   `contrib = einsum("c b m, m -> c b", scaled, direction)`
4. **Average over batch to match the return shape.**
   `return contrib.mean(dim=-1)`

Why this works at all: the unembedding is a plain linear map and the
residual stream is a plain sum of component outputs, so
`logit_diff(sum of parts) == sum of logit_diff(each part)`. LayerNorm
is the one thing in the way, and treating its scale as a constant —
which is what `apply_ln_to_stack` does — is what makes the
decomposition exact enough to be useful.

</details>

**Key insight.** Any ARENA function whose docstring specifies an
output shape starts with subgoal 1 — read the shape backwards from the
return. Here the return has no `d_model`, so some subgoal must contract
it away, and that contraction is the dot product with the logit-diff
direction.
