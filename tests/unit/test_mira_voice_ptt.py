"""Strict text coaching does not activate the legacy voice preference."""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, settings=None):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_MIRA_ADMIN_ONLY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    store = {"settings": dict(settings or {})}
    monkeypatch.setattr(m, "_user_settings", lambda _uid: store["settings"])
    monkeypatch.setattr(
        m, "_save_user_settings", lambda _uid, s: store.update(settings=s)
    )
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID, email="u@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m, store


def _get_console(client, m):
    session = SimpleNamespace(id="s1", title=None, started_at=None)
    with patch.object(m.mira_repo, "create_session", return_value="s1"), \
         patch.object(m.mira_repo, "get_session", return_value=session), \
         patch.object(m.mira_repo, "list_turns", return_value=[]), \
         patch.object(m.mira_repo, "list_sessions", return_value=[session]), \
         patch("app.services.spend_cap.over_cap_for", return_value=False):
        return client.get("/mira")


def test_local_coaching_has_no_audio_or_provider_hooks(mock_anthropic, monkeypatch):
    client, m, _ = _client(monkeypatch)
    r = _get_console(client, m)
    assert r.status_code == 200
    assert "Text coaching preview" in r.text
    assert 'action="/mira/coach"' in r.text
    assert 'data-voice-note' not in r.text
    assert 'id="mira-speak"' not in r.text
    assert 'speechSynthesis' not in r.text


def test_saved_voice_preference_does_not_enable_audio_in_text_coach(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch, settings={"mira_speak_replies": True})
    r = _get_console(client, m)
    assert r.status_code == 200
    assert store["settings"]["mira_speak_replies"] is True
    assert 'speechSynthesis' not in r.text
    assert 'data-voice-note' not in r.text


def test_preference_endpoint_persists_and_removes(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    r = client.post(
        "/settings/mira-voice", data={"enabled": "1"},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 204
    assert store["settings"]["mira_speak_replies"] is True

    r = client.post(
        "/settings/mira-voice", data={"enabled": "0"},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 204
    # Default = absent key, matching the glass-level convention.
    assert "mira_speak_replies" not in store["settings"]

    r = client.post("/settings/mira-voice", data={"enabled": "1"},
                    follow_redirects=False)
    assert r.status_code == 303  # no-JS fallback


def test_legacy_replies_are_never_automatically_spoken(mock_anthropic, monkeypatch):
    client, m, _ = _client(monkeypatch, settings={"mira_speak_replies": True})
    session = SimpleNamespace(id="s1", meta={}, title=None, started_at=None)
    with patch.object(m.mira_repo, "get_session", return_value=session), \
         patch.object(m.mira_repo, "list_turns", return_value=[]), \
         patch.object(m.mira_repo, "list_sessions", return_value=[]):
        r = client.get("/mira/session/s1")
    assert r.status_code == 200
    assert "read-only" in r.text
    assert 'speechSynthesis' not in r.text
    assert 'action="/mira/coach"' not in r.text
