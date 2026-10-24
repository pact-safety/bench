---
slug: multi-head-attention-reshape
title: Multi-head attention — projections, reshape, output merge
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, attention]
domain_tags: [attention]
competency_tags: [transformer_internals]
jd_signal_tags: [transformer, interpretability]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement multi-head attention forward (no causal mask needed). Given an
input `x` of shape `(batch, seq, d_model)` and the four projection
matrices `W_q, W_k, W_v, W_o` each `(d_model, d_model)`, produce the
output of shape `(batch, seq, d_model)`.

Use `n_heads` heads with `d_head = d_model // n_heads`. The reshape to
multi-head must split the `d_model` axis into `(n_heads, d_head)` and
move the head axis ahead of the sequence axis so each head is its own
attention computation. Reverse the reshape before the output projection.

You may call `F.scaled_dot_product_attention` for the actual attention.
The exercise is the reshape, not the softmax.

## Starter

```
import torch
import torch.nn.functional as F


def mha_forward(
    x: torch.Tensor,
    w_q: torch.Tensor,
    w_k: torch.Tensor,
    w_v: torch.Tensor,
    w_o: torch.Tensor,
    n_heads: int,
) -> torch.Tensor:
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn.functional as F


def mha_forward(x, w_q, w_k, w_v, w_o, n_heads):
    B, S, D = x.shape
    assert D % n_heads == 0
    d_head = D // n_heads

    q = (x @ w_q).view(B, S, n_heads, d_head).transpose(1, 2)
    k = (x @ w_k).view(B, S, n_heads, d_head).transpose(1, 2)
    v = (x @ w_v).view(B, S, n_heads, d_head).transpose(1, 2)
    # shape now: (B, n_heads, S, d_head)

    attn = F.scaled_dot_product_attention(q, k, v)
    # shape: (B, n_heads, S, d_head)

    merged = attn.transpose(1, 2).contiguous().view(B, S, D)
    return merged @ w_o
```

## Tests

```
import torch
import torch.nn.functional as F

torch.manual_seed(1)
B, S, D, H = 2, 8, 32, 4
x = torch.randn(B, S, D)
w_q = torch.randn(D, D) * 0.1
w_k = torch.randn(D, D) * 0.1
w_v = torch.randn(D, D) * 0.1
w_o = torch.randn(D, D) * 0.1

out = mha_forward(x, w_q, w_k, w_v, w_o, H)
assert out.shape == (B, S, D), out.shape

# Sanity: heads computed independently. Permuting heads after projection
# should produce permuted attention output before w_o is applied.
# Easier check: with H = 1, this should match a single-head computation.
single = F.scaled_dot_product_attention(x @ w_q, x @ w_k, x @ w_v) @ w_o
out1 = mha_forward(x, w_q, w_k, w_v, w_o, 1)
assert torch.allclose(out1, single, atol=1e-5), "single-head case mismatched"

# Different head counts produce different outputs (shape invariant).
out2 = mha_forward(x, w_q, w_k, w_v, w_o, 2)
out4 = mha_forward(x, w_q, w_k, w_v, w_o, 4)
assert not torch.allclose(out2, out4, atol=1e-3), "n_heads should affect result"

print("OK")
```

## Key insight

The `view → transpose` order matters: you `view` to split into heads,
then `transpose` to move heads ahead of sequence. Reverse that order at
the end. A `.contiguous()` before the final view is required after a
transpose.

## Pitfalls

- `view` on a non-contiguous tensor errors. After `transpose(1, 2)`,
  call `.contiguous()` before the next `view`.
- Splitting d_model with `view(B, S, d_head, n_heads)` instead of
  `view(B, S, n_heads, d_head)` swaps which axis is "head" and which is
  "feature within head". The output shape stays the same; the values are
  wrong. This is the canonical silent bug in MHA implementations.
- Don't forget the output projection `w_o`. The final reshape gives you
  concatenated heads; `w_o` mixes information across heads.
