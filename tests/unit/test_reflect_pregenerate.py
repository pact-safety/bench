"""Tests for the Saturday Reflect pre-generation service (GH #229)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import reflect_pregenerate as pregen


_USER = "11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 5, 23, 7, 0, 0)  # a Saturday morning


def _attempts_repo(*, recent_at: datetime | None = None):
    """Mock attempts_repo with a `list_for_user_since` that returns one
    attempt if `recent_at` is given, else nothing."""
    repo = MagicMock()
    repo.list_for_user_since.return_value = (
        [SimpleNamespace(id=1, user_id=_USER, started_at=recent_at)]
        if recent_at is not None
        else []
    )
    return repo


def _reflection_repo(*, existing=None):
    repo = MagicMock()
    repo.latest_in_period.return_value = existing
    repo.insert.return_value = 42
    return repo


def _week_summary_builder(uid, days):
    return SimpleNamespace(uid=uid, days=days, attempts=3, attempts_passed=2)


def _generator(week, *, days, user_id):
    return {
        "prompts": [{"label": "Hits", "prompt": "What worked this week?"}],
        "summary": "Solid week.",
        "method": "claude",
        "model_used": "claude-haiku-4-5",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_pregenerates_when_active_and_no_existing_row():
    attempts = _attempts_repo(recent_at=_NOW - timedelta(days=2))
    reflections = _reflection_repo(existing=None)

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "inserted"
    assert out.reflection_id == 42
    # The Reflection passed to insert must have pregenerated=True
    inserted = reflections.insert.call_args[0][0]
    assert inserted.pregenerated is True
    assert inserted.user_id == _USER
    assert inserted.prompts == [{"label": "Hits", "prompt": "What worked this week?"}]
    # Period must be (now - 7d) -> now
    assert inserted.period_end == _NOW
    assert inserted.period_start == _NOW - timedelta(days=7)


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def test_skips_when_existing_reflection_covers_period():
    attempts = _attempts_repo(recent_at=_NOW - timedelta(days=1))
    existing = SimpleNamespace(id=9, response_md=None)
    reflections = _reflection_repo(existing=existing)

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "skipped_existing"
    assert out.reflection_id == 9
    reflections.insert.assert_not_called()


def test_skips_when_user_has_no_recent_activity():
    # No attempts in the last 30 days → skip.
    attempts = _attempts_repo(recent_at=None)
    reflections = _reflection_repo(existing=None)

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "skipped_inactive"
    reflections.insert.assert_not_called()
    reflections.latest_in_period.assert_not_called()


def test_skips_when_no_activity_this_week_even_if_recent_activity_exists():
    """30d activity check passes, but the 7d window is empty → quiet-week
    skip. Prevents the cron from emitting a 'complete no-show' Hamming
    reflection on a week with zero attempts. (Validation feedback 2026-05-25.)
    """
    # One attempt 20 days ago: inside the 30d activity window but outside
    # the 7d reflection window.
    attempt = SimpleNamespace(
        id=1, user_id=_USER, started_at=_NOW - timedelta(days=20)
    )

    attempts = MagicMock()
    # The implementation calls list_for_user_since(uid, since) twice with
    # different `since` cutoffs (30d then 7d). Filter against `since` so
    # each call returns the correct slice.
    attempts.list_for_user_since.side_effect = (
        lambda uid, since: [attempt] if attempt.started_at >= since else []
    )

    reflections = _reflection_repo(existing=None)

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "skipped_quiet_week"
    reflections.insert.assert_not_called()
    reflections.latest_in_period.assert_not_called()


def test_falls_back_to_all_for_user_when_since_helper_missing():
    """Some repo fixtures lack `list_for_user_since` — defensive path."""
    repo = MagicMock()
    repo.list_for_user_since.side_effect = AttributeError("no _since on this repo")
    repo.all_for_user.return_value = [
        SimpleNamespace(id=1, user_id=_USER, started_at=_NOW - timedelta(days=2)),
    ]
    reflections = _reflection_repo(existing=None)

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=repo,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "inserted"


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_returns_error_outcome_when_generator_raises():
    attempts = _attempts_repo(recent_at=_NOW - timedelta(days=1))
    reflections = _reflection_repo(existing=None)

    def _failing_generator(week, *, days, user_id):
        raise RuntimeError("API timeout")

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_failing_generator,
    )

    assert out.action == "error"
    assert "API timeout" in out.error_message
    reflections.insert.assert_not_called()


def test_returns_error_outcome_when_insert_raises():
    attempts = _attempts_repo(recent_at=_NOW - timedelta(days=1))
    reflections = _reflection_repo(existing=None)
    reflections.insert.side_effect = RuntimeError("db down")

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator,
    )

    assert out.action == "error"
    assert "db down" in out.error_message


def test_returns_error_outcome_when_week_summary_builder_raises():
    attempts = _attempts_repo(recent_at=_NOW - timedelta(days=1))
    reflections = _reflection_repo(existing=None)

    def _bad_builder(uid, days):
        raise RuntimeError("week summary failed")

    out = pregen.pregenerate_for_user(
        user_id=_USER,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_bad_builder,
        generator=_generator,
    )

    assert out.action == "error"
    assert "week summary" in out.error_message


# ---------------------------------------------------------------------------
# Multi-user wrapper
# ---------------------------------------------------------------------------


def test_pregenerate_for_users_processes_each_independently():
    """One user's failure must not affect others."""
    uids = ["aaaa", "bbbb"]
    attempts = MagicMock()
    # Both users active
    attempts.list_for_user_since.return_value = [
        SimpleNamespace(started_at=_NOW - timedelta(days=1)),
    ]
    reflections = _reflection_repo(existing=None)

    call_count = {"n": 0}
    def _generator_first_fails(week, *, days, user_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("first call boom")
        return _generator(week, days=days, user_id=user_id)

    outcomes = pregen.pregenerate_for_users(
        uids,
        now=_NOW,
        attempts_repo=attempts,
        reflection_repo=reflections,
        week_summary_builder=_week_summary_builder,
        generator=_generator_first_fails,
    )

    assert len(outcomes) == 2
    assert outcomes[0].action == "error"
    assert outcomes[1].action == "inserted"
