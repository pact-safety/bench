---
slug: r14-annotated-jepa
kind: reading
title: "The Annotated JEPA"
source: "Elon Litman — elonlit.com, Jan 2026"
url: "https://elonlit.com/scrivings/the-annotated-jepa/"
duration_min: 60
axes: [training_mechanics, transformer_internals]
domain_tags: [embedding, training, transformer]
authored_by: claude_code_v1_build
authored_date: 2026-05-14
version: 1
---

Annotated-paper-style walkthrough (in the lineage of Harvard NLP's
*Annotated Transformer*) of Joint Embedding Predictive Architectures.
Builds working PyTorch implementations of **I-JEPA** (images), **V-JEPA**
(video), and **LeJEPA** (the 2026 theoretical refinement) from scratch,
side-by-side with the relevant paper sections.

**Why read.** JEPA is LeCun's bet against generative pretraining —
predict in *representation space*, not pixel/token space. Whether or
not you buy the broader thesis, the architecture is now widely cited
in interp + world-modeling work, and "annotated paper" is the right
format to learn from: code under every equation.

**What to take from it.**

1. **The energy-based framing.** JEPA is a contrastive-ish setup
   without the negative-sample machinery — predictor learns to match
   target-encoder outputs of a different view. Compare to MAE
   (generative) and SimCLR (contrastive); the trade-offs are sharp.
2. **The "stop-gradient" half.** The target encoder is an EMA of the
   context encoder with no gradient flow. That structural detail is
   what makes the loss not collapse. Watching the PyTorch trace
   makes this concrete.
3. **LeJEPA's theoretical fix.** §later sections cover the
   *isotropic gaussian* prior LeJEPA introduces to provably avoid
   representation collapse. Worth the time if you're prepping for
   interp roles — collapse is a recurring topic.

**Pair with** [the annotated transformer](/content/r15-annotated-transformer)
for the format, and with [r13-goat-attention-priors]
(/content/r13-goat-attention-priors) — both push on "the right
inductive bias" from opposite directions (attention vs. predictor).

**Compose-mode pacing:** budget ~60 min and run the PyTorch cells
yourself; passive read undersells it.
