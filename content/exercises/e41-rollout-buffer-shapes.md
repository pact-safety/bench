---
slug: e41-rollout-buffer-shapes
kind: exercise
title: "What a rollout buffer actually holds"
source: "prep for ARENA 2.1 Intro to RL"
duration_min: 8
axes: [training_mechanics, algorithmic]
domain_tags: [rl, rollout buffer, state, action, reward]
arena_section: "2.1"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** You run a vectorised CartPole with `num_envs=4`, observation
shape `(4,)`, `num_actions=2`. You collect `num_steps=128` steps before
each update. At every step `t` the loop stores the tuple returned by the
policy and `env.step`: the observation you acted on, the action, the
log-prob of that action under the sampling policy, the critic's value
estimate, the reward, and the terminated flag.

**Question.** Give the shape of each buffer field after the 128 steps,
and then the shape of `obs` and `actions` after the buffer is flattened
for minibatch sampling.

1. `obs` → ?
2. `actions` → ?
3. `logprobs` → ?
4. `values` → ?
5. `rewards` → ?
6. `terminated` → ?
7. flattened `obs`, flattened `actions` → ?

Write all seven down before opening the reveal.

<details>
<summary>reveal</summary>

1. `(128, 4, 4)` — `(num_steps, num_envs, *obs_shape)`. The trailing `4`
   is CartPole's observation dim; the middle `4` is envs. Two different
   fours, which is exactly why you name axes instead of counting them.
2. `(128, 4)` — one discrete action index per env per step. Not
   `(128, 4, 2)`: you store the action taken, not the distribution over
   actions.
3. `(128, 4)` — one scalar log-prob per stored action.
4. `(128, 4)` — the critic emits one scalar per state.
5. `(128, 4)` — the reward that arrived with that step's transition.
6. `(128, 4)` — boolean per env per step. `terminated[t]` says the
   episode ended *as a result of* `actions[t]`, so `values[t+1]` must not
   be bootstrapped through it.
7. `(512, 4)` and `(512,)` — flattening collapses the leading two axes
   into one batch axis of `num_steps * num_envs = 512`. Order across that
   axis is irrelevant once advantages are computed; order along `t` is
   load-bearing *before* that, because the advantage recursion walks
   backwards through time.

</details>

**Key insight.** Every rollout-buffer field is `(num_steps, num_envs, *item_shape)`
— the two leading axes are shared, and everything else is the shape of
one item. Time only matters until advantages are computed; after that you
flatten and treat it as supervised data.
