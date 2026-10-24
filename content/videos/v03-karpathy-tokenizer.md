---
slug: v03-karpathy-tokenizer
kind: video
title: "Let's build the GPT Tokenizer"
source: "Andrej Karpathy"
url: "https://www.youtube.com/watch?v=zduSFxRajkE"
duration_min: 134
axes: [tokenization]
domain_tags: [bpe, tokenization, tokenizer, tokens]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

Karpathy's standalone tokenizer walkthrough. Two-plus hours of "here
is how GPT-4's actual tokenizer works, built up from nothing." The
single best resource on the subject.

**Why watch.** Tokenization is one of the platform's gap axes — most
people learn it lossily through "well, GPT tokens are weird." This
video makes it specific. After watching, the
[bpe-merges](/problem/bpe-merges) compose problem and
[greedy-tokenizer-rust](/problem/greedy-tokenizer-rust) Rust-write
problem feel like translations of what you saw.

**What to take from it.**

1. **The byte-level twist** (~30 min in). Modern tokenizers don't
   operate on characters or words — they operate on bytes. Why:
   non-ASCII characters become 2-4 bytes that the tokenizer can
   then merge ad-lib, no special unicode handling needed. Every
   weird edge case (emoji tokenization, Chinese characters
   splitting strangely) follows from this.
2. **Why models fail at counting characters / reversing strings.**
   Karpathy makes this concrete: the tokens the model sees don't
   align with the characters the user typed. Most "is this a
   reasoning failure?" questions about LLM behavior turn out to be
   tokenization questions in disguise.
3. **The vocab-size vs sequence-length trade-off.** Bigger vocab =
   fewer tokens per text = longer context per dollar at inference,
   but more parameters in the embedding/unembedding layers. The
   choice is an architectural decision, not a tokenizer-level
   detail.

**Pair with** the [Sennrich BPE paper](/content/r08-bpe-paper) above
— they answer different questions. The paper gives you the spec; the
video gives you the implementation, the historical context, and the
"why GPT-4 specifically tokenizes the way it does."

**Background-watch fine** at 1.5x; the dense parts are §3 (BPE merge)
and §5 (the GPT-4 tokenizer specifically).
