# Drilling problems

This is the surface I touch most. A typical morning: open `/`, see the day's pick under "Up next", click into the problem page, work through it, submit, read the review while I drink coffee.

The page walks me through five phases on the way to a submission. That structure is the point — without it, I jump straight to keyboard and miss the part of the interview I'm actually weakest at.

## The five phases

I started writing my way through interview problems instead of just coding through them because every mock interviewer I've spoken to said the same thing: the gap isn't usually the code. It's the framing.

| Phase | What I do here |
|---|---|
| **Explore** | I/O contract first. Shapes, dtypes, the smallest concrete example I can hand-trace. Edge cases I'd care about if I were grading this. |
| **Brainstorm** | Two or three approaches. Naive first. Each with one sentence on what it costs in time, space, or attention. The point is to notice the trade I'd otherwise have skipped. |
| **Plan** | The actual algorithm. Step-by-step, with invariants named. "After step 3, the buffer holds the k largest seen so far" — that kind of sentence. |
| **Implement** | The code. The editor stays locked until my Plan has 80+ characters in it, which is the plan-gate. I tried removing it once; my Implement-tier hint usage spiked the same week. Put it back. |
| **Verify** | The smallest input that would distinguish correct from off-by-one. The property I'd write a fuzzer against if I were paid to break this. The thing the provided tests don't catch. |

The plan-gate is the most opinionated thing on this page and the one I'd defend hardest. The most expensive interview mistake I've made is jumping to keyboard before the plan is in my head; the gate makes that mistake structurally impossible.

## Submitting

Bottom of the page, in order:

1. **Code editor** (Python or Rust depending on the problem).
2. **Notes** — usually empty for me, but it's there if I want a freeform "what I'd revisit" line at the end.
3. **Confidence** 1–5. I lie to myself less when I have to pick a number. 4 means "I'd ship this." 3 means "I'd write a test for it first." 2 or below and I know I'm guessing.
4. **Reference solution / pitfalls disclosure**. Clicking these is logged as a lookup. I look ~30% of the time on hard problems and ~5% on warmups. The scheduler reads those numbers to de-prioritize problems I've leaned on.
5. **`run tests`** button. Amber, with the live spinner the operator added during the 2026-05-25 validation pass.

What happens server-side:

```
POST /submit/{slug}
  → run_python_tests() / run_rust_tests()   (8s timeout default)
  → INSERT attempts row (code + per-phase notes + hint counts + lookup bools + test pass/fail + time-per-phase)
  → review_attempt() → Sonnet call in the selected voice
  → INSERT attempt_reviews row
  → HTMX swap renders the result inline
```

## The review I get back

A structured JSON the page renders as a per-phase card. The shape:

```json
{
  "summary": "2-3 sentence overall read",
  "per_phase": {
    "explore":    {"strength": "...", "gap": "...", "question": "..."},
    "brainstorm": {"strength": "...", "gap": "...", "question": "..."},
    "plan":       {"strength": "...", "gap": "...", "question": "..."},
    "implement":  {"strength": "...", "gap": "...", "question": "..."},
    "verify":     {"strength": "...", "gap": "...", "question": "..."}
  },
  "overall_score": 0.7,
  "voice_key": "default"
}
```

A phase is omitted if I didn't engage with it (no notes AND it isn't Implement).

The anti-sycophancy rule I baked into the prompt: a strength has to be **specific** — `"you named the invariant about axis discipline before coding"`, not `"good job thinking through the problem"`. A gap has to be **specific** — `"the kernel loop iterates n+1 times — off by one at the boundary"`. The question is open-ended, for me, not Sonnet.

When the review comes back without those specifics, I notice. It's usually a sign that my notes were too thin to evaluate against — which tells me something about my actual focus, not just the model's review quality.

## Voices

The default voice is the platform's house style — structured, anti-sycophancy, written from the perspective of someone who's seen ten thousand of these. But I'll route a submission through a specific voice when the problem warrants it:

- **Hamming** when I've drifted toward "interesting" over "important"
- **Petroski** when the problem is about failure modes
- **Meadows** for systems-shaped problems
- **Wade** when I'm doing something that touches people who'd otherwise be invisible to the work

The voice page (`/voices`) has the full roster + the review lens for each. See [Hints and mentor voices](hints-and-voices.md) for the rest.

## Resubmit guard

A second click on `run tests` within the same page load triggers a confirm dialog. Each submission burns a Sonnet review call (so each costs me real money via the API spend cap), and an accidental double-submit during a network hiccup used to cost me $0.04 and an extraneous attempts row. Now it costs me one click.

First click stays friction-free.

## Interview mode

`/problem/<slug>?mode=interview` removes the plan-gate, hides the reference / pitfalls / hint affordances entirely, and starts a timer. The submission gets graded against an algorithm-interview rubric (`assumption_clarification`, `multiple_approaches`, `complexity_stated`, `plan_before_code`, `code_quality`, `verification`) on top of the per-phase critique.

I use it for warmups before a real interview. It's punishing on purpose. The first time I tried interview mode on a problem I'd seen before, I scored a 4/10 because I didn't state complexity — that's the kind of gap I needed the rubric to make legible.

## What I'd change

- **Per-attempt voice memory.** The page picks the last voice I used; I'd rather it suggest a voice based on the problem's domain tags (Petroski for failure-mode debugging problems, etc.). Queued mentally, not on the roadmap yet.
- **Plan-gate as a soft suggestion, not a hard lock.** I'm 95% confident the lock is right, but there's a long-running mock-interview scenario where a strict timer + locked editor would actually punish good triage. Watching for the failure case.

## See also

- [Hints and mentor voices](hints-and-voices.md)
- [Readiness scoring](readiness.md)
- [Weekly Hamming reflections](reflect.md)
