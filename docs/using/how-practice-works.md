# How practice works

The pedagogy, and how confident to be in it. Bench makes specific choices about
how you practise; this page states them, names what they're borrowed from, and
is explicit about which parts are evidence-backed and which are opinion.

## The five phases

Every core problem is structured as Explore → Brainstorm → Plan → Implement →
Verify, and the editor stays locked until Plan has content in it.

| Phase | What you do |
|---|---|
| Explore | Pin down the I/O, constraints, edge cases |
| Brainstorm | Two or three approaches, with trade-offs |
| Plan | A paragraph-deep outline |
| Implement | Write the code |
| Verify | Properties, boundary cases, hand-traced inputs |

**Why the lock.** The failure mode this targets is jumping straight to typing,
which feels productive and skips the part interviews and real research work
actually select on. You cannot practise framing a problem if you never frame
one. Warmups deliberately skip the scaffolding — they're a barrier-lowering
ramp, not the main event.

**Confidence: opinionated.** Structured problem-solving frameworks are old and
well-regarded (Pólya, and every "understand before you code" pedagogy since),
but the specific five phases and the editor lock are a design choice tuned to
this domain, not a result copied from a study.

## Retrieval, not review

Reading something again is close to worthless for retention and feels
excellent, which is the worst possible combination. Bench asks you to say the
idea back without looking, then compares what you said to the source.

**Confidence: strong.** The testing effect — that retrieving information
strengthens memory more than restudying it — is one of the better-replicated
findings in cognitive psychology.

## Spaced return, and what a miss means

Each concept sits on a ladder: **1 day → 7 days → 30 days**. Recall it and it
moves up a rung. Miss it and it drops back to 1 day.

**Confidence: strong on the principle, opinionated on the numbers.** Spacing
beats massing, robustly. The specific 1/7/30 rungs are a legible approximation,
not a fitted forgetting curve — a scheduler like SM-2 or FSRS would adapt per
item. Legibility was chosen over optimality: you can predict when something
comes back, and predictability is worth more than a few percent of efficiency
when the thing competing for your attention is not practising at all.

The combination — retrieval plus spacing, with failures rescheduled rather than
merely repeated — is what the literature calls **successive relearning**.

## No scores

This is the strongest opinion in the product, so it gets stated in full.

Bench will not show you a score, a percentage, a grade, a letter, an "x out of
y", a progress bar toward 100%, a streak that breaks, or a trend line that goes
down. It does not compute one privately either.

A recitation tells you which ideas were **covered**, **missing**, **misstated**,
or left as an **open question**, and then tells you what comes back sooner.
Miss three things and the app says *"three concepts return Thursday"* — never
*"you missed three."*

**Why.** The intended user is someone moving toward AI safety research
engineering, frequently while doubting they belong there. A number attached to
a bad day converts a scheduling fact into evidence about your worth, and the
predictable response is to stop opening the app — which is the only outcome
that actually costs you the skill. Removing the number removes the thing to
flinch from, while losing no information: "returns Thursday" carries everything
"60%" did, and points at an action.

This is enforced twice, because a constraint that lives only in a prompt is a
suggestion. The grader's output shape has no score field, and any number a
model tries to emit is stripped before it reaches you.

**Honest about the trade-off.** Some people are motivated by streaks and
numbers, and for them this is worse. The scoring the app *does* keep — the
skill profile across 13 axes — exists to route what you see next, and it is
deliberately not framed as a report card.

**Confidence: opinionated.** Research on feedback and motivation is genuinely
mixed. This is a designed stance, not a finding.

## Interleaving

The daily pick rotates across kinds — reading, watch, exercise, practice,
writing — and chooses from where you're weakest across 13 skill axes, rather
than letting you do six problems of the thing you already enjoy.

**Confidence: good.** Interleaved practice reliably beats blocked practice for
transfer, and reliably feels worse while you're doing it. If the daily pick
seems to be handing you the awkward thing, that is the design.

## The parts that are not AI

Worth separating clearly, because "AI learning platform" usually means the
model is in the loop everywhere:

- What you practise next — **deterministic**, from your skill profile and what
  you've completed today
- The spacing ladder — **deterministic**
- Test results — **actual execution** in a sandbox, not a model's opinion
- Skill scores and readiness — **deterministic**

The model writes hints, reviews, mentor conversation, and the recitation
comparison. It does not schedule you, score you, or decide whether your code
works. See [AI in the bench](ai-and-your-work.md).

## Bring your own material

Papers, lectures and exercises you're already working through can be ingested,
get scored on the same 13 axes, and enter the same rotation. Curricula ship as
**tracks** — ARENA 3.0 and MATS-oriented paths today — which run a fixed
sequence with the retrieval loop underneath.

**The notebook gap.** Working through a Colab notebook with autocomplete on
teaches your editor as much as it teaches you, and the cell that produced the
answer is right there while you "recall" it. Tracks ask for the same idea cold,
later, away from that cell.

## Related

- [Drilling problems](problems.md)
- [Curriculum tracks](../architecture/tracks.md)
- [Readiness scoring](readiness.md)
- [Weekly reflections](reflect.md)
