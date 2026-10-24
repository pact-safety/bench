"""BEN-135 recitation schedule — the successive-relearning ladder.

Pins the two rules that make the loop work: a held concept advances
+1 → +7 → +30, and a miss resets to +1 (returns sooner). Plus the
pretest guarantee: blanking a pretest leaves no penalty state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import recitation_schedule as rs

_NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def test_ladder_advances_1_7_30_and_caps():
    assert rs.advance_interval(None) == 1
    assert rs.advance_interval(1) == 7
    assert rs.advance_interval(7) == 30
    assert rs.advance_interval(30) == 30  # caps at the top rung


def test_miss_resets_to_plus_one():
    # A concept sitting at +30 that gets missed drops all the way to +1.
    assert rs.interval_after(30, missed=True) == 1
    # A hold at +1 advances to +7.
    assert rs.interval_after(1, missed=False) == 7


def test_apply_grade_missed_concept_returns_sooner():
    state = {"attention mask": {"interval_days": 30, "due_at": rs._iso(_NOW), "misses": 0}}
    out = rs.apply_grade(state, covered=[], missing=["attention mask"], now=_NOW)
    entry = out["attention mask"]
    assert entry["interval_days"] == 1  # reset
    due = datetime.fromisoformat(entry["due_at"])
    assert abs((due - (_NOW + timedelta(days=1))).total_seconds()) < 2


def test_apply_grade_covered_concept_advances():
    state = {"softmax": {"interval_days": 1, "due_at": rs._iso(_NOW), "misses": 0}}
    out = rs.apply_grade(state, covered=["softmax"], missing=[], now=_NOW)
    assert out["softmax"]["interval_days"] == 7


def test_pretest_records_no_penalty_state():
    """Blanking a pretest is the expected result — it must schedule the
    concept (retention benefit) but leave misses at 0 (no penalty)."""
    out = rs.apply_grade(
        {}, covered=[], missing=["layernorm", "rmsnorm"], now=_NOW, pretest=True
    )
    for concept in ("layernorm", "rmsnorm"):
        assert out[concept]["interval_days"] == 1
        assert out[concept]["misses"] == 0  # no penalty recorded


def test_due_concepts_only_returns_past_due_soonest_first():
    state = {
        "a": {"due_at": rs._iso(_NOW - timedelta(days=2))},
        "b": {"due_at": rs._iso(_NOW - timedelta(days=1))},
        "future": {"due_at": rs._iso(_NOW + timedelta(days=5))},
    }
    assert rs.due_concepts(state, _NOW) == ["a", "b"]


def test_apply_grade_does_not_mutate_input():
    state = {"x": {"interval_days": 7, "due_at": rs._iso(_NOW), "misses": 1}}
    rs.apply_grade(state, covered=[], missing=["x"], now=_NOW)
    assert state["x"]["interval_days"] == 7  # original untouched
