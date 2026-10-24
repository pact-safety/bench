---
slug: layernorm-from-scratch
title: LayerNorm from scratch
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, numerical_stability]
domain_tags: [training]
competency_tags: [transformer_internals]
jd_signal_tags: [transformer, training_internals]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
references:
  - title: "Layer Normalization (Ba, Kiros, Hinton, 2016)"
    url: "https://arxiv.org/abs/1607.06450"
    why: "Original spec — note the biased variance estimator"
    phase: explore
  - title: "PyTorch docs — torch.nn.LayerNorm (Notes)"
    url: "https://pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html"
    why: "Confirms `unbiased=False`/`correction=0` is the convention — most common source of off-by-factor bugs"
    phase: implement
  - title: "Machine Learning with PyTorch and Scikit-Learn — Normalization in deep networks"
    book: "Raschka, Liu, Mirjalili (Packt, 2022)"
    why: "Compares LayerNorm/BatchNorm/RMSNorm with worked examples"
    phase: plan
---

## Prompt

Implement LayerNorm from scratch. Normalize over the last dimension of
the input. Signature:

```
def layer_norm(x, gamma, beta, eps=1e-5) -> torch.Tensor
```

`x` has shape `(..., d)`. `gamma` and `beta` are 1-D of length `d`. The
output has the same shape as `x`. Match `torch.nn.LayerNorm`'s behavior
to within 1e-5.

## Starter

```
import torch


def layer_norm(x: torch.Tensor, gamma: torch.Tensor, beta: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    # TODO
    pass
```

## Solution

```
import torch


def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    var = x.var(dim=-1, keepdim=True, unbiased=False)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(2)
x = torch.randn(3, 5, 8)
gamma = torch.randn(8)
beta = torch.randn(8)

ref_layer = nn.LayerNorm(8)
with torch.no_grad():
    ref_layer.weight.copy_(gamma)
    ref_layer.bias.copy_(beta)
ref = ref_layer(x)

out = layer_norm(x, gamma, beta)
assert out.shape == x.shape
assert torch.allclose(out, ref, atol=1e-5), (out - ref).abs().max().item()

# Normalization property: post-norm, gamma=1, beta=0, mean ~ 0, var ~ 1
out_id = layer_norm(x, torch.ones(8), torch.zeros(8))
assert out_id.mean(dim=-1).abs().max() < 1e-5
assert (out_id.var(dim=-1, unbiased=False) - 1.0).abs().max() < 1e-4

print("OK")
```

## Key insight

LayerNorm uses the **biased** variance (divides by N, not N-1). PyTorch's
`torch.var` defaults to `unbiased=True` — passing `unbiased=False` is what
matches `nn.LayerNorm`.

## Pitfalls

- `torch.var` with the default `unbiased=True` gives Bessel's correction
  (`/ (N-1)`). LayerNorm uses `/ N`. A correct-looking implementation
  with `unbiased=True` will disagree with `nn.LayerNorm` by a factor of
  `sqrt(N / (N-1))` on the variance — subtle and hard to spot in eval.
- `keepdim=True` is required on both mean and var so broadcasting against
  `x` works.
- `eps` goes inside the sqrt, not outside. `1 / (sqrt(var) + eps)` is a
  different (and wrong) operation.
