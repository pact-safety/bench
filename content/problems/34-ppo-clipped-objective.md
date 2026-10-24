---
slug: 34-ppo-clipped-objective
title: PPO clipped surrogate objective
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [loss_functions, numerical_stability, numpy_only]
domain_tags: [reinforcement_learning, rlhf]
competency_tags: [training_mechanics]
jd_signal_tags: [rl, rlhf, training]
original: true
authored_by: claude_code_arena_prep
authored_date: 2026-08-19
version: 1
---

## Prompt

Implement the PPO clipped surrogate objective — the loss that made
policy-gradient RL stable enough to be the default in RLHF pipelines.

Signature:

```python
def ppo_clip_loss(logp_old, logp_new, advantages, eps=0.2) -> float:
    # logp_old:   (N,) log-probs from the policy that collected the data
    # logp_new:   (N,) log-probs from the policy being updated
    # advantages: (N,) advantage estimate per sample
    # returns: scalar LOSS (negative objective) as a Python float
```

The objective is

```
ratio_i = exp(logp_new_i - logp_old_i)
L_i     = min( ratio_i * A_i,  clip(ratio_i, 1-eps, 1+eps) * A_i )
```

and you return `-mean(L_i)`, because optimizers minimize.

Two things to get right:

1. **Compute the ratio from the log-prob difference**, not by
   exponentiating each term and dividing. `exp(a)/exp(b)` overflows for
   the perfectly ordinary log-probs a language-model policy produces.
2. **The `min` is over the two products, not the two ratios.** Because
   `A_i` can be negative, taking the minimum of the ratios first flips
   which branch is pessimistic and silently inverts the clip for every
   negative-advantage sample.

numpy only — no torch.

## Starter

```python
import numpy as np


def ppo_clip_loss(logp_old, logp_new, advantages, eps=0.2):
    """Compute the PPO clipped surrogate loss.

    Args:
        logp_old:   (N,) log-probs of the sampled actions under the
                    behavior policy that collected the rollout.
        logp_new:   (N,) log-probs of the same actions under the policy
                    currently being optimized.
        advantages: (N,) advantage estimate for each sample.
        eps:        clip range; the ratio is constrained to [1-eps, 1+eps].

    Returns:
        The scalar loss as a Python float: the negated mean of the
        per-sample clipped surrogate objective.
    """
    # 1. Recover the probability ratio from the log-probability difference.
    ...
    # 2. Score the unconstrained surrogate objective.
    ...
    # 3. Score the constrained (clipped) surrogate objective.
    ...
    # 4. Take the pessimistic branch per sample.
    ...
    # 5. Reduce over the batch and return as a loss.
    raise NotImplementedError()
```

## Solution

```python
import numpy as np


def ppo_clip_loss(logp_old, logp_new, advantages, eps=0.2):
    logp_old = np.asarray(logp_old, dtype=float)
    logp_new = np.asarray(logp_new, dtype=float)
    advantages = np.asarray(advantages, dtype=float)

    # Subtract in log space, then exponentiate once. exp(new)/exp(old)
    # overflows on the log-probs a real policy produces.
    ratio = np.exp(logp_new - logp_old)

    unclipped = ratio * advantages
    clipped = np.clip(ratio, 1.0 - eps, 1.0 + eps) * advantages

    # The min is over the two OBJECTIVES, not the two ratios. With a
    # negative advantage the multiplication flips the ordering, and that
    # flip is exactly what makes the clip bite on the correct side.
    return float(-np.mean(np.minimum(unclipped, clipped)))
```

## Tests

```python
import numpy as np


def test_ratio_one_is_negative_mean_advantage():
    logp = np.array([-1.0, -2.0, -0.5, -3.0])
    adv = np.array([1.0, -0.5, 2.0, 0.25])
    loss = ppo_clip_loss(logp, logp, adv, eps=0.2)
    assert isinstance(loss, float)
    assert np.allclose(loss, -adv.mean())


def test_large_ratio_with_positive_advantage_is_clipped():
    loss = ppo_clip_loss([0.0], [np.log(5.0)], [1.0], eps=0.2)
    assert np.allclose(loss, -1.2)


def test_small_ratio_with_negative_advantage_is_clipped():
    loss = ppo_clip_loss([0.0], [np.log(0.1)], [-1.0], eps=0.2)
    assert np.allclose(loss, 0.8)
    big = ppo_clip_loss([0.0], [np.log(5.0)], [-1.0], eps=0.2)
    assert np.allclose(big, 5.0)


def test_loss_decreases_as_objective_improves():
    base = ppo_clip_loss([0.0], [0.0], [1.0], eps=0.2)
    better = ppo_clip_loss([0.0], [np.log(1.1)], [1.0], eps=0.2)
    worse = ppo_clip_loss([0.0], [np.log(0.9)], [1.0], eps=0.2)
    assert better < base < worse
    assert np.allclose(better, -1.1)
```

## Key insight

The clip is deliberately **one-sided per sample**, and the asymmetry is
the whole design. For a positive advantage the objective is capped at
`(1+eps) * A`: once the policy has raised the action's probability by
20%, further increases earn nothing, so there is no gradient pulling it
further from the behavior policy. For a negative advantage the *floor*
at `(1-eps) * A` limits how much reward you can collect by driving the
probability down — but a ratio that has already blown up to 5 with a
negative advantage is *not* clipped, and takes the full penalty.

That last case looks like a bug the first time you see it and is
intentional: the `min` never protects a sample from a large penalty, only
from a large reward. PPO is pessimistic by construction.

`test_small_ratio_with_negative_advantage_is_clipped` is the test worth
keeping — it pins both negative-advantage branches, and every
sign-confusion bug in this function breaks one of them.

## Pitfalls

- `np.exp(logp_new) / np.exp(logp_old)` instead of
  `np.exp(logp_new - logp_old)`. Mathematically identical, numerically
  not: real log-probs are large and negative, both exponentials
  underflow to zero, and you get `nan` from `0/0`.
- `np.minimum(ratio, np.clip(ratio, ...)) * advantages` — clipping the
  ratio before multiplying. It agrees with the correct version for
  positive advantages and is wrong for every negative one, so it passes a
  careless test suite and quietly trains the wrong objective.
- Returning `+mean(L)` instead of `-mean(L)`. Gradient ascent on the loss
  means the policy walks away from high-advantage actions; the run does
  not crash, it just gets steadily worse.
- Clipping the *loss* rather than the ratio (`np.clip(unclipped, ...)`).
  That bounds the loss value while leaving the trust region unenforced.
- Forgetting that `logp_old` must be detached / recomputed from the
  behavior policy's snapshot. If both log-probs come from the live
  policy, `ratio` is identically 1, the clip never engages, and you have
  written vanilla policy gradient with extra steps.
