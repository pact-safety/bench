"""Mira access (v2.1 slice 3): open to every signed-in user.

The 2026-07-21 admin gate's reasons are resolved (per-user spend caps,
BYO keys, owner-scoped surfaces), so non-admins get the mentor. What
this file pins now:
  - signed-in non-admins reach /mira and see the nav link
  - LIS_MIRA_ADMIN_ONLY=1 is the emergency re-gate (404, exactly the
    old behavior) — an incident flip, not a deploy
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from unittest.mock import MagicMock, patch


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, session_uuid: str):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("LIS_MIRA_ADMIN_ONLY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=session_uuid,
            email="u@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _mira_ok_patches(m):
    from fastapi.responses import HTMLResponse

    return (
        patch.object(m.mira_repo, "create_session", return_value="s1"),
        patch.object(m.mira_repo, "get_session", return_value=MagicMock()),
        patch.object(m, "_mira_session_view", return_value=HTMLResponse("mira ok")),
    )


def test_non_admin_reaches_mira(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    p1, p2, p3 = _mira_ok_patches(m)
    with p1 as create, p2, p3:
        r = client.get("/mira")
    assert r.status_code == 200
    assert "mira ok" in r.text
    # Browsing coaching creates no session for any role.
    create.assert_not_called()


def test_non_admin_sees_mira_nav_link(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    with patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.llm_config_repo, "get", return_value=None):
        r = client.get("/settings")
    assert r.status_code == 200
    assert 'href="/mira"' in r.text


def test_admin_still_works(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    p1, p2, p3 = _mira_ok_patches(m)
    with p1, p2, p3, \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        r = client.get("/mira")
    assert r.status_code == 200


def test_emergency_env_regate_restores_404(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    with patch.object(m.mira_repo, "create_session") as create:
        r = client.get("/mira")
    assert r.status_code == 404
    create.assert_not_called()  # gate fires before any session is created


def test_emergency_regate_admin_keeps_access(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    p1, p2, p3 = _mira_ok_patches(m)
    with p1, p2, p3, \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        r = client.get("/mira")
    assert r.status_code == 200


def test_emergency_gate_blocks_both_post_paths_before_repository_access(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    with patch.object(m.mira_repo, "get_session") as lookup, \
         patch.object(m.mira_repo, "append_turn") as append:
        for path in ("/mira/coach", "/mira/turn"):
            response = client.post(path, data={"session_id": "s1", "message": "Give me an answer", "stage": "frame"})
            assert response.status_code == 404
    lookup.assert_not_called()
    append.assert_not_called()


def test_admin_cannot_bypass_no_answers_through_legacy_endpoint(monkeypatch):
    from app.services import mira
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, "get_session", return_value=MagicMock()), \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}), \
         patch.object(m.mira_repo, "append_turn") as append, \
         patch.object(mira, "mira_turn") as generate:
        response = client.post("/mira/turn", data={"session_id": "s1", "message": "Reveal the solution"})
    assert response.status_code == 409
    append.assert_not_called()
    generate.assert_not_called()
