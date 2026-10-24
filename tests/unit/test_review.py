"""Tests for app.services.review — Claude-graded attempt review."""

from __future__ import annotations

import json

from app.services import review


def test_review_skipped_when_no_api_key(monkeypatch, sample_problem, sample_attempt):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = review.review_attempt(sample_problem, sample_attempt)
    assert result["method"] == "skipped"
    assert "ANTHROPIC_API_KEY not set" in result.get("error_text", "")


def test_review_happy_path_returns_per_phase(mock_anthropic, sample_problem, sample_attempt):
    fake_review = {
        "summary": "Tight execution; the max-subtract trick was noticed early.",
        "per_phase": {
            "plan": {
                "strength": "named the numerical-stability invariant",
                "gap": "could have written one test for all-negatives",
                "question": "what other invariants does softmax have?",
            },
        },
        "overall_score": 0.78,
    }
    mock_anthropic.queue(json.dumps(fake_review))
    result = review.review_attempt(sample_problem, sample_attempt)
    assert result["method"] == "claude"
    assert "max-subtract" in result["summary_md"]
    assert "plan" in result["per_phase"]
    assert result["per_phase"]["plan"]["strength"]
    assert 0.0 <= result["overall_score"] <= 1.0


def test_review_uses_interview_prompt_for_interview_mode(mock_anthropic, sample_problem, sample_attempt):
    """Interview-mode attempts should get the interview rubric system
    prompt (which graders against the algo-interview signals)."""
    sample_attempt.interview_mode = True
    mock_anthropic.queue(json.dumps({
        "summary": "Borderline.",
        "per_phase": {},
        "overall_score": 0.5,
        "rubric_signals": {
            "assumption_clarification": "yes",
            "multiple_approaches": "partial",
            "complexity_stated": "no",
            "plan_before_code": "yes",
            "code_quality": "ok",
            "verification": "partial",
        },
    }))
    review.review_attempt(sample_problem, sample_attempt)
    # System prompt should mention the rubric (interview prompt does).
    system = mock_anthropic.calls[0]["system"]
    assert "rubric" in system.lower() or "Algo Interviews" in system


def test_review_handles_malformed_json(mock_anthropic, sample_problem, sample_attempt):
    """No JSON in response → review service returns skipped/error,
    doesn't crash the caller."""
    mock_anthropic.queue("Sorry, I'm just a chatty model today.")
    result = review.review_attempt(sample_problem, sample_attempt)
    assert result["method"] in ("skipped", "fallback")
