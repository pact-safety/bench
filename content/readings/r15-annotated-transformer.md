---
slug: r15-annotated-transformer
kind: reading
title: "The Annotated Transformer"
source: "Harvard NLP — Rush et al."
url: "https://nlp.seas.harvard.edu/annotated-transformer/"
duration_min: 90
axes: [transformer_internals, training_mechanics]
domain_tags: [attention, head, multi-head, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-14
version: 1
---

The canonical "annotated paper": Vaswani et al.'s *Attention Is All
You Need* with working PyTorch under every equation. The format every
subsequent "Annotated X" post is descended from.

**Why read.** If a research-engineering interviewer asks you to
implement scaled-dot-product attention from scratch and you blank,
the recovery move is to mentally re-derive from this post. The line-
by-line correspondence between equation and code is what makes the
algorithm stick — much more than the original paper read alone.

**What to take from it.**

1. **The order of operations in multi-head attention.** Split → project
   → attend → recombine → final linear. The PyTorch trace makes the
   tensor shapes unambiguous; this is the exact thing
   [scaled-dot-product-attention](/problem/scaled-dot-product-attention)
   tests you on.
2. **The mask machinery.** Padding mask vs. causal mask vs. the
   combined-mask trick. Where the `masked_fill(-inf)` goes (before
   softmax) and *why*.
3. **The training loop scaffolding.** LR warmup, label smoothing,
   the Adam settings — small choices that the paper specifies but
   are easy to miss on first read. The Karpathy
   [training recipe](/content/r04-karpathy-training-recipe) reading
   reinforces these patterns from a different angle.

**Pair with** [r01-attention-is-all-you-need](/content/r01-attention-is-all-you-need)
(read the paper first, then this), and [r14-annotated-jepa]
(/content/r14-annotated-jepa) for the format applied to a more recent
architecture.

**Background-read at 1.5x** for the prose sections; **stop the clock**
and run the cells for the attention + masking sections. Total
~90 min if you actually code along.
