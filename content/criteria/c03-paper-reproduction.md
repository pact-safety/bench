---
slug: c03-paper-reproduction
title: "A reproduction you ran and wrote up"
track: technical
weight: 4
effort_hours: 40
axes: [mechanistic_interpretability, debugging]
authored_by: claude_code_signal
authored_date: 2026-08-21
version: 1
---

## What it is

You took a published safety or interpretability result, re-ran it yourself, and
wrote up what happened — including the parts that did not match. Constellation's
guidance frames this under engaging with mentors' work: "run the projects on
your computer." The reproduction is the cheapest artifact on this list that
still produces a genuinely new fact, because published results are underspecified
far more often than anyone writes down.

## What strong looks like

- You state up front which specific number or figure you targeted, and the
  compute you had. "Figure 3, at 1/20th the model scale" is a real scope.
- You report the delta: what matched, what did not, and by how much.
- The interesting content is the friction — the undocumented preprocessing
  step, the hyperparameter the paper omits, the version pin that changes the
  result. That is the contribution.
- Where you diverged from the paper's method, you say so and say why.
- You made a judgement call about whether the divergence threatens the paper's
  conclusion, and defended it. Not "results differed slightly," but "the effect
  survives at smaller scale but the reported magnitude does not."
- Code is public, runnable, and states its cost — "reproduces the small-model
  arm in 40 minutes on one A100" is enormously more useful than an unbounded
  repo.
- You contacted the authors about the discrepancy, or filed an issue. Often the
  most valuable output: a public, findable answer.

## What weak looks like

- Running the authors' own notebook end to end and reporting that it worked.
  That tests their packaging, not the result.
- "I reproduced it" with no numbers next to the paper's numbers.
- Reproducing the toy example in the paper's tutorial section and stopping.
- Choosing a paper whose result is trivially reproducible because the authors
  shipped a one-command script — the effort is real, the signal is not.
- Silently changing scale, dataset, or model and reporting a mismatch as the
  paper being wrong.
- A repo with no writeup. The writeup is the artifact; the code is the evidence.
- Picking a famous paper everyone has already reproduced. Fine as learning,
  weak as evidence — nobody learns anything from your version.

## How to produce it

1. Pick a paper that is close to a mentor's current work, ideally by a mentor
   you would name in an application. This makes the artifact do double duty
   with `c08`.
2. Before touching code, write down the exact figure or table you are targeting
   and the number you expect.
3. Estimate compute honestly and pick the arm you can actually afford. A
   faithful small-scale arm beats an abandoned full-scale attempt.
4. Use the bench's mechinterp and ARENA track sections to close the specific
   gaps the paper assumes — hooks, activation caching, probe training. Do the
   prerequisite section rather than skimming past a technique you have not
   implemented.
5. Keep a running log of every point where the paper was ambiguous and you had
   to guess. This file becomes the most-read section of your writeup.
6. Run it. When numbers disagree, spend the debugging effort — most mismatches
   are your bug, and finding yours is the skill being evidenced. Use the bench
   debugging problems (`19`-`26`) if the failure is a mechanics bug rather than
   a method one.
7. Write it up with a side-by-side table, publish, and send it to the authors.

## How a selector sees it

They look for a comparison table and a "what didn't match" heading. If those
exist, they read the friction log — that is the part that tells them how you
behave when something is wrong, which is most of what research work is. Under
a minute. What makes it skippable: no numbers, or an all-green table, which
reads either as a packaging test or as insufficiently probed. A reproduction
that found nothing surprising is still worth publishing, but say plainly that
the result held.
