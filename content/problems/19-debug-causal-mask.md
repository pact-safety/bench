---
slug: debug-causal-mask
title: Debug — silently bidirectional attention
difficulty: medium
time_bucket: 30
problem_type: code_debug
is_warmup: false
structural_tags: [attention, debugging]
domain_tags: [attention]
competency_tags: [debugging, transformer_internals]
jd_signal_tags: [debugging, transformer]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

The implementation below was meant to be causal. Training loss looks
fine on a small synthetic next-token task, but eval-time generation is
incoherent — the model seems to "see the future." Find the bug, fix it,
and write a one-line comment above the fix explaining what the symptom
told you.

The function must take `(q, k, v)` shaped `(B, S, D)` and return the
causally-masked attended values.

## Starter

```
import torch
import torch.nn.functional as F


def causal_attention(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    # Build mask of shape (S, S). Intended: position i attends to j <= i.
    mask = torch.ones(S, S, dtype=torch.bool, device=q.device)
    # bug somewhere in this block
    scores = scores.masked_fill(mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v
```

## Solution

```
import torch
import torch.nn.functional as F


def causal_attention(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    # Symptom was "model sees the future": the mask was all-True, so
    # every score got -inf, softmax produced NaN (or uniform after a
    # zero-row), and the function returned values that didn't depend on
    # the prefix. The fix is to mask only the strict upper triangle.
    mask = torch.triu(torch.ones(S, S, dtype=torch.bool, device=q.device), diagonal=1)
    scores = scores.masked_fill(mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v
```

## Tests

```
import torch
import torch.nn.functional as F

torch.manual_seed(10)
B, S, D = 2, 6, 16
q = torch.randn(B, S, D)
k = torch.randn(B, S, D)
v = torch.randn(B, S, D)

out = causal_attention(q, k, v)
ref = F.scaled_dot_product_attention(q, k, v, is_causal=True)
assert torch.allclose(out, ref, atol=1e-5), (out - ref).abs().max().item()

# Causal property: changing v[t+1:] cannot change out[:t+1]
v2 = v.clone()
v2[:, 3:] = torch.randn_like(v2[:, 3:])
out2 = causal_attention(q, k, v2)
assert torch.allclose(out[:, :3], out2[:, :3], atol=1e-5)

print("OK")
```

## Key insight

"Train loss is fine, eval generation is incoherent" is the fingerprint
of a causality bug. Teacher-forced training tolerates a lot of
attention silliness; autoregressive eval doesn't.

## Pitfalls

- `torch.ones(S, S)` with no triangle operation is "all-True" — masks
  every position. That's the bug.
- `torch.triu(..., diagonal=1)` is the strict upper triangle (positions
  to forbid). `diagonal=0` includes the diagonal, which forbids
  self-attention — a different (also wrong) bug.
- `torch.tril` of the same shape and inverting (`~mask`) is the
  equivalent correct construction. Either convention is fine; mixing
  them inside one function is how silent flips happen.
