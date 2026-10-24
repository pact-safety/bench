---
slug: e44-policy-gradient-subgoals
kind: exercise
title: "Decompose the vanilla policy-gradient loss"
source: "prep for ARENA 2.2 Q-Learning and DQN (VPG)"
duration_min: 10
axes: [training_mechanics, algorithmic]
domain_tags: [rl, policy gradient, advantage, log-prob, sign convention]
arena_section: "2.2"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** ARENA hands you this and a `raise NotImplementedError()`.

```python
def policy_gradient_loss(
    logits: Float[Tensor, "batch num_actions"],
    actions: Int[Tensor, "batch"],
    advantages: Float[Tensor, "batch"],
) -> Float[Tensor, ""]:
    '''Scalar loss for the vanilla policy gradient.

    The estimator to *maximise* is mean over the batch of
    log pi(a_t | s_t) * A_t. `advantages` is a constant with respect to
    the policy parameters. Returns a 0-dim tensor suitable for
    `.backward()`.
    '''
```

**Question.** Before writing any code, name the 4–5 subgoals.

Write your list down before revealing.

<details>
<summary>reveal</summary>

1. **Turn logits into log-probs over the action axis.**
   `logprobs = logits.log_softmax(dim=-1)` → `(batch, num_actions)`.
   `log_softmax`, not `softmax().log()` — the fused version subtracts the
   max internally and does not underflow on small probabilities.
2. **Select the log-prob of the action that was actually taken.**
   `chosen = logprobs.gather(1, actions.unsqueeze(1)).squeeze(1)` →
   `(batch,)`. This is the only place the sampled trajectory enters.
3. **Cut the gradient path through the advantage.**
   `adv = advantages.detach()`. The estimator treats `A_t` as a weight,
   not as something to optimise; if it carries a graph from the critic,
   the policy update also drags the value head.
4. **Form the objective, reduced to a scalar.**
   `objective = (chosen * adv).mean()` → `()`. Mean over the batch, which
   is what makes the scale independent of batch size.
5. **Return the negated objective.**
   `return -objective`.

**What the sign does.** For a transition with `A_t > 0` — the action did
better than the critic expected — gradient ascent on the objective raises
`log pi(a_t|s_t)`, so that action gets more probable in that state. For
`A_t < 0` the same expression lowers it. The magnitude of `A_t` is the
step size: an action that beat expectations by a lot moves further than
one that barely did. Advantages near zero contribute almost nothing, which
is the whole reason you subtract a baseline instead of using raw returns.

**Why the minus sign.** Torch optimisers *minimise*. Everything in the RL
literature is written as an objective to maximise. Drop the negation and
the run still executes, the loss still prints, and the policy walks
steadily downhill toward whatever it was worst at — a near-perfect
inversion that no shape check catches.

</details>

**Key insight.** Any ARENA function whose docstring specifies an output
shape starts with subgoal 1 — read the shape backwards from the return.
Here the return is `()`, so the last subgoal is always a reduction — and
when the docstring says "maximise" but the function is named `*_loss`,
that reduction gets negated.
