"""Rest-day home route + timezone behavior tests."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


_USER_UUID = "11111111-1111-1111-1111-111111111111"


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

    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: dict(settings))
    client = TestClient(m.app)
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


def _request_with_settings(settings: dict):
    return SimpleNamespace(state=SimpleNamespace(user_settings=settings))


def test_is_weekend_for_user_true_on_sat_sun_false_on_weekday():
    import app.main as m

    req = _request_with_settings({"display_tz": "UTC"})

    sat = datetime(2026, 5, 16, 12, 0, tzinfo=ZoneInfo("UTC"))
    sun = datetime(2026, 5, 17, 12, 0, tzinfo=ZoneInfo("UTC"))
    mon = datetime(2026, 5, 18, 12, 0, tzinfo=ZoneInfo("UTC"))

    assert m._is_weekend_for_user(req, _USER_UUID, now_utc=sat) is True
    assert m._is_weekend_for_user(req, _USER_UUID, now_utc=sun) is True
    assert m._is_weekend_for_user(req, _USER_UUID, now_utc=mon) is False


def test_home_saturday_renders_rest_variant_without_up_next(monkeypatch):
    client, m = _signed_in_client(
        monkeypatch,
        settings={"display_tz": "UTC", "display_name": "Li"},
    )

    saturday = datetime(2026, 5, 16, 9, 0, tzinfo=ZoneInfo("UTC"))

    with patch.object(m, "_local_now_for_settings", return_value=saturday), \
         patch.object(m.attempt_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.content_repo, "list_progress_since", return_value=[]), \
         patch.object(m.writing_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.assessment_repo, "completed_since", return_value=[]), \
         patch.object(m.credentials_repo, "completed_since", return_value=[]):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    assert "Saturday." in r.text
    assert "Up next" not in r.text


def test_home_saturday_no_activity_shows_empty_recap_message(monkeypatch):
    client, m = _signed_in_client(
        monkeypatch,
        settings={"display_tz": "UTC", "display_name": "Li"},
    )

    saturday = datetime(2026, 5, 16, 9, 0, tzinfo=ZoneInfo("UTC"))

    with patch.object(m, "_local_now_for_settings", return_value=saturday), \
         patch.object(m.attempt_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.content_repo, "list_progress_since", return_value=[]), \
         patch.object(m.writing_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.assessment_repo, "completed_since", return_value=[]), \
         patch.object(m.credentials_repo, "completed_since", return_value=[]):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    assert "Nothing logged this week — that's fine too." in r.text


def test_home_saturday_with_activity_shows_recap_items_and_links(monkeypatch):
    client, m = _signed_in_client(
        monkeypatch,
        settings={"display_tz": "UTC", "display_name": "Li"},
    )

    from app.models import (
        AssessmentRun,
        Attempt,
        ContentItem,
        ContentProgress,
        CredentialRun,
        Problem,
        Reflection,
        Writing,
    )

    saturday = datetime(2026, 5, 16, 9, 0, tzinfo=ZoneInfo("UTC"))

    attempt = Attempt(
        id=9,
        user_id=_USER_UUID,
        problem_id=101,
        problem_version=1,
        started_at=datetime(2026, 5, 15, 16, 0),
        ended_at=None,
        language_used="python",
        final_code=None,
        solved_without_lookup=None,
        confidence_1_to_5=None,
        time_to_first_edit_seconds=None,
        edit_count=0,
        looked_at_solution=False,
        looked_at_pitfalls=False,
        test_passed=None,
        test_output=None,
        notes_md=None,
    )
    problem = Problem(
        id=101,
        slug="two-sum",
        title="Two Sum",
        difficulty="easy",
        time_bucket=15,
        problem_type="code_compose",
        is_warmup=False,
    )

    content_item = ContentItem(
        id=5,
        slug="attention-is-all-you-need",
        kind="reading",
        title="Attention Is All You Need",
    )
    content_progress = ContentProgress(
        user_id=_USER_UUID,
        content_id=5,
        status="completed",
        checked_at=datetime(2026, 5, 14, 10, 0),
        notes_md=None,
    )

    writing = Writing(
        id=3,
        user_id=_USER_UUID,
        title="Prompt engineering notes",
        body_md="",
        source_refs=[],
        status="draft",
        word_count=120,
        created_at=datetime(2026, 5, 14, 11, 0),
        updated_at=datetime(2026, 5, 14, 11, 30),
        published_at=None,
    )

    reflection = Reflection(
        id=4,
        user_id=_USER_UUID,
        period_start=datetime(2026, 5, 9, 0, 0),
        period_end=datetime(2026, 5, 16, 0, 0),
        generated_at=datetime(2026, 5, 16, 6, 0),
        prompts=[],
        response_md="A short reflection entry",
        response_updated_at=None,
        summary_md="Weekly calibration",
        method="keyword_fallback",
        model_used=None,
    )

    assessment = AssessmentRun(
        id=7,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 15, 8, 0),
        completed_at=datetime(2026, 5, 15, 8, 10),
        final_scores={"debugging": 0.8},
    )

    credential = CredentialRun(
        id=12,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 13, 9, 0),
        completed_at=datetime(2026, 5, 13, 9, 5),
        status_text="uploaded",
    )

    with patch.object(m, "_local_now_for_settings", return_value=saturday), \
         patch.object(m.attempt_repo, "list_for_user_since", return_value=[attempt]), \
         patch.object(m.problem_repo, "get_by_id", return_value=problem), \
         patch.object(m.content_repo, "list_progress_since", return_value=[content_progress]), \
         patch.object(m.content_repo, "get_by_id", return_value=content_item), \
         patch.object(m.writing_repo, "list_for_user_since", return_value=[writing]), \
         patch.object(m.reflection_repo, "list_for_user_since", return_value=[reflection]), \
         patch.object(m.assessment_repo, "completed_since", return_value=[assessment]), \
         patch.object(m.credentials_repo, "completed_since", return_value=[credential]):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    assert "Have to peek? Here's what your week looked like at the bench." in r.text
    assert "Two Sum" in r.text
    assert "Attention Is All You Need" in r.text
    assert "Prompt engineering notes" in r.text
    assert "Weekly calibration" in r.text
    assert 'href="/attempt/9/review"' in r.text
    assert 'href="/content/attention-is-all-you-need"' in r.text
    assert 'href="/writings/3"' in r.text
    assert 'href="/reflect/4"' in r.text
    assert 'href="/assess/7/result"' in r.text
    assert 'href="/credentials/12"' in r.text


def test_home_respects_tokyo_timezone_when_utc_is_friday(monkeypatch):
    client, m = _signed_in_client(
        monkeypatch,
        settings={"display_tz": "Asia/Tokyo", "display_name": "Li"},
    )

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 5, 15, 15, 30, tzinfo=ZoneInfo("UTC"))
            if tz is None:
                return base.replace(tzinfo=None)
            return base.astimezone(tz)

    monkeypatch.setattr(m, "datetime", _FixedDateTime)

    with patch.object(m.attempt_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.content_repo, "list_progress_since", return_value=[]), \
         patch.object(m.writing_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user_since", return_value=[]), \
         patch.object(m.assessment_repo, "completed_since", return_value=[]), \
         patch.object(m.credentials_repo, "completed_since", return_value=[]):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    assert "Saturday." in r.text
    assert "Up next" not in r.text


def test_home_weekday_behavior_is_unchanged(monkeypatch):
    client, m = _signed_in_client(
        monkeypatch,
        settings={"display_tz": "UTC", "onboarding_skipped": True},
    )

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
         patch.object(m.problem_repo, "list_recent_for_user", return_value=[]):
        r = client.get("/", follow_redirects=False)

    assert r.status_code == 200
    assert "Up next" in r.text
    assert "No drills today." not in r.text
