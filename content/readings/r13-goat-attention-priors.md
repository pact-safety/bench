---
slug: r13-goat-attention-priors
kind: reading
title: "You Need Better Attention Priors (the GOAT paper)"
source: "Litman & Guo — arXiv 2026"
url: "https://arxiv.org/abs/2601.15380"
duration_min: 35
axes: [transformer_internals, training_mechanics]
domain_tags: [attention, softmax]
authored_by: claude_code_v1_build
authored_date: 2026-05-14
version: 1
---

A 2026 paper that reframes attention through the lens of **entropic
optimal transport** — showing that standard softmax attention has an
implicit *uniform* prior, and that you can do strictly better by
making the prior learnable.

**Why read.** It connects three threads you've already touched: the
shape of attention scores (your [scaled-dot-product-attention]
(/problem/scaled-dot-product-attention) problem), length-generalization
failure modes (attention sinks, position bias), and FlashAttention
compatibility. GOAT — Generalized Optimal-transport Attention with
Trainable priors — slots into the same compute envelope but improves
extrapolation and removes the "attention sinks" pathology.

**What to take from it.**

1. **The implicit-uniform-prior framing.** Once you see attention as
   solving an entropic OT problem, "why does this fail at long
   contexts" stops being magic. The uniform prior gets exposed as a
   modeling choice, not physics.
2. **Trainable priors that play nice with FlashAttention.** Most
   "better attention" papers break the IO-aware kernel; GOAT is
   designed to compose. Useful pattern: research that respects the
   systems constraints from the start.
3. **Spatial integration → length generalization.** The prior is
   what carries position structure; with a learned spatial prior,
   train-time tricks like RoPE matter less.

**Pair with** the original [attention-is-all-you-need]
(/content/r01-attention-is-all-you-need) for the uniform-prior baseline.
Lighter pair: [r14-annotated-jepa](/content/r14-annotated-jepa) — both
push on "what's the right inductive bias?" from different angles.

**Background-read fine** at 1.5x speed for §1-2; slow down on §3
where the OT formulation lands. The empirical section is short and
direct.
