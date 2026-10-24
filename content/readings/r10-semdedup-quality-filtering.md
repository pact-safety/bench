---
slug: r10-semdedup-quality-filtering
kind: reading
title: "SemDeDup: Data-efficient learning at web-scale through semantic deduplication"
source: "Abbas, Tirumala, Simig, Ganguli, Morcos — Meta AI / Stanford, 2023"
url: "https://arxiv.org/abs/2303.09540"
duration_min: 25
axes: [data_pipeline]
domain_tags: [data pipeline, dataset, pipeline]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The follow-up to The Pile's naive hash dedup. SemDeDup uses *semantic*
similarity (embedding-based) rather than byte-level matching to find
near-duplicates that string-hashing misses.

**Why read.** Production LM training datasets have ~20-50% of their
*compute* spent on near-duplicate content that SHA-256 dedup
preserves. SemDeDup's argument is empirical: cluster embeddings,
drop within-cluster duplicates above a threshold, train faster
without quality loss. This is a clean example of "the algorithm and
the data pipeline are the same project."

**What to take from it.**

1. **§2 The phenomenon.** "How a teaspoon of duplicates degrades a
   gallon of training" — the paper shows that even with exact-hash
   dedup, near-duplicates form ~25% of common web crawls.
2. **§3 Algorithm.** Embed every document → cluster (K-means at
   scale) → within each cluster, drop documents whose pairwise
   cosine similarity exceeds threshold. Conceptually 5 lines;
   engineering challenge is sharding the embedding step.
3. **§5 Downstream impact.** Models trained on the deduped subset
   match or beat models trained on full data at 50-70% of the
   compute. This is the "alignment of metric" insight: less data
   isn't worse if the dropped data was redundant.

**Pair with** the [Pile paper](/content/r09-the-pile) for what
preceded this. The [jsonl-pipeline](/problem/jsonl-pipeline)
problem's "drop duplicates" step is a toy version of dedup;
SemDeDup is the production version with the embedding layer.

**Useful in interviews.** If asked "how would you reduce training
cost without hurting quality," semantic dedup is one of the
short list of correct answers. Knowing it by name and shape is
worth the 25 minutes.
