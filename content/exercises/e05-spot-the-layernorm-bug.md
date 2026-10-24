---
slug: e05-spot-the-layernorm-bug
kind: exercise
title: "Spot the LayerNorm bug"
source: "pairs with the Ba et al. LayerNorm paper"
duration_min: 10
axes: [transformer_internals, numerical_stability]
domain_tags: [layer_norm]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** Three implementations of LayerNorm. *One* matches
`torch.nn.LayerNorm`'s default behavior. The other two are wrong
in different ways.

```python
def a(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    var  = x.var(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta

def b(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=-1, keepdim=True)
    var  = x.var(dim=-1, keepdim=True, unbiased=False)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta

def c(x, gamma, beta, eps=1e-5):
    mean = x.mean(dim=0, keepdim=True)
    var  = x.var(dim=0, keepdim=True, unbiased=False)
    return (x - mean) / torch.sqrt(var + eps) * gamma + beta
```

**Question.** Which is correct? What's wrong with the other two?

<details>
<summary>reveal</summary>

**(b) is correct.**

**(a)** uses the default `unbiased=True`, which divides by `(N - 1)`
— Bessel's correction. `nn.LayerNorm` uses the *biased* estimator
(divide by `N`). The two disagree by a factor of
`sqrt(N / (N - 1))`. On `d = 8`, that's a ~7% mismatch — large
enough to fail a `1e-5` allclose test, small enough to look like
"numerical noise" to someone who doesn't know the convention.

**(c)** normalizes over `dim=0` — the batch axis. That's
*BatchNorm*-flavored: it makes activations depend on other examples
in the batch. LayerNorm's whole point is per-example normalization
over the feature dim (`dim=-1`).

</details>

**Key insight.** LayerNorm = **biased** variance + **per-example,
per-token** normalization over the feature axis. Both choices
disagree with PyTorch's defaults, so a from-scratch implementation
has to know to pass `unbiased=False` *and* `dim=-1`.
