from __future__ import annotations

import base64
import json
import logging
import time
import uuid


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_NON_ADMIN_UUID = "22222222-2222-2222-2222-222222222222"


def _client():
    # Late-import so conftest env setup lands before app.main import.
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app), m


def _set_fake_session_cookie(client, *, user_id: str, email: str = "user@example.com") -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": user_id,
                "email": email,
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _authed_client(monkeypatch, *, user_id: str, admin_uuid: str = _ADMIN_UUID):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", admin_uuid)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=user_id, email=f"{user_id[:8]}@example.com")
    return client, m


def test_admin_diag_recent_events_renders_page_and_events(mock_anthropic, monkeypatch):
    from app.services import diag_log

    diag_log.install()
    diag_log.clear()

    older_marker = f"diag-route-older-{uuid.uuid4()}"
    newer_marker = f"diag-route-newer-{uuid.uuid4()}"
    logger = logging.getLogger("tests.diag_recent_events")
    logger.warning(older_marker)
    logger.error(newer_marker)

    client, _m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    response = client.get("/admin/diag/recent-events")

    assert response.status_code == 200
    assert "Recent events" in response.text
    assert "Copy all" in response.text
    assert older_marker in response.text
    assert newer_marker in response.text
    assert response.text.index(newer_marker) < response.text.index(older_marker)


def test_admin_diag_recent_events_requires_admin(mock_anthropic, monkeypatch):
    client, _m = _authed_client(monkeypatch, user_id=_NON_ADMIN_UUID)
    response = client.get("/admin/diag/recent-events")

    assert response.status_code == 403
    assert "Not authorized" in response.text
