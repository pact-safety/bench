---
slug: debug-padding-mask
title: Debug — padding mask direction error
difficulty: medium
time_bucket: 30
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, attention]
domain_tags: [attention]
competency_tags: [debugging, transformer_internals]
jd_signal_tags: [debugging, transformer, attention]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

The encoder below should ignore padding tokens. The convention used
elsewhere in the codebase: `pad_mask` is shape `(B, S)`, `True` where
the position **is padding** (i.e., should be ignored). The function
runs without error but downstream tasks slowly degrade as padded
batches enter training — eventually the model is paying real attention
to pad tokens.

Find the bug.

## Starter

```
import torch
import torch.nn.functional as F


def masked_attention(q, k, v, pad_mask):
    # q, k, v: (B, S, D)
    # pad_mask: (B, S), True at padding positions.
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    # Block attention to padding positions.
    mask = pad_mask.unsqueeze(1)  # (B, 1, S), broadcasts over query positions
    scores = scores.masked_fill(~mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v
```

## Solution

```
import torch
import torch.nn.functional as F


def masked_attention(q, k, v, pad_mask):
    d = q.shape[-1]
    scores = q @ k.transpose(-1, -2) / (d ** 0.5)
    mask = pad_mask.unsqueeze(1)
    # Bug: the `~mask` inversion is wrong because `pad_mask` is already
    # True at the positions we want to ignore. masked_fill writes -inf
    # where the mask is True, so we pass `mask` directly. The original
    # was masking out the *non-padding* positions, leaving padding
    # attended to.
    scores = scores.masked_fill(mask, float("-inf"))
    return F.softmax(scores, dim=-1) @ v
```

## Tests

```
import torch
import torch.nn.functional as F

torch.manual_seed(15)
B, S, D = 2, 6, 8
q = torch.randn(B, S, D)
k = torch.randn(B, S, D)
v = torch.randn(B, S, D)
pad = torch.tensor([
    [False, False, False, True, True, True],
    [False, False, True, True, True, True],
])

out = masked_attention(q, k, v, pad)

# Changing the values at padded positions must not change the output at
# non-padded query positions.
v2 = v.clone()
v2[0, 3:] = torch.randn_like(v2[0, 3:])
v2[1, 2:] = torch.randn_like(v2[1, 2:])
out2 = masked_attention(q, k, v2, pad)
# Compare outputs only at non-pad query positions.
mask_keep = ~pad.unsqueeze(-1)
assert torch.allclose(out * mask_keep, out2 * mask_keep, atol=1e-5), \
    "padding leakage: output at non-pad positions changes with pad-position values"

print("OK")
```

## Key insight

`masked_fill` writes the fill value *at the truthy positions of the
mask*. If the convention you receive is "True = ignore", you pass the
mask directly, not negated. Negating turns it into "True = keep" which
is the wrong semantics with `masked_fill`.

## Pitfalls

- The HuggingFace `attention_mask` convention is the *opposite*:
  `1 = attend, 0 = ignore`. Mixing conventions across libraries is the
  source of this whole family of bugs. Always ground the convention in
  the *destination function*'s semantics (here: `masked_fill`).
- Watch the broadcast axis: `(B, S)` -> `unsqueeze(1)` makes it
  `(B, 1, S)` which broadcasts over query positions. `unsqueeze(2)`
  would make it `(B, S, 1)` which broadcasts the other way and creates
  a different, also-wrong, masking pattern.
- Eval at pad-position queries is undefined — those rows of the output
  will be NaN if every key is masked. Most real code zeroes them after
  attention, or uses a query-side mask too. The test only inspects
  non-pad query positions.
