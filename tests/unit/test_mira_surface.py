"""The local coaching surface stays available independently of AI spend caps."""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from types import SimpleNamespace
from unittest.mock import patch


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_ADMIN_UUID,
            email="u@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _get_mira(monkeypatch, *, resting: bool):
    client, m = _client(monkeypatch)
    with patch.object(m.mira_repo, "list_sessions", return_value=[]), \
         patch("app.services.spend_cap.over_cap_for", return_value=resting) as cap, \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        r = client.get("/mira")
    cap.assert_not_called()
    return r


def test_coaching_remains_available_without_using_an_api_budget(monkeypatch):
    r = _get_mira(monkeypatch, resting=True)
    assert r.status_code == 200
    assert "Mira is resting" not in r.text
    assert 'action="/mira/coach"' in r.text
    assert "not sent to an AI provider" in r.text


def test_coaching_explains_its_limits_even_when_budget_is_available(monkeypatch):
    r = _get_mira(monkeypatch, resting=False)
    assert r.status_code == 200
    assert "fixed prompts" in r.text
    assert "not a correctness assessment" in r.text


def test_research_workspace_is_separate_from_practice_coaching(monkeypatch):
    r = _get_mira(monkeypatch, resting=False)
    assert r.status_code == 200
    assert "Research workspace" in r.text
    assert "separate from this coaching session" in r.text
    for path in ("agenda", "memory", "evals", "kb"):
        assert f'href="/mira/{path}"' in r.text
    assert 'href="/mira/voice"' not in r.text
