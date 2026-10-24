"""Tests for app.services.readiness — the gap-analysis math behind
the /readiness page.

These pin down the boundary cases that aren't intuitive:
  - empty assessment or empty JD weights → has_data=False, not 0%
  - axes the JD doesn't weight don't drag the readiness number
  - user above JD target → axis contributes 100% to readiness, 0 hrs
  - duration formatting in human English

Calibration constants are imported so the tests stay stable across
future tweaks to the hours-per-axis-point heuristic."""

from __future__ import annotations

import math

import pytest

from app.services import readiness as r


# --- compute() boundary cases ----------------------------------------------


def test_no_scores_returns_no_data():
    out = r.compute(user_scores={}, jd_axis_weights={"transformer_internals": 0.8}, axes=("transformer_internals",))
    assert out.has_data is False
    assert "assessment" in (out.note or "").lower()


def test_no_jd_weights_returns_no_data():
    out = r.compute(user_scores={"transformer_internals": 0.5}, jd_axis_weights={}, axes=("transformer_internals",))
    assert out.has_data is False
    assert "jd" in (out.note or "").lower()


def test_all_jd_weights_zero_returns_no_data():
    """A JD parse that returned zeros everywhere is functionally
    equivalent to no JD — would yield meaningless 100% match."""
    out = r.compute(
        user_scores={"transformer_internals": 0.5},
        jd_axis_weights={"transformer_internals": 0.0, "debugging": 0.0},
        axes=("transformer_internals", "debugging"),
    )
    assert out.has_data is False


# --- compute() correctness on toy data --------------------------------------


def test_user_above_target_yields_zero_gap():
    """If the user's score exceeds the JD weight, hours_needed is 0
    and that axis contributes 100% to the readiness pct."""
    out = r.compute(
        user_scores={"transformer_internals": 0.9},
        jd_axis_weights={"transformer_internals": 0.5},
        axes=("transformer_internals",),
    )
    assert out.has_data
    assert out.total_hours_needed == 0.0
    assert out.readiness_pct == 100.0
    assert out.gaps[0].at_target is True


def test_axes_jd_doesnt_weight_are_ignored():
    """Rust score shouldn't drag interpretability readiness."""
    out = r.compute(
        user_scores={"transformer_internals": 0.6, "rust_fluency": 0.0},
        jd_axis_weights={"transformer_internals": 0.6, "rust_fluency": 0.0},
        axes=("transformer_internals", "rust_fluency"),
    )
    assert out.has_data
    # readiness only computed against transformer_internals; rust skipped
    assert len(out.gaps) == 1
    assert out.gaps[0].axis == "transformer_internals"


def test_partial_gap_produces_hours_proportional_to_gap():
    """User 0.3, JD wants 0.6 → 0.3 axis-points → 36 hrs at default rate (12 hrs/0.1)."""
    out = r.compute(
        user_scores={"debugging": 0.3},
        jd_axis_weights={"debugging": 0.6},
        axes=("debugging",),
    )
    assert out.has_data
    assert out.gaps[0].at_target is False
    # 0.3 gap × 10 × 12 = 36 hrs
    assert out.gaps[0].hours_needed == pytest.approx(36.0)
    assert out.total_hours_needed == pytest.approx(36.0)
    # match_pct: 0.3/0.6 = 50%
    assert out.gaps[0].match_pct == pytest.approx(50.0)


def test_weighted_readiness_is_jd_weight_weighted():
    """Two axes with different JD weights — readiness should weight
    by JD importance, not just average."""
    out = r.compute(
        user_scores={"transformer_internals": 1.0, "debugging": 0.0},
        # transformer weighted heavily, debugging lightly
        jd_axis_weights={"transformer_internals": 0.8, "debugging": 0.2},
        axes=("transformer_internals", "debugging"),
    )
    # transformer: 100% match × 0.8 weight = 0.8
    # debugging:    0% match × 0.2 weight = 0.0
    # total weight = 1.0
    # readiness = 0.8 / 1.0 = 80%
    assert out.readiness_pct == pytest.approx(80.0)


def test_gaps_sorted_by_hours_descending():
    """Largest gap surfaces first — drives focus."""
    out = r.compute(
        user_scores={"a": 0.1, "b": 0.4, "c": 0.7},
        jd_axis_weights={"a": 0.8, "b": 0.5, "c": 0.8},
        axes=("a", "b", "c"),
    )
    hours = [g.hours_needed for g in out.gaps]
    assert hours == sorted(hours, reverse=True)


# --- weeks_to_ready + format_duration --------------------------------------


def test_weeks_to_ready_simple():
    assert r.weeks_to_ready(40, 10) == 4.0


def test_weeks_to_ready_zero_hours_returns_zero():
    assert r.weeks_to_ready(0, 10) == 0.0


def test_weeks_to_ready_zero_per_week_is_infinite():
    assert math.isinf(r.weeks_to_ready(40, 0))


def test_format_duration_weeks():
    assert r.format_duration(0) == "already there"
    assert r.format_duration(1) == "1 weeks"  # uses "weeks" plural for simplicity
    assert r.format_duration(4) == "4 weeks"
    assert r.format_duration(7) == "7 weeks"


def test_format_duration_months():
    assert "months" in r.format_duration(10)   # 10 weeks ≈ 2.3 months
    assert "months" in r.format_duration(20)   # 20 weeks ≈ 4.6 months


def test_format_duration_years():
    assert "years" in r.format_duration(60)    # 60 weeks ≈ 13.8 months → years


# --- snapshot_for_template ------------------------------------------------


def test_snapshot_separates_needs_work_from_at_target():
    readiness = r.compute(
        user_scores={"a": 0.9, "b": 0.2},
        jd_axis_weights={"a": 0.5, "b": 0.6},
        axes=("a", "b"),
    )
    snap = r.snapshot_for_template(readiness, axis_labels={"a": "Axis A", "b": "Axis B"})
    assert snap["has_data"]
    assert len(snap["needs_work"]) == 1
    assert snap["needs_work"][0]["axis"] == "b"
    assert len(snap["at_target"]) == 1
    assert snap["at_target"][0]["axis"] == "a"


def test_unknown_jd_axis_does_not_invent_a_gap_or_dilute_match():
    out = r.compute(user_scores={"debugging": 0.3},
                    jd_axis_weights={"debugging": 0.6, "algorithmic": 0.9},
                    axes=("debugging", "algorithmic", "rust_fluency"))
    assert out.has_data
    assert out.readiness_pct == pytest.approx(50.0)
    assert out.total_hours_needed == pytest.approx(36.0)
    assert [g.axis for g in out.gaps] == ["debugging"]
    assert out.unknown_axes == ("algorithmic",)
    snapshot = r.snapshot_for_template(out, {"algorithmic": "Algorithmic"})
    assert snapshot["unknown_axes"] == [{"axis": "algorithmic", "label": "Algorithmic"}]


def test_assessed_zero_stays_in_scenario_while_unknown_axis_is_excluded():
    out = r.compute(user_scores={"debugging": 0.0},
                    jd_axis_weights={"debugging": 0.6, "algorithmic": 0.9},
                    axes=("debugging", "algorithmic"))
    assert out.has_data
    assert out.readiness_pct == 0.0
    assert out.total_hours_needed == pytest.approx(72.0)
    assert len(out.gaps) == 1
    assert out.gaps[0].user_score == 0.0
    assert out.unknown_axes == ("algorithmic",)


@pytest.mark.parametrize("scores", [{}, {"rust_fluency": 0.8}])
def test_no_assessed_jd_axes_retains_unknown_coverage_without_a_scenario(scores):
    out = r.compute(user_scores=scores, jd_axis_weights={"algorithmic": 0.9},
                    axes=("algorithmic", "rust_fluency"))
    assert not out.has_data
    assert out.gaps == []
    assert out.unknown_axes == ("algorithmic",)
    assert out.total_hours_needed == 0
    assert "assessment" in out.note.lower()
    assert "JD" in out.note
    assert r.snapshot_for_template(out, {})["unknown_axes"] == [
        {"axis": "algorithmic", "label": "algorithmic"}]


def test_jd_weights_outside_supported_axes_do_not_create_empty_scenario():
    out = r.compute(user_scores={"debugging": 0.5}, jd_axis_weights={"obsolete": 0.9},
                    axes=("debugging",))
    assert not out.has_data
    assert "JD" in out.note
