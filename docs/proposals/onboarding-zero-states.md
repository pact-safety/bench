# Proposal: zero-state onboarding (Pattern C — contextual CTAs)

**Status:** draft — operator decision on implementation needed

**Date:** 2026-05-25

## Why this exists

Operator asked: "is there a way we can do onboarding with CTAs to introduce the user to the platform?"

Three patterns were considered last session:

- **Pattern A — first-N-visits banner.** Dismissible card on each surface for the first 3 visits. Stored as `settings.seen_surfaces`. Cheap but state-heavy.
- **Pattern B — one-time guided tour.** "Take the tour" button → linear walk through 8 surfaces. Heaviest UX commitment. Most onboarding tours get clicked through without reading.
- **Pattern C — contextual CTAs at zero-state.** Each surface has a richer empty-state with an explanation of what the surface does and a concrete first action. Encountered when the operator/visitor is actually trying to do the thing, which is when explanation lands.

**Recommended: Pattern C.** This doc audits the current state and identifies the gap fixes.

## Audit results (2026-05-25)

Eight primary nav surfaces, scored on three axes:

| Axis | Means |
|---|---|
| **Has zero-state branch** | Template explicitly handles "no data yet" with distinct copy |
| **Explains the surface** | Tells the visitor *what this is for*, not just *that it's empty* |
| **Proposes a next action** | Concrete CTA with link/button that initiates the right first action |

| Surface | Zero-state? | Explains? | CTA? | Verdict |
|---|---|---|---|---|
| `/` Drill (home) | n/a — never empty (daily-progress strip or rest-day card always present) | yes | yes | ✅ |
| `/library` Learn | partial — empty filter result not explicitly handled, but content/ is checked in so the surface is never truly empty | yes (header copy) | yes (`+ Add external content`) | ✅ acceptable |
| `/tracks` Tracks | partial — "No active track" mention but no first-time-here framing | partial (lists tracks) | partial (activate buttons) | ⚠️ **gap** |
| `/reflect` Reflect | no — week-card shows all zeros for first-time user; no explanation that the *first* reflection differs | yes (header) | yes (Generate button) | ⚠️ **gap** |
| `/writings` Write | yes — explicit `empty-state__msg` | yes | yes (`+ Start a draft`) | ✅ Pattern C exemplar |
| `/aim` Aim | yes — "No assessment yet → take the initial assessment" | yes | yes (link to /onboarding) | ✅ partial sections could be richer |
| `/focus` Focus | yes — "No active initiatives. Add a markdown file under content/initiatives/…" | yes | yes (markdown instructions) | ✅ Pattern C exemplar |
| `/decisions` Decisions | yes — full explanation of `log_chat_outcome` MCP tool | yes | yes (MCP setup pointer) | ✅ Pattern C exemplar |

## Identified gaps

### 1. `/tracks` — first-time visitor has no "start here"

**Current state:** the page lists all tracks (ARENA 3.0 today; future ones added as content files). If no track is active, the operator sees a list with "activate" buttons but no framing of *which one* to pick or *why* this is the first step toward whatever they're trying to accomplish.

**Proposed fix:** when `state == "not_started"` for every track AND no active track exists, render a leading paragraph:

```
You haven't started any curriculum yet. Tracks are ordered overlays
on the bench's content corpus — they sequence what to read and
practice, with checkpoint gating so you can't skip ahead.

If you're targeting AI-safety / interpretability roles, start with
ARENA 3.0 (Callum McDougall's curriculum). It's the only track
shipped today; more land as the operator curates them.

→ [Activate ARENA 3.0]   (the actual button below acts on this)
```

Then the existing track list renders below, with the operator's recommended one called out.

**Effort:** ~30 lines of template + maybe 10 lines of CSS. One PR.

### 2. `/reflect` — first reflection is different from the Nth

**Current state:** `reflect.html` shows the "week in numbers" panel with all zeros for a brand-new user, then a "Generate" button. The header text explains Hamming style but doesn't acknowledge that the *first* reflection is different — there's no prior week to compare against, and Hamming framing assumes a track of recent activity.

**Proposed fix:** detect the first-time case (`len(reflections) == 0 AND week.attempts == 0`) and render a callout instead of the zeros panel:

```
First reflection. Your activity log is empty so far — there's not
much for Claude to write a Hamming retrospective about yet. Three
options:

→ Skip the reflection until you've attempted a problem or two.
→ Generate anyway — Claude's canned fallback prompts will give you
  3 questions to think through, without trying to fabricate a
  retrospective on no data.
→ Read the Hamming framing first: [Hamming foundations] (in /library)
```

**Effort:** ~25 lines. One PR.

### 3. `/aim` — multiple sections, each with their own empty state

**Current state:** `/aim` is the largest single surface in the bench. It has these sections: skill chart + per-axis breakdown, calibration scatter, JDs, credentials, evidence/imposter. Each section can be empty independently (e.g., assessment done but no JDs uploaded). The current code handles "no assessment at all" but not the partial-data cases.

**Proposed fix:** add lightweight empty-state callouts per section:

- **Calibration scatter section:** if zero calibration reflections — "No calibration data yet. The calibration prompt rotates into your weekly Reflect; check the gap chart after a few reflections."
- **JDs section:** if zero JDs — "No JD profiles yet. Paste a job description into [Aim → Add JD] to get an axis-weights breakdown + iterator/amplifier/connector profile fit." (link to /aim/jd/new)
- **Credentials section:** if zero credential runs — "Upload a resume PDF to get an axis-evidence breakdown + iterator/amplifier/connector profile inference. Used to detect imposter-signal patterns when your stated confidence diverges from documented experience."

**Effort:** ~60 lines of template + 0 CSS (reuse `.empty-state`). One PR — or split into 3 small PRs if the operator wants the changes reviewable separately.

## What this proposal explicitly does NOT recommend

- **Pattern A (first-N-visits banner).** Adds a `seen_surfaces` JSON field to settings, requires per-surface tracking, gives a marginal-at-best gain over rich zero-states. Pattern C addresses the same audience (first-time visitor) at the same moment (first encounter with the surface) without the state-tracking.
- **Pattern B (one-time tour).** Most tours get click-throughed. The bench's existing /onboarding flow already handles the most important first action (the assessment quiz). Adding a separate guided-surface tour duplicates that mechanism.
- **A `/getting-started` route in the bench.** The mkdocs site already has a `Getting started` section (first-run / onboarding / daily-flow). PR #260 surfaces that site from inside the bench via the docs link. Don't fork two getting-started surfaces.

## Implementation plan

If approved:

1. **PR 1** — `/tracks` first-time framing (gap #1). Small, low-risk.
2. **PR 2** — `/reflect` first-reflection callout (gap #2). Small, low-risk.
3. **PR 3** — `/aim` per-section empty-states (gap #3). Larger, splittable.

All three are template-only changes with light tests asserting the empty-state markup appears under the right conditions. No schema changes, no migration.

Total scope: ~120 lines + ~6-9 tests across 3 PRs. Roughly half a day of work.

## Operator decisions

1. **Ship all three fixes?** Or just gap #1 (the most-felt one) first?
2. **`/aim` empty-states: one PR or three?** Splitting makes review easier; bundling ships faster.
3. **Anything to add to the audit that I missed?** Particular surfaces feel rough that aren't flagged here?

## Why not now (honestly)

These are real polish items that improve the bench for any new visitor — fellowship reviewer, prospective second user, the operator returning after a capstone-deep-work week. But they're polish, not unlock-something-new. The chat-outcomes table cutover (PR #253) and the RLS migration (PR #254) are doing more security and architectural work right now; the bench's structure benefits more from those landing than from these surface polish items.

**Trigger to ship:** when the operator next needs to *show* the bench to someone unfamiliar (reviewer, recruiter, peer). That's when the zero-states get encountered cold.
