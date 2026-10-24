from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch


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


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {"display_tz": "UTC", "display_name": "Li"})
    client = TestClient(m.app)
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


def _today_next_location(monkeypatch, *, kind: str, url: str) -> str:
    client, m = _signed_in_client(monkeypatch)
    from app.services.daily_flow import NextAction

    nxt = NextAction(kind=kind, verb="Go", title="Next", url=url, why="test")

    with patch.object(m, "_build_session", return_value=[]), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.content_repo, "axis_ratings_for_user", return_value={}), \
         patch.object(m.content_repo, "all_by_kind", return_value=[]), \
         patch.object(m.content_service, "pick_daily", return_value=None), \
         patch.object(m, "_compute_next_action", return_value=nxt):
        r = client.get("/today/next", follow_redirects=False)

    assert r.status_code == 303
    return r.headers.get("location") or ""


def _render_content(monkeypatch, *, query: str = ""):
    client, m = _signed_in_client(monkeypatch)

    from app.models import ContentItem

    item = ContentItem(
        id=21,
        slug="r99-chain-crumb",
        kind="reading",
        title="Chain crumb content",
        content_md="Body",
    )

    with patch.object(m.content_repo, "get_by_slug", return_value=item), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.problem_repo, "all_core", return_value=[]), \
         patch.object(m.problem_repo, "all_warmups", return_value=[]), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]), \
         patch.object(m.crosslink_service, "attempts_following_content", return_value=[]):
        return client.get(f"/content/{item.slug}{query}", follow_redirects=False)


def _render_problem(monkeypatch, *, query: str = ""):
    client, m = _signed_in_client(monkeypatch)

    from app.models import Problem

    p = Problem(
        id=77,
        slug="softmax-chain-crumb",
        title="Softmax chain crumb",
        difficulty="medium",
        time_bucket=30,
        problem_type="code_compose",
        is_warmup=False,
        content_md="Implement softmax.",
    )

    with patch.object(m.problem_repo, "get_by_slug", return_value=p), \
         patch("app.services.voices.all_voices", return_value=[]):
        return client.get(f"/problem/{p.slug}{query}", follow_redirects=False)


def test_today_next_adds_chain_params_for_content_destinations(monkeypatch):
    loc = _today_next_location(
        monkeypatch,
        kind="exercise",
        url="/content/e08-training-loop-ordering",
    )

    assert loc == "/content/e08-training-loop-ordering?chain=1&step=3&total=4"


def test_today_next_adds_chain_params_for_problem_destinations(monkeypatch):
    loc = _today_next_location(monkeypatch, kind="practice", url="/problem/softmax")

    assert loc == "/problem/softmax?chain=1&step=4&total=4"


def test_content_shows_chain_crumb_for_valid_query(monkeypatch):
    r = _render_content(monkeypatch, query="?chain=1&step=2&total=4")

    assert r.status_code == 200
    assert "Step 2 of 4" in r.text


def test_content_hides_chain_crumb_for_direct_link(monkeypatch):
    r = _render_content(monkeypatch)

    assert r.status_code == 200
    assert "Step 2 of 4" not in r.text


def test_problem_shows_chain_crumb_for_valid_query(monkeypatch):
    r = _render_problem(monkeypatch, query="?chain=1&step=4&total=4")

    assert r.status_code == 200
    assert "Step 4 of 4" in r.text


def test_problem_hides_chain_crumb_for_direct_link(monkeypatch):
    r = _render_problem(monkeypatch)

    assert r.status_code == 200
    assert "Step 4 of 4" not in r.text
