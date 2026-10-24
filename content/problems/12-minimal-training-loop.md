---
slug: minimal-training-loop
title: Minimal training loop on a synthetic task
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [training_loop_mechanics, control_flow]
domain_tags: [training]
competency_tags: [training_internals]
jd_signal_tags: [training]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Write a training loop that learns a 2-class linear separation. You're
given:

- A model `nn.Linear(D, 2)`
- `X` of shape `(N, D)` and labels `y` of shape `(N,)` in `{0, 1}`
- `epochs`, `batch_size`, `lr`

Return the trained model. Use minibatch SGD (no momentum), cross-entropy
loss, no shuffling between epochs (deterministic order), no validation.

```
def train(model, X, y, epochs, batch_size, lr) -> nn.Module
```

Correctness target: on a linearly separable synthetic dataset, training
accuracy after `epochs=20` must exceed 95%.

## Starter

```
import torch
import torch.nn as nn
import torch.nn.functional as F


def train(model: nn.Module, X: torch.Tensor, y: torch.Tensor, epochs: int, batch_size: int, lr: float) -> nn.Module:
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn as nn
import torch.nn.functional as F


def train(model, X, y, epochs, batch_size, lr):
    optimizer = torch.optim.SGD(model.parameters(), lr=lr)
    model.train()
    N = X.shape[0]
    for _ in range(epochs):
        for start in range(0, N, batch_size):
            xb = X[start : start + batch_size]
            yb = y[start : start + batch_size]
            optimizer.zero_grad()
            logits = model(xb)
            loss = F.cross_entropy(logits, yb)
            loss.backward()
            optimizer.step()
    return model
```

## Tests

```
import torch
import torch.nn as nn

torch.manual_seed(6)
N, D = 200, 4
w_true = torch.tensor([1.0, -1.0, 0.5, 0.0])
X = torch.randn(N, D)
y = (X @ w_true > 0).long()

model = nn.Linear(D, 2)
train(model, X, y, epochs=20, batch_size=16, lr=0.1)
model.eval()
with torch.no_grad():
    pred = model(X).argmax(dim=-1)
acc = (pred == y).float().mean().item()
assert acc > 0.95, acc

print("OK")
```

## Key insight

`zero_grad` goes at the top of each step, not the end of the previous
step. Either works in this loop because the steps don't share state with
anything outside the loop, but the convention of "zero before forward"
is what survives refactors (e.g., gradient accumulation), where bottom
placement breaks correctness silently.

## Pitfalls

- `model.train()` and `model.eval()` mode toggles. With a bare `Linear`
  it doesn't matter, but the moment you add dropout or batchnorm, eval
  is silently wrong if you stay in train mode.
- `F.cross_entropy(logits, y)` — `y` must be `long`. Passing `float`
  raises a runtime error in newer PyTorch but used to silently miscast.
- `optimizer.zero_grad(set_to_none=True)` is the modern preference (it
  avoids a separate memory allocation), but for an interview answer
  plain `zero_grad()` is fine.
