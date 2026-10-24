"""Illustrative comparison of assessed scores and inferred JD axis weights.

Only axes with assessment evidence and positive JD weights enter the
scenario. Unknown JD axes are reported separately, never treated as zero.
The fixed 12-hours-per-0.1-gap conversion is a planning assumption, not an
empirically validated learning rate or a personalized readiness forecast.
Practice attempts do not calibrate it. JD weights express role emphasis,
not validated proficiency thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any


# Fixed illustrative conversion; it does not model measured learning speed.
HOURS_PER_TENTH_POINT: float = 12.0

# Bounds for the planning slider, not claims about learning capacity.
HOURS_PER_WEEK_MIN: int = 2
HOURS_PER_WEEK_MAX: int = 25
HOURS_PER_WEEK_DEFAULT: int = 8


@dataclass(frozen=True)
class AxisGap:
    axis: str
    user_score: float          # 0..1
    jd_weight: float           # 0..1 (how central this axis is to the role)
    hours_needed: float        # illustrative hours under the fixed conversion
    match_pct: float           # min(user_score / jd_weight, 1.0) * 100; 100% means user >= JD
    at_target: bool            # True if user_score >= jd_weight (gap is zero)


@dataclass(frozen=True)
class Readiness:
    readiness_pct: float           # 0..100 — weighted-average match across assessed JD-weighted axes
    total_hours_needed: float      # sum of axis gaps in hours
    gaps: list[AxisGap]            # sorted by hours_needed desc
    has_data: bool                 # False if no assessed axes have positive JD weights
    note: str | None               # optional caveat ("no JD axes weighted > 0", etc.)
    unknown_axes: tuple[str, ...] = ()


def compute(
    *,
    user_scores: dict[str, float] | None,
    jd_axis_weights: dict[str, float] | None,
    axes: tuple[str, ...] | list[str],
    hours_per_tenth_point: float = HOURS_PER_TENTH_POINT,
) -> Readiness:
    """Compute an illustrative snapshot using only assessed, JD-weighted axes.

    Callers must omit axes without assessment evidence from ``user_scores``.
    A present zero is a measured score. ``has_data=False`` means there is
    no assessed overlap; render the note and coverage instead of a percentage.
    """
    scores = user_scores or {}
    weights = jd_axis_weights or {}

    weighted_axes = tuple(axis for axis in axes if weights.get(axis, 0.0) > 0)
    unknown_axes = tuple(axis for axis in weighted_axes if axis not in scores)

    if not weighted_axes:
        return Readiness(
            readiness_pct=0.0,
            total_hours_needed=0.0,
            gaps=[],
            has_data=False,
            note=(
                "No JD with weighted axes. Add a JD via /jds to see how its "
                "specific axis demands map to your assessment."
            ),
        )

    gaps: list[AxisGap] = []
    weighted_match_sum = 0.0
    total_weight = 0.0

    for axis in weighted_axes:
        if axis not in scores:
            # Missing evidence cannot establish a skill gap or learning time.
            continue
        weight = weights[axis]
        user_score = max(0.0, min(1.0, scores[axis]))
        at_target = user_score >= weight
        if at_target:
            hours = 0.0
            match_pct = 100.0
        else:
            gap_points = weight - user_score          # 0..1, in "axis score units"
            # 10 × hours_per_tenth_point converts "1.0 axis-point" → hours.
            hours = gap_points * 10.0 * hours_per_tenth_point
            match_pct = (user_score / weight) * 100.0 if weight > 0 else 100.0
        gaps.append(AxisGap(
            axis=axis,
            user_score=user_score,
            jd_weight=weight,
            hours_needed=hours,
            match_pct=match_pct,
            at_target=at_target,
        ))
        weighted_match_sum += weight * (match_pct / 100.0)
        total_weight += weight

    gaps.sort(key=lambda g: g.hours_needed, reverse=True)
    readiness_pct = (weighted_match_sum / total_weight * 100.0) if total_weight > 0 else 0.0
    total_hours = sum(g.hours_needed for g in gaps)

    return Readiness(
        readiness_pct=readiness_pct,
        total_hours_needed=total_hours,
        gaps=gaps,
        has_data=bool(gaps),
        note=(None if gaps else
              "No assessment evidence overlaps the weighted JD axes. "
              "These axes are not assessed; no practice scenario is available."),
        unknown_axes=unknown_axes,
    )


def weeks_to_ready(total_hours: float, hours_per_week: float) -> float:
    """Linear projection. Returns +inf if hours_per_week <= 0."""
    if hours_per_week <= 0 or total_hours <= 0:
        return 0.0 if total_hours <= 0 else inf
    return total_hours / hours_per_week


def format_duration(weeks: float) -> str:
    """Human-friendly: '4 weeks' / '~2.5 months' / '~9 months' / '~1.5 years'.

    Lives in the service (not the template) because the rounding
    decisions are user-facing English and easier to test here than
    in Jinja."""
    if weeks <= 0:
        return "already there"
    if weeks == inf:
        return "indefinite"
    if weeks < 1:
        return "~1 week"
    if weeks < 8:
        return f"{round(weeks)} weeks"
    months = weeks / 4.345
    if months < 12:
        # round to nearest 0.5
        m = round(months * 2) / 2
        return f"~{m:g} months"
    years = months / 12.0
    y = round(years * 2) / 2
    return f"~{y:g} years"


def snapshot_for_template(readiness: Readiness, axis_labels: dict[str, str]) -> dict[str, Any]:
    """Shape the readiness object for the Jinja context. Splits out
    the "above target" axes from the "needs work" axes so the template
    doesn't have to do this filtering in template code."""
    needs_work = [g for g in readiness.gaps if not g.at_target]
    at_target = [g for g in readiness.gaps if g.at_target]
    return {
        "has_data": readiness.has_data,
        "note": readiness.note,
        "unknown_axes": [
            {"axis": axis, "label": axis_labels.get(axis, axis)}
            for axis in readiness.unknown_axes
        ],
        "readiness_pct": readiness.readiness_pct,
        "readiness_pct_rounded": round(readiness.readiness_pct),
        "total_hours_needed": readiness.total_hours_needed,
        "total_hours_rounded": round(readiness.total_hours_needed),
        "needs_work": [
            {
                "axis": g.axis,
                "label": axis_labels.get(g.axis, g.axis),
                "user_score": round(g.user_score, 2),
                "jd_weight": round(g.jd_weight, 2),
                "hours_needed": round(g.hours_needed),
                "match_pct": round(g.match_pct),
                # Bar-fill percentage: how much of the JD's bar is filled by user
                "fill_pct": round(g.match_pct),
            }
            for g in needs_work
        ],
        "at_target": [
            {
                "axis": g.axis,
                "label": axis_labels.get(g.axis, g.axis),
                "user_score": round(g.user_score, 2),
                "jd_weight": round(g.jd_weight, 2),
            }
            for g in at_target
        ],
        "hours_per_tenth_point": HOURS_PER_TENTH_POINT,
        "hours_per_week_min": HOURS_PER_WEEK_MIN,
        "hours_per_week_max": HOURS_PER_WEEK_MAX,
        "hours_per_week_default": HOURS_PER_WEEK_DEFAULT,
    }
