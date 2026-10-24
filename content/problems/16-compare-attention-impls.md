---
slug: compare-attention-impls
title: Compare two attention implementations and pick the correct one
difficulty: medium
time_bucket: 30
problem_type: code_read
is_warmup: false
structural_tags: [attention, tensor_manipulation]
domain_tags: [attention]
competency_tags: [code_review]
jd_signal_tags: [code_review, transformer]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Two implementations of single-head causal attention are below. Without
running the test cases — just reading — figure out which one is correct.
Implement:

```
def pick_correct() -> str
    # return 'A' or 'B'
```

That function should hard-return the answer. The test harness will run
both implementations against a reference and verify your pick.

## Starter

```
import torch
import torch.nn.functional as F


def impl_a(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    mask = torch.tril(torch.ones(S, S, dtype=torch.bool, device=q.device))
    scores = scores.masked_fill(~mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v


def impl_b(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    mask = torch.tril(torch.ones(S, S, dtype=torch.bool, device=q.device))
    scores = scores.masked_fill(mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v


def pick_correct():
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn.functional as F


def impl_a(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    mask = torch.tril(torch.ones(S, S, dtype=torch.bool, device=q.device))
    scores = scores.masked_fill(~mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v


def impl_b(q, k, v):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    S = q.shape[-2]
    mask = torch.tril(torch.ones(S, S, dtype=torch.bool, device=q.device))
    scores = scores.masked_fill(mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v


def pick_correct():
    return "A"
```

## Tests

```
import torch
import torch.nn.functional as F

torch.manual_seed(8)
q = torch.randn(1, 5, 8)
k = torch.randn(1, 5, 8)
v = torch.randn(1, 5, 8)
ref = F.scaled_dot_product_attention(q, k, v, is_causal=True)

choice = pick_correct()
assert choice in ("A", "B")
chosen = impl_a if choice == "A" else impl_b

assert torch.allclose(chosen(q, k, v), ref, atol=1e-5), "chosen impl is wrong"

# The other impl really is broken
other = impl_b if choice == "A" else impl_a
assert not torch.allclose(other(q, k, v), ref, atol=1e-3), "both impls passed — test setup is broken"

print("OK")
```

## Key insight

`torch.tril` produces the lower triangle including the diagonal — these
are the positions that *should* attend. So you mask the *complement*
(`~mask`) with `-inf`. Impl B masks the kept positions and lets the
forbidden positions through; classic sign-flip bug.

## Pitfalls

- `torch.tril` vs `torch.triu` flips which triangle is masked, and you
  invert the mask either way; both conventions appear in the wild. Read
  the masked_fill argument: it sets values *to* `-inf` at the truthy
  positions. So the truthy positions are the *forbidden* positions.
- A common variant uses `torch.tril(torch.ones(...))` as a float mask
  and `*` or `+ (1 - mask) * -inf`; same semantics, different sharp
  edges around `0 * inf = nan`. Stick to bool + masked_fill.
- This problem is read-and-reason: don't try to "fix both" or rewrite —
  pick one, justify in the key insight, and verify against the
  reference at test time.
