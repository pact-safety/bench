---
slug: e46-rlhf-kl-penalty
kind: exercise
title: "Decompose the RLHF KL penalty"
source: "prep for ARENA 2.4 RLHF"
duration_min: 10
axes: [ai_safety_fundamentals, training_mechanics]
domain_tags: [rlhf, kl penalty, reference model, reward hacking, beta]
arena_section: "2.4"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The reward the PPO loop optimises in RLHF is not the reward
model's score. It is the score minus a penalty for drifting away from the
frozen pre-RLHF model.

```python
def kl_penalized_reward(
    rm_score: Float[Tensor, "batch"],
    logprobs: Float[Tensor, "batch seq"],
    ref_logprobs: Float[Tensor, "batch seq"],
    beta: float,
) -> Float[Tensor, "batch"]:
    '''Per-sequence reward for a batch of sampled completions.

    `logprobs` and `ref_logprobs` are the per-token log-probs of the
    sampled tokens under the current policy and the frozen reference
    model. Returns one scalar reward per sequence.
    '''
```

**Question.** Before writing any code, name the 4 subgoals — and then say
what happens as `beta` goes to 0.

Commit to both before revealing.

<details>
<summary>reveal</summary>

1. **Per-token KL estimate.**
   `kl_per_token = logprobs - ref_logprobs` → `(batch, seq)`. The tokens
   were sampled from the current policy, so the expectation of this
   difference is `KL(pi || pi_ref)` — one sample of it per token, no
   normalisation needed.
2. **Reduce over the sequence axis, by sum.**
   `kl = kl_per_token.sum(dim=-1)` → `(batch,)`. Sum, not mean: the KL
   between two autoregressive distributions over a sequence is the sum of
   the per-token KLs. Using `.mean()` makes the effective `beta` depend on
   completion length, which quietly rewards the policy for writing longer.
3. **Confirm nothing here carries a gradient.** Both tensors are
   sampling-time constants; the reference model is in eval mode and
   evaluated under `torch.no_grad()`. This is a *reward*, not a loss term
   — PPO's gradient enters later, through the ratio.
4. **Combine.** `return rm_score - beta * kl` → `(batch,)`.

**As `beta` → 0.** Nothing anchors the policy to the distribution the
reward model was trained on. The policy is free to walk off-distribution,
and it will, because the reward model is a finite network with exploitable
seams. The failure shows up as: RM score climbing steadily while human
ratings fall (reward hacking — the policy found an adversarial input to
the RM, not a better completion), and outputs collapsing to a narrow set
of high-scoring phrasings regardless of prompt (mode collapse — the
entropy the reference model supplied is no longer being paid for).

**As `beta` → infinity.** The reverse: the policy is pinned to the
reference and RLHF does nothing. `beta` is the dial between "trust the
reward model" and "trust the pretrained distribution", and the right value
is the one where RM score and held-out human judgement still move
together.

</details>

**Key insight.** The KL term is not a generic regulariser — it is a
validity constraint on the reward model. The RM is only meaningful near
the distribution it was trained on, so the penalty buys the right to
believe the score.
