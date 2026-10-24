---
slug: e43-dqn-moving-target
kind: exercise
title: "Spot the DQN moving-target bug"
source: "prep for ARENA 2.2 Q-Learning and DQN"
duration_min: 10
axes: [training_mechanics, debugging]
domain_tags: [rl, dqn, target network, bootstrapping, divergence]
arena_section: "2.2"
pedagogy: debug
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup — the symptom first.** CartPole-v1 with `gamma=0.99`. The loss
curve looks healthy: it goes down and stays low. But the logged mean
predicted Q climbs past 300 and keeps going, and episode return rises to
~80 around step 8k and then collapses to ~20 and stays there. On
CartPole the maximum possible return is 500, so with `gamma=0.99` the
true optimal Q is bounded by `(1 - 0.99**500) / 0.01`, under 100. The
network is predicting values that are not achievable.

```python
q = q_net(obs).gather(1, actions.unsqueeze(1)).squeeze(1)     # (B,)

with torch.no_grad():
    next_q = q_net(next_obs).max(-1).values                   # (B,)

target = rewards + gamma * (1.0 - terminated.float()) * next_q
loss = F.mse_loss(q, target)

optimizer.zero_grad()
loss.backward()
optimizer.step()
```

**Question.** Name the bug, the fix, and say what the *combination* of
"low loss" and "unbounded Q" told you.

Commit before revealing.

<details>
<summary>reveal</summary>

**Bug.** The bootstrap target is computed from `q_net` — the same network
being updated. There is no target network. The `torch.no_grad()` is
correct and is *not* the bug; it stops the gradient, but it does not stop
the target from moving.

**Why it diverges.** `obs` and `next_obs` are neighbouring states, so
they share features. Raising `q_net(obs)` also raises `q_net(next_obs)`,
which raises the target for the next update, which raises `q_net(obs)`
again. That is a positive feedback loop with gain `gamma` times a
generalisation factor, and when that product exceeds 1 the values grow
without bound. The overestimation is systematic rather than random
because `.max(-1)` selects whichever action was most over-predicted.

**Fix.** Bootstrap from a frozen copy, refreshed on a slower clock:
`target_net = copy.deepcopy(q_net)`, bootstrap with
`target_net(next_obs).max(-1).values`, and every `target_update_freq`
gradient steps call `target_net.load_state_dict(q_net.state_dict())`.

Between syncs the target is a constant function, so each update is
ordinary supervised regression onto a fixed label set. Expect the loss to
*spike at every sync* once this is fixed — that is the target moving on
purpose, and it is the healthy version.

**What the symptom told you.** Low loss plus diverging predictions is
only possible when the label depends on the prediction. Loss measures
`q` against `target`; if the target chases `q`, the residual stays small
while both run off to infinity. A low loss is evidence about the *gap*,
never about correctness — bound-check the prediction against what the
environment can actually pay out.

</details>

**Key insight.** `no_grad` freezes the gradient path; a target network
freezes the function. Any time the regression label is produced by the
model you are fitting, you need the second copy — otherwise you are
solving a fixed-point problem with an optimiser that assumes fixed
labels.
