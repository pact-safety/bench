---
slug: r16-lilianweng-rlhf
kind: reading
title: "Lilian Weng — RLHF, alignment, and LLM-agent deep dives"
source: "lilianweng.github.io"
url: "https://lilianweng.github.io/"
duration_min: 75
axes: [training_mechanics, eval_design]
domain_tags: [training]
authored_by: claude_code_v1_build
authored_date: 2026-05-14
version: 1
---

Lilian Weng's blog is the single highest-leverage long-form resource
on RLHF, LLM agents, and training-data design that's freely
available. Each post is a literature-review-density walkthrough with
real citations and clean diagrams; the "deep technical writeup"
equivalent of an annotated paper, but covering whole subfields
instead of single papers.

**Why read.** For roles that interview on RLHF / safety / agents
(Anthropic, OpenAI alignment, fellowships), her posts are
*structural* knowledge — interviewers regularly draw their mental
maps from these. You'll see questions whose right answer maps
directly to a section of one of her posts.

**What to take from it (the highest-priority posts).**

1. **["LLM Powered Autonomous Agents"](https://lilianweng.github.io/posts/2023-06-23-agent/)** —
   the canonical taxonomy: planning, memory, tool use, reflection.
   If a JD says "agent" anywhere, this is the prep reading.
2. **["The Transformer Family"](https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/)** —
   a survey of architectural variants (linear attention, sparse,
   long-context). Pairs with [r13-goat-attention-priors]
   (/content/r13-goat-attention-priors).
3. **["RL for LLM Reasoning"](https://lilianweng.github.io/posts/2025-05-01-thinking/)** —
   the post-o1 update: how RL shows up in modern reasoning systems.
4. **["Adversarial Attacks on LLMs"](https://lilianweng.github.io/posts/2023-10-25-adv-attack-llm/)** —
   for safety-org interviews; pairs with sycophancy work.

**Pair with** [Karpathy's training recipe](/content/r04-karpathy-training-recipe)
for the practitioner-level companion; her posts go up a level of
abstraction.

**Strategy.** Don't try to read everything. Pick one post that maps
to your current active JD and read it deeply, including the linked
papers' abstracts. ~75 min for one post done right.
