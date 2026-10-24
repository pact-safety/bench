---
slug: r01-attention-is-all-you-need
kind: reading
title: "Attention Is All You Need — §3.2.1 Scaled Dot-Product Attention"
source: "Vaswani et al., 2017"
url: "https://arxiv.org/abs/1706.03762"
duration_min: 12
axes: [transformer_internals]
domain_tags: [attention, head, mask, multi-head, scaled dot-product, softmax, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

The single section of this paper that survives every transformer
implementation since. ~3 pages, math-light, code-adjacent.

**Why read it.** Most ML coding problems in Li's Bench assume you
know what scaled dot-product attention *is*. The paper's spec is
clearer than any blog post: query–key dot products, divide by
sqrt(d_k), softmax, multiply by values.

**What to take from it.**

1. The scale factor isn't aesthetic — it's what keeps gradients alive
   as d_k grows. Without it, dot products' variance grows linearly
   with dimension and softmax saturates.
2. The mask is applied **before** softmax (additive `-inf`), not
   after. This is the source of half of all attention bugs.
3. The "all you need" framing is a marketing claim; the actual
   contribution is the multi-head reshape pattern.

**After you read it,** the [scaled-dot-product-attention](/problem/scaled-dot-product-attention)
problem should feel like translation work rather than invention.
