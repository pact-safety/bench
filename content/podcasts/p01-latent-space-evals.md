---
slug: p01-latent-space-evals
kind: podcast
title: "Latent Space — evals are bad, here's why"
source: "swyx & Alessio"
url: "https://www.latent.space/p/braintrust"
duration_min: 55
axes: [eval_design]
domain_tags: [benchmark, evals, scoring]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

Conversation about what real production eval workflows actually look
like — held judgment models, paired comparisons, the gap between
benchmark accuracy and "does this thing work in our product."

**Why listen.** Eval design is the area least covered by papers and
most discussed by practitioners. The
[sycophancy-eval-scoring](/problem/sycophancy-eval-scoring) problem
on Li's Bench treats one corner of this; the podcast widens the
frame to "what makes any eval pipeline trustworthy."

**What to take from it.**

1. The paired-comparison framing (same item, two conditions) is more
   robust than headline-accuracy single-prompt evals — but it
   requires more thought about what the *paired* dimension is.
2. The arguments for held-out judge models vs. self-judging.
3. The practical reasons most published eval numbers don't reproduce
   in production — distribution shift, prompt format drift, judge
   instability.

**Background-listen-able.** Doesn't need full attention; you can run
it while doing chores or a walk.
