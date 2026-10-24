---
slug: cross-entropy-stable
title: Cross-entropy from logits with log-sum-exp
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [numerical_stability]
domain_tags: [training]
competency_tags: [training_internals]
jd_signal_tags: [training, numerical_stability]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement cross-entropy from raw logits with `log-sum-exp` stabilization.
You may not call `F.cross_entropy` or `F.log_softmax`. You may use `exp`,
`log`, `sum`, `max`, and indexing.

```
def cross_entropy(logits, targets) -> torch.Tensor:
    # logits: (N, C) raw scores
    # targets: (N,) integer class indices in [0, C)
    # returns: scalar mean loss
```

The result must be finite even when some logits are ~1e3 in magnitude.

## Starter

```
import torch


def cross_entropy(logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    # TODO
    pass
```

## Solution

```
import torch


def cross_entropy(logits, targets):
    m = logits.max(dim=-1, keepdim=True).values
    shifted = logits - m
    log_sum_exp = torch.log(torch.exp(shifted).sum(dim=-1)) + m.squeeze(-1)
    correct = logits.gather(1, targets.unsqueeze(1)).squeeze(1)
    return (log_sum_exp - correct).mean()
```

## Tests

```
import torch
import torch.nn.functional as F

torch.manual_seed(3)
logits = torch.randn(7, 12)
targets = torch.randint(0, 12, (7,))
ref = F.cross_entropy(logits, targets)
out = cross_entropy(logits, targets)
assert torch.allclose(out, ref, atol=1e-5), (out - ref).abs().item()

# Stability under large logits
big = torch.tensor([[1000.0, 999.0, 998.0], [-1000.0, -1001.0, -999.0]])
tgt = torch.tensor([0, 2])
out_big = cross_entropy(big, tgt)
ref_big = F.cross_entropy(big, tgt)
assert torch.isfinite(out_big)
assert torch.allclose(out_big, ref_big, atol=1e-4)

print("OK")
```

## Key insight

`log(sum(exp(x_i)))` overflows if any `x_i` is large. Subtracting the
per-row max before the `exp` doesn't change the result — `log(sum exp x_i)
= m + log(sum exp(x_i - m))` — and keeps every `exp` argument ≤ 0.

## Pitfalls

- The naive `-log(softmax(logits)).gather(...)` is numerically the same
  as log-sum-exp only if softmax was stabilized. A bare `exp(logits) /
  exp(logits).sum()` overflows.
- `gather` requires the index tensor to have the same number of dims as
  the input; `.unsqueeze(1)` is required before gathering along dim 1.
- `mean()` not `sum()` for matching PyTorch's default reduction.
