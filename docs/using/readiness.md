# Readiness evaluation

`/readiness` tells you, in concrete hours and weeks, how close you are to interview-ready for your active JD.

## What you see

When you have **both** an assessment and a JD active:

- **Hero**: `<match-%>` and `~<hours>` to 100% match, with a fill bar.
- **Slider**: hours/week → projected weeks/months/years. Live JS recalc; deterministic with the server-side hours total.
- **Gap, by axis**: sorted bars showing your score vs the JD's weight, with a vertical target marker.
- **Already at JD level**: the axes you've cleared.
- **Other JDs**: same metrics computed against your other (non-archived) JDs, sorted by current readiness — useful for "which role is the shortest path?"
- **How this works**: the math, surfaced on-page.

When you lack either an assessment OR a JD: a "complete X first" empty state with a CTA to the missing piece.

## The math

Pure-functional in `app/services/readiness.py`. For each axis the JD weights > 0:

```
gap_axis     = max(0, jd_weight - user_score)
hours_axis   = gap_axis × 10 × HOURS_PER_TENTH_POINT       # default 12
readiness%   = sum(jd_weight × match%) / sum(jd_weight)    # JD-weighted average
weeks(h/w)   = total_hours / h/w
```

- `HOURS_PER_TENTH_POINT` defaults to **12** — meaning 12 hours of focused practice ≈ 0.1 axis-point lift. This is a documented heuristic (see the module docstring), not a calibrated number. Once you have ≥20 attempts logged, the page will refine this against your actual rate of progress (currently follow-on work).
- **Weighted-average readiness**: an axis the JD doesn't weight (`jd_weight = 0`) doesn't contribute to your score. Your rust score won't drag your interpretability fit.
- **Per-axis target marker** on each gap bar: a thin vertical line at `jd_weight * 100%` of the bar. Reads at-a-glance as "I'm at 40, they want ≥ 65."

## Discovery

You can reach `/readiness` from:

- The Today page's JD focus line (`Focused on <jd-title> · readiness → · manage JDs →`)
- The `/skills` page top-right (`Readiness for active JD →`)
- Directly: `/readiness`

## Defensive behavior

- No assessment? → empty state, CTA to `/onboarding`.
- No active JD? → empty state, CTA to `/jds`.
- JD parsed but all `axis_weights` are zero? → empty state — no math is meaningful.
- Hours-per-week slider at 0 or below? → "indefinite" duration label.

## What it doesn't do (yet)

- **Acceleration mode** — research replications + extra daily slots. Content authoring work; queued.
- **Real calibration from attempts** — replaces the 12-hours heuristic with your actual axis-lift-per-hour from logged attempts. Needs ≥20 attempts.
- **Multi-JD aggregate** — "what should I focus on this week given all your active JDs." Easy follow-on.
- **IAC alignment** in the readiness card — currently shown on the JD detail page only; could be folded in here once the reflect-IAC integration lands.

## See also

- [JDs](jds.md)
- [Architecture: services](../architecture/services.md#readiness)
