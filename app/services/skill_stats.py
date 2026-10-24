"""Five high-level stats consolidated from the 13 assessment axes.

A radar/pentagon reads cleanly with 5-6 vertices; 13 axes looks like
noise. Each stat is a weighted mean of related axes.

Stat groupings (kept stable — the scheduler and any future feature
should reference these names if/when stats become first-class):

- TRANSFORMER: transformer_internals + numerical_stability + mechanistic_interpretability
- TRAINING:    training_mechanics + debugging
- DECODING:    sampling_decoding + tokenization
- EVAL/DATA:   eval_design + data_pipeline + ai_safety_fundamentals + ai_governance_strategy
- SYSTEMS:     algorithmic + rust_fluency

Geometry is also computed here so the template doesn't have to do trig.

Design notes:
- Tier-based badge coloring (strong / mid / weak) is the headline
  signal — the user wants to know "where am I weak?" at a glance.
  Per-stat hues fragmented the chart; tiers unify it.
- Stem lines from each data vertex out to the badge make the
  badge-to-data correspondence explicit.
- The top spoke carries numeric tick labels (25/50/75/100) so the
  polygon size is readable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Stat:
    key: str
    label: str
    axes: tuple[str, ...]


STATS: tuple[Stat, ...] = (
    Stat(
        "transformer",
        "TRANSFORMER",
        ("transformer_internals", "numerical_stability", "mechanistic_interpretability"),
    ),
    Stat("training",    "TRAINING",    ("training_mechanics", "debugging")),
    Stat("decoding",    "DECODING",    ("sampling_decoding", "tokenization")),
    Stat(
        "eval_data",
        "EVAL/DATA",
        ("eval_design", "data_pipeline", "ai_safety_fundamentals", "ai_governance_strategy"),
    ),
    Stat("systems",     "SYSTEMS",     ("algorithmic", "rust_fluency")),
)


@dataclass(frozen=True)
class StatPoint:
    key: str
    label: str
    score: float | None    # 0..1, or unknown when no axes were measured
    pct: int | None        # rounded percent for display
    tier: str              # "weak" | "mid" | "strong" | "unknown"
    measured: bool
    vertex_x: float        # outer pentagon corner (100% radius)
    vertex_y: float
    value_x: float         # data point at this stat's score
    value_y: float
    badge_x: float         # circular label center
    badge_y: float
    stem_x: float          # where the stem line starts (at the rim of the badge)
    stem_y: float


@dataclass(frozen=True)
class PentagonGeometry:
    view_w: int
    view_h: int
    center_x: float
    center_y: float
    plot_r: float
    points: tuple[StatPoint, ...]
    value_polygon: str
    outline_polygon: str
    grid_polygons: tuple[tuple[float, str], ...]  # (radius_fraction, points_attr)
    axis_lines: tuple[tuple[float, float, float, float], ...]
    tick_labels: tuple[tuple[float, float, str], ...]  # (x, y, text) at the top spoke


# Viewport sized so the top badge has visual breathing room above it
# and the bottom badges have room below. Original 520-tall viewBox
# clipped the TRANSFORMER badge's top rim at y=-17.
_VIEW_W = 560
_VIEW_H = 580
_CX = 280
_CY = 290
_PLOT_R = 130
_BADGE_R = 215
_BADGE_RADIUS = 42  # the circle radius around each badge


def _tier(score: float) -> str:
    if score >= 0.66:
        return "strong"
    if score >= 0.33:
        return "mid"
    return "weak"


def _angle_for(idx: int) -> float:
    return math.radians(-90 + idx * (360.0 / len(STATS)))


def compute_stats(axis_scores: dict[str, float]) -> list[StatPoint]:
    out: list[StatPoint] = []
    for idx, stat in enumerate(STATS):
        vals = [axis_scores[a] for a in stat.axes if a in axis_scores]
        score = max(0.0, min(1.0, sum(vals) / len(vals))) if vals else None
        ang = _angle_for(idx)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        vx = _CX + _PLOT_R * cos_a
        vy = _CY + _PLOT_R * sin_a
        valx = _CX + _PLOT_R * (score or 0.0) * cos_a
        valy = _CY + _PLOT_R * (score or 0.0) * sin_a
        bx = _CX + _BADGE_R * cos_a
        by = _CY + _BADGE_R * sin_a
        # Stem starts at the inner rim of the badge (toward center).
        stem_x = bx - _BADGE_RADIUS * cos_a
        stem_y = by - _BADGE_RADIUS * sin_a
        out.append(StatPoint(
            key=stat.key,
            label=stat.label,
            score=score,
            pct=round(score * 100) if score is not None else None,
            tier=_tier(score) if score is not None else "unknown",
            measured=score is not None,
            vertex_x=vx, vertex_y=vy,
            value_x=valx, value_y=valy,
            badge_x=bx, badge_y=by,
            stem_x=stem_x, stem_y=stem_y,
        ))
    return out


def _polygon_points(coords: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)


def pentagon_geometry(axis_scores: dict[str, float]) -> PentagonGeometry:
    points = compute_stats(axis_scores)
    outline_coords = [(p.vertex_x, p.vertex_y) for p in points]
    # A closed polygon would invent zeroes for missing groups. Partial
    # coverage is shown with only the measured points and their stems.
    value_coords = [(p.value_x, p.value_y) for p in points] if all(p.measured for p in points) else []

    # Concentric rings at 25 / 50 / 75 — also expressed as the fraction
    # so the template can decide saturation per ring.
    fractions = (0.25, 0.50, 0.75)
    grid: list[tuple[float, str]] = []
    for f in fractions:
        ring = []
        for idx in range(len(STATS)):
            ang = _angle_for(idx)
            ring.append((_CX + _PLOT_R * f * math.cos(ang), _CY + _PLOT_R * f * math.sin(ang)))
        grid.append((f, _polygon_points(ring)))

    axis_lines = tuple(
        (_CX, _CY, p.vertex_x, p.vertex_y) for p in points
    )

    # Tick labels along the TOP spoke (which goes from center upward).
    # Only 50 and 100 are labeled; 25/75 grid is implicit. The labels
    # sit slightly to the right of the spoke so they don't overlap it.
    top_ang = _angle_for(0)
    cos_a = math.cos(top_ang)
    sin_a = math.sin(top_ang)
    tick_labels = (
        (_CX + _PLOT_R * 0.50 * cos_a + 8, _CY + _PLOT_R * 0.50 * sin_a + 4, "50"),
        (_CX + _PLOT_R * 1.00 * cos_a + 8, _CY + _PLOT_R * 1.00 * sin_a + 4, "100"),
    )

    return PentagonGeometry(
        view_w=_VIEW_W,
        view_h=_VIEW_H,
        center_x=_CX,
        center_y=_CY,
        plot_r=_PLOT_R,
        points=tuple(points),
        value_polygon=_polygon_points(value_coords),
        outline_polygon=_polygon_points(outline_coords),
        grid_polygons=tuple(grid),
        axis_lines=axis_lines,
        tick_labels=tick_labels,
    )


VIEW_W = _VIEW_W
VIEW_H = _VIEW_H
