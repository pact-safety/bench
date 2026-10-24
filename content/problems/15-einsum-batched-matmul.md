---
slug: einsum-batched-matmul
title: einsum / broadcasting — three ways to batched matmul
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation]
domain_tags: [training]
competency_tags: [tensor_internals]
jd_signal_tags: [tensor_ops, einsum]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

You're given two batched tensors `A` of shape `(B, M, K)` and `B`
(unfortunate naming, but bear with it — call it `Bt`) of shape
`(B, K, N)`. Compute the per-example matrix product `(B, M, N)` three
ways:

```
def via_loop(A, Bt) -> torch.Tensor
def via_bmm(A, Bt) -> torch.Tensor
def via_einsum(A, Bt) -> torch.Tensor
```

The three must agree to within float noise (1e-5). Then implement a
fourth function:

```
def find_bad(impls: list[callable], A, Bt) -> list[int]
```

`impls` is a list of candidate implementations. Return the indices of
the implementations whose output disagrees with the majority on a
non-square shape (e.g., `M != N`).

## Starter

```
import torch


def via_loop(A, Bt):
    pass


def via_bmm(A, Bt):
    pass


def via_einsum(A, Bt):
    pass


def find_bad(impls, A, Bt):
    pass
```

## Solution

```
import torch


def via_loop(A, Bt):
    return torch.stack([A[i] @ Bt[i] for i in range(A.shape[0])], dim=0)


def via_bmm(A, Bt):
    return torch.bmm(A, Bt)


def via_einsum(A, Bt):
    return torch.einsum("bmk,bkn->bmn", A, Bt)


def find_bad(impls, A, Bt):
    # Implementations may raise (shape mismatch is itself a "bad" signal).
    outs: list = []
    raised = set()
    for i, f in enumerate(impls):
        try:
            outs.append(f(A, Bt))
        except Exception:
            outs.append(None)
            raised.add(i)
    n = len(outs)
    votes = [0] * n
    for i in range(n):
        if outs[i] is None:
            continue
        for j in range(n):
            if i == j or outs[j] is None:
                continue
            if outs[i].shape == outs[j].shape and torch.allclose(outs[i], outs[j], atol=1e-5):
                votes[i] += 1
    best = max(votes) if votes else 0
    bad = {i for i, v in enumerate(votes) if v < best} | raised
    return sorted(bad)
```

## Tests

```
import torch

torch.manual_seed(7)
B, M, K, N = 3, 4, 5, 6
A = torch.randn(B, M, K)
Bt = torch.randn(B, K, N)

out_loop = via_loop(A, Bt)
out_bmm = via_bmm(A, Bt)
out_einsum = via_einsum(A, Bt)

assert out_loop.shape == (B, M, N)
assert torch.allclose(out_loop, out_bmm, atol=1e-5)
assert torch.allclose(out_loop, out_einsum, atol=1e-5)


# An incorrect implementation: transposes Bt — produces wrong values on
# non-square shapes (different output shape), or wrong on square shapes.
def wrong(A, Bt):
    return torch.einsum("bmk,bnk->bmn", A, Bt)


bad = find_bad([via_bmm, via_einsum, wrong], A, Bt)
assert bad == [2], bad

# Three correct should yield no flags
bad2 = find_bad([via_bmm, via_einsum, via_loop], A, Bt)
assert bad2 == [], bad2

print("OK")
```

## Key insight

`einsum` is the unambiguous way to write batched contractions because
the index letters make the operation auditable at a glance. `bmm` is
the fastest for the standard three-axis case. The loop is what you
write when you want a correctness oracle.

## Pitfalls

- The classic einsum bug is swapping two index letters in one operand —
  `'bmk,bnk->bmn'` looks correct, but it transposes Bt and silently
  computes `A @ Bt.transpose(-1, -2)`, which has the right shape when
  `K == N` and the wrong shape otherwise.
- `torch.matmul` works here too via broadcasting, but `bmm` is stricter
  about shapes and surfaces shape bugs at runtime instead of silently
  broadcasting. Use bmm in code you want to be loud.
- A pure-Python loop is fine for correctness checks but is two orders of
  magnitude slower than `bmm`. Never ship the loop version.
