---
slug: layernorm-vs-rmsnorm
title: LayerNorm vs RMSNorm — implement both and reason about choice
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, numerical_stability]
domain_tags: [training]
competency_tags: [transformer_internals]
jd_signal_tags: [transformer, training_internals, rmsnorm]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement both normalization layers from scratch, normalizing over the
last dimension:

```
def layer_norm(x, gamma, beta, eps=1e-5) -> torch.Tensor
def rms_norm(x, gamma, eps=1e-5) -> torch.Tensor
```

RMSNorm: `x / sqrt(mean(x^2) + eps) * gamma`. No mean-centering, no
bias. The motivation in the Llama-family papers: the mean-centering
step in LayerNorm is the bulk of the cost and contributes little to the
training signal in practice; dropping it is a ~7% speedup with no
measurable quality loss.

## Starter

```
import torch


def layer_norm(x: torch.Tensor, gamma: torch.Tensor, beta: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    pass


def rms_norm(x: torch.Tensor, gamma: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    pass
```

## Solution

```
import torch


def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    var = x.var(dim=-1, keepdim=True, unbiased=False)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta


def rms_norm(x, gamma, eps=1e-5):
    rms = torch.sqrt((x * x).mean(dim=-1, keepdim=True) + eps)
    return x / rms * gamma
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(9)
D = 8
x = torch.randn(3, 5, D)
gamma = torch.randn(D)
beta = torch.randn(D)

ref_ln = nn.LayerNorm(D)
with torch.no_grad():
    ref_ln.weight.copy_(gamma)
    ref_ln.bias.copy_(beta)
assert torch.allclose(layer_norm(x, gamma, beta), ref_ln(x), atol=1e-5)

# RMSNorm reference: identity-gamma, zero-mean check would FAIL because
# RMSNorm does not center. Property test: scale-equivariance up to eps.
# With eps > 0, equivariance is approximate; use a larger scale so eps
# is negligible against mean(x*x).
x_big = x * 100.0
out = rms_norm(x_big, gamma)
out_scaled = rms_norm(x_big * 3.0, gamma)
assert torch.allclose(out, out_scaled, atol=1e-4)

# And RMSNorm produces non-zero mean in general (no centering).
plain = rms_norm(x, torch.ones(D))
assert plain.mean(dim=-1).abs().max() > 1e-3, "rmsnorm should not center"

print("OK")
```

## Key insight

The right question isn't "which is better" — it's "which constraint
matters here." If the architecture relies on activations being
mean-centered (older pre-Llama transformers, some interpretability
probes), use LayerNorm. If you want a 5-10% throughput bump and you
control the architecture, RMSNorm.

## Pitfalls

- Variance in LayerNorm is biased (`unbiased=False`). The same pitfall
  as the LayerNorm-from-scratch problem; here it appears alongside a
  totally different operator and is easy to mis-apply by reflex.
- RMSNorm has no `beta`. Adding one accidentally is a silent
  off-by-bias bug.
- `mean(x*x)` and `(x.square()).mean()` are the same; `x.norm(dim=-1) /
  sqrt(D)` is the same thing too. The unit test doesn't care which form
  you pick; pick the one that reads.
