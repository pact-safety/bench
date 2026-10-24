"""Coverage checks for skill stat grouping."""

from __future__ import annotations

from app.services import assessment as assess_service
from app.services import skill_stats


def test_stats_axes_cover_all_assessment_axes():
    stats_axes = {axis for stat in skill_stats.STATS for axis in stat.axes}
    assessment_axes = set(assess_service.AXES)
    assert stats_axes == assessment_axes


def test_partial_groups_average_only_measured_axes():
    points = {point.key: point for point in skill_stats.compute_stats({
        "transformer_internals": 1.0, "numerical_stability": 0.0,
        "eval_design": 1.0,
    })}
    assert points["transformer"].score == 0.5
    assert points["eval_data"].score == 1.0
    assert points["eval_data"].measured


def test_unmeasured_groups_are_distinct_from_measured_zero():
    points = {point.key: point for point in skill_stats.compute_stats({"debugging": 0.0})}
    assert points["training"].measured
    assert points["training"].score == 0.0
    assert points["training"].pct == 0
    assert points["training"].tier == "weak"
    assert not points["systems"].measured
    assert points["systems"].score is None
    assert points["systems"].pct is None
    assert points["systems"].tier == "unknown"


def test_unknown_groups_do_not_create_zero_polygon_vertices():
    assert skill_stats.pentagon_geometry({"debugging": 0.0}).value_polygon == ""
    assert skill_stats.pentagon_geometry({}).value_polygon == ""
    geometry = skill_stats.pentagon_geometry({axis: 0.0 for axis in assess_service.AXES})
    assert geometry.value_polygon
    assert len(geometry.points) == 5
