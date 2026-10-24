---
slug: debug-softmax-before-ce
title: Debug — softmax applied before cross-entropy
difficulty: easy
time_bucket: 10
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

The model below never converges. Loss is roughly flat at ~0.69 for a
2-class problem regardless of training time. Find the bug, fix it.

## Starter

```
import torch
import torch.nn as nn
import torch.nn.functional as F


def step(model, x, y, optimizer):
    logits = model(x)
    probs = F.softmax(logits, dim=-1)
    loss = F.cross_entropy(probs, y)
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
    # F.cross_entropy expects raw logits, not softmax output. Applying
    # softmax first gives a "double softmax" inside the loss — the
    # gradient direction is right but the magnitude is collapsed because
    # the inputs are already in [0, 1] and re-softmaxing flattens them
    # toward uniform.
    loss = F.cross_entropy(logits, y)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return loss.item()
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(12)
N, D, V = 200, 4, 2
X = torch.randn(N, D)
w = torch.tensor([1.0, -1.0, 0.5, 0.0])
y = (X @ w > 0).long()

model = nn.Linear(D, V)
opt = torch.optim.SGD(model.parameters(), lr=0.1)
losses = []
for epoch in range(40):
    epoch_losses = []
    for s in range(0, N, 16):
        epoch_losses.append(step(model, X[s : s + 16], y[s : s + 16], opt))
    losses.append(sum(epoch_losses) / len(epoch_losses))

assert losses[4] < 0.3, (
    f"loss too high at epoch 5: {losses[4]:.3f} — likely double-softmax"
)

with torch.no_grad():
    pred = model(X).argmax(dim=-1)
acc = (pred == y).float().mean().item()
assert acc > 0.95, acc

print("OK")
```

## Key insight

`F.cross_entropy` and `nn.CrossEntropyLoss` take **logits**, not
probabilities. The function internally does `log_softmax + nll_loss`.
Passing probabilities is the canonical PyTorch beginner bug; it still
"works" (loss decreases slightly) which is why it survives review.

## Pitfalls

- Symptom fingerprint: loss starts around the random-guessing value
  (`log(C)` ≈ 0.69 for C=2) and decreases very slowly. Compare to a
  correct training run where it falls within a few epochs.
- A genuine "I want softmax output as input" loss is `F.nll_loss(log_probs, y)`
  with `log_probs = F.log_softmax(logits, dim=-1)`. Don't mix conventions.
- This bug is undetectable from the loss value alone — the magnitude
  is reasonable, just stuck. The accuracy metric is what reveals it.
