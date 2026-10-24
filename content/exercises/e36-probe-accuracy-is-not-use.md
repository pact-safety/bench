---
slug: e36-probe-accuracy-is-not-use
kind: exercise
title: "Your probe reads 97% — does the model use it?"
source: "prep for ARENA 1.3.1 Linear Probes"
duration_min: 9
axes: [mechanistic_interpretability, debugging]
domain_tags: [linear probe, causal intervention, ablation, projection]
arena_section: "1.3.1"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** A linear probe on `blocks.8.hook_resid_post` predicts, at
97% held-out accuracy, whether the current token sits inside a
parenthetical. That tells you the property is *linearly decodable*
from layer 8. It does not tell you the model reads it. The test that
would: delete the probe direction from the residual stream mid-run
and see whether behaviour changes.

**Question.** One line is blanked. What goes there, and what breaks
if you get it wrong?

```python
w = probe_dir / probe_dir.norm()          # (d_model,), unit norm

def ablate_along_probe(resid, hook):
    # resid: (batch, seq, d_model)
    return ____

logits = model.run_with_hooks(
    tokens,
    fwd_hooks=[("blocks.8.hook_resid_post", ablate_along_probe)],
)
```

Write the line before revealing.

<details>
<summary>reveal</summary>

```python
return resid - (resid @ w).unsqueeze(-1) * w
```

`resid @ w` contracts the last axis → `(batch, seq)`: the signed
component of each position along the probe direction.
`.unsqueeze(-1)` makes it `(batch, seq, 1)`, which broadcasts
against `w`'s `(d_model,)` to rebuild the component as a full
vector. Subtracting it projects every position onto the hyperplane
orthogonal to `w`, leaving everything else untouched.

The failure modes:

- **Drop `.unsqueeze(-1)`** — `(batch, seq) * (d_model,)` only
  broadcasts if `seq == d_model`. Usually a loud shape error;
  occasionally, on a square-ish tensor, a silent wrong answer.
- **Drop the normalization of `w`** — you subtract
  `‖w‖²` times the component instead of one times it, so you
  overshoot (or undershoot) rather than zeroing the direction.
  The probe's raw `coef_` has arbitrary scale; nothing sets it to 1.
- **`return resid - w`** — subtracts a constant vector from every
  position. That shifts the whole stream and removes nothing.

And the result you should expect to reason about, not assume: if
the logits barely move, the model was not reading that direction at
layer 8 — the probe found information that is present but unused, or
information the model computes as a byproduct. If they move a lot,
you have evidence of use — though the projection also deletes any
*other* feature overlapping `w`, so a positive result localizes a
direction, not a concept.

</details>

**Key insight.** Probe accuracy is a claim about the *representation*
— this information is linearly available here. Only an intervention
is a claim about the *computation*. High accuracy plus a null
ablation is a real and common result, not a failed experiment.
