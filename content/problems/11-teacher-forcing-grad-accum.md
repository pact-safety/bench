---
slug: teacher-forcing-grad-accum
title: Teacher-forcing training step with gradient accumulation
difficulty: hard
time_bucket: 60
problem_type: code_compose
is_warmup: false
structural_tags: [training_loop_mechanics, control_flow]
domain_tags: [training]
competency_tags: [training_internals]
jd_signal_tags: [training, gradient_accumulation]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement one effective training step using gradient accumulation. You
get a model, an optimizer, a list of micro-batches `(inputs, targets)`,
and a number of accumulation steps `N` (equal to `len(microbatches)`).

```
def train_one_step(model, optimizer, microbatches) -> float
```

Return the mean loss across micro-batches. The function must produce
the same parameter update as one big batch made of the concatenation of
all micro-batches — i.e., the gradient is the mean of per-example losses,
not the sum.

The model takes `inputs` and returns logits of shape `(B, V)`; targets
are class indices `(B,)`. Use `F.cross_entropy(reduction='mean')` per
micro-batch.

## Starter

```
import torch
import torch.nn.functional as F


def train_one_step(model, optimizer, microbatches):
    # TODO
    pass
```

## Solution

```
import torch
import torch.nn.functional as F


def train_one_step(model, optimizer, microbatches):
    n = len(microbatches)
    optimizer.zero_grad()
    total = 0.0
    for inputs, targets in microbatches:
        logits = model(inputs)
        loss = F.cross_entropy(logits, targets) / n
        loss.backward()
        total += loss.item() * n  # un-scale for reporting
    optimizer.step()
    return total / n
```

## Tests

```
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(5)

V, D = 10, 8
model_a = nn.Linear(D, V)
model_b = nn.Linear(D, V)
# Same weights for the two models
model_b.load_state_dict(model_a.state_dict())

opt_a = torch.optim.SGD(model_a.parameters(), lr=0.1)
opt_b = torch.optim.SGD(model_b.parameters(), lr=0.1)

big_x = torch.randn(8, D)
big_y = torch.randint(0, V, (8,))

# Single big batch
opt_a.zero_grad()
loss_single = F.cross_entropy(model_a(big_x), big_y)
loss_single.backward()
opt_a.step()

# Gradient accumulation in 4 micro-batches of 2
micro = [(big_x[i : i + 2], big_y[i : i + 2]) for i in range(0, 8, 2)]
reported = train_one_step(model_b, opt_b, micro)

# Parameters should match after the update
for p_a, p_b in zip(model_a.parameters(), model_b.parameters()):
    assert torch.allclose(p_a, p_b, atol=1e-5), (p_a - p_b).abs().max().item()

# Reported loss should equal the single-batch loss within float noise
assert abs(reported - loss_single.item()) < 1e-5, (reported, loss_single.item())

print("OK")
```

## Key insight

`F.cross_entropy(reduction='mean')` already divides by `B`. To make the
sum of micro-batch losses equal the single-batch mean, divide each
micro-batch loss by `N` (the number of accumulation steps). That keeps
the per-example weighting right when micro-batch sizes are equal.

## Pitfalls

- Forgetting to divide by `N` makes the effective learning rate `N×` too
  high. Symptom: training is unstable at the LR that worked for a single
  big batch.
- `optimizer.zero_grad()` goes before the loop, not before each
  micro-batch. Zeroing inside the loop wipes accumulated gradients.
- This solution assumes equal-size micro-batches. Unequal sizes need
  weighting by `B_i / sum(B_i)` instead of `1 / N`.
