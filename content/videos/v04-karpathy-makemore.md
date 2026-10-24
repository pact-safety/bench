---
slug: v04-karpathy-makemore
kind: video
title: "The spelled-out intro to language modeling: building makemore (part 1)"
source: "Andrej Karpathy"
url: "https://www.youtube.com/watch?v=PaCmpygFfXo"
duration_min: 117
axes: [data_pipeline, training_mechanics]
domain_tags: [batch, dataset, pipeline, training]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

Karpathy's gentler companion to "Let's build GPT." `makemore` is a
character-level language model on a names dataset — small enough to
run on a laptop, large enough to teach all the *data-pipeline* moves
production training relies on: tokenizing, batching, train/dev/test
splits, vocab construction.

**Why watch.** Most production ML failures are upstream data-pipeline
failures dressed in model-training clothing. The Karpathy GPT video
in your Today queue ([v01](/content/v01-karpathy-build-gpt)) walks
the model; this video walks the *data*. They're complementary.

**What to take from it.**

1. **The character-tokenization minimal example.** Before BPE, before
   sentencepiece, before tiktoken — just character→index mapping.
   Watch this with the [Sennrich BPE paper](/content/r08-bpe-paper)
   in your queue; the trajectory from "tokenization is a 2-line
   dict" to "tokenization is a research subfield" gets vivid.
2. **The train/dev/test split discussion.** ~20 minutes in: when
   you build the splits, you commit to a *generalization* claim.
   The mechanics (shuffling, hash-based partitioning) are simple;
   the discipline is keeping the test set out of your hands until
   you ship.
3. **Batching mechanics.** How a `(batch, context_len)` tensor of
   token IDs gets assembled from a stream of characters. This is
   the smallest legible version of what the
   [jsonl-pipeline](/problem/jsonl-pipeline) problem
   abstracts.

**Pair with** the [Pile paper](/content/r09-the-pile) — the video
shows the toy version of dataset construction; the paper shows
the production version of the same decisions.

**Background-watch fine** at 1.5-2x for the parts you already know.
The new-to-you parts are usually the tokenization+batching segment.
