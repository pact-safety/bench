---
slug: e42-epsilon-decay-blank
kind: exercise
title: "Fill in the epsilon decay schedule"
source: "prep for ARENA 2.2 Q-Learning and DQN"
duration_min: 7
axes: [training_mechanics, algorithmic]
domain_tags: [rl, dqn, exploration, epsilon-greedy, schedule]
arena_section: "2.2"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Epsilon-greedy picks a uniformly random action with
probability `epsilon` and the argmax Q-action otherwise. A fixed epsilon
is wrong at both ends of training: at step 0 the Q-network is noise, so
acting greedily on it explores nothing useful; at step 400k the network
is good, so 100% random actions throw away the policy you paid for. The
schedule interpolates between those two regimes, then holds a small floor
so the agent never fully stops sampling off-policy data.

```python
def epsilon_at(step: int, eps_start: float = 1.0, eps_end: float = 0.05,
               decay_steps: int = 50_000) -> float:
    frac = min(step / decay_steps, 1.0)
    return ____
```

**Question.** What is the missing line, and what breaks if you drop the
`min(..., 1.0)` clamp on the line above it?

Commit to both answers before revealing.

<details>
<summary>reveal</summary>

```python
    return eps_start + frac * (eps_end - eps_start)
```

A linear interpolation from `eps_start` to `eps_end`. Check the ends:
`frac = 0` gives `1.0`; `frac = 1` gives `1.0 + (0.05 - 1.0) = 0.05`.
At step 25,000, `frac = 0.5` and epsilon is `0.525`.

**Without the clamp.** `frac` keeps growing past 1. At step 100,000,
`frac = 2` and epsilon is `1.0 + 2 * (-0.95) = -0.9`. Negative epsilon
means `rng.random() < epsilon` is never true, so exploration stops
*completely* rather than settling at the 5% floor. The symptom is a run
that trains fine for the first 50k steps and then freezes its behaviour:
the replay buffer fills with near-identical trajectories, the agent stops
discovering the states it has not yet learned, and returns plateau below
the achievable optimum with no error and no loss spike.

**The other classic sign error.** Writing
`eps_end + frac * (eps_start - eps_end)` runs the schedule backwards —
greedy on a random network at step 0, and near-uniform actions once the
network is good. It also trains without erroring.

</details>

**Key insight.** A decay schedule is two decisions, not one: the
interpolation and the floor. Both linear forms typecheck, both run, and
only the endpoints tell you which one you wrote — evaluate the schedule
at `step = 0` and at `step = 2 * decay_steps` before trusting it.
