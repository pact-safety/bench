---
slug: c02-published-research
title: "Research output others can cite"
track: technical
weight: 5
effort_hours: 200
axes: [ai_safety_fundamentals, eval_design]
authored_by: claude_code_signal
authored_date: 2026-08-21
version: 1
---

## What it is

A piece of original research on an AI safety question, written up so that
someone else can build on it and point at it. Constellation/Astra's guidance
lists "have published AI safety research," and adds that "publishing at a
reputable conference, citations, and reputable co-authors and institutions,
are a major plus." Note the structure of that sentence: publication is the
criterion, venue and citations are amplifiers. A well-executed workshop paper
or a substantive Alignment Forum post with real experiments counts as output;
it just carries less amplification than a NeurIPS paper with a known co-author.

## What strong looks like

- A stated claim that could have come out false, and did not — or did, and you
  published that.
- Experiments that a reader could rerun: code released, seeds fixed, model
  versions and dates pinned (frontier model behaviour drifts; an unpinned
  result is unreproducible six months later).
- The obvious confound is addressed in the paper, not left for the reader.
  Whatever a reviewer would ask first, you already answered.
- A related-work section showing you know the three-to-five closest existing
  results and can say precisely what yours adds.
- Limitations that are real. "We only tested one model family" is a real
  limitation; "future work could extend this" is not.
- Someone unaffiliated has engaged with it: cited it, replied substantively,
  built on the code, or argued with the conclusion in public.
- If co-authored, your specific contribution is visible — a contributions
  statement, or commit history that shows what you did.

## What weak looks like

- A preprint on arXiv nobody has read, cited, or commented on, submitted to no
  venue. Posting is not publishing.
- A survey or "landscape" post with no new evidence. These are common because
  they are cheap; they are read as such.
- Results on a single model, single prompt template, no variance reported,
  framed as a general property of language models.
- A paper whose contribution is a new name for an existing phenomenon.
- Your name fifth on a paper where you ran a script. Real, but small — do not
  present it as more.
- A blog post with a strong claim and an appendix of cherry-picked
  transcripts.
- Work rejected from a venue, never revised, never resubmitted, still listed.
  Reviewers can usually tell.

## How to produce it

1. Start from a result you already have — most commonly the eval artifact
   (`c01`) or the reproduction (`c03`). Research output is usually a second
   pass over something you already ran, not a fresh start.
2. Write the claim as a single sentence and show it to two people who work in
   the area. If they cannot tell you what would falsify it, rewrite it.
3. Find the closest five existing results before you run anything more. Use the
   bench knowledge base and Mira to trace the citation neighbourhood, then read
   the papers themselves — a summary is not a literature position.
4. Design the experiment so the null result is publishable. If a null would
   waste the work, the design is wrong.
5. Run it, including the confound arm and the ablation a reviewer will demand.
6. Draft, then deliberately attack your own claim in a section. Whatever
   survives is the paper.
7. Submit somewhere with review — a workshop counts, and workshop review is
   substantially more feedback than fellowship review gives you. Post the
   preprint and the code at the same time.

## How a selector sees it

Title, abstract, and figure one. They are checking whether there is a claim,
whether the evidence shape matches the claim, and whether they recognise the
venue or a co-author. Thirty seconds, often less. What makes it skippable: an
abstract that describes activity rather than a finding ("we explore...", "we
investigate..."), or a headline number with no comparison. Be aware that
publication is the slowest criterion on this list and the least controllable —
plenty of accepted fellows have none, and having one does not move you past a
capacity ceiling.
