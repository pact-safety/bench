# Imposter-signal detection and mitigation

How the bench detects when a user is undervaluing themselves and adjusts curriculum + framing in response. Filed in response to operator observation 2026-05-18.

## Problem

The bench's audience — research-engineer interview prep, mid-to-senior level — is exactly the population where imposter syndrome is most common. Accomplished people with strong credentials repeatedly under-rate their own competence, then push back the daily drill onto problems too hard for the morale-building they need.

Two observable signal patterns:

1. **High "I'm not sure" rate on the onboarding quiz** — the user defers on questions they could probably answer if they pushed.
2. **Wide credentials-vs-self-assessment gap** — the LLM-derived credential analysis (from their CV / transcript / diploma) implies a score profile noticeably stronger than the self-assessment they just filled out.

Without intervention, the picker hands them medium-to-hard compose problems on day one, they fail or stall, the imposter feeling calcifies. The intervention: detect the signal, surface evidence, ease the early curriculum, and accelerate as the user demonstrates capability.

## What the science actually says

The relevant body of work is decades old and well-replicated. Highlights:

- **Clance & Imes (1978)** identified the "impostor phenomenon" — accomplished people experiencing persistent self-doubt despite objective success. Their original intervention recommendation: **cognitive reframing** + externalize the inner critic.
- **Bandura (1977, 1997)** — self-efficacy is built through **mastery experiences**. Early successes calibrate "I can do this"; early failures calcify "I can't." Mastery-learning literature (Bloom 1968) shows ≥80% early success rates produce durable confidence; ≤50% produces learned helplessness.
- **Dweck (2006)** — growth mindset reduces imposter feelings by reframing difficulty as growth signal rather than evidence of incompetence. The "yet" framing ("I don't know transformers *yet*") is empirically supported.
- **Kross & Ayduk (2017)** — self-distancing (third-person inner speech) reduces affective intensity around self-criticism.
- **Moore & Healy (2008)** — underconfident people specifically benefit from **calibration training**: predict outcome → observe actual → recalibrate. Repeated cycles narrow the prediction-vs-outcome gap.
- **Gollwitzer (1999)** — **implementation intentions** ("if X, then Y") bridge the intention-action gap. For imposter syndrome: "if I feel like I don't belong, then I'll review my credentials and log one win."
- **Cokley et al. (2013–2017)** — mentor relationships and identity-affirming experiences mitigate imposter feelings, especially for underrepresented populations. The bench's mentor-voice system is a partial substitute.

The bench's interventions below all map to one or more of these mechanisms. We are not building a clinical tool; we're applying well-replicated learning-science to curriculum sequencing and framing.

## What the bench will do

### 1. Detect — `app/services/imposter.py`

Pure-functional detector. No side effects, no DB access. Inputs:

- `quiz_answers: list[Literal["yes", "no", "not_sure"]]` — onboarding self-assessment responses
- `assessment_scores: dict[str, float]` — self-rated 0..1 per axis (from the quiz)
- `credential_scores: dict[str, float] | None` — LLM-derived axis profile from credentials (may be None if no upload yet)

Outputs:

```python
@dataclass
class ImposterSignal:
    state: Literal["none", "mild", "strong"]
    not_sure_rate: float          # fraction of quiz answers that were "not_sure"
    credential_gap: float | None  # mean(credential - self) where credential exists; None if no cred
    triggering_axes: list[str]    # axes where the gap exceeds the per-axis threshold
    detected_at: datetime
```

Detection thresholds (tunable via `config.toml`):

- `not_sure_rate >= 0.5` → mild signal
- `not_sure_rate >= 0.75` → strong signal
- `credential_gap >= 0.20` (i.e., credentials suggest the user is 20+ points stronger than they self-rated) → mild
- `credential_gap >= 0.35` → strong
- Either signal alone is enough; both together strengthens but doesn't multiply

The state is **persisted** to `user_settings.imposter_signal` so downstream services can read it without recomputing. It **auto-decays** when (a) the gap narrows to below the mild threshold OR (b) the user has completed N mastery experiences (see §3).

### 2. Acknowledge — onboarding follow-up screen

When detection fires at the end of onboarding (the user has just rated themselves), instead of jumping straight to Today, intercept with a single screen:

- **Header**: "Your credentials say something different" (if credential-gap fires) or "It's OK to be unsure here" (if only the not-sure rate fires).
- **Body** (concrete, evidence-based, NOT preachy):
  - The specific axes where the gap is widest, with the credential-derived score next to the self-rated score
  - One sentence framing it as common ("This pattern is the most common shape we see in senior-engineer prep" — true)
  - One sentence framing the bench's response ("We're going to start you on warmups for the first week, then accelerate as the data comes in")
- **Action**: continue to Today (no opt-out; the framing IS the intervention, not a wall to climb).

Copy is in plain English. Avoid the words "imposter syndrome" — the framing matters; clinical labels reduce agency. The intervention is "we noticed a pattern in your data; here's how the bench will adapt," not "we've diagnosed you."

### 3. Adjust curriculum — scheduler bias

When `imposter_signal.state != "none"`, the daily-flow picker biases toward:

- **Warmups first** — exhaust the warmup queue before any compose problem
- **Easier compose problems** — when warmups are exhausted, prefer `difficulty: easy` over `medium` / `hard`
- **Mastery framing** — the home page's "Up next" card shows "Today's win" instead of "Today's challenge" while the signal is active
- **Skip the readiness scoring against the active JD** — the gap visualization can amplify the imposter feeling; defer it for the first week

This continues for a **mastery window**: until the user completes N (default: 5) practice attempts where `solved_without_lookup=true` AND `confidence_1_to_5 >= 4`. After that, the signal auto-decays to "none" and the normal scheduler takes over.

If the user is breezing through warmups (>80% solved-without-lookup, high confidence), the signal can decay earlier — the bench notices and stops treating them gently. The "accelerate" half of the operator's ask.

### 4. Calibration ritual — weekly Reflect

Adds one optional Reflect prompt while the signal is active:

> "Pick one problem from this past week. Before the answer was revealed, what did you predict — would you solve it, and how long would it take? What actually happened? What's the gap?"

This is the Moore & Healy calibration loop in narrative form. Over time, the prediction-vs-outcome data trains the user's self-rating to be more accurate. The prompt **stays** even after the imposter signal decays — calibration is a permanent skill, not a remediation.

### 5. Surface evidence — /aim

When the signal is active, the `/aim` "Where you stand" section shows an additional small panel:

> **What your credentials say**
> Your CV shows strong signal on: {top 3 axes from credential analysis}.
> Self-rated lower: {axes where gap > 0.20}.
> _Use the difference as a starting hypothesis, not a verdict._

The credentials-gap analysis already exists at `/credentials/{id}/gap`. We surface a condensed version on /aim, prominently, while the signal is active.

## Implementation plan

Six sub-deliverables, sequenced so each is independently shippable:

| # | Sub-issue | Complexity | Notes |
|---|---|---|---|
| A | Detection service (`imposter.py` + tests) | `complexity:m` | Pure-functional, no DB, easy to unit-test |
| B | Onboarding intercept screen | `complexity:m` | Template + route; needs the detection from A |
| C | Scheduler / daily-flow bias when signal active | `complexity:m` | Touches `daily_flow.py` and scheduler scoring |
| D | /aim evidence panel | `complexity:s` | Template addition; reads `imposter_signal` from settings |
| E | Onboarding copy edit (growth-mindset framing) | `complexity:s` | Pure copy/text |
| F | Reflect calibration prompt | `complexity:s`, **human-only** | Touches `voices.py` or `hamming.py` — CODEOWNERS |

Total: 4 Charlie-eligible + 2 small (one CODEOWNERS-protected).

### Order of landing

1. **A** lands first (everything else reads from it).
2. **B** + **E** can ship in parallel (no overlap).
3. **C** + **D** ship after A.
4. **F** is a human-author follow-up after the rest stabilize.

## What this is NOT

- **Not** a clinical assessment. The bench is not a therapist. The "imposter signal" is a data-shape pattern, not a diagnosis.
- **Not** permanent gentling. The point is to ramp the user up to where their credentials suggest they should be — the signal decays as they demonstrate capability.
- **Not** a substitute for actual learning. Warmups still teach; the credential gap still surfaces; the bench is honest about what the data shows.

## Open questions

- **Tunable thresholds**: the 0.5 not-sure rate and 0.20 credential gap are first-pass calibrated. Worth revisiting after 2-3 users have run through the flow.
- **Display name on the framing copy**: should it use the operator's `display_name` from settings, or stay impersonal? Impersonal is safer (less "the bench knows you" creep), but personal may be more affecting. Empirical question.
- **Should the operator be allowed to opt out / opt back in?** Imposter syndrome literature suggests *not* offering an opt-out is more therapeutic for the target audience — the framing is the intervention. But power-user override might be courteous. Default: no opt-out; revisit if it's a real annoyance.

## References

- Clance, P. R., & Imes, S. A. (1978). The Impostor Phenomenon in High Achieving Women. *Psychotherapy: Theory, Research and Practice*.
- Bandura, A. (1997). *Self-Efficacy: The Exercise of Control*. Freeman.
- Bloom, B. S. (1968). Learning for Mastery. *Evaluation Comment*.
- Dweck, C. S. (2006). *Mindset: The New Psychology of Success*. Random House.
- Kross, E., & Ayduk, O. (2017). Self-Distancing: Theory, Research, and Current Directions. *Advances in Experimental Social Psychology*.
- Moore, D. A., & Healy, P. J. (2008). The Trouble With Overconfidence. *Psychological Review*.
- Gollwitzer, P. M. (1999). Implementation Intentions: Strong Effects of Simple Plans. *American Psychologist*.
- Cokley, K., et al. (2013). An Examination of the Impact of Minority Status Stress and Impostor Feelings on the Mental Health of Diverse Ethnic Minority College Students. *Journal of Multicultural Counseling and Development*.

## See also

- [`app/services/assessment.py`](https://github.com/pact-safety/bench/blob/main/app/services/assessment.py) — produces the self-rating that one half of the signal reads
- [`app/services/credentials.py`](https://github.com/pact-safety/bench/blob/main/app/services/credentials.py) — produces the credential profile the other half reads
- [`app/services/daily_flow.py`](https://github.com/pact-safety/bench/blob/main/app/services/daily_flow.py) — the scheduler that adjusts under §3
