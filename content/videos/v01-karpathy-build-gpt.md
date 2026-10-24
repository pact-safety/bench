---
slug: v01-karpathy-build-gpt
kind: video
title: "Let's build GPT: from scratch, in code, spelled out"
source: "Andrej Karpathy"
url: "https://www.youtube.com/watch?v=kCc8FmEb1nY"
duration_min: 117
axes: [transformer_internals, training_mechanics, sampling_decoding]
domain_tags: [attention, embedding, head, kv-cache, multi-head, training, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

The canonical "transformer from scratch" video. Long (~2h), but the
density of takeaways per minute is unusually high. Watch at 1.25x
unless you're new to the material.

**Why watch.** Three of the Li's Bench compose problems
(scaled-dot-product-attention, multi-head-attention-reshape,
kv-cache) sit inside the model Karpathy builds in real time. Seeing
the full system makes each individual problem feel like a piece of
something rather than an isolated drill.

**What to take from it.**

1. The forward pass mechanics — embeddings → attention → projection
   → residual — are the same regardless of model size. Builds the
   "small model is just a thinner GPT-4" intuition.
2. The training loop section reinforces the choices in the
   [minimal-training-loop](/problem/minimal-training-loop) problem:
   when zero_grad is called, when backward is called, why eval()
   matters.
3. The sampling section walks temperature, top-k, and the practical
   reasons to combine them.

**Pair with** the Vaswani §3.2.1 reading above; they answer different
questions ("what is the spec" vs. "what does the working system look
like").
