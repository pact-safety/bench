---
slug: e08-training-loop-ordering
kind: exercise
title: "Spot the training-loop ordering bug"
source: "pairs with Karpathy's training recipe"
duration_min: 10
axes: [training_mechanics, debugging]
domain_tags: [batch, gradient, learning rate, loss, optimizer, training]
gpu_required: true
colab_url: "https://colab.research.google.com/github/LiBearden/research-engineer-interview-prep/blob/main/notebooks/exercises/e08-training-loop-ordering.ipynb"
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** A junior engineer writes the inner loop of a training
script. Tests pass on a toy problem; they ship it to a real model;
training silently fails to converge.

```python
for batch in dataloader:
    logits = model(batch.x)
    loss = loss_fn(logits, batch.y)
    loss.backward()
    optimizer.step()
```

**Question.** What's wrong, what does it produce in practice, and
how do you fix it with the minimum edit?

<details>
<summary>reveal</summary>

**Bug.** `optimizer.zero_grad()` is never called. Each iteration's
gradients accumulate on top of the prior iteration's instead of
replacing them.

**Symptom in practice.** Effective learning rate runs away — by
step N, the gradient magnitude is roughly N× what a clean loop
would compute. Training either diverges fast (LR was already at the
edge) or oscillates wildly (LR was conservative). On a toy problem
with N small and a tiny LR, you might not notice.

**Minimum fix.**

```python
for batch in dataloader:
    optimizer.zero_grad()         # <-- the fix
    logits = model(batch.x)
    loss = loss_fn(logits, batch.y)
    loss.backward()
    optimizer.step()
```

**Why zero_grad at the *top* of the loop, not the bottom?** Both
work in the simple case. But the top-of-loop convention survives
refactors: if you later add gradient accumulation, a checkpoint
restore, or a multi-loss summation, "zero before forward" is what
keeps correctness. Bottom-of-loop placement creates correctness
landmines that only surface when the loop body changes.

</details>

**Key insight.** This is the bug Karpathy's recipe warns about
under "training neural nets is a leaky abstraction" — the code runs,
the loss prints, the gradient norms grow, and nothing in the
default stack tells you that you forgot `zero_grad`. The
[minimal-training-loop](/problem/minimal-training-loop) problem on
the bench has this exact pitfall written into its test cases.
