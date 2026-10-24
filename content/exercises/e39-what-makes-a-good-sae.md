---
slug: e39-what-makes-a-good-sae
kind: exercise
title: "Name the subgoals of scoring a trained SAE"
source: "prep for ARENA 1.3.3 Interpretability with SAEs"
duration_min: 10
axes: [mechanistic_interpretability, eval_design]
domain_tags: [sparse autoencoder, l0, loss recovered, ablation baseline]
arena_section: "1.3.3"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Your SAE trained. Now you have to say whether it is any
good. The signature:

```python
def evaluate_sae(sae, model, tokens, hook_name) -> dict[str, float]:
    """
    Returns {"l0": ..., "mse": ..., "ce_recovered": ...}

    l0:           mean number of non-zero latents per token.
    mse:          mean squared reconstruction error at hook_name.
    ce_recovered: 1.0 if splicing the SAE reconstruction into the
                  forward pass costs no cross-entropy; 0.0 if it is
                  as bad as destroying the activation entirely.
    """
    raise NotImplementedError()
```

**Question.** Before writing code: how many forward passes does this
need, and what are the subgoals? Commit to a number first.

<details>
<summary>reveal</summary>

**Three forward passes.**

1. **Clean pass — gets you both the activations and the baseline
   loss, in one go.**
   `clean_ce, cache = model.run_with_cache(tokens, return_type="loss", names_filter=hook_name)`
2. **Run the SAE on the cached activations.**
   `_, _, _, acts, recon = sae(cache[hook_name])`
   That one call gives you everything the first two metrics need.
3. **L0 and MSE are pure tensor arithmetic — no model involved.**
   `l0 = (acts > 0).float().sum(-1).mean()`
   `mse = ((recon - cache[hook_name]) ** 2).mean()`
4. **Second pass: splice the reconstruction in and re-measure loss.**
   `recon_ce = model.run_with_hooks(tokens, return_type="loss",
       fwd_hooks=[(hook_name, lambda act, hook: recon)])`
5. **Third pass: the destroyed baseline. This is the subgoal people
   forget.**
   `abl_ce = model.run_with_hooks(tokens, return_type="loss",
       fwd_hooks=[(hook_name, lambda act, hook: act.mean(0, keepdim=True).expand_as(act))])`
   Mean-ablation beats zero-ablation as the baseline: zeroing a
   residual stream is so far off-distribution that it makes any SAE
   look good by comparison.
6. **Normalize into a fraction.**
   `ce_recovered = (abl_ce - recon_ce) / (abl_ce - clean_ce)`
   Check the endpoints: `recon_ce == clean_ce` → 1.0;
   `recon_ce == abl_ce` → 0.0.

**Transferable rule.** Any "fraction recovered" metric needs three
numbers — clean, intervened, and destroyed. Without the destroyed
baseline the difference `recon_ce - clean_ce` has no scale, and you
cannot compare it across layers or models.

</details>

**Key insight.** No single number scores an SAE. Reconstruction alone
is gameable — an SAE that fires half its latents on every token has
near-zero MSE and explains nothing. A result is a point on the L0 vs.
loss-recovered frontier, and SAEs are only comparable at matched L0.
