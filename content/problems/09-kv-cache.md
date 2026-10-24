---
slug: kv-cache
title: KV-cache update for incremental decoding
difficulty: hard
time_bucket: 60
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, attention, control_flow]
domain_tags: [attention]
competency_tags: [transformer_internals]
jd_signal_tags: [decoding, inference, transformer]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement an incremental KV cache for single-head attention. Two
functions:

```
def forward_full(x, w_q, w_k, w_v, w_o):
    # x: (1, S, D). Returns output (1, S, D). Causal.

def forward_step(x_new, cache, w_q, w_k, w_v, w_o):
    # x_new: (1, 1, D) — the new token's input embedding.
    # cache: dict with keys 'k' and 'v', tensors shaped (1, S_prev, D)
    #        (may be None initially).
    # Returns: (output_for_new_token (1, 1, D), updated_cache)
```

Correctness condition: if you call `forward_step` repeatedly to decode N
tokens, the concatenation of outputs must equal `forward_full` on the
same inputs to within 1e-5.

## Starter

```
import torch
import torch.nn.functional as F


def forward_full(x, w_q, w_k, w_v, w_o):
    # TODO
    pass


def forward_step(x_new, cache, w_q, w_k, w_v, w_o):
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn.functional as F


def forward_full(x, w_q, w_k, w_v, w_o):
    q = x @ w_q
    k = x @ w_k
    v = x @ w_v
    out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
    return out @ w_o


def forward_step(x_new, cache, w_q, w_k, w_v, w_o):
    q = x_new @ w_q          # (1, 1, D)
    k_new = x_new @ w_k      # (1, 1, D)
    v_new = x_new @ w_v      # (1, 1, D)
    if cache is None:
        k = k_new
        v = v_new
    else:
        k = torch.cat([cache["k"], k_new], dim=1)
        v = torch.cat([cache["v"], v_new], dim=1)
    # Query is only the new token; keys/values include the full history.
    # Causality is automatic: the new token can attend to everything in
    # the cache, which is exactly the prefix.
    out = F.scaled_dot_product_attention(q, k, v)
    return out @ w_o, {"k": k, "v": v}
```

## Tests

```
import torch

torch.manual_seed(4)
S, D = 6, 16
x = torch.randn(1, S, D)
w_q = torch.randn(D, D) * 0.1
w_k = torch.randn(D, D) * 0.1
w_v = torch.randn(D, D) * 0.1
w_o = torch.randn(D, D) * 0.1

full = forward_full(x, w_q, w_k, w_v, w_o)

# Incremental decode token by token
cache = None
outs = []
for t in range(S):
    out_t, cache = forward_step(x[:, t : t + 1, :], cache, w_q, w_k, w_v, w_o)
    outs.append(out_t)
incremental = torch.cat(outs, dim=1)

assert incremental.shape == full.shape, (incremental.shape, full.shape)
assert torch.allclose(incremental, full, atol=1e-5), (incremental - full).abs().max().item()

print("OK")
```

## Key insight

The single-token query attends over the full cached K/V. Causality is
free at decode time because the query is the new position and there are
no future positions to mask out — they don't exist yet.

## Pitfalls

- Setting `is_causal=True` in the incremental step is wrong (and slower).
  At decode time the query is length 1, and the cache contains exactly
  the prefix you want it to see. A causal mask would block all but the
  diagonal, which is meaningless for a single query position.
- Concatenating the new K/V along the wrong axis is the canonical bug.
  Cache shape is `(batch, seq, d)`; new K/V is `(batch, 1, d)`; concat
  along `dim=1`. Concatenating along `dim=-1` gives a feature-dim cat
  that silently produces wrong logits with the right shape.
- Don't recompute K/V for the prefix on every step — that defeats the
  point of the cache. Only the new token's K/V is projected each step.
