---
slug: c07-threat-model-fluency
title: "Demonstrated, specific threat-model reasoning"
track: governance
weight: 5
effort_hours: 30
axes: [ai_safety_fundamentals, ai_governance_strategy]
authored_by: claude_code_signal
authored_date: 2026-08-21
version: 1
---

## What it is

You can lay out a specific pathway from a specific capability to a specific
harm, say which step is load-bearing, and say what evidence would change your
mind about it. Constellation's governance guidance asks for "demonstrated clear
understanding of threat models relevant to AI risks, such as loss of control
risk." Demonstrated is the operative word — this is assessed through your
writing and in interview, not through a claim that you understand it.

## What strong looks like

- You reason about a *named* threat model — deceptive alignment, gradual
  disempowerment, a specific misuse uplift pathway — and can state its steps in
  order.
- You name the step you think is weakest, and say why. Every threat model has
  one; identifying it is what distinguishes reading from thinking.
- You can state what observation would raise or lower your credence, at a
  granularity someone could actually go and measure.
- You hold calibrated uncertainty across models — you can say which risks you
  weight more and why, without flattening everything into "AI is dangerous."
- You connect the threat model to a measurement or an intervention. A threat
  model that implies no eval and no policy is not doing work.
- You can argue the skeptical case competently. If you cannot state why a
  thoughtful person finds loss-of-control arguments unpersuasive, you have read
  one side.
- Your writing shows this in passing rather than announcing it — the threat
  model frames the question rather than sitting in a preamble.

## What weak looks like

- Reciting the standard chain — capable system, misaligned goal, instrumental
  convergence, catastrophe — with no step you own or doubt.
- Threat models as vocabulary: mesa-optimisation, sharp left turn, treacherous
  turn used as tokens rather than as claims with cruxes.
- Collapsing everything into "misalignment" without distinguishing misuse,
  accident, structural, and control failures, which imply different
  interventions.
- Confident probability numbers with no reasoning attached. Reviewers read an
  unexplained "p(doom) = 0.2" as a social signal, not an estimate.
- Deference: "as Bostrom argues..." for every step, no independent view.
- Dismissing the skeptics rather than engaging them.
- A threat model that conveniently justifies the work you already wanted to do.

## How to produce it

1. Pick one threat model and write it out as an explicit chain of numbered
   steps, each of which could fail.
2. For each step, write the strongest objection and your response. Where your
   response is weak, mark it — those are your cruxes.
3. Read the serious critics of that model, not summaries of them. Being able to
   pass the ideological Turing test is the check.
4. Convert one crux into something empirical: what would you measure to move it?
   If you can, actually measure it — this is a natural feed into `c01`.
5. Use Mira for adversarial questioning on the chain. It will push on steps you
   have hand-waved, which is the point; treat its objections as a rehearsal for
   interview, not as authority.
6. Write your position publicly, including the parts you are unsure about.
   Stated uncertainty reads as competence here, not weakness.
7. Find someone who disagrees and have the argument in public.

## How a selector sees it

In writing, they check whether your framing paragraph does work or is
decoration — whether the threat model constrains what you go on to argue. In
interview, they ask one follow-up question, usually "why that step?" or "what
would change your mind?", and the answer separates people quickly. Seconds on
the page, one question in the room. What makes it skippable: the standard chain
recited in the standard order, which reads as absorbed rather than reasoned. If
you have been rejected after final-round interviews, this is one of the
criteria most likely to have been the silent reason, because it is assessed
conversationally and almost never fed back.
