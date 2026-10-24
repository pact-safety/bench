---
slug: r07-mlpyt-transformers
kind: reading
title: "ML with PyTorch and Scikit-Learn — Ch. 16: Transformers"
source: "Raschka, Liu, Mirjalili (Packt, 2022)"
url: ""
book: "Chapter 16: Transformers — Improving Natural Language Processing with Attention Mechanisms"
duration_min: 60
axes: [transformer_internals, training_mechanics]
domain_tags: [attention, head, kv-cache, layer_norm, mask, multi-head, self-attention, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The most code-first transformer walkthrough among the standard
textbooks. Pairs cleanly with the Vaswani paper: the paper gives you
the equations; this chapter gives you the PyTorch.

**Why read.** Several Li's Bench problems are implementations of
operators this chapter walks through end-to-end:
[scaled-dot-product-attention](/problem/scaled-dot-product-attention),
[multi-head-attention-reshape](/problem/multi-head-attention-reshape),
[layernorm-from-scratch](/problem/layernorm-from-scratch), and
[kv-cache](/problem/kv-cache). The chapter's worked code makes the
sequence-and-tensor-shape choreography concrete in a way the paper
alone doesn't.

**What to take from it.**

1. **The masked-self-attention walkthrough**, with shapes annotated
   at every step. Read it with one finger on
   [scaled-dot-product-attention](/problem/scaled-dot-product-attention)
   open; the chapter is the answer key for the shape problems you'll
   hit there.
2. **The training-loop section.** The chapter shows the full
   forward-loss-backward-step rhythm with attention to gradient
   accumulation, `model.train()` / `.eval()` toggling, and the
   `optimizer.zero_grad()` placement debate. Directly load-bearing
   for [minimal-training-loop](/problem/minimal-training-loop) and
   [teacher-forcing-grad-accum](/problem/teacher-forcing-grad-accum).
3. **The "encoder-decoder vs decoder-only" decision tree.** Modern
   LLMs are decoder-only; the chapter explains *why* — and what the
   encoder-only choice (BERT) is good for instead. Knowing the
   landscape is interview-table-stakes.

**What to skip.** The Hugging Face fine-tuning section at the end is
fine but adds little to the bench's coverage. Stop after the
from-scratch attention implementation; that's the high-leverage
content.
