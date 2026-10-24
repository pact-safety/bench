---
slug: debug-detach-block
title: Debug — detach() blocking gradient flow through a residual
difficulty: medium
time_bucket: 30
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, training_loop_mechanics]
domain_tags: [training]
competency_tags: [debugging, autograd]
jd_signal_tags: [debugging, autograd, training]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

The two-layer block below is supposed to be a residual: `block(x) = x +
f(x)`. The internal `f` is a `Linear`. With this layer, training the
output projection at the end of a small stack converges, but loss
plateaus higher than expected. Specifically, the gradient never reaches
the residual layer's parameters. Find the bug.

## Starter

```
import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.f = nn.Linear(d, d)

    def forward(self, x):
        y = self.f(x).detach()
        return x + y
```

## Solution

```
import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.f = nn.Linear(d, d)

    def forward(self, x):
        # The `.detach()` cuts the autograd graph at f(x). Forward output
        # is unchanged, gradients flow through the `x +` term, but `f`
        # receives no gradient and never updates. Remove the detach.
        return x + self.f(x)
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(16)
D = 8
block = ResidualBlock(D)
head = nn.Linear(D, 2)

opt = torch.optim.SGD(list(block.parameters()) + list(head.parameters()), lr=0.1)
N = 200
X = torch.randn(N, D)
y = (X.sum(dim=-1) > 0).long()

for _ in range(20):
    for s in range(0, N, 16):
        xb, yb = X[s : s + 16], y[s : s + 16]
        logits = head(block(xb))
        loss = torch.nn.functional.cross_entropy(logits, yb)
        opt.zero_grad()
        loss.backward()
        opt.step()

# Block parameters must have moved from their initialization.
initial = ResidualBlock(D)
moved_w = (block.f.weight - initial.f.weight).abs().max().item()
assert moved_w > 1e-3, f"block.f.weight unchanged ({moved_w}); detach is still blocking"

with torch.no_grad():
    pred = head(block(X)).argmax(dim=-1)
acc = (pred == y).float().mean().item()
assert acc > 0.85, acc

print("OK")
```

## Key insight

`.detach()` returns a tensor with the same values but no autograd
history. The forward output is correct; gradients through that
particular tensor are silently dropped. The fingerprint is: training
"works" in the sense that some parameters move (those reachable through
the other path), but a specific layer's params never change.

## Pitfalls

- Detach inside a residual is the most common surprise; the user often
  added it during debugging to "stop the gradient explosion" and never
  reverted.
- `with torch.no_grad():` around an *assignment* (e.g., `self.x = ...`)
  is a different bug — that one detaches everything stored, which can
  silently break downstream layers too.
- The symptom is usually "training plateaus higher than baseline" not
  "training diverges." This makes the bug survive long evaluations.
