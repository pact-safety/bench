---
slug: e49-position-bias-gap
kind: exercise
title: "Trace the position-bias gap in a multiple-choice eval"
source: "prep for ARENA 3.1 Intro to Evals"
duration_min: 8
axes: [eval_design, ai_safety_fundamentals]
domain_tags: [multiple choice, position bias, randomization, validity]
arena_section: "3.1"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** You have 100 four-option multiple-choice items. You run each item
twice against the same model at temperature 0: once with the correct option
placed at **A**, once with the same options rotated so the correct one sits at
**D**. Nothing else changes — same stem, same distractors, same wording.

Results:

```
correct option at A:  accuracy 0.82
correct option at D:  accuracy 0.61
```

**Question.** Answer three things without running anything.

1. What is the honest headline accuracy for this model on this eval?
2. What does the 21-point gap measure, and what does it *not* measure?
3. You fix this by randomizing the correct option's position per item. What
   does randomizing buy you, and what does it hide?

Commit to all three before revealing.

<details>
<summary>reveal</summary>

1. **0.715.** Every item ran once at A and once at D, so the two conditions are
   equally weighted: `(0.82 + 0.61) / 2`. Reporting 0.82 would be reporting the
   model's best seat. Report the mean *and* both conditions — the pair is the
   result, the mean alone throws away the finding.

2. The gap measures **answer-order sensitivity**: how much of the score comes
   from where the answer sat rather than what the answer said. Two things it is
   not. It is not a bias *toward A* in general — you tested A and D only, so
   B and C are unmeasured and the profile could be non-monotonic. And it is not
   an upper bound on total ordering effects; distractor order matters too, and
   you held that fixed.

3. Randomizing removes the *systematic* inflation: across many items no single
   position is favored, so the expected accuracy stops being an artifact of
   your item-writing habit (correct answer typed first). It buys an unbiased
   headline number. It hides the gap itself — with one sample per item at one
   random position, position variance is folded into the noise and you can no
   longer report "21 points of this model's score is seating." Keep the paired
   design, or balance positions and report per-position accuracy alongside the
   mean. Inspect's `multiple_choice()` solver has a shuffle option, which is
   the randomize path, not the measure path.

</details>

**Key insight.** Randomizing answer order makes the headline number honest;
only running the same item in more than one position tells you how big the
artifact was — and that number is a validity check on the eval, not a fact
about the model.
