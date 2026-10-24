from types import SimpleNamespace

from app.services import assessment as assess


def test_measured_zero_is_kept_and_unmeasured_defaults_are_omitted():
    responses = [SimpleNamespace(
        question_id=assess.Q_CALIBRATION.id,
        axis_scores=assess.Q_CALIBRATION.options[-1].scores,
    )]
    saved = assess.aggregate_scores(responses)
    assert set(saved) == set(assess.AXES)
    assert assess.measured_axes(responses) == (
        "transformer_internals", "training_mechanics", "debugging",
    )
    assert assess.measured_scores(saved, responses) == {
        "transformer_internals": 0.0, "training_mechanics": 0.0, "debugging": 0.0,
    }


def test_historical_coverage_uses_saved_evidence_and_preserves_saved_scores():
    responses = [SimpleNamespace(
        question_id="retired-question", axis_scores={"eval_design": 0, "old_axis": 3},
    )]
    saved = {axis: 0.0 for axis in assess.AXES}
    saved["eval_design"] = 0.25
    assert assess.measured_axes(responses) == ("eval_design",)
    assert assess.measured_scores(saved, responses) == {"eval_design": 0.25}
    assert len(saved) == len(assess.AXES)


def test_scores_without_response_evidence_are_unknown():
    assert assess.measured_scores({"debugging": 0.0}, []) == {}
    assert assess.measured_scores({}, [SimpleNamespace(
        question_id="old-question", axis_scores={"debugging": 0},
    )]) == {}


def test_duplicate_answers_do_not_expand_coverage():
    responses = [
        SimpleNamespace(question_id="old-question", axis_scores={"debugging": 0}),
        SimpleNamespace(question_id="old-question", axis_scores={"eval_design": 3}),
    ]
    assert assess.measured_axes(responses) == ("debugging",)


def test_weakest_axis_uses_only_measured_axes_with_exercises():
    axis = assess.weakest_axis({"ai_safety_fundamentals": 0.0, "debugging": 0.5})
    assert axis == "debugging"
    assert assess.suggested_slugs_for_axis(axis)
    assert assess.weakest_axis({"debugging": 0.0, "eval_design": 1.0}) == "debugging"
    assert assess.weakest_axis({"ai_safety_fundamentals": 0.0}) is None
    assert assess.weakest_axis({}) is None


def test_mode_uses_measured_scores_including_measured_zero():
    assert assess.recommended_daily_mode({"debugging": 0.8}) == "remix"
    assert assess.recommended_daily_mode({"debugging": 0.8, "eval_design": 0.0}) == "path"
