---
slug: e23-adam-subgoals
kind: exercise
title: "Name the subgoals of implementing Adam.step"
source: "prep for ARENA 0.3 Optimization"
duration_min: 12
axes: [training_mechanics, numerical_stability]
domain_tags: [adam, moments, bias correction, optimizer]
arena_section: "0.3"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The ARENA-shaped signature, blank body.

```python
class Adam:
    def __init__(
        self,
        params: Iterable[Tensor],
        lr: float = 1e-3,
        betas: tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
    ):
        ...

    @t.inference_mode()
    def step(self) -> None:
        """One Adam update over self.params, matching torch.optim.Adam."""
        raise NotImplementedError()
```

**Question.** Before writing any code, name the 4–5 subgoals of
`step()`. Then answer: what do the two buffers hold, and why does bias
correction exist?

Write your list down before opening the reveal.

<details>
<summary>reveal</summary>

1. **Advance the step counter — bias correction needs `t`.**
   `self.t += 1` (initialised to `0`, so the first step runs at `t=1`).
2. **Read the gradient and apply weight decay to it.**
   `g = p.grad + self.wd * p`
   Adam decays the *gradient*, so the penalty then flows through both
   moment estimates. AdamW's entire contribution is moving this out of
   `g` and onto `p` directly.
3. **Update the two buffers in place.**
   ```python
   self.ms[i] = b1 * self.ms[i] + (1 - b1) * g
   self.vs[i] = b2 * self.vs[i] + (1 - b2) * g.pow(2)
   ```
4. **Bias-correct into *copies*, never back into the buffers.**
   ```python
   m_hat = self.ms[i] / (1 - b1 ** self.t)
   v_hat = self.vs[i] / (1 - b2 ** self.t)
   ```
   Writing the corrected value back into `self.ms[i]` corrupts the next
   step's EMA — a top-three ARENA 0.3 test failure.
5. **Write the parameter in place.**
   `p -= self.lr * m_hat / (v_hat.sqrt() + self.eps)`

**What the buffers hold.** `m` is an EMA of the gradient — the
*direction*, smoothed over ~`1/(1-b1)` = 10 steps. `v` is an EMA of the
gradient *squared* — a per-parameter magnitude estimate over ~1000
steps. The update divides one by the square root of the other, so Adam
takes a step of roughly `lr` in units of "typical recent gradient size
for this specific parameter". That per-parameter rescaling is the whole
idea.

**Why bias correction.** Both buffers start at zero, so early on they
are pulled toward zero: `E[m_t] = (1 - b1**t) * E[g]`. At `t=1`,
`m_1 = 0.1*g` — a tenth of the true gradient, and `v_1 = 0.001*g²`.
Dividing by `1 - b**t` cancels that factor exactly. At `t=1` it
recovers `m_hat = g` and `v_hat = g²`; by `t=1000` the correction
factor is ~1 and does nothing. It is a fix for the *initialisation*,
not for the algorithm.

</details>

**Key insight.** Any ARENA optimiser decomposes the same way: advance
the clock → read and transform the gradient → update state → derive the
step from state (in copies) → write in place. If a subgoal mutates
state that a later step still needs to read, you've collapsed two
subgoals that must stay separate.
