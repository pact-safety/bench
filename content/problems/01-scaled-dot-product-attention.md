---
slug: scaled-dot-product-attention
title: Scaled dot-product attention with causal mask
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, attention, numerical_stability]
domain_tags: [attention]
competency_tags: [transformer_internals]
jd_signal_tags: [interpretability, mechanistic_interp, transformer]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
references:
  - title: "Attention Is All You Need — §3.2.1 Scaled Dot-Product Attention"
    url: "https://arxiv.org/abs/1706.03762"
    why: "Original spec: sqrt(d_k) scale, mask convention, the equation you're reproducing"
    phase: explore
  - title: "Machine Learning with PyTorch and Scikit-Learn — Transformer chapter"
    book: "Raschka, Liu, Mirjalili (Packt, 2022)"
    why: "Worked PyTorch implementation with reshape and masking walkthroughs"
    phase: plan
  - title: "PyTorch docs — torch.nn.functional.scaled_dot_product_attention"
    url: "https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html"
    why: "Reference behavior; useful as a correctness oracle"
    phase: verify
---

## Prompt

Implement single-head scaled dot-product attention with an optional causal
mask. Signature:

```
def attention(q, k, v, causal: bool = False) -> torch.Tensor:
    # q, k, v: shape (batch, seq, d_head)
    # returns: shape (batch, seq, d_head)
```

The scale factor is `1 / sqrt(d_head)`. When `causal=True`, position `i`
must attend only to positions `j <= i`. Use `-inf` (or a very negative
number) on the masked entries pre-softmax. Return the attended values.

Do not use `torch.nn.functional.scaled_dot_product_attention`. The point
of the exercise is the manual implementation.

## Starter

```
import torch
import torch.nn.functional as F


def attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, causal: bool = False) -> torch.Tensor:
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn.functional as F


def attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, causal: bool = False) -> torch.Tensor:
    d_head = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d_head ** 0.5)
    if causal:
        seq = q.shape[-2]
        mask = torch.triu(torch.ones(seq, seq, dtype=torch.bool, device=q.device), diagonal=1)
        scores = scores.masked_fill(mask, float("-inf"))
    weights = F.softmax(scores, dim=-1)
    return weights @ v
```

## Tests

```
import torch

torch.manual_seed(0)
B, S, D = 2, 6, 16
q = torch.randn(B, S, D)
k = torch.randn(B, S, D)
v = torch.randn(B, S, D)

out = attention(q, k, v, causal=False)
assert out.shape == (B, S, D), out.shape

# Non-causal matches reference
ref = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=False)
assert torch.allclose(out, ref, atol=1e-5), "non-causal mismatch"

# Causal: the t-th output should be invariant to changes in v[t+1:]
out_c = attention(q, k, v, causal=True)
v2 = v.clone()
v2[:, 3:] = torch.randn_like(v2[:, 3:])
out_c2 = attention(q, k, v2, causal=True)
assert torch.allclose(out_c[:, :3], out_c2[:, :3], atol=1e-5), "causal leak"

# Causal also matches PyTorch reference
ref_c = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=True)
assert torch.allclose(out_c, ref_c, atol=1e-5), "causal mismatch"

print("OK")
```

## Key insight

The scale by `sqrt(d_head)` is what keeps softmax inputs in a regime where
gradients don't vanish — without it, dot products grow with `d_head` and
softmax saturates. The causal mask goes inside the softmax, not outside.

## Pitfalls

- `torch.triu` with `diagonal=1` gives the strict upper triangle — these
  are the positions to mask. `diagonal=0` would block self-attention too,
  which is wrong.
- Use `masked_fill(mask, float('-inf'))`, not multiplication by zero.
  Zeroing scores still lets them affect softmax via `exp(0) = 1`.
- `F.scaled_dot_product_attention` in PyTorch accepts `q, k, v` shaped
  `(batch, ..., seq, head_dim)` and applies its own scaling; passing a
  pre-scaled tensor will double-scale.
