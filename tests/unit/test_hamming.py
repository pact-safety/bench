"""Tests for app.services.hamming — weekly reflection generation."""

from __future__ import annotations

import json
from collections import Counter

from app.services import hamming


def _week_summary(**overrides) -> hamming.WeekSummary:
    """Build a sample WeekSummary with realistic-looking numbers."""
    defaults = dict(
        attempts=8, attempts_passed=5, attempts_with_hints=2,
        attempts_with_lookup=1, avg_confidence=3.2,
        weakest_axes=[("sampling_decoding", 0.33), ("eval_design", 0.5)],
        strongest_axes=[("transformer_internals", 0.9)],
        content_finished=4, content_highly_rated=["BPE paper"],
        content_low_rated=[],
        hint_phases=Counter({"plan": 3, "implement": 1}),
        writings_drafted=1, writings_published=0,
        feedback_opened=2,
    )
    defaults.update(overrides)
    return hamming.WeekSummary(**defaults)


def test_generate_with_no_api_key_returns_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = hamming.generate(_week_summary())
    assert result["method"] == "fallback"
    assert len(result["prompts"]) >= 3
    # Each fallback prompt has a label + body.
    for p in result["prompts"]:
        assert p["label"]
        assert p["prompt"]


def test_generate_with_claude_returns_claude(mock_anthropic):
    fake = {
        "summary": "Hint use leaned on Implement; data_pipeline pass rate dropped.",
        "prompts": [
            {"label": "Avoiding", "prompt": "Why did you reach for hints in implement 3 times?"},
            {"label": "Compounding", "prompt": "What habit produced the transformer-internals strength?"},
            {"label": "Biggest problem", "prompt": "What's the single biggest gap?"},
        ],
    }
    mock_anthropic.queue(json.dumps(fake))
    result = hamming.generate(_week_summary())
    assert result["method"] == "claude"
    assert "Hint use" in result["summary"]
    assert len(result["prompts"]) == 3
    assert result["prompts"][0]["label"] == "Avoiding"


def test_generate_falls_back_on_malformed_json(mock_anthropic):
    mock_anthropic.queue("not JSON")
    result = hamming.generate(_week_summary())
    assert result["method"] == "fallback"


def test_generate_falls_back_when_prompts_empty(mock_anthropic):
    mock_anthropic.queue('{"summary": "x", "prompts": []}')
    result = hamming.generate(_week_summary())
    assert result["method"] == "fallback"


def test_summarize_week_aggregates_axis_pass_rates():
    """The summarize helper computes weakest/strongest axes from attempt
    tags. Verify the math on a tiny synthetic set."""
    from app.models import Attempt, Problem
    from datetime import datetime

    p1 = _problem(id=1, tags=["transformer"])
    p2 = _problem(id=2, tags=["sampling"])
    a1 = _attempt(problem_id=1, test_passed=True)
    a2 = _attempt(problem_id=1, test_passed=True)
    a3 = _attempt(problem_id=2, test_passed=False)
    week = hamming.summarize_week(
        attempts=[a1, a2, a3],
        problem_by_id={1: p1, 2: p2},
        content_progress=[],
        writings_count_by_status={"draft": 0, "published": 0, "archived": 0},
        feedback_opened_count=0,
    )
    assert week.attempts == 3
    assert week.attempts_passed == 2
    # transformer: 2/2 = 1.0; sampling: 0/1 = 0
    weakest = dict(week.weakest_axes)
    assert weakest["sampling"] == 0.0
    strongest = dict(week.strongest_axes)
    assert strongest["transformer"] == 1.0


def _problem(*, id: int, tags: list[str]):
    from app.models import Problem
    return Problem(
        id=id, slug=f"p{id}", title=f"p{id}", difficulty="medium",
        time_bucket=30, problem_type="code_compose", is_warmup=False,
        domain_tags=tags, structural_tags=[], competency_tags=[],
        jd_signal_tags=[], content_md="", version=1, em_mode="full",
        em_prompts={}, references=[],
    )


def _attempt(*, problem_id: int, test_passed: bool):
    from datetime import datetime
    from app.models import Attempt
    return Attempt(
        id=problem_id, user_id="u", problem_id=problem_id, problem_version=1,
        started_at=datetime(2026, 5, 14), ended_at=None,
        language_used="python", final_code=None, solved_without_lookup=None,
        confidence_1_to_5=3, time_to_first_edit_seconds=None, edit_count=0,
        looked_at_solution=False, looked_at_pitfalls=False,
        test_passed=test_passed, test_output=None, notes_md=None,
    )
