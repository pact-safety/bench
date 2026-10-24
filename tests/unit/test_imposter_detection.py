from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import imposter as i


def test_detect_no_answers_and_no_credentials_returns_none_state():
    signal = i.detect(
        quiz_answers=[],
        assessment_scores={},
        credential_scores=None,
    )

    assert signal.state == "none"
    assert signal.not_sure_rate == 0.0
    assert signal.credential_gap is None
    assert signal.triggering_axes == []


def test_detect_all_yes_with_balanced_credentials_is_none_gap_zero():
    signal = i.detect(
        quiz_answers=["yes", "yes", "yes"],
        assessment_scores={"ml": 0.7, "stats": 0.6},
        credential_scores={"ml": 0.7, "stats": 0.6},
    )

    assert signal.state == "none"
    assert signal.not_sure_rate == 0.0
    assert signal.credential_gap == pytest.approx(0.0)
    assert signal.triggering_axes == []


def test_detect_half_not_sure_and_no_credentials_is_mild():
    signal = i.detect(
        quiz_answers=["not_sure", "yes", "no", "unsure"],
        assessment_scores={},
        credential_scores=None,
    )

    assert signal.not_sure_rate == pytest.approx(0.5)
    assert signal.state == "mild"
    assert signal.credential_gap is None


def test_detect_three_quarters_not_sure_and_no_credentials_is_strong():
    signal = i.detect(
        quiz_answers=["not_sure", "not_sure", "yes", "not_sure"],
        assessment_scores={},
        credential_scores=None,
    )

    assert signal.not_sure_rate == pytest.approx(0.75)
    assert signal.state == "strong"


def test_detect_balanced_quiz_and_mean_gap_point_25_is_mild_with_triggers():
    signal = i.detect(
        quiz_answers=["yes", "no", "yes", "no"],
        assessment_scores={"axis_a": 0.5, "axis_b": 0.3},
        credential_scores={"axis_a": 0.8, "axis_b": 0.5},
    )

    assert signal.state == "mild"
    assert signal.credential_gap == pytest.approx(0.25)
    assert signal.triggering_axes == ["axis_a", "axis_b"]


def test_detect_balanced_quiz_and_mean_gap_point_40_is_strong():
    signal = i.detect(
        quiz_answers=["yes", "yes", "no", "no"],
        assessment_scores={"axis_a": 0.1, "axis_b": 0.2},
        credential_scores={"axis_a": 0.5, "axis_b": 0.6},
    )

    assert signal.state == "strong"
    assert signal.credential_gap == pytest.approx(0.4)


def test_detect_combined_strong_not_sure_and_gap_is_strong_not_multiplied():
    signal = i.detect(
        quiz_answers=["not_sure", "not_sure", "not_sure", "yes"],
        assessment_scores={"axis_a": 0.2, "axis_b": 0.4},
        credential_scores={"axis_a": 0.6, "axis_b": 0.8},
    )

    assert signal.not_sure_rate == pytest.approx(0.75)
    assert signal.credential_gap == pytest.approx(0.4)
    assert signal.state == "strong"


def test_detect_negative_credential_gap_does_not_raise_signal_state():
    signal = i.detect(
        quiz_answers=["not_sure", "yes"],
        assessment_scores={"axis_a": 0.8, "axis_b": 0.6},
        credential_scores={"axis_a": 0.4, "axis_b": 0.3},
    )

    assert signal.not_sure_rate == pytest.approx(0.5)
    assert signal.credential_gap == pytest.approx(-0.35)
    assert signal.triggering_axes == []
    assert signal.state == "mild"


def test_detect_normalizes_not_sure_variants():
    signal = i.detect(
        quiz_answers=["Not Sure", "not-sure", "unsure", "yes"],
        assessment_scores={},
        credential_scores=None,
    )

    assert signal.not_sure_rate == pytest.approx(0.75)
    assert signal.state == "strong"


def test_detect_triggering_axes_sorted_by_gap_and_threshold_filtered():
    signal = i.detect(
        quiz_answers=["yes"],
        assessment_scores={"axis_a": 0.2, "axis_b": 0.2, "axis_c": 0.2},
        credential_scores={"axis_a": 0.6, "axis_b": 0.5, "axis_c": 0.35},
        per_axis_gap=0.2,
    )

    # gaps: axis_a=0.40, axis_b=0.30, axis_c=0.15
    assert signal.triggering_axes == ["axis_a", "axis_b"]


def test_detect_with_no_overlapping_axes_reports_gap_none():
    signal = i.detect(
        quiz_answers=["yes", "no"],
        assessment_scores={"axis_a": 0.2},
        credential_scores={"axis_b": 0.8},
    )

    assert signal.credential_gap is None
    assert signal.triggering_axes == []
    assert signal.state == "none"


def test_as_dict_rounds_values_and_serializes_datetime_iso():
    now = datetime(2026, 5, 18, 9, 44, 14)
    signal = i.ImposterSignal(
        state="mild",
        not_sure_rate=0.6666,
        credential_gap=0.23456,
        triggering_axes=["axis_b", "axis_a"],
        detected_at=now,
    )

    assert signal.as_dict() == {
        "state": "mild",
        "not_sure_rate": 0.667,
        "credential_gap": 0.235,
        "triggering_axes": ["axis_b", "axis_a"],
        "detected_at": "2026-05-18T09:44:14",
    }


def test_detect_state_none_keeps_detected_at_none_even_when_now_provided():
    now = datetime(2026, 5, 18, 10, 5, 0)

    signal = i.detect(
        quiz_answers=["yes", "no", "yes", "no"],
        assessment_scores={},
        credential_scores=None,
        now=now,
    )

    assert signal.state == "none"
    assert signal.detected_at is None


@pytest.mark.parametrize(
    ("quiz_answers", "expected_state"),
    [
        (["not_sure", "yes", "no", "unsure"], "mild"),
        (["not_sure", "not_sure", "yes", "not_sure"], "strong"),
    ],
)
def test_detect_mild_or_strong_uses_provided_now_for_detected_at(
    quiz_answers: list[str], expected_state: str
):
    now = datetime(2026, 5, 18, 10, 6, 0)

    signal = i.detect(
        quiz_answers=quiz_answers,
        assessment_scores={},
        credential_scores=None,
        now=now,
    )

    assert signal.state == expected_state
    assert signal.detected_at == now


@pytest.mark.parametrize(
    ("quiz_answers", "expected_state"),
    [
        (["not_sure", "yes", "no", "unsure"], "mild"),
        (["not_sure", "not_sure", "yes", "not_sure"], "strong"),
    ],
)
def test_detect_mild_or_strong_without_now_keeps_detected_at_none(
    quiz_answers: list[str], expected_state: str
):
    signal = i.detect(
        quiz_answers=quiz_answers,
        assessment_scores={},
        credential_scores=None,
    )

    assert signal.state == expected_state
    assert signal.detected_at is None


def test_maybe_decay_sets_state_none_when_mastery_threshold_met():
    settings = {
        "imposter_signal": {
            "state": "strong",
            "not_sure_rate": 0.75,
            "credential_gap": 0.4,
            "triggering_axes": ["debugging"],
        }
    }
    attempts = [
        SimpleNamespace(solved_without_lookup=True, confidence_1_to_5=4)
        for _ in range(5)
    ]
    now = datetime(2026, 5, 18, 11, 0, 0)

    changed = i.maybe_decay(settings, attempts, now=now)

    assert changed is True
    assert settings["imposter_signal"]["state"] == "none"
    assert settings["imposter_signal"]["decayed_at"] == "2026-05-18T11:00:00"


def test_maybe_decay_leaves_signal_when_mastery_threshold_not_met():
    settings = {
        "imposter_signal": {
            "state": "mild",
            "not_sure_rate": 0.5,
            "credential_gap": None,
            "triggering_axes": [],
        }
    }
    attempts = [
        SimpleNamespace(solved_without_lookup=True, confidence_1_to_5=4)
        for _ in range(4)
    ]

    changed = i.maybe_decay(settings, attempts)

    assert changed is False
    assert settings["imposter_signal"]["state"] == "mild"
