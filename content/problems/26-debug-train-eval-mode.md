---
slug: debug-train-eval-mode
title: Debug — train/eval mode confusion in evaluation harness
difficulty: easy
time_bucket: 10
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, training_loop_mechanics]
domain_tags: [eval]
competency_tags: [debugging, training_internals]
jd_signal_tags: [debugging, eval, robustness]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

An evaluation harness reports stochastic results — running it twice on
the same model and same data gives slightly different accuracy each
time. Find the bug.

## Starter

```
import torch
import torch.nn as nn


def evaluate(model, X, y):
    correct = 0
    total = 0
    for i in range(0, len(X), 32):
        xb = X[i : i + 32]
        yb = y[i : i + 32]
        logits = model(xb)
        pred = logits.argmax(dim=-1)
        correct += (pred == yb).sum().item()
        total += len(yb)
    return correct / total
```

## Solution

```
import torch
import torch.nn as nn


def evaluate(model, X, y):
    # Two changes:
    # 1) Switch to eval mode so dropout / batchnorm use their
    #    deterministic eval-time behavior.
    # 2) Disable autograd to avoid building the graph.
    was_training = model.training
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for i in range(0, len(X), 32):
            xb = X[i : i + 32]
            yb = y[i : i + 32]
            logits = model(xb)
            pred = logits.argmax(dim=-1)
            correct += (pred == yb).sum().item()
            total += len(yb)
    if was_training:
        model.train()
    return correct / total
```

## Tests

```
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(17)


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(8, 16)
        self.drop = nn.Dropout(0.5)
        self.fc2 = nn.Linear(16, 2)

    def forward(self, x):
        h = F.relu(self.fc1(x))
        h = self.drop(h)
        return self.fc2(h)


model = Net()
model.train()  # simulate "left in train mode" state

X = torch.randn(64, 8)
y = torch.randint(0, 2, (64,))

a = evaluate(model, X, y)
b = evaluate(model, X, y)
assert abs(a - b) < 1e-9, f"evaluate is stochastic across calls: {a} vs {b}"

# Bonus: after evaluate, the model should still be in train mode.
assert model.training is True

print("OK")
```

## Key insight

`Dropout` and `BatchNorm` (and a few other layers) read `self.training`
on every forward pass and behave differently in train vs eval mode.
Forgetting `model.eval()` in an evaluation function is the canonical
"results aren't reproducible" bug. Pair it with `torch.no_grad()` to
avoid building the autograd graph during eval — that's correctness
(saves memory) but doesn't change accuracy numbers.

## Pitfalls

- Restore the original mode after eval. A harness that leaves the model
  in eval mode breaks the next training step. The `was_training`
  pattern handles it.
- `torch.no_grad()` and `model.eval()` are independent. `eval()` is
  required for correctness when dropout / batchnorm are present;
  `no_grad()` is required for memory; neither is sufficient alone.
- BatchNorm in eval mode uses running statistics, which can be
  uninitialized in a freshly-created model — the first eval call may
  produce odd results until the running stats stabilize. Not the bug
  here, but a related trap.
