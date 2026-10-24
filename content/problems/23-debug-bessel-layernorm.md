---
slug: debug-bessel-layernorm
title: Debug — LayerNorm computing variance with Bessel's correction
difficulty: easy
time_bucket: 10
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, numerical_stability]
domain_tags: [training]
competency_tags: [debugging, transformer_internals]
jd_signal_tags: [debugging, transformer]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

The "from-scratch" LayerNorm below disagrees with `nn.LayerNorm` by a
small but persistent factor on every test, even though it looks
algebraically correct. Find the bug.

## Starter

```
import torch


def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    var = x.var(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta
```

## Solution

```
import torch


def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    # torch.var defaults to unbiased=True (Bessel's correction, dividing
    # by N-1). nn.LayerNorm uses the biased estimator (divides by N).
    # Pass unbiased=False — or equivalently correction=0 in newer PyTorch.
    var = x.var(dim=-1, keepdim=True, unbiased=False)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(14)
D = 8
x = torch.randn(3, 5, D)
gamma = torch.randn(D)
beta = torch.randn(D)

ref = nn.LayerNorm(D)
with torch.no_grad():
    ref.weight.copy_(gamma)
    ref.bias.copy_(beta)
ref_out = ref(x)

out = layer_norm(x, gamma, beta)
assert torch.allclose(out, ref_out, atol=1e-5), (out - ref_out).abs().max().item()

print("OK")
```

## Key insight

`torch.var(unbiased=True)` divides by `N-1`. `nn.LayerNorm` divides by
`N`. The two differ by a multiplicative factor of `sqrt(N / (N-1))` in
the normalized output. On `D = 8`, that's ~6.7% — enough to fail a
1e-5 allclose test, small enough to look like "numerical noise" to
someone who doesn't know the convention.

## Pitfalls

- `unbiased=False` is the explicit form. In newer PyTorch,
  `correction=0` is the preferred argument; both work today.
- This applies to `torch.std` too — same default, same fix.
- Numpy's `np.var` defaults to `ddof=0` (the LayerNorm convention), so
  porting from numpy to torch without thinking is exactly when this
  bites.
