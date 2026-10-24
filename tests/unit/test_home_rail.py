"""Unit coverage for _build_home_rail (WS4 Today rebuild).

Tests the pure-aggregation helper that composes the right-rail
content on the home surface. No DB, no I/O — just data shaping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import app.main as m


@dataclass
class _FakeAttempt:
    started_at: datetime | None


@dataclass
class _FakeProgress:
    status: str
    checked_at: datetime | None


@dataclass
class _FakeInitiative:
    slug: str
    title: str
    status: str
    priority: int
    target_date: str | None = None
    # focus._format_target_date only reads target_date; the other
    # Initiative fields aren't touched by _build_home_rail. The real
    # service-side Initiative has more, but the rail doesn't care.

    # Match the dataclass shape just enough to satisfy attribute
    # access. focus_service._format_target_date uses init.target_date.


def _now():
    return datetime(2026, 5, 28, 14, 0, 0)


def _make_initiatives():
    return [
        _FakeInitiative(slug="prep", title="Anthropic prep", status="active",
                         priority=1, target_date="2026-08-15"),
        _FakeInitiative(slug="consulting", title="Consulting launch",
                         status="active", priority=2, target_date="2026-05-30"),
        _FakeInitiative(slug="dormant", title="Old project",
                         status="dormant", priority=3),
        _FakeInitiative(slug="closed", title="Shipped thing",
                         status="done", priority=0),
    ]


def test_rail_initiatives_picks_top_3_active_sorted_by_priority():
    """Active initiatives are sorted by priority asc (0 = highest),
    then by target_date (earliest first). Dormant/done are excluded.
    Capped at 3."""
    with patch.object(m.initiatives_service, "load_initiatives",
                       return_value=_make_initiatives()):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={},
            now=_now(),
            active_track_progress=None,
        )

    slugs = [i["slug"] for i in rail["initiatives"]]
    # Only the two active ones present; "dormant" + "closed" filtered.
    assert slugs == ["prep", "consulting"]
    # Priority sort holds.
    assert rail["initiatives"][0]["priority"] < rail["initiatives"][1]["priority"]


def test_rail_initiatives_hoists_pinned_initiative_to_top():
    """The currently-pinned initiative renders first regardless of
    priority — the rail row gets is_pinned=True so the template can
    decorate it with a star."""
    with patch.object(m.initiatives_service, "load_initiatives",
                       return_value=_make_initiatives()):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={},
            now=_now(),
            # consulting has lower priority than prep but is pinned.
            active_track_progress={"track_slug": "consulting"},
        )

    slugs = [i["slug"] for i in rail["initiatives"]]
    assert slugs[0] == "consulting"
    assert rail["initiatives"][0]["is_pinned"] is True
    assert rail["initiatives"][1]["is_pinned"] is False


def test_rail_signal_counts_7d_attempts_and_content():
    """7-day signal is computed against the now passed in. Older
    rows don't count; same-second rows do."""
    now = _now()
    attempts = [
        _FakeAttempt(started_at=now - timedelta(days=1)),
        _FakeAttempt(started_at=now - timedelta(days=6, hours=23)),
        _FakeAttempt(started_at=now - timedelta(days=8)),  # outside
        _FakeAttempt(started_at=None),                       # ignored
    ]
    progress = {
        "a": _FakeProgress(status="completed", checked_at=now - timedelta(days=2)),
        "b": _FakeProgress(status="completed", checked_at=now - timedelta(days=10)),
        "c": _FakeProgress(status="started",   checked_at=now),  # wrong status
        "d": _FakeProgress(status="completed", checked_at=None),
    }
    with patch.object(m.initiatives_service, "load_initiatives", return_value=[]):
        rail = m._build_home_rail(
            attempts=attempts,
            progress_by_id=progress,
            scores={},
            now=now,
            active_track_progress=None,
        )

    assert rail["signal"]["attempts_7d"] == 2
    assert rail["signal"]["content_7d"] == 1


def test_rail_signal_active_today_flips_when_anything_happened_today():
    now = _now()
    attempts = [_FakeAttempt(started_at=now - timedelta(hours=3))]
    with patch.object(m.initiatives_service, "load_initiatives", return_value=[]):
        rail = m._build_home_rail(
            attempts=attempts,
            progress_by_id={},
            scores={},
            now=now,
            active_track_progress=None,
        )
    assert rail["signal"]["active_today"] is True


def test_rail_signal_none_when_no_recent_activity():
    """Fresh user with no signal at all gets signal=None so the
    template skips the card."""
    with patch.object(m.initiatives_service, "load_initiatives", return_value=[]):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={},
            now=_now(),
            active_track_progress=None,
        )
    assert rail["signal"] is None


def test_rail_weak_axis_picks_min_score_and_labels_it():
    """Weak axis is the lowest score, mapped to a human label via
    AXIS_LABELS. The score is converted to 0-100 int percent."""
    with patch.object(m.initiatives_service, "load_initiatives", return_value=[]):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={"debugging": 0.85, "eval_design": 0.42, "algorithmic": 0.71},
            now=_now(),
            active_track_progress=None,
        )

    assert rail["weak_axis"]["label"] == m.assess_service.AXIS_LABELS["eval_design"]
    assert rail["weak_axis"]["score_pct"] == 42


def test_rail_weak_axis_none_when_no_scores():
    """Pre-assessment users get weak_axis=None — no rail card."""
    with patch.object(m.initiatives_service, "load_initiatives", return_value=[]):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={},
            now=_now(),
            active_track_progress=None,
        )
    assert rail["weak_axis"] is None


def test_rail_degrades_gracefully_when_load_initiatives_raises():
    """If the initiatives config is broken (yaml error, missing
    field, etc.) the rail still renders — just without the
    initiatives card."""
    with patch.object(m.initiatives_service, "load_initiatives",
                       side_effect=ValueError("bad yaml")):
        rail = m._build_home_rail(
            attempts=[],
            progress_by_id={},
            scores={},
            now=_now(),
            active_track_progress=None,
        )
    assert rail["initiatives"] == []
    assert rail["signal"] is None
    assert rail["weak_axis"] is None
