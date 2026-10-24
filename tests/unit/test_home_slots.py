"""Home-page slot + section-card regression tests for BEN-33."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import app.main as m
import pytest
from app.models import ContentItem, ContentProgress


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _content(*, id: int, slug: str, kind: str, title: str) -> ContentItem:
    return ContentItem(
        id=id,
        slug=slug,
        kind=kind,
        title=title,
        source=None,
        url=None,
        duration_min=10,
        axes=[],
        prerequisites=[],
        content_md=None,
        authored_by=None,
        authored_date=None,
        version=1,
        source_kind="authored",
        created_by_user_id=None,
    )


def _progress(*, content_id: int) -> ContentProgress:
    return ContentProgress(
        user_id="u-test",
        content_id=content_id,
        status="completed",
        checked_at=datetime.utcnow(),
        notes_md=None,
        favorited=False,
        rating_1_to_5=None,
    )


def _done_by_key(slots: list[dict]) -> dict[str, bool]:
    return {str(s["key"]): bool(s["done"]) for s in slots}


def _set_fake_session_cookie(client, *, user_id: str = _USER_UUID) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": user_id,
                "email": "test@example.com",
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _signed_in_client(monkeypatch, *, settings: dict):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: dict(settings))
    client = TestClient(m.app)
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client


def _render_weekday_home(monkeypatch, *, settings: dict, track=None):
    client = _signed_in_client(monkeypatch, settings=settings)

    fake_next = {
        "kind": "reading",
        "verb": "Read",
        "title": "A reading pick",
        "why": "continue today's plan",
        "url": "/content/a-reading",
        "badge": "reading",
        "difficulty": None,
        "duration_min": 12,
    }

    with patch.object(m, "_is_weekend_for_user", return_value=False), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.writing_repo, "active_draft_today", return_value=None), \
         patch.object(m.content_repo, "all_by_kinds", return_value={"reading": [], "video": [], "podcast": [], "exercise": []}), \
         patch.object(m, "_build_session", return_value=[]), \
         patch.object(m.content_repo, "axis_ratings_for_user", return_value={}), \
         patch.object(m, "_compute_next_action", return_value=fake_next), \
         patch.object(m.problem_repo, "list_recent_for_user", return_value=[]), \
         patch.object(m, "get_track", return_value=track):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    return r


def test_daily_slots_map_problem_types_without_double_counting():
    """REGRESSION (BEN-99 / #299): each slot should only tick for the
    activity kind the operator actually did.

    Mapping choice in this test: `code_compose` powers the Composing
    slot only; non-compose attempts (e.g. `code_debug`) should not tick
    either Practicing or Composing by themselves.
    """
    compose_slots = m._build_home_daily_slots(
        kinds_completed_today=set(),
        attempted_problem_types_today={"code_compose"},
        active_writing=None,
    )
    compose_done = _done_by_key(compose_slots)
    assert compose_done["practicing"] is False
    assert compose_done["composing"] is True

    debug_slots = m._build_home_daily_slots(
        kinds_completed_today=set(),
        attempted_problem_types_today={"code_debug"},
        active_writing=None,
    )
    debug_done = _done_by_key(debug_slots)
    assert debug_done["practicing"] is False
    assert debug_done["composing"] is False


def test_reading_section_card_sticks_to_completed_today_item():
    """REGRESSION (BEN-33 sub-bug #3): when today's reading is done,
    the section card should keep showing the completed item instead of
    rotating to the next unread queue item."""
    completed_reading = _content(
        id=1,
        slug="layer-normalization",
        kind="reading",
        title="Layer Normalization",
    )
    queued_next_reading = _content(
        id=2,
        slug="recipe-for-training-neural-networks",
        kind="reading",
        title="A Recipe for Training Neural Networks",
    )

    cards = m._build_home_section_cards(
        done_today_items=[(completed_reading, _progress(content_id=completed_reading.id))],
        daily_reading=queued_next_reading,
        daily_watch=None,
        daily_exercise=None,
    )

    assert cards["reading"]["done_today"] is True
    assert cards["reading"]["item"].slug == "layer-normalization"


def test_home_without_active_track_renders_daily_slot_strip(monkeypatch):
    r = _render_weekday_home(
        monkeypatch,
        settings={"display_tz": "UTC", "onboarding_skipped": True},
    )

    assert 'class="daily-progress"' in r.text
    assert "track-progress" not in r.text


def test_home_with_active_track_renders_progress_and_hides_slot_strip(monkeypatch):
    r = _render_weekday_home(
        monkeypatch,
        settings={
            "display_tz": "UTC",
            "onboarding_skipped": True,
            "active_track": {"slug": "arena_3", "cursor": 3},
        },
        track=SimpleNamespace(slug="arena_3", title="ARENA 3.0", total_sections=6),
    )

    assert "track-progress" in r.text
    assert 'href="/tracks/arena_3"' in r.text  # widget now links into the track
    assert "ARENA 3.0" in r.text
    assert "checkpoints 3 of 6" in r.text
    assert "next unlocked section 4" in r.text
    assert 'class="daily-progress"' not in r.text


@pytest.mark.parametrize(
    ("cursor", "total", "expected_pct"),
    [
        (0, 8, 0),
        (3, 6, 50),
        (8, 8, 100),
    ],
)
def test_home_active_track_fill_width_matches_cursor(monkeypatch, cursor, total, expected_pct):
    r = _render_weekday_home(
        monkeypatch,
        settings={
            "display_tz": "UTC",
            "onboarding_skipped": True,
            "active_track": {"slug": "arena_3", "cursor": cursor},
        },
        track=SimpleNamespace(slug="arena_3", title="ARENA 3.0", total_sections=total),
    )

    assert f'width: {expected_pct}%' in r.text
