---
slug: debug-grad-accum-scale
title: Debug — gradient accumulation that doesn't scale loss
difficulty: medium
time_bucket: 30
problem_type: code_debug
is_warmup: false
structural_tags: [debugging, training_loop_mechanics]
domain_tags: [training]
competency_tags: [debugging, training_internals]
jd_signal_tags: [debugging, training, gradient_accumulation]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

A team migrating a recipe to gradient accumulation reports that the
exact same learning rate they used before now causes training to
diverge. The function below is what they're running. Find the bug.

## Starter

```
import torch
import torch.nn.functional as F


def train_one_step(model, optimizer, microbatches):
    optimizer.zero_grad()
    total = 0.0
    for x, y in microbatches:
        logits = model(x)
        loss = F.cross_entropy(logits, y)
        loss.backward()
        total += loss.item()
    optimizer.step()
    return total / len(microbatches)
```

## Solution

```
import torch
import torch.nn.functional as F


def train_one_step(model, optimizer, microbatches):
    n = len(microbatches)
    optimizer.zero_grad()
    total = 0.0
    for x, y in microbatches:
        logits = model(x)
        # F.cross_entropy(reduction='mean') already divides by the
        # micro-batch size. Calling backward() on every micro-batch
        # accumulates the *sum* of micro-batch means. To match a single
        # big batch's mean gradient, scale each micro-batch loss by 1/n.
        loss = F.cross_entropy(logits, y) / n
        loss.backward()
        total += loss.item() * n
    optimizer.step()
    return total / n
```

## Tests

```
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(13)
V, D = 10, 8
m_a = nn.Linear(D, V)
m_b = nn.Linear(D, V)
m_b.load_state_dict(m_a.state_dict())

opt_a = torch.optim.SGD(m_a.parameters(), lr=0.1)
opt_b = torch.optim.SGD(m_b.parameters(), lr=0.1)

x = torch.randn(8, D)
y = torch.randint(0, V, (8,))

# Reference: single big batch
opt_a.zero_grad()
loss_ref = F.cross_entropy(m_a(x), y)
loss_ref.backward()
opt_a.step()

# Accumulated: should match
micro = [(x[i : i + 2], y[i : i + 2]) for i in range(0, 8, 2)]
train_one_step(m_b, opt_b, micro)

for a, b in zip(m_a.parameters(), m_b.parameters()):
    assert torch.allclose(a, b, atol=1e-5), (a - b).abs().max().item()

print("OK")
```

## Key insight

Without the `/ n`, each micro-batch's mean gradient gets summed into
the same `.grad` tensors. The result is `n × ` the gradient you'd get
from a single big batch — equivalent to multiplying the effective
learning rate by `n`. With `n = 4`, an LR that was barely stable now
explodes.

## Pitfalls

- The bug is invisible if `n = 1` (single-batch accumulation degenerates
  to the non-accumulation case). It only surfaces once accumulation
  matters.
- Some recipes use `reduction='sum'` instead and divide by the global
  batch size at the end. Equivalent if done consistently, but mixing
  `mean` per-microbatch with no scale is the canonical bug.
- "Loss looks reasonable" is *not* a check for this bug because the
  reported loss is per-microbatch and is normal in magnitude. The
  symptom is in the gradient magnitudes / training instability.
