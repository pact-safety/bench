---
slug: top-p-sampling
title: Top-p (nucleus) sampling from logits
difficulty: medium
time_bucket: 30
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

Sample a token from a `(C,)` logits vector under top-p (nucleus)
decoding. Sort probabilities descending; keep tokens until the cumulative
mass first exceeds `p`; mask everything else; renormalize; sample.

The smallest set whose sum is ≥ p — meaning if the first token's mass
alone is ≥ p, only that token is kept.

```
def top_p_sample(logits, p, generator=None) -> int
```

## Starter

```
import torch


def top_p_sample(logits: torch.Tensor, p: float, generator: torch.Generator | None = None) -> int:
    # TODO
    pass
```

## Solution

```
import torch


def top_p_sample(logits, p, generator=None):
    probs = torch.softmax(logits, dim=-1)
    sorted_probs, sorted_idx = torch.sort(probs, descending=True)
    cum = torch.cumsum(sorted_probs, dim=-1)
    # Tokens whose cumulative sum at position i-1 already exceeded p are
    # outside the nucleus. We shift by 1 so the first token to push cum
    # past p is still kept.
    keep = cum - sorted_probs <= p
    sorted_probs = sorted_probs * keep
    sorted_probs = sorted_probs / sorted_probs.sum()
    chosen_sorted = int(torch.multinomial(sorted_probs, num_samples=1, generator=generator).item())
    return int(sorted_idx[chosen_sorted].item())
```

## Tests

```
import torch

# p = 1.0 keeps everything: sampling matches a plain multinomial
torch.manual_seed(0)
logits = torch.randn(8)
g = torch.Generator().manual_seed(7)
out = top_p_sample(logits, p=1.0, generator=g)
assert 0 <= out < 8

# Very small p keeps only the top token
top_idx = int(logits.argmax().item())
for _ in range(20):
    assert top_p_sample(logits, p=0.001) == top_idx

# Determinism
g1 = torch.Generator().manual_seed(11)
g2 = torch.Generator().manual_seed(11)
seq1 = [top_p_sample(logits, p=0.9, generator=g1) for _ in range(50)]
seq2 = [top_p_sample(logits, p=0.9, generator=g2) for _ in range(50)]
assert seq1 == seq2

# Two-class case: probs ~ [0.7, 0.3]. p=0.5 keeps only top; p=0.8 keeps both.
two = torch.tensor([2.0, 1.0])
seen_low = set(top_p_sample(two, p=0.5) for _ in range(50))
seen_high = set(top_p_sample(two, p=0.8) for _ in range(200))
assert seen_low == {0}
assert seen_high == {0, 1}

print("OK")
```

## Key insight

The nucleus is the smallest prefix of the sorted distribution whose mass
≥ p — *including* the token that pushes it over. The standard one-liner
`cum - sorted_probs <= p` captures "this token's predecessors had less
than p total, so include it."

## Pitfalls

- Using `cum <= p` (instead of `cum - sorted_probs <= p`) excludes the
  pivot token — for p = 0.5 and a 0.7-mass top token, you would keep
  nothing. Always include the token that crosses the threshold.
- After masking, you must renormalize. `torch.multinomial` does not
  require probabilities to sum to 1, but skipping renormalization makes
  the effective temperature wrong.
- Sample from the *sorted* probabilities and map back through
  `sorted_idx` — sampling from a re-scattered original-order distribution
  works too but is more error-prone.
