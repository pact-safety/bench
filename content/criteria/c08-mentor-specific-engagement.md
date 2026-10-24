---
slug: c08-mentor-specific-engagement
title: "Evidence you engaged with a specific mentor's actual work"
track: all
weight: 5
effort_hours: 15
axes: [ai_safety_fundamentals, debugging]
authored_by: claude_code_signal
authored_date: 2026-08-21
version: 1
---

## What it is

Something you produced that could only exist if you had gone through a
particular researcher's work in detail. Constellation's guidance for all
applicants: "Demonstrate deep interest in research mentors' research — read
their bios and recent research papers in detail, run the projects on your
computer." The last clause is the one applicants skip. Running the code is what
turns interest into an artifact.

## What strong looks like

- You ran their repo, hit a real problem, and wrote up what you found — an
  issue, a gist, a short post. Five minutes of their reading time, produced by
  ten hours of yours.
- Your question is one only a reader who got to section four could ask. Not
  "how did you choose this dataset" but "the ablation in Table 2 drops the
  effect at layer 14 — is that the residual-stream norm or the probe?"
- You can trace the arc of their work: what they were doing three years ago,
  what changed, what they seem to be moving toward. Their agenda, not their
  greatest hit.
- You found something they would want to know: a broken link in the repo, a
  version incompatibility, a result that does not reproduce on current library
  versions.
- Your proposed project extends their actual open thread rather than restating
  their published result as a plan.
- If you contacted them, the message was short, specific, and asked for nothing.

## What weak looks like

- "I read your paper on X and found it fascinating." This is the modal message
  and it is invisible.
- Citing their most-cited paper from five years ago while their current work is
  elsewhere. Reads as a search-result-depth read.
- A project proposal that is their published paper with a different dataset.
- Questions answered in the abstract, or in the FAQ of their repo.
- Naming four mentors in one application with a paragraph each. Depth in one
  beats coverage of four, and coverage of four signals you are optimising for
  acceptance rather than for a project.
- Cold-emailing them a long document asking for feedback. That is a cost
  imposed, not a signal given.
- Engagement that exists only inside the application form. If it is not public,
  a reviewer cannot verify it in the time they have.

## How to produce it

1. Pick one mentor. One. Choose by whether you would want to spend three months
   on their open problem, not by prestige.
2. Read their last three outputs in order, footnotes included, and write a
   one-page summary of the arc for yourself.
3. Clone the repo and run it. Budget for it not working — this is where the
   artifact comes from.
4. Log every friction point. Fix one and open a PR (`c04`); document one and
   open an issue.
5. If they have a public result you can reproduce at small scale, do that
   (`c03`) and make it about their specific claim.
6. Write one public thing they could read in five minutes that tells them
   something they did not know about their own work.
7. Only then, if at all, contact them — with the link, two sentences, no ask.

## How a selector sees it

A reviewer who knows that mentor's work can tell within one paragraph whether
you have read it or read about it. They look for a detail that is not in the
abstract. Fifteen seconds, and it is close to binary. What makes it skippable:
generic admiration, a stale citation, or a proposal that could be sent to any
of five mentors with the names swapped. This is the highest ratio of signal to
effort on the entire list — fifteen hours, and it is the criterion most
consistently underdone.
