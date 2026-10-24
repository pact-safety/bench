---
slug: v02-3b1b-attention
kind: video
title: "Attention in transformers, visually explained"
source: "3Blue1Brown"
url: "https://www.youtube.com/watch?v=eMlx5fFNoYc"
duration_min: 26
axes: [transformer_internals]
domain_tags: [attention, causal mask, head, mask, masking, multi-head, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

The geometric/intuition counterpart to Karpathy's code-first walkthrough.
3Blue1Brown's signature animation does for attention what it did for
gradient descent and Fourier transforms.

**Why watch.** Most attention-bug intuitions are
shape-and-axis-discipline intuitions in disguise. Seeing the matrices
animated as transformations makes "query attends to keys via inner
products" stop being words and start being a picture.

**What to take from it.**

1. The visualization of Q · K^T as a "compatibility matrix" — which
   tokens want to talk to which other tokens — makes causal masking
   feel obvious rather than tricky.
2. The walkthrough of multi-head attention as "parallel
   subconversations" justifies the reshape mechanics in the
   [multi-head-attention-reshape](/problem/multi-head-attention-reshape)
   problem.

**Pair with** the Vaswani paper for the spec, Karpathy's video for
the working code, and this one for the geometric why.
