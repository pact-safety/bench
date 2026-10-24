---
slug: r09-the-pile
kind: reading
title: "The Pile: An 800GB Dataset of Diverse Text for Language Modeling"
source: "Gao et al., EleutherAI, 2020"
url: "https://arxiv.org/abs/2101.00027"
duration_min: 35
axes: [data_pipeline]
domain_tags: [dataset, pipeline]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The paper that made "the training data is the secret" legible. Before
The Pile, the leading public LMs were trained on Common Crawl
fragments; after it, dataset design became a first-class research
problem.

**Why read.** Almost every modern training run sits on top of
opinionated decisions about *what* to include, in *what* proportion,
*how* to deduplicate, and *which* domain mixtures to balance. The
[jsonl-pipeline](/problem/jsonl-pipeline) problem on the bench is
the smallest legible version of these decisions; this paper is the
canonical example at scale.

**What to take from it.**

1. **§3 Component datasets.** 22 sub-corpora — academic papers,
   code, mathematical text, dialogue, prose — picked to *diversify*
   the model's exposure. Knowing this list is interview-table-stakes
   when you talk about training-data composition.
2. **§4 Deduplication strategy.** SHA-256 hash dedup at document
   level. Looks naive; turns out to be enough at this scale.
   Subsequent papers (SemDeDup, MinHash-LSH) sharpen this; the
   Pile establishes the baseline.
3. **§5 Quality filtering** — what they DID NOT do. The Pile is
   deliberately under-filtered to preserve linguistic diversity.
   Compare with C4's heuristic filtering; the choice reflects a
   real research-design tradeoff, not a "best" answer.

**What's outdated.** Specific dataset compositions; legal/ethical
norms around scraped data have shifted hard since 2020. Read for
the *shape* of the decisions, not for the catalog.

**Pair with** [SemDeDup](/content/r10-semdedup-quality-filtering)
for the dedup follow-up. The [jsonl-pipeline](/problem/jsonl-pipeline)
bench problem is the toy version of what's described in §3.
