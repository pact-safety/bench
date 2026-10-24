"""Tests for app.services.initiative_picker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.initiative_picker import (
    UnknownInitiativeError,
    resolve_initiative_slug,
)


def _init(slug: str, status: str = "active"):
    return SimpleNamespace(slug=slug, status=status)


_BENCH = _init("bench")
_CAPSTONE = _init("capstone")
_LEGAL = _init("legal")
_DONE_FELLOWS = _init("anthropic-fellows", status="done")
_DORMANT_CONTENT = _init("content", status="dormant")
_ALL = [_BENCH, _CAPSTONE, _LEGAL, _DONE_FELLOWS, _DORMANT_CONTENT]


# ---------------------------------------------------------------------------
# Precedence: explicit form override wins
# ---------------------------------------------------------------------------


def test_form_override_wins_over_settings():
    out = resolve_initiative_slug(
        settings={"active_initiative": "bench"},
        form_override="capstone",
        initiatives=_ALL,
    )
    assert out == "capstone"


def test_form_override_empty_string_is_treated_as_no_override():
    out = resolve_initiative_slug(
        settings={"active_initiative": "bench"},
        form_override="",
        initiatives=_ALL,
    )
    assert out == "bench"


def test_form_override_whitespace_only_is_treated_as_no_override():
    out = resolve_initiative_slug(
        settings={"active_initiative": "bench"},
        form_override="   ",
        initiatives=_ALL,
    )
    assert out == "bench"


def test_form_override_strips_whitespace_before_matching():
    out = resolve_initiative_slug(
        settings={},
        form_override="  bench  ",
        initiatives=_ALL,
    )
    assert out == "bench"


# ---------------------------------------------------------------------------
# Fallback to settings.active_initiative
# ---------------------------------------------------------------------------


def test_fallback_to_settings_when_no_override():
    out = resolve_initiative_slug(
        settings={"active_initiative": "bench"},
        form_override=None,
        initiatives=_ALL,
    )
    assert out == "bench"


def test_returns_none_when_no_override_and_no_settings():
    out = resolve_initiative_slug(
        settings={},
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


def test_returns_none_when_settings_is_none():
    out = resolve_initiative_slug(
        settings=None,
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


def test_returns_none_when_settings_active_initiative_empty_string():
    out = resolve_initiative_slug(
        settings={"active_initiative": ""},
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


# ---------------------------------------------------------------------------
# Active-only validation: closed/dormant initiatives are not valid targets
# ---------------------------------------------------------------------------


def test_settings_pointing_at_done_initiative_returns_none():
    """If settings remembers a slug that's since been closed, do NOT
    keep tagging fresh activity to it. Validation feedback that drove
    this rule: operator marked anthropic-fellows done after rejection
    but settings still pointed at it; we don't want stale tags."""
    out = resolve_initiative_slug(
        settings={"active_initiative": "anthropic-fellows"},
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


def test_settings_pointing_at_dormant_initiative_returns_none():
    """Dormant is paused — same treatment as done for write-side tagging."""
    out = resolve_initiative_slug(
        settings={"active_initiative": "content"},
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


def test_settings_pointing_at_unknown_slug_returns_none():
    """Stale settings — slug no longer exists at all."""
    out = resolve_initiative_slug(
        settings={"active_initiative": "removed-initiative"},
        form_override=None,
        initiatives=_ALL,
    )
    assert out is None


def test_form_override_pointing_at_done_initiative_raises():
    """An explicit override to a closed initiative is a user-error
    (probably stale link / browser back button). Route handler maps
    this to 400 with the message."""
    with pytest.raises(UnknownInitiativeError) as excinfo:
        resolve_initiative_slug(
            settings={},
            form_override="anthropic-fellows",
            initiatives=_ALL,
        )
    assert "anthropic-fellows" in str(excinfo.value)


def test_form_override_pointing_at_unknown_slug_raises():
    with pytest.raises(UnknownInitiativeError):
        resolve_initiative_slug(
            settings={},
            form_override="hallucinated-slug",
            initiatives=_ALL,
        )


def test_unknown_initiative_error_message_lists_valid_choices():
    """When the override is rejected, the error message should help
    the operator self-diagnose. Listing active slugs in the message
    means the error is actionable without docs lookup."""
    with pytest.raises(UnknownInitiativeError) as excinfo:
        resolve_initiative_slug(
            settings={},
            form_override="typo",
            initiatives=_ALL,
        )
    msg = str(excinfo.value)
    assert "bench" in msg
    assert "capstone" in msg
    assert "legal" in msg


def test_empty_active_set_does_not_crash_on_error_message():
    """Defensive: if there are zero active initiatives, the error
    message should still render cleanly without raising IndexError."""
    with pytest.raises(UnknownInitiativeError) as excinfo:
        resolve_initiative_slug(
            settings={},
            form_override="x",
            initiatives=[_DONE_FELLOWS],
        )
    assert "none" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Default loading from initiatives_service (covers the no-explicit-list path)
# ---------------------------------------------------------------------------


def test_loads_initiatives_when_not_passed_explicitly(monkeypatch):
    """When called without an explicit ``initiatives`` arg, the picker
    delegates to ``initiatives_service.load_initiatives()``. Verify
    that path so production callers don't have to manually pass them."""
    from app.services import initiative_picker as picker_module
    from app.services import initiatives as initiatives_module

    calls: list[bool] = []

    def fake_load():
        calls.append(True)
        return _ALL

    monkeypatch.setattr(initiatives_module, "load_initiatives", fake_load)

    out = picker_module.resolve_initiative_slug(
        settings={"active_initiative": "bench"},
        form_override=None,
    )
    assert out == "bench"
    assert len(calls) == 1
