# Linear-on-Today v2 — refined picks from v1 (PR #332)

Operator picks from PR #332:
- **Default view:** rail addition from Variant A — Linear cards in the right rail; bench surfaces stay primary
- **Optional view:** "day at a glance" — timeline (variant C structure) populated with B's time blocks
- **Cognitive flow:** warm-up (readings/videos over coffee) → focus → coding/debug exercises → wind-down with small tasks before lunch
- **Required new:** current-time indicator, day-progress display, "extend block / defer tasks" affordance
- **Future:** historical time-tracking data informs future estimates (placeholder in v1)

The two answered scoping questions:
- **Day extent:** flexible. Default 6a–11a; MIRA exposes "extend block" + "defer to lower-intensity day" actions when load doesn't fit
- **Toggle placement:** "give me a few options" → each variant in this set uses a different toggle treatment

## The three new variants

| Variant | Toggle treatment | Timeline orientation | Progress display |
|---|---|---|---|
| **D** — Segmented pill | Top-of-page pill `[ Rail · Timeline ]` | Vertical (time on left axis, tasks read top-to-bottom) | Horizontal progress bar across top with hour markers + now indicator |
| **E** — Mini-timeline in rail | Click the rail's "day at a glance" thumbnail to expand to full timeline | Horizontal day-strip (like v1's variant C) but with cognitive-phase labels (Warm-up · Focus · Exercise · Wind-down) | Circular donut: % of block elapsed + remaining tasks count |
| **F** — Inline header pill | Small "🗓 timeline" toggle next to the date | Horizontal stacked: phase rows (Warm-up / Focus / Exercise / Wind-down), each with tasks placed inside | Now-line cursor on the timeline + "3 of 6 done" inline text |

All three variants share:
- Linear filter `dueDate <= today AND state != completed` (overdue + today's items)
- 6-item day reordered for cognitive flow (mix of Linear tasks + bench items, MIRA's plan)
- Current time mocked at **8:30 AM** (mid-block) so you can see the "now" indicator in context
- Same "Extend block →" / "Defer N tasks to Friday →" footer in the timeline view
- Estimate-from-history hint: `MIRA · estimate based on your last 4 similar tasks (avg 1h 50m)` shown in the timeline view — placeholder copy in v1; real once time tracking ships

## How to view

```bash
python3 -m http.server 8765
```

→ <http://localhost:8765/prototypes/2026-linear-today-v2/today.html>

Flip variants with the floating bar or keys `1` / `2` / `3`. Within each variant, click the toggle to flip between rail and timeline.

## Decisions to capture (post-pick)

- **Variant chosen:** _(fill in)_
- **Default view on first page-load:** rail or timeline? _(probably rail per the operator's earlier statement)_
- **Bits to steal from non-winning variants:** _(fill in)_
- **Cognitive-phase labels** — keep the four-phase model (Warm-up · Focus · Exercise · Wind-down), or simpler (just "morning / midday / wind-down")? _(fill in)_
- **Time-tracking estimate hint copy** — exact text for v1 (placeholder) vs. once data lands? _(fill in)_
