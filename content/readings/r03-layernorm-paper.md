---
slug: r03-layernorm-paper
kind: reading
title: "Layer Normalization — the original paper"
source: "Ba, Kiros, Hinton, 2016"
url: "https://arxiv.org/abs/1607.06450"
duration_min: 18
axes: [transformer_internals, numerical_stability]
domain_tags: [layer_norm, normalization, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

A short paper that's the answer to about a third of "why doesn't my
training converge?" questions. Read the intro + the LN definition;
the RNN-focused experiments are skippable.

**Why read it.** LayerNorm is the most-used normalization in modern
transformers, and its specific choice of biased variance (dividing by
N, not N-1) is the single most common silent bug in
implementation-from-scratch code. The
[layernorm-from-scratch](/problem/layernorm-from-scratch) and
[debug-bessel-layernorm](/problem/debug-bessel-layernorm) problems
both turn on it.

**What to take from it.**

1. The normalization is **per-example, per-token** — over the feature
   dimension, not the batch. This is the difference vs. BatchNorm.
   Less batch-size-sensitive; works on RNNs and small batches.
2. The variance estimator is biased (`/N`, not `/(N-1)`). PyTorch's
   `torch.var` defaults to *unbiased* — you must pass
   `unbiased=False` (or `correction=0` in newer PyTorch) to match.
3. The learnable affine `γ` and `β` are per-feature. They restore
   the model's ability to represent things normalization throws away.

**After you read it,** RMSNorm (the Llama-family variant) reads as a
deliberate simplification: drop the mean-centering and `β`, keep just
the variance normalization. The
[layernorm-vs-rmsnorm](/problem/layernorm-vs-rmsnorm) problem leans
directly on this comparison.
