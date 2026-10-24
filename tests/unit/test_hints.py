"""Tests for app.services.hints.

These would have caught the `problem.prompt_md` AttributeError that
made the entire hint ladder fall back to canned text. The pattern:
exercise `claude_hint()` with a real Problem dataclass + mocked
Anthropic client; assert the call shape and the parsed result.
"""

from __future__ import annotations

import json

from app.services import hints


def test_tier_for_count():
    assert hints.tier_for(0) == 1
    assert hints.tier_for(1) == 2
    assert hints.tier_for(2) == 3
    # Capped at MAX_TIER for any further requests.
    assert hints.tier_for(3) == 3
    assert hints.tier_for(99) == 3


def test_is_exhausted():
    assert not hints.is_exhausted(0)
    assert not hints.is_exhausted(2)
    assert hints.is_exhausted(3)
    assert hints.is_exhausted(99)


def test_fallback_hint_per_phase():
    """Each known phase has a generic process nudge."""
    for phase in ("explore", "brainstorm", "plan", "implement", "verify"):
        r = hints.fallback_hint(phase, 0)
        assert r["method"] == "fallback"
        assert r["tier"] == 1
        assert r["hint"]
        assert not r["exhausted"]


def test_fallback_hint_exhausted_message():
    r = hints.fallback_hint("plan", 3)
    assert r["exhausted"] is True
    assert "end of the hint ladder" in r["hint"]


def test_claude_hint_real_attribute_access(mock_anthropic, sample_problem):
    """REGRESSION: previously `claude_hint` read `problem.prompt_md`,
    which doesn't exist on the Problem dataclass. The AttributeError
    was swallowed by `get_hint`'s try/except and every request silently
    fell back. This test would have caught that on the first run."""
    mock_anthropic.queue('{"hint": "What invariant holds when you transpose?", "tier": 1}')
    result = hints.claude_hint(
        problem=sample_problem,
        phase="plan",
        current_notes="thinking about it",
        code=None,
        count_so_far=0,
    )
    assert result["method"] == "claude"
    assert result["hint"] == "What invariant holds when you transpose?"
    assert result["tier"] == 1
    # Verify Claude was actually called once with the right model.
    assert len(mock_anthropic.calls) == 1
    call = mock_anthropic.calls[0]
    assert "haiku" in call["model"]  # default is claude-haiku-4-5-20251001
    # The user message should include the problem prompt text — proving
    # we read the right attribute off Problem.
    user_msg = call["messages"][0]["content"]
    assert "numerically-stable softmax" in user_msg


def test_claude_hint_passes_prior_hints(mock_anthropic, sample_problem):
    """Prior hints must be sent to Claude so escalation works."""
    mock_anthropic.queue('{"hint": "Mask before softmax, not after.", "tier": 2}')
    hints.claude_hint(
        problem=sample_problem,
        phase="plan",
        current_notes="",
        code=None,
        count_so_far=1,
        prior_hints=["What invariant holds when you transpose?"],
    )
    call = mock_anthropic.calls[0]
    # The payload (in user_msg) must mention the prior hints array.
    user_msg = call["messages"][0]["content"]
    assert "What invariant" in user_msg


def test_claude_hint_tier_escalates_with_count(mock_anthropic, sample_problem):
    """count_so_far=2 should request tier 3 (scaffolding)."""
    mock_anthropic.queue('{"hint": "Look at masked_fill(mask, float(\\"-inf\\"))", "tier": 3}')
    r = hints.claude_hint(
        problem=sample_problem,
        phase="implement",
        current_notes="",
        code="def attn(): pass",
        count_so_far=2,
    )
    assert r["tier"] == 3
    assert r["tier_label"] == "scaffolding"


def test_claude_hint_implement_includes_code(mock_anthropic, sample_problem):
    """For implement / verify phases we send the code snippet too."""
    mock_anthropic.queue('{"hint": "Check your axis arg", "tier": 1}')
    hints.claude_hint(
        problem=sample_problem,
        phase="implement",
        current_notes="",
        code="def softmax(x): return x",
        count_so_far=0,
    )
    user_msg = mock_anthropic.calls[0]["messages"][0]["content"]
    assert "return x" in user_msg


def test_claude_hint_explore_omits_code(mock_anthropic, sample_problem):
    """Explore + Brainstorm + Plan don't need the code — should be
    None or absent in the payload."""
    mock_anthropic.queue('{"hint": "What\'s invariant?", "tier": 1}')
    hints.claude_hint(
        problem=sample_problem,
        phase="explore",
        current_notes="",
        code="this should NOT appear in payload",
        count_so_far=0,
    )
    user_msg = mock_anthropic.calls[0]["messages"][0]["content"]
    assert "this should NOT appear" not in user_msg


def test_claude_hint_raises_on_no_json(mock_anthropic, sample_problem):
    """Claude returned text with no JSON object — we raise so the
    caller (get_hint) falls back."""
    mock_anthropic.queue("Sorry, I'm not sure what you mean.")
    import pytest
    with pytest.raises(ValueError, match="no JSON"):
        hints.claude_hint(
            problem=sample_problem, phase="plan", current_notes="",
            code=None, count_so_far=0,
        )


def test_get_hint_falls_back_when_no_api_key(monkeypatch, sample_problem):
    """No ANTHROPIC_API_KEY → fallback path, no LLM call attempted."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = hints.get_hint(
        problem=sample_problem, phase="plan", current_notes="",
        code=None, count_so_far=0,
    )
    assert r["method"] == "fallback"


def test_get_hint_falls_back_on_claude_exception(mock_anthropic, sample_problem):
    """Claude raised → get_hint catches → fallback returned."""
    # Queue a response that fails parsing (no JSON).
    mock_anthropic.queue("not JSON")
    r = hints.get_hint(
        problem=sample_problem, phase="plan", current_notes="",
        code=None, count_so_far=0,
    )
    assert r["method"] == "fallback"


def test_get_hint_returns_claude_when_happy(mock_anthropic, sample_problem):
    mock_anthropic.queue('{"hint": "good hint", "tier": 1}')
    r = hints.get_hint(
        problem=sample_problem, phase="plan", current_notes="",
        code=None, count_so_far=0,
    )
    assert r["method"] == "claude"
    assert r["hint"] == "good hint"


def test_get_hint_invalid_phase_returns_safe_message(mock_anthropic, sample_problem):
    r = hints.get_hint(
        problem=sample_problem, phase="nonsense", current_notes="",
        code=None, count_so_far=0,
    )
    assert r["method"] == "fallback"
    assert "Unknown phase" in r["hint"]
