---
slug: 31-sae-forward-and-loss
title: Sparse autoencoder forward pass and loss
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tensor_manipulation, loss_functions, numpy_only]
domain_tags: [sparse_autoencoders, interpretability]
competency_tags: [mechanistic_interpretability]
jd_signal_tags: [interpretability, mechanistic_interp, sae]
original: true
authored_by: claude_code_arena_prep
authored_date: 2026-08-19
version: 1
---

## Prompt

Implement the forward pass of a ReLU sparse autoencoder plus its training
loss. This is the workhorse of dictionary-learning interpretability: an
SAE takes a model's residual-stream activations, encodes them into a much
wider, mostly-zero latent space, and decodes back. The loss is
reconstruction MSE plus an L1 penalty on the latents, weighted by a
sparsity coefficient.

Signature:

```python
def sae_forward(x, W_enc, b_enc, W_dec, b_dec, l1_coeff=1e-3):
    # x:     (batch, d_in)      input activations
    # W_enc: (d_in, d_hidden)   b_enc: (d_hidden,)
    # W_dec: (d_hidden, d_in)   b_dec: (d_in,)
    # returns (recon, latents, losses)
```

Three details that are conventions in the SAE literature, not arbitrary:

1. **Subtract the decoder bias from the input before encoding.** The
   decoder bias is the SAE's estimate of the "mean" activation; the
   dictionary should describe deviations from it, not the offset itself.
2. **The nonlinearity is ReLU**, which is what makes latents exactly zero
   rather than merely small.
3. **The reconstruction term is the mean over the batch of the summed
   squared error per example**, and the sparsity term is `l1_coeff` times
   the mean over the batch of the summed absolute latent value per
   example. Sum over features, mean over batch — for both.

Return `(recon, latents, losses)` where `recon` is `(batch, d_in)`,
`latents` is `(batch, d_hidden)`, and `losses` is a dict with keys
`'recon'`, `'sparsity'`, and `'total'` holding Python floats.

numpy only — no torch.

## Starter

```python
import numpy as np


def sae_forward(x, W_enc, b_enc, W_dec, b_dec, l1_coeff=1e-3):
    """Run a ReLU sparse autoencoder and score its loss.

    Args:
        x:       (batch, d_in) float array of input activations.
        W_enc:   (d_in, d_hidden) encoder weights.
        b_enc:   (d_hidden,) encoder bias.
        W_dec:   (d_hidden, d_in) decoder weights.
        b_dec:   (d_in,) decoder bias, also used to center the input.
        l1_coeff: scalar weight on the sparsity penalty.

    Returns:
        recon:   (batch, d_in) reconstruction of x.
        latents: (batch, d_hidden) non-negative latent activations.
        losses:  dict with float keys 'recon', 'sparsity', 'total',
                 where total == recon + sparsity. Both terms sum over
                 features and average over the batch.
    """
    # 1. Center the input against the decoder bias.
    ...
    # 2. Encode to the latent space and apply the nonlinearity.
    ...
    # 3. Decode back to the input space.
    ...
    # 4. Score how faithful the reconstruction is.
    ...
    # 5. Score how expensive the latent code is, and combine the terms.
    ...
    # 6. Return in the documented shape.
    raise NotImplementedError()
```

## Solution

```python
import numpy as np


def sae_forward(x, W_enc, b_enc, W_dec, b_dec, l1_coeff=1e-3):
    x = np.asarray(x, dtype=float)

    # The decoder bias is the SAE's estimate of the mean activation. Encoding
    # the centered input means the dictionary spends its capacity on
    # deviations from that mean rather than re-learning the offset.
    x_centered = x - b_dec

    latents = np.maximum(x_centered @ W_enc + b_enc, 0.0)
    recon = latents @ W_dec + b_dec

    # Sum over features, mean over batch — for both terms, so that l1_coeff
    # means the same thing regardless of batch size.
    recon_term = float(np.mean(np.sum((recon - x) ** 2, axis=-1)))
    sparsity_term = float(l1_coeff * np.mean(np.sum(np.abs(latents), axis=-1)))

    losses = {
        "recon": recon_term,
        "sparsity": sparsity_term,
        "total": recon_term + sparsity_term,
    }
    return recon, latents, losses
```

## Tests

```python
import numpy as np


def test_shapes_and_loss_keys():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(5, 8))
    W_enc, b_enc = rng.normal(size=(8, 16)) * 0.1, np.zeros(16)
    W_dec, b_dec = rng.normal(size=(16, 8)) * 0.1, np.zeros(8)
    recon, latents, losses = sae_forward(x, W_enc, b_enc, W_dec, b_dec, 1e-3)
    assert recon.shape == (5, 8)
    assert latents.shape == (5, 16)
    assert set(losses) == {"recon", "sparsity", "total"}
    assert np.all(latents >= 0.0)


def test_zero_input_gives_zero_loss():
    x = np.zeros((3, 4))
    recon, latents, losses = sae_forward(
        x, np.ones((4, 6)), np.zeros(6), np.ones((6, 4)), np.zeros(4), 0.5
    )
    assert np.allclose(latents, 0.0)
    assert np.allclose(recon, 0.0)
    assert np.allclose(losses["total"], 0.0)


def test_higher_l1_raises_sparsity_only():
    rng = np.random.default_rng(1)
    x = np.abs(rng.normal(size=(4, 5))) + 1.0
    W_enc, b_enc = np.abs(rng.normal(size=(5, 7))) + 0.5, np.zeros(7)
    W_dec, b_dec = rng.normal(size=(7, 5)) * 0.1, np.zeros(5)
    _, latents, low = sae_forward(x, W_enc, b_enc, W_dec, b_dec, 0.01)
    _, _, high = sae_forward(x, W_enc, b_enc, W_dec, b_dec, 0.10)
    assert latents.sum() > 0.0
    assert high["sparsity"] > low["sparsity"]
    assert np.allclose(high["recon"], low["recon"])


def test_components_sum_to_total():
    rng = np.random.default_rng(2)
    x = rng.normal(size=(6, 5))
    W_enc, b_enc = rng.normal(size=(5, 9)), rng.normal(size=9)
    W_dec, b_dec = rng.normal(size=(9, 5)), rng.normal(size=5)
    _, _, losses = sae_forward(x, W_enc, b_enc, W_dec, b_dec, 0.03)
    assert np.allclose(losses["recon"] + losses["sparsity"], losses["total"])
    assert losses["recon"] > 0.0
```

## Key insight

The SAE loss is a two-term bargain and the whole method lives in the
exchange rate between them. Reconstruction alone gives you a dense,
uninterpretable code; L1 alone gives you a dead autoencoder. `l1_coeff`
is the dial, and the reason both terms must use the *same* reduction
(sum over features, mean over batch) is that otherwise the dial's
meaning drifts with `d_hidden` or batch size — you'd retune it every
time you changed the architecture.

Centering by `b_dec` is the detail people skip and then wonder why every
latent fires: without it, the mean activation vector has to be
reconstructed by the dictionary itself, which burns latents on a
constant.

## Pitfalls

- Reconstructing against `x_centered` instead of the original `x`. The
  error is measured in the input space; only the *encoder* sees the
  centered version. The `b_dec` you add back in step 3 is what closes
  the loop.
- Using `np.mean` over both axes for the reconstruction term but
  `np.sum` over both for the sparsity term (or any other mismatched
  pair). The tests catch the resulting inconsistency indirectly, but in
  real training it shows up as an `l1_coeff` that needs a mysterious
  factor of `d_in` to work.
- Applying the ReLU to the reconstruction as well as the latents. The
  output lives in the residual-stream space and is signed; only the
  latent code is non-negative.
- Returning numpy scalars instead of floats in the dict. Harmless here,
  but it makes the loss dict awkward to log or JSON-serialize later.
