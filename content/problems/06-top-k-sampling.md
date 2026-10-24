---
slug: top-k-sampling
title: Top-k sampling from logits
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: false
structural_tags: [sampling, tensor_manipulation]
domain_tags: [eval]
competency_tags: [sampling]
jd_signal_tags: [decoding, sampling]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Sample a token id from a `(C,)` logits vector under top-k decoding. The k
largest logits keep their values; everything else gets `-inf` before
softmax; sample from that masked distribution.

```
def top_k_sample(logits, k, generator=None) -> int
```

Determinism: when `generator` is provided, the result must be reproducible
for a given seed.

## Starter

```
import torch


def top_k_sample(logits: torch.Tensor, k: int, generator: torch.Generator | None = None) -> int:
    # TODO
    pass
```

## Solution

```
import torch


def top_k_sample(logits, k, generator=None):
    topk = torch.topk(logits, k)
    masked = torch.full_like(logits, float("-inf"))
    masked.scatter_(0, topk.indices, topk.values)
    probs = torch.softmax(masked, dim=-1)
    return int(torch.multinomial(probs, num_samples=1, generator=generator).item())
```

## Tests

```
import torch

# k = 1 is greedy
logits = torch.tensor([0.5, 3.0, -1.0, 2.0])
g = torch.Generator().manual_seed(0)
for _ in range(20):
    assert top_k_sample(logits, k=1, generator=g) == 1

# k = 2 restricts to {1, 3}
seen = set()
g = torch.Generator().manual_seed(0)
for _ in range(200):
    seen.add(top_k_sample(logits, k=2, generator=g))
assert seen.issubset({1, 3}), seen

# Determinism
g1 = torch.Generator().manual_seed(42)
g2 = torch.Generator().manual_seed(42)
seq1 = [top_k_sample(logits, k=2, generator=g1) for _ in range(30)]
seq2 = [top_k_sample(logits, k=2, generator=g2) for _ in range(30)]
assert seq1 == seq2

print("OK")
```

## Key insight

The cleanest path: build a mask of `-inf`, then `scatter_` the top-k
values back in. Softmax of `-inf` is exactly 0, so multinomial never
picks them.

## Pitfalls

- `torch.topk` returns `(values, indices)`. `scatter_(dim, indices,
  values)` writes back to the right positions; `gather` is the reverse
  operation and the wrong direction here.
- `torch.multinomial` requires nonzero probabilities at chosen positions.
  Building probs over `-inf` masks is fine because softmax produces
  exactly 0 at those positions; do not pre-zero or pre-normalize.
- Setting `k > C` (vocab size) silently works for `topk` but is logically
  meaningless — the function should still work; tests don't probe this
  edge case but it's worth a guard in production.
