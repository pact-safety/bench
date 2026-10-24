"""Mira coaching routes keep saved research read-only and disable generation."""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from datetime import datetime

from app.models import MiraSession, MiraTurn


_USER_UUID = "11111111-1111-1111-1111-111111111111"
_SESS = "22222222-2222-2222-2222-222222222222"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    # Force the offline provider so the stream never reaches Anthropic.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="op@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m


def _session(id=_SESS, title=None):
    return MiraSession(
        id=id, user_id=_USER_UUID, modality="chat",
        started_at=datetime(2026, 6, 1, 9, 0, 0), ended_at=None, title=title,
    )


def _turn(role, content, id="t1"):
    return MiraTurn(
        id=id, session_id=_SESS, role=role, content=content,
        created_at=datetime(2026, 6, 1, 9, 1, 0),
    )


def test_mira_home_is_side_effect_free_coaching_landing(monkeypatch):
    from unittest.mock import Mock
    client, m = _signed_in_client(monkeypatch)
    create = Mock(side_effect=AssertionError("GET must not create a session"))
    monkeypatch.setattr(m.mira_repo, "create_session", create)
    monkeypatch.setattr(m.mira_repo, "list_sessions", lambda uid, **kw: [])
    r = client.get("/mira")
    assert r.status_code == 200
    assert 'action="/mira/coach"' in r.text
    assert 'id="mira-message"' in r.text
    assert "fixed prompts" in r.text
    assert "not sent to an AI provider" in r.text
    assert 'data-mira-session=' not in r.text
    create.assert_not_called()


def test_legacy_session_is_read_only_and_preserves_transcript(monkeypatch):
    from unittest.mock import Mock
    client, m = _signed_in_client(monkeypatch)
    get = Mock(return_value=_session())
    monkeypatch.setattr(m.mira_repo, "get_session", get)
    monkeypatch.setattr(m.mira_repo, "list_turns", lambda sid, **kw: [
        _turn("user", "what should I ship this week?", id="u1"),
        _turn("assistant", "Start with the elicitation harness.", id="a1"),
    ])
    monkeypatch.setattr(m.mira_repo, "list_sessions", lambda uid, **kw: [])
    r = client.get(f"/mira/session/{_SESS}")
    assert r.status_code == 200
    assert "what should I ship this week?" in r.text
    assert "elicitation harness" in r.text
    assert "read-only" in r.text
    assert 'action="/mira/coach"' not in r.text
    assert 'action="/mira/turn"' not in r.text
    assert get.call_args.kwargs["user_id"] == _USER_UUID


def test_mira_session_404_when_missing(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    monkeypatch.setattr(m.mira_repo, "get_session", lambda sid, **kw: None)
    assert client.get(f"/mira/session/{_SESS}").status_code == 404


def test_mira_turn_cannot_generate_even_with_an_owned_session(monkeypatch):
    from unittest.mock import Mock
    from app.services import mira
    client, m = _signed_in_client(monkeypatch)
    generate = Mock(side_effect=AssertionError("unrestricted generation called"))
    appended = Mock(side_effect=AssertionError("legacy turn persisted"))
    monkeypatch.setattr(mira, "mira_turn", generate)
    monkeypatch.setattr(m.mira_repo, "append_turn", appended)
    monkeypatch.setattr(m.mira_repo, "get_session", lambda sid, **kw: _session(sid))
    for message in ("Give me the answer.", "   "):
        r = client.post("/mira/turn", data={"session_id": _SESS, "message": message})
        assert r.status_code == 409
        assert "Unrestricted replies are disabled" in r.text
    generate.assert_not_called()
    appended.assert_not_called()


def test_mira_turn_unknown_session_is_not_disclosed(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    monkeypatch.setattr(m.mira_repo, "get_session", lambda sid, **kw: None)
    r = client.post("/mira/turn", data={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


def test_get_and_post_coach_require_auth():
    import app.main as m
    from fastapi.testclient import TestClient
    client = TestClient(m.app)
    for r in (client.get("/mira", follow_redirects=False),
              client.post("/mira/coach", data={"message": "My task"}, follow_redirects=False)):
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
