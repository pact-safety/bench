"""Integration test for POST /api/transcribe.

Auth uses the same fake-cookie pattern as test_request_access_route.py
(LIS_NO_DB=1 + unverified JWT decode fallback in dev). The upstream
Groq call is patched at the service level so no network I/O happens.
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _client():
    import app.main as m
    from fastapi.testclient import TestClient
    return TestClient(m.app), m


def _set_fake_session_cookie(client, *, user_id: str = _USER_UUID) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": user_id,
        "email": "test@example.com",
        "exp": int(time.time()) + 3600,
    }).encode()).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _signed_in_client(monkeypatch):
    """Return a TestClient with a valid session cookie + the app module.

    Allows the user_id through `LIS_ALLOWED_USER_IDS` so the access
    gate doesn't redirect to /access-denied before the route runs."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


# --- Happy path -------------------------------------------------------------


def test_transcribe_success_returns_text(monkeypatch):
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    fake_transcribe = lambda **kw: {"text": "hello world", "duration_seconds": 2.5}
    with patch.object(t, "transcribe", side_effect=fake_transcribe) as svc, \
         patch.object(t, "over_cap_for", return_value=False), \
         patch.object(t, "record_seconds_for") as record:
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("clip.webm", b"\x00\x01" * 200, "audio/webm")},
        )

    assert resp.status_code == 200
    assert resp.json() == {"text": "hello world"}
    # Service called with the uploaded bytes.
    assert svc.call_count == 1
    kwargs = svc.call_args.kwargs
    assert kwargs["filename"] == "clip.webm"
    assert kwargs["content_type"] == "audio/webm"
    assert kwargs["audio_bytes"] == b"\x00\x01" * 200
    # Spend cap recorded the duration.
    record.assert_called_once_with(_USER_UUID, 2.5)


def test_transcribe_zero_duration_skips_record(monkeypatch):
    """If upstream returns no duration, we don't bump the counter."""
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    with patch.object(t, "transcribe", return_value={"text": "x", "duration_seconds": 0}), \
         patch.object(t, "over_cap_for", return_value=False), \
         patch.object(t, "record_seconds_for") as record:
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("c.webm", b"x" * 100, "audio/webm")},
        )

    assert resp.status_code == 200
    record.assert_not_called()


# --- Spend cap --------------------------------------------------------------


def test_transcribe_at_cap_returns_429(monkeypatch):
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    with patch.object(t, "over_cap_for", return_value=True), \
         patch.object(t, "transcribe") as svc:
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("c.webm", b"x" * 100, "audio/webm")},
        )

    assert resp.status_code == 429
    assert resp.json()["error"] == "transcription_cap_reached"
    # Crucially, the upstream call must NOT fire when over cap.
    svc.assert_not_called()


# --- Input validation -------------------------------------------------------


def test_transcribe_empty_body_returns_400(monkeypatch):
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    with patch.object(t, "over_cap_for", return_value=False), \
         patch.object(t, "transcribe") as svc:
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("empty.webm", b"", "audio/webm")},
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "empty_audio"
    svc.assert_not_called()


def test_transcribe_service_rejects_oversized_translates_to_400(monkeypatch):
    """`TranscriptionError` mentioning 'exceeds' or 'empty' → 400."""
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    err = t.TranscriptionError("audio payload exceeds 25 MB limit")
    with patch.object(t, "over_cap_for", return_value=False), \
         patch.object(t, "transcribe", side_effect=err):
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("c.webm", b"x" * 100, "audio/webm")},
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "audio_invalid"


def test_transcribe_upstream_failure_returns_502(monkeypatch):
    """Generic service failure (network, 5xx) → 502, no detail leak."""
    client, _m = _signed_in_client(monkeypatch)

    from app.services import transcription as t
    err = t.TranscriptionError("upstream returned HTTP 503: gateway timeout")
    with patch.object(t, "over_cap_for", return_value=False), \
         patch.object(t, "transcribe", side_effect=err):
        resp = client.post(
            "/api/transcribe",
            files={"audio": ("c.webm", b"x" * 100, "audio/webm")},
        )

    assert resp.status_code == 502
    assert resp.json() == {"error": "transcription_failed"}
    # Crucially, the upstream error message must NOT leak to the client
    # (could include internal IPs, vendor identifiers, etc.).
    assert "503" not in resp.text


# --- Auth gate --------------------------------------------------------------


def test_transcribe_unsigned_redirects_to_login(monkeypatch):
    """No session cookie → auth middleware redirects to /login."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    client, _m = _client()

    resp = client.post(
        "/api/transcribe",
        files={"audio": ("c.webm", b"x" * 100, "audio/webm")},
        follow_redirects=False,
    )

    # Auth middleware redirects unauthenticated POSTs to /login.
    assert resp.status_code in (302, 303, 307)
    assert "/login" in resp.headers.get("location", "")
