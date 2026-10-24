---
slug: e38-sae-forward-and-loss
kind: exercise
title: "Name the subgoals of an SAE forward pass and loss"
source: "prep for ARENA 1.5.4 Superposition & SAEs"
duration_min: 11
axes: [mechanistic_interpretability, training_mechanics]
domain_tags: [sparse autoencoder, l1 penalty, reconstruction loss, sparsity]
arena_section: "1.5.4"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The ARENA-shaped signature you will be handed:

```python
class SAE(nn.Module):
    W_enc: Float[Tensor, "d_in d_sae"]
    b_enc: Float[Tensor, "d_sae"]
    W_dec: Float[Tensor, "d_sae d_in"]
    b_dec: Float[Tensor, "d_in"]
    l1_coeff: float

    def forward(self, x: Float[Tensor, "batch d_in"]):
        """
        Returns (loss, l2_loss, l1_loss, acts, x_recon).

        acts:    (batch, d_sae), non-negative and mostly zero.
        x_recon: (batch, d_in), the reconstruction of x.
        loss:    scalar, the thing you call .backward() on.
        """
        raise NotImplementedError()
```

**Question.** Before writing any code, name the 4–6 subgoals. Write
your list down first.

<details>
<summary>reveal</summary>

1. **Center the input by the decoder bias.**
   `x_cent = x - self.b_dec`
   `b_dec` plays the role of the data mean; subtracting it here and
   adding it back at decode means the latents only have to explain
   deviations from it.
2. **Encode, then rectify — this is where sparsity becomes possible.**
   `acts = F.relu(x_cent @ self.W_enc + self.b_enc)`
   ReLU is what lets a latent be exactly 0 rather than merely small.
3. **Decode back to `d_in`.**
   `x_recon = acts @ self.W_dec + self.b_dec`
4. **Reconstruction term: squared error, summed over features,
   averaged over the batch.**
   `l2_loss = ((x_recon - x) ** 2).sum(-1).mean()`
   Compare against `x`, not `x_cent`.
5. **Sparsity term: L1 on the latents, scaled by the coefficient.**
   `l1_loss = self.l1_coeff * acts.abs().sum(-1).mean()`
   `acts` is already non-negative, so this is a sum; `abs()` just
   makes the intent explicit.
6. **Add them and return.**
   `loss = l2_loss + l1_loss`

One trap that is not a subgoal but will bite: the rows of `W_dec`
must be constrained to unit norm (renormalized after each step, or
folded into the penalty). Otherwise the SAE shrinks `acts` and grows
`W_dec` to buy a lower L1 at no reconstruction cost, and the
sparsity penalty stops meaning anything.

**Transferable rule.** When a docstring lists the tuple you return,
write the subgoals *backwards from that tuple*: every returned name
is one subgoal, and the loss subgoals are always "one term per name
in the loss".

</details>

**Key insight.** `l1_coeff` is the whole design decision: raise it
and you get fewer active latents and a worse reconstruction; lower
it and you get a faithful reconstruction spread over so many latents
that nothing is interpretable. You are not tuning it to a best
value — you are choosing a point on that trade.
