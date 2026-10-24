---
slug: r08-bpe-paper
kind: reading
title: "Neural Machine Translation of Rare Words with Subword Units (the BPE paper)"
source: "Sennrich, Haddow, Birch — ACL 2016"
url: "https://arxiv.org/abs/1508.07909"
duration_min: 30
axes: [tokenization]
domain_tags: [bpe, subword, tokenization, tokenizer]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The paper that introduced byte-pair encoding to NLP. Short and
unintimidating — §3 is the only section you strictly need; the rest
is the NMT evaluation that motivated it.

**Why read.** BPE (and its descendants — sentencepiece, wordpiece,
tiktoken) is what your tokenizer is, even when you think you're not
thinking about tokenization. The
[bpe-merges](/problem/bpe-merges) compose problem and
[greedy-tokenizer-rust](/problem/greedy-tokenizer-rust) write
problem are direct implementations of what this paper specifies.

**What to take from it.**

1. **The merge loop** (§3.2). Start with single characters as the
   vocabulary; at each step, find the most frequent adjacent pair
   in the corpus and merge it into a single token. Repeat until
   you hit your vocab target. This is the algorithm you implement
   in [bpe-merges](/problem/bpe-merges).
2. **The "open vocabulary" framing.** Pre-BPE, NMT used fixed
   word-level vocabularies with `<UNK>` for out-of-vocab. BPE makes
   the vocab *compositional* — any string is representable as a
   sequence of subwords, even ones never seen at training time.
3. **The throughput argument** (§4.1). Smaller vocabs = smaller
   softmax output projections = faster training. The paper makes
   this point explicit; it's why even byte-level tokenizers (32K
   vocab tiktoken) are normal now.

**Pair with** the Karpathy tokenizer video (also in your Today
queue) — the paper gives you the math; Karpathy walks the
implementation. Both feed directly into the bench's BPE problem.

**Why this paper specifically.** There are flashier tokenizer papers
(SentencePiece, BPE-dropout) but Sennrich is the *original*. The
others assume you've read this one.
