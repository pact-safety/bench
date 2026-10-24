---
slug: e02-where-does-the-mask-go
kind: exercise
title: "Where does the causal mask go?"
source: "pairs with Vaswani §3.2.1"
duration_min: 6
axes: [transformer_internals]
domain_tags: [causal mask, head, mask, softmax]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** Three candidate places to apply a causal mask, marked A / B / C:

```python
scores  = q @ k.transpose(-1, -2) / sqrt(d_head)
# A
weights = softmax(scores, dim=-1)
# B
out     = weights @ v
# C
```

**Question.** Which spot is correct, and why are the other two wrong?

<details>
<summary>reveal</summary>

**A** is correct. The mask is applied additively as `-inf` to the
forbidden positions in `scores`; after softmax those positions
become exactly 0 and the remaining weights are renormalized.

**B** is wrong because it clobbers `weights` *after* softmax has
already produced a valid probability distribution. Zeroing entries
breaks the simplex (rows no longer sum to 1) and re-renormalizing
gives a different (and incorrect) distribution.

**C** is wrong because by the time you get to `out`, the model has
already pulled information from forbidden positions through the
attention weights — masking the output doesn't undo that. The
information leak is upstream.

</details>

**Key insight.** Masks live in pre-softmax score space, additive
`-inf`. Anywhere else and you're either too late or breaking the
probability distribution.
