---
slug: e06-when-rmsnorm
kind: exercise
title: "LayerNorm vs RMSNorm — when to switch?"
source: "pairs with the Ba et al. LayerNorm paper"
duration_min: 7
axes: [transformer_internals, numerical_stability]
domain_tags: [layer_norm, normalization, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** A new transformer architecture proposes replacing
LayerNorm with RMSNorm (the Llama-family normalization: no
mean-centering, no `β`).

**Question.** Which is the strongest *practical* reason to make
the swap?

a) RMSNorm uses fewer multiplications, improving throughput.
b) RMSNorm produces tighter gradient flow at extreme activations.
c) RMSNorm's lack of mean-centering helps with interpretability.
d) The Llama paper said so, and we should follow.

<details>
<summary>reveal</summary>

**(a) is correct.**

The mean-centering step is the bulk of LayerNorm's arithmetic cost
at inference. Dropping it (and the bias `β`) saves ~7-10% of the
norm op's throughput, which adds up across hundreds of norm calls
per forward pass in a deep model. The Llama family standardized on
this and the quality loss in measured benchmarks is, in practice,
nil.

**(b)** is occasionally argued in informal write-ups but isn't
well-supported by ablations.

**(c)** comes up in interpretability discussion but isn't the
practical motivation — and centering removal can actually
*hurt* certain probing setups that expect zero-mean activations.

**(d)** is a vibes argument, not a reason.

</details>

**Key insight.** The practical case for RMSNorm is throughput.
Quality is a wash; downstream choices (probing, interpretability)
might prefer LayerNorm. Pick based on which constraint actually
matters for your project.
