---
slug: 33-gae-advantages
title: Generalized advantage estimation over a rollout
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [recurrence, backward_pass, numpy_only]
domain_tags: [reinforcement_learning, rlhf]
competency_tags: [training_mechanics]
jd_signal_tags: [rl, rlhf, training]
original: true
authored_by: claude_code_arena_prep
authored_date: 2026-08-19
version: 1
---

## Prompt

Implement generalized advantage estimation (GAE) over a single rollout.
This is the piece that sits between your value head and your policy loss
in PPO — it turns a sequence of rewards and value estimates into
per-timestep advantages that trade off bias against variance via `lam`.

Signature:

```python
def compute_gae(rewards, values, dones, gamma=0.99, lam=0.95,
                last_value=0.0):
    # rewards:    (T,) reward received at each step
    # values:     (T,) value-head estimate V(s_t) for each visited state
    # dones:      (T,) 1.0 if the episode ended AFTER the transition at t
    # last_value: V(s_T), the estimate for the state after the final step
    # returns (advantages, returns), both (T,)
```

The recurrence, computed backwards over the rollout:

```
delta_t = r_t + gamma * V(s_{t+1}) * (1 - done_t) - V(s_t)
A_t     = delta_t + gamma * lam * (1 - done_t) * A_{t+1}
```

with `V(s_{t+1})` taken from `values[t+1]` for interior steps and from
`last_value` at the final step. `returns` is `advantages + values` — the
value-head regression target.

The `(1 - done_t)` factor appears **twice** and both matter. At an
episode boundary there is no next state to bootstrap from, and the
advantage accumulator must not carry across into the previous episode.

numpy only — no torch.

## Starter

```python
import numpy as np


def compute_gae(rewards, values, dones, gamma=0.99, lam=0.95, last_value=0.0):
    """Compute GAE advantages and value targets for one rollout.

    Args:
        rewards:    (T,) float array, reward at each timestep.
        values:     (T,) float array, V(s_t) for each visited state.
        dones:      (T,) float array of 0.0/1.0; 1.0 means the episode
                    terminated after the transition at t.
        gamma:      discount factor.
        lam:        GAE lambda; 0 gives the one-step TD residual, 1 gives
                    the Monte-Carlo return minus the baseline.
        last_value: V(s_T) used to bootstrap the final step.

    Returns:
        advantages: (T,) float array.
        returns:    (T,) float array equal to advantages + values.
    """
    # 1. Allocate the output buffer and the running accumulator.
    ...
    # 2. Walk the rollout backwards, one timestep at a time.
    ...
    # 3. Look up the bootstrap value for the next state, zeroing it at an
    #    episode boundary.
    ...
    # 4. Form the one-step temporal-difference residual.
    ...
    # 5. Fold the residual into the running accumulator, cutting the carry
    #    at an episode boundary.
    ...
    # 6. Derive the value targets and return both arrays.
    raise NotImplementedError()
```

## Solution

```python
import numpy as np


def compute_gae(rewards, values, dones, gamma=0.99, lam=0.95, last_value=0.0):
    rewards = np.asarray(rewards, dtype=float)
    values = np.asarray(values, dtype=float)
    dones = np.asarray(dones, dtype=float)
    T = rewards.shape[0]

    advantages = np.zeros(T, dtype=float)
    running = 0.0
    # Backwards, because A_t depends on A_{t+1}. A forward pass would need
    # the full O(T^2) sum of discounted residuals instead of this recurrence.
    for t in range(T - 1, -1, -1):
        next_value = last_value if t == T - 1 else values[t + 1]
        nonterminal = 1.0 - dones[t]

        # First use of nonterminal: no state after termination, so nothing
        # to bootstrap from — the residual is just r_t - V(s_t).
        delta = rewards[t] + gamma * next_value * nonterminal - values[t]

        # Second use: the accumulator must not leak the next episode's
        # advantage backwards across the boundary.
        running = delta + gamma * lam * nonterminal * running
        advantages[t] = running

    return advantages, advantages + values
```

## Tests

```python
import numpy as np


def test_lam_zero_is_one_step_td_residual():
    rng = np.random.default_rng(0)
    T = 8
    rewards, values = rng.normal(size=T), rng.normal(size=T)
    dones = np.zeros(T)
    adv, _ = compute_gae(rewards, values, dones, gamma=0.9, lam=0.0, last_value=0.5)
    next_values = np.append(values[1:], 0.5)
    expected = rewards + 0.9 * next_values - values
    assert np.allclose(adv, expected)


def test_lam_one_is_monte_carlo_return_minus_value():
    rng = np.random.default_rng(1)
    T, gamma, last_value = 6, 0.9, 0.3
    rewards, values = rng.normal(size=T), rng.normal(size=T)
    dones = np.zeros(T)
    adv, _ = compute_gae(rewards, values, dones, gamma=gamma, lam=1.0,
                         last_value=last_value)
    mc = np.zeros(T)
    running = last_value
    for t in range(T - 1, -1, -1):
        running = rewards[t] + gamma * running
        mc[t] = running
    assert np.allclose(adv, mc - values)


def test_done_truncates_bootstrapping():
    rewards = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    values = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    dones = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0])
    adv, _ = compute_gae(rewards, values, dones, gamma=0.9, lam=0.95, last_value=0.0)
    assert np.allclose(adv[3], rewards[3] - values[3])

    rewards2 = rewards.copy()
    rewards2[4:] = 99.0
    adv2, _ = compute_gae(rewards2, values, dones, gamma=0.9, lam=0.95, last_value=0.0)
    assert np.allclose(adv[:4], adv2[:4])
    assert not np.allclose(adv[4:], adv2[4:])


def test_returns_equal_advantages_plus_values():
    rng = np.random.default_rng(2)
    T = 10
    rewards, values = rng.normal(size=T), rng.normal(size=T)
    dones = (rng.random(T) < 0.2).astype(float)
    adv, ret = compute_gae(rewards, values, dones, gamma=0.99, lam=0.95, last_value=1.0)
    assert adv.shape == (T,) and ret.shape == (T,)
    assert np.allclose(ret, adv + values)
```

## Key insight

GAE is an exponentially-weighted average over all the n-step advantage
estimators, and `lam` is the only knob: at `lam=0` you get the one-step
TD residual (low variance, high bias — it trusts the value head
completely), at `lam=1` you get the Monte-Carlo return minus the
baseline (unbiased, high variance — it trusts the value head not at all).
Everything useful lives in between, which is why 0.95 is the default you
see everywhere.

The two `lam` limits are also the two tests you should write first for
any GAE implementation you encounter in the wild. They pin the recurrence
from both ends, and almost every real bug — a missing `lam`, a `gamma`
where a `gamma * lam` belongs, an off-by-one in the bootstrap — breaks at
least one of them.

## Pitfalls

- Applying `(1 - done_t)` to only one of the two places. Zeroing just the
  bootstrap still lets the accumulator carry the next episode's advantage
  backwards across the boundary; zeroing just the accumulator still
  bootstraps a value for a state that does not exist. Both bugs are
  silent — training merely gets worse.
- Iterating forward. `A_t` depends on `A_{t+1}`, so a forward loop either
  gives you the wrong answer or forces an O(T^2) rewrite.
- Using `values[t+1]` at `t == T-1` and reading past the end (or, worse,
  wrapping around to `values[0]` via negative indexing). The final step
  bootstraps from `last_value`, which is a separate input precisely
  because it is not in the array.
- Confusing "done because the episode terminated" with "done because the
  rollout hit its step limit." A time-limit truncation should still
  bootstrap — treating it as terminal teaches the policy that the world
  ends at step 128.
- Normalizing advantages inside this function. Batch normalization of
  advantages is a PPO-loop concern; folding it in here makes the `lam=1`
  identity untestable.
