---
slug: softmax-temperature
title: Softmax with temperature
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [numerical_stability, sampling]
domain_tags: [training, eval]
competency_tags: [sampling]
jd_signal_tags: [decoding, sampling]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement temperature-scaled softmax over the last dim. As `T -> 0+`,
the distribution should approach the argmax one-hot; as `T -> inf`, it
should approach uniform. Numerically stable.

```
def softmax_with_temperature(logits, T) -> torch.Tensor
```

`T > 0`. `logits` shape `(..., C)`. Output same shape, sums to 1 along
the last dim.

## Starter

```
import torch


def softmax_with_temperature(logits: torch.Tensor, T: float) -> torch.Tensor:
    # TODO
    pass
```

## Solution

```
import torch


def softmax_with_temperature(logits, T):
    scaled = logits / T
    m = scaled.max(dim=-1, keepdim=True).values
    exp = torch.exp(scaled - m)
    return exp / exp.sum(dim=-1, keepdim=True)
```

## Tests

```
import torch

logits = torch.tensor([[2.0, 1.0, 0.0, -1.0]])

p_low = softmax_with_temperature(logits, T=0.01)
assert p_low.argmax(dim=-1).item() == 0
assert p_low[0, 0] > 0.99

p_high = softmax_with_temperature(logits, T=1000.0)
assert torch.allclose(p_high, torch.full_like(p_high, 0.25), atol=1e-3)

p_one = softmax_with_temperature(logits, T=1.0)
ref = torch.softmax(logits, dim=-1)
assert torch.allclose(p_one, ref, atol=1e-6)

# All rows sum to 1
batch = torch.randn(5, 7)
out = softmax_with_temperature(batch, T=0.7)
assert torch.allclose(out.sum(dim=-1), torch.ones(5), atol=1e-6)

print("OK")
```

## Key insight

Temperature divides logits before softmax. Lower `T` sharpens (logits
spread out further), higher `T` flattens. Subtract the post-scale max
for stability, not the pre-scale max.

## Pitfalls

- Dividing the softmax output by T instead of the logits does not give
  temperature scaling — it un-normalizes.
- For tiny `T` (e.g. 0.01), `scaled = logits / T` becomes huge; without
  the `- max` shift, `exp` overflows.
