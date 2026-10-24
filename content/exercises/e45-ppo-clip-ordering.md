---
slug: e45-ppo-clip-ordering
kind: exercise
title: "Order the PPO clipped-objective update"
source: "prep for ARENA 2.3 PPO"
duration_min: 12
axes: [training_mechanics, debugging]
domain_tags: [rl, ppo, clipping, ratio, detach]
arena_section: "2.3"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** One PPO minibatch update. `mb_obs`, `mb_actions`,
`mb_advantages` and `mb_logprobs` all come out of the rollout buffer;
`mb_logprobs` was recorded under `torch.no_grad()` at sampling time by the
policy that generated the data. Seven of the eight lines below belong in
the update, in some order. One does not belong at all.

```
A.  policy_loss = -torch.min(unclipped, clipped).mean()
B.  ratio = (new_logprobs - mb_logprobs).exp()
C.  logits, values = agent(mb_obs)
D.  clipped = torch.clamp(ratio, 1 - clip_eps, 1 + clip_eps) * adv
E.  adv = (mb_advantages - mb_advantages.mean()) / (mb_advantages.std() + 1e-8)
F.  new_logprobs = Categorical(logits=logits).log_prob(mb_actions)
G.  unclipped = ratio * adv
H.  mb_logprobs = Categorical(logits=logits).log_prob(mb_actions)
```

**Question.** Give the order, name the line that must not be used, and
say what it would do to the gradient.

Commit to an order before revealing.

<details>
<summary>reveal</summary>

**Order: C, F, E, B, G, D, A.** Then `zero_grad` / `backward` / `step`.

**Forced edges.** `C` before `F` — `F` consumes `logits`. `F` before `B` —
the ratio needs the new log-probs. `B` before `G` and `D` — both scale the
ratio. `E` before `G` and `D` — both use `adv`. `G` and `D` before `A`.
`G` and `D` are interchangeable with each other, and `E` may float
anywhere before `G`, so `C, F, B, E, G, D, A` is equally correct. Every
other permutation raises `NameError`.

**Why `E` is per-minibatch, not per-rollout.** Advantage normalisation
rescales the gradient to roughly unit variance so one clip range works
across environments and across training. Normalising the whole buffer
once and then slicing gives minibatches whose mean is not zero; the
mainstream implementations normalise inside the minibatch loop. It is the
step people misplace most often, because it runs and trains either way —
just worse.

**The line that must not be used: `H`.** It recomputes the "old"
log-probs from the *current* forward pass. Then
`ratio = (new_logprobs - mb_logprobs).exp()` is `exp(x - x)`, which is
exactly `1.0` for every sample — and its gradient is exactly zero, since
the same `x` appears with both signs. Clipping never engages, the loss is
a constant `-adv.mean()`, and the policy does not move. The old log-probs
are data, not a recomputation: they must come from the buffer, detached
at sampling time.

**The sign.** `A` maximises `min(unclipped, clipped)`, so the loss is its
negative. The `min` takes the pessimistic branch of the two, which makes
the bound one-sided: once the ratio has moved outside `[1-eps, 1+eps]` in
the direction that *improves* the objective, the selected term is constant
in `ratio` and its gradient is exactly zero. Moves that make the objective
worse are never clipped — the policy can always correct itself.

</details>

**Key insight.** In PPO, "old" means *recorded at sampling time*. Any
quantity you recompute from the live network stops being a reference
point — and when a reference cancels against its own numerator, the bug
does not crash, it silently returns a zero gradient.
