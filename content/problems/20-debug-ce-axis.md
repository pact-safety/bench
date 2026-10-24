---
slug: debug-ce-axis
title: Debug — cross-entropy reducing the wrong axis
difficulty: medium
time_bucket: 30
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, training_loop_mechanics]
domain_tags: [training]
competency_tags: [debugging, training_internals]
jd_signal_tags: [debugging, training]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

The training loop below reports plausible-looking loss numbers but the
model never improves. The symptom is "loss numbers look reasonable, but
gradients are wrong." Find the bug and fix it. Keep the function
signature.

The model output is `(B, V)` logits, the targets are `(B,)` class
indices, and the data is linearly separable.

## Starter

```
import torch
import torch.nn as nn
import torch.nn.functional as F


def step(model, x, y, optimizer):
    logits = model(x)
    # Cross-entropy implemented manually for "stability"
    log_probs = F.log_softmax(logits, dim=0)  # bug hides here
    nll = -log_probs.gather(1, y.unsqueeze(1)).squeeze(1)
    loss = nll.mean()
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return loss.item()
```

## Solution

```
import torch
import torch.nn as nn
import torch.nn.functional as F


def step(model, x, y, optimizer):
    logits = model(x)
    # log_softmax must be over the class axis (dim=-1), not the batch axis.
    # Reducing over batch makes "probabilities" sum to 1 across examples,
    # which produces a finite loss number but gradients that have nothing
    # to do with the classification task.
    log_probs = F.log_softmax(logits, dim=-1)
    nll = -log_probs.gather(1, y.unsqueeze(1)).squeeze(1)
    loss = nll.mean()
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return loss.item()
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(11)
N, D, V = 200, 4, 2
w_true = torch.tensor([1.0, -1.0, 0.5, 0.0])
X = torch.randn(N, D)
y = (X @ w_true > 0).long()

model = nn.Linear(D, V)
opt = torch.optim.SGD(model.parameters(), lr=0.1)
for _ in range(40):
    for s in range(0, N, 16):
        step(model, X[s : s + 16], y[s : s + 16], opt)

with torch.no_grad():
    pred = model(X).argmax(dim=-1)
acc = (pred == y).float().mean().item()
assert acc > 0.95, acc

print("OK")
```

## Key insight

`F.log_softmax(logits, dim=0)` normalizes across the batch — every
sample's logit gets compared to the same-class logits of other samples
in the batch, not to its own other-class logits. The gradient
direction is wrong but the loss value still looks like a normal
cross-entropy number, which is what makes the bug survive review.

## Pitfalls

- The fix is `dim=-1` (or equivalently `dim=1` for this shape).
- `F.cross_entropy(logits, y)` takes a `dim` only implicitly (the class
  axis is always the second one); the manual two-step version
  (`log_softmax + gather`) is where this bug lives.
- The `loss.item()` number for the buggy version still decreases for the
  first few steps because the batch-normalized probabilities have *some*
  correlation with the right answer; it stalls quickly, around chance.
