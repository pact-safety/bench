"""Tests for app.services.external_capture — the URL → Claude parse
helper that pre-fills /library/add.

Network fetching is exercised via the existing _strip_tags_to_text
helper in jds.py (which has its own coverage); these tests focus on
the parse-with-Claude step: the contract of what the LLM is asked to
return, and how the service defends against malformed responses."""

from __future__ import annotations

import json

import pytest

from app.services import external_capture


# --- parse_with_claude contract ---------------------------------------------


def test_parse_with_claude_returns_filtered_axes(mock_anthropic):
    """Claude can return axes not in the allowed list — the service must
    filter them out so the form never gets junk values."""
    mock_anthropic.queue(json.dumps({
        "title": "Talent Needs of Technical AI Safety Teams",
        "source": "LessWrong",
        "axes": ["transformer_internals", "made_up_axis", "evaluation"],
        "summary_md": "Larsen-Hubinger taxonomy of iterators, amplifiers, connectors.",
    }))
    fetched = {"page_title": "raw title", "source_text": "body...", "meta": {}}
    result = external_capture.parse_with_claude(
        "https://www.lesswrong.com/posts/abc",
        fetched,
        valid_axes=["transformer_internals", "evaluation"],
    )
    assert result is not None
    assert result["axes"] == ["transformer_internals", "evaluation"]
    assert result["title"] == "Talent Needs of Technical AI Safety Teams"
    assert "Larsen-Hubinger" in result["summary_md"]


def test_parse_with_claude_caps_axes_at_four(mock_anthropic):
    """A piece could legitimately touch many axes; cap so the user
    isn't overwhelmed by checkboxes auto-flipped."""
    valid = ["a", "b", "c", "d", "e", "f"]
    mock_anthropic.queue(json.dumps({
        "title": "Wide piece",
        "source": "",
        "axes": valid,  # all six
        "summary_md": "x",
    }))
    result = external_capture.parse_with_claude("https://x", {"page_title": "", "source_text": "x"}, valid)
    assert result is not None
    assert len(result["axes"]) == 4


def test_parse_with_claude_handles_code_fence(mock_anthropic):
    """Haiku sometimes wraps JSON in ```json fences despite being asked
    not to. The service must strip those before parsing."""
    mock_anthropic.queue(
        "```json\n"
        + json.dumps({"title": "T", "source": "S", "axes": ["a"], "summary_md": "x"})
        + "\n```"
    )
    result = external_capture.parse_with_claude("https://x", {"page_title": "", "source_text": "x"}, ["a"])
    assert result is not None
    assert result["title"] == "T"


def test_parse_with_claude_returns_none_on_garbage(mock_anthropic):
    """If Claude returns prose instead of JSON, the service degrades
    gracefully (caller falls back to manual entry)."""
    mock_anthropic.queue("Sorry, I cannot process that.")
    result = external_capture.parse_with_claude("https://x", {"page_title": "", "source_text": "x"}, ["a"])
    assert result is None


def test_parse_with_claude_defends_against_missing_fields(mock_anthropic):
    """A partial JSON (missing summary or source) should still produce
    a usable dict — empty strings beat None for form pre-fill."""
    mock_anthropic.queue(json.dumps({"title": "Only Title", "axes": ["a"]}))
    result = external_capture.parse_with_claude(
        "https://x", {"page_title": "", "source_text": "x"}, ["a"]
    )
    assert result is not None
    assert result["title"] == "Only Title"
    assert result["source"] == ""
    assert result["summary_md"] == ""


# --- Reflect integration ----------------------------------------------------


def test_summarize_week_threads_external_readings():
    """The new field on WeekSummary should propagate from the
    summarize_week call so reflect.py can reference it."""
    from app.services.hamming import summarize_week

    week = summarize_week(
        attempts=[],
        problem_by_id={},
        content_progress=[],
        writings_count_by_status={},
        feedback_opened_count=0,
        external_readings=["Talent Needs — iterators vs amplifiers vs connectors..."],
    )
    assert week.external_readings == ["Talent Needs — iterators vs amplifiers vs connectors..."]


def test_summarize_week_external_readings_defaults_to_empty():
    """Backwards-compat: old callers that don't pass the kwarg still work."""
    from app.services.hamming import summarize_week

    week = summarize_week(
        attempts=[],
        problem_by_id={},
        content_progress=[],
        writings_count_by_status={},
        feedback_opened_count=0,
    )
    assert week.external_readings == []
