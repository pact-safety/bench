---
slug: e24-warmup-lr-lambda
kind: exercise
title: "Fill the blank in a linear warmup schedule"
source: "prep for ARENA 0.3 Optimization"
duration_min: 10
axes: [training_mechanics, numerical_stability]
domain_tags: [learning rate, warmup, schedule, adam]
arena_section: "0.3"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Adam at `lr=3e-4` on a fresh transformer. The loss spikes in
the first ~200 steps and never recovers. You add linear warmup over
1000 steps, then flat.

```python
opt = t.optim.Adam(model.parameters(), lr=3e-4)
warmup_steps, total_steps = 1000, 100_000

def lr_lambda(step: int) -> float:
    """Multiplier applied to the base LR at `step` (0-indexed)."""
    if step < warmup_steps:
        return ____
    return 1.0

sched = t.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
```

**Question.** What goes in the blank — and what is warmup actually
fixing? "Large early steps are bad" is not an answer; say what makes
the *early* steps different.

Commit to both before opening the reveal.

<details>
<summary>reveal</summary>

**The line.** `return (step + 1) / warmup_steps`

**What warmup fixes.** Look at Adam's denominator at `t=1`. The
buffers start at zero, so after bias correction `v_hat = g²` exactly
and `m_hat = g` exactly. The update is

```
lr * m_hat / (sqrt(v_hat) + eps)  =  lr * g / (|g| + eps)  ≈  lr * sign(g)
```

**Every parameter in the model moves by the full `lr`**, in a direction
estimated from a single minibatch. `v` is supposed to be an average
over ~1000 batches; at `t=1` it has one sample, so the adaptive step
size — the thing that makes Adam Adam — is pure noise for the first
few dozen steps. Warmup shrinks the multiplier over exactly the window
where the second-moment estimate has too few samples to be trusted.
(This is the argument behind RAdam, which computes the correction
analytically instead of hand-tuning `warmup_steps`.)

**Three ways the blank goes wrong.**

- `step / warmup_steps` — step 0 runs at `lr` exactly `0`. The
  parameters don't move, but `opt.step()` still folds that batch into
  `m` and `v`. You burn a step and seed the moment estimates from it.
- `step / total_steps` — the ramp reaches `0.01`, not `1.0`, at the
  handoff; the LR then jumps 100× on the step where the branch flips.
- `3e-4 * step / warmup_steps` — returning an LR instead of a
  *multiplier*. `LambdaLR` multiplies by `base_lr`, so you train at
  `9e-8` and the loss curve goes flat.

</details>

**Key insight.** Warmup is not a general "be careful at the start"
heuristic — it is compensation for an adaptive optimiser whose variance
estimate is built from almost no data. That is also why plain SGD with
momentum needs it far less than Adam does.
