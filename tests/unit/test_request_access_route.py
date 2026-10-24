"""Integration-ish test for the /request-access form + POST handler.

Uses FastAPI's TestClient so we exercise:
  - The middleware path (public route → no auth gate)
  - The form rendering (200, contains alpha pill class)
  - The honeypot bounce (filled `website` → thanks page, no DB row)
  - The validation error path
  - The success path with the notification stubbed

The access_request_repo is patched module-level so the test doesn't
need a real Postgres."""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _client():
    """Late-import so the conftest env (LIS_NO_DB=1 etc.) takes effect
    before app.main loads."""
    import app.main as m
    from fastapi.testclient import TestClient
    return TestClient(m.app), m


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_NON_ADMIN_UUID = "22222222-2222-2222-2222-222222222222"


def _set_fake_session_cookie(client, *, user_id: str, email: str = "user@example.com") -> None:
    """Set a minimally-shaped auth cookie accepted by local test auth.

    In unit tests we run in local mode without SUPABASE_JWT_SECRET,
    so auth parsing falls back to unverified payload decode.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + 3600,
    }).encode()).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _authed_client(monkeypatch, *, user_id: str, admin_uuid: str = _ADMIN_UUID):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", admin_uuid)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=user_id, email=f"{user_id[:8]}@example.com")
    return client, m


def test_get_request_access_renders_form(mock_anthropic):
    client, _m = _client()
    r = client.get("/request-access")
    assert r.status_code == 200
    assert "Request access" in r.text
    # Alpha pill must show on this public page.
    assert "alpha-pill" in r.text
    # The honeypot input must be present (the bot trap).
    assert 'name="website"' in r.text
    # Local static assets should include a hash query param so
    # content changes invalidate browser caches automatically.
    assert re.search(r'href="/static/css/main\.css\?v=(?:[0-9a-f]{10}|0)"', r.text)
    assert re.search(r'src="/static/js/autosave\.js\?v=(?:[0-9a-f]{10}|0)"', r.text)
    assert re.search(r'src="/static/js/voice-note\.js\?v=(?:[0-9a-f]{10}|0)"', r.text)


def test_get_request_access_prefills_email(mock_anthropic):
    client, _m = _client()
    r = client.get("/request-access?email=foo%40bar.com")
    assert r.status_code == 200
    assert 'value="foo@bar.com"' in r.text


def test_feedback_widget_sets_htmx_parameters_from_current_context(mock_anthropic):
    """Regression test for issue #8: submit-time metadata must come
    from current DOM state, not stale hidden-input values."""
    client, _m = _client()
    r = client.get("/request-access")
    assert r.status_code == 200

    # Theme should be read from the live <html data-theme="..."> state.
    # (#378: report the actual theme key — hyperbolic etc. — with the
    # attribute-less default being "dark", instead of collapsing every
    # theme to dark/light.)
    assert 'document.documentElement.dataset.theme || "dark"' in r.text
    # htmx:configRequest fires after HTMX has built parameters, so the
    # handler must overwrite request params directly.
    assert "evt.detail.parameters.url = context.url;" in r.text
    assert "evt.detail.parameters.page_title = context.pageTitle;" in r.text
    assert "evt.detail.parameters.theme = context.theme;" in r.text
    assert "evt.detail.parameters.viewport_width = String(context.viewportWidth);" in r.text


def test_post_honeypot_bounces_without_inserting(mock_anthropic):
    client, m = _client()
    with patch.object(m.access_request_repo, "insert") as insert_mock, \
         patch.object(m.access_request_repo, "has_recent_pending", return_value=False):
        r = client.post("/auth/request-access", data={
            "name": "Bot", "email": "bot@bot.com",
            "website": "https://spam.example",  # honeypot tripped
        })
        # User-facing: success-shaped (don't tell the bot)
        assert r.status_code == 200
        assert "Thanks" in r.text
        # But no row written.
        insert_mock.assert_not_called()


def test_post_validation_error_missing_name(mock_anthropic):
    client, _m = _client()
    r = client.post("/auth/request-access", data={
        "name": "", "email": "ok@example.com",
    })
    assert r.status_code == 400
    assert "required" in r.text.lower()
    # Form is re-rendered with the email preserved.
    assert 'value="ok@example.com"' in r.text


def test_post_success_inserts_and_notifies(mock_anthropic, monkeypatch):
    client, m = _client()
    fake_insert = MagicMock(return_value=123)
    fake_send = MagicMock(return_value=True)
    with patch.object(m.access_request_repo, "insert", fake_insert), \
         patch.object(m.access_request_repo, "has_recent_pending", return_value=False):
        # Stub the email sender so the test doesn't hit Resend.
        from app.services import notifications
        monkeypatch.setattr(notifications, "send_operator_email", fake_send)

        r = client.post("/auth/request-access", data={
            "name": "Dana",
            "email": "dana@example.com",
            "github_handle": "@dana",
            "note": "Working on interp.",
        })
        assert r.status_code == 200
        assert "Thanks" in r.text
        # The thanks page surfaces both the request id and the email
        # so the submitter knows where the follow-up will land.
        assert "123" in r.text
        assert "dana@example.com" in r.text

        # Repo got the right kwargs.
        fake_insert.assert_called_once()
        call_kwargs = fake_insert.call_args.kwargs
        assert call_kwargs["name"] == "Dana"
        assert call_kwargs["email"] == "dana@example.com"
        assert call_kwargs["github_handle"] == "@dana"
        assert call_kwargs["note"] == "Working on interp."
        # Email got sent (or attempted, since send is soft-fail).
        fake_send.assert_called_once()


def test_post_dedupes_recent_pending(mock_anthropic):
    """Submitting twice in quick succession must not double-insert."""
    client, m = _client()
    fake_insert = MagicMock()
    with patch.object(m.access_request_repo, "insert", fake_insert), \
         patch.object(m.access_request_repo, "has_recent_pending", return_value=True):
        r = client.post("/auth/request-access", data={
            "name": "Dana", "email": "dana@example.com",
        })
        assert r.status_code == 200
        assert "Thanks" in r.text
        fake_insert.assert_not_called()


def test_admin_get_access_requests_requires_admin(mock_anthropic, monkeypatch):
    client, _m = _authed_client(monkeypatch, user_id=_NON_ADMIN_UUID)
    r = client.get("/admin/access-requests")
    assert r.status_code == 403


def test_admin_get_access_requests_renders_rows(mock_anthropic, monkeypatch):
    from app.repositories.access_request_repository import AccessRequest

    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    rows = [
        AccessRequest(
            id=41,
            name="Dana",
            email="dana@example.com",
            github_handle="@dana",
            note="Working on interp",
            ip="127.0.0.1",
            user_agent="pytest",
            status="pending",
            created_at=datetime(2026, 5, 16, 3, 0, 0),
            processed_at=None,
            processed_note=None,
        )
    ]
    with patch.object(m.access_request_repo, "list_recent", return_value=rows) as list_mock, \
         patch.object(m.allowlist_repo, "list_active", return_value=[]), \
         patch.object(
             m.access_request_repo,
             "counts_by_status",
             return_value={"pending": 1, "granted": 0, "declined": 0},
         ):
        r = client.get("/admin/access-requests")
        assert r.status_code == 200
        list_mock.assert_called_once_with(status="pending", limit=200)
        assert "Access requests" in r.text
        assert "Dana" in r.text
        assert "dana@example.com" in r.text


@pytest.mark.parametrize("status", ["pending", "granted", "declined"])
def test_admin_get_access_requests_filters_by_status(mock_anthropic, monkeypatch, status):
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    with patch.object(m.access_request_repo, "list_recent", return_value=[]) as list_mock, \
         patch.object(m.allowlist_repo, "list_active", return_value=[]), \
         patch.object(
             m.access_request_repo,
             "counts_by_status",
             return_value={"pending": 0, "granted": 0, "declined": 0},
         ):
        r = client.get(f"/admin/access-requests?status={status}")
        assert r.status_code == 200
        list_mock.assert_called_once_with(status=status, limit=200)


def _fake_request(req_id=41, email="dana@example.com", status="pending"):
    from app.repositories.access_request_repository import AccessRequest

    return AccessRequest(
        id=req_id,
        name="Dana",
        email=email,
        github_handle=None,
        note=None,
        ip=None,
        user_agent=None,
        status=status,
        created_at=datetime(2026, 5, 16, 3, 0, 0),
        processed_at=None,
        processed_note=None,
    )


def test_admin_post_access_request_status_updates_and_redirects(mock_anthropic, monkeypatch):
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    set_status = MagicMock()
    grant = MagicMock()
    with patch.object(m.access_request_repo, "set_status", set_status), \
         patch.object(m.access_request_repo, "get", return_value=_fake_request()), \
         patch.object(m.allowlist_repo, "grant", grant):
        r = client.post(
            "/admin/access-requests/41/status",
            data={"status": "granted", "processed_note": "added to allowlist"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/access-requests"
        set_status.assert_called_once_with(41, "granted", "added to allowlist")
        # Bench v2: granting the request IS the grant — the DB
        # allowlist gets the email, no deploy required.
        grant.assert_called_once_with(
            "dana@example.com",
            added_by=_ADMIN_UUID,
            access_request_id=41,
            note="added to allowlist",
        )


def test_admin_post_decline_revokes_allowlist_entry(mock_anthropic, monkeypatch):
    """Flipping a request to declined pulls any existing grant, so
    'declined' in the triage UI always means 'cannot sign in'."""
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    revoke = MagicMock()
    with patch.object(m.access_request_repo, "set_status", MagicMock()), \
         patch.object(m.access_request_repo, "get",
                      return_value=_fake_request(status="granted")), \
         patch.object(m.allowlist_repo, "revoke", revoke):
        r = client.post(
            "/admin/access-requests/41/status",
            data={"status": "declined", "processed_note": ""},
            follow_redirects=False,
        )
        assert r.status_code == 303
        revoke.assert_called_once_with("dana@example.com")


def test_admin_allowlist_add_grants_directly(mock_anthropic, monkeypatch):
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    grant = MagicMock()
    with patch.object(m.allowlist_repo, "grant", grant):
        r = client.post(
            "/admin/allowlist/add",
            data={"email": "  Demo@Example.COM ", "note": "Mac demo"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        grant.assert_called_once_with(
            "demo@example.com", added_by=_ADMIN_UUID, note="Mac demo"
        )


def test_admin_allowlist_add_rejects_bad_email(mock_anthropic, monkeypatch):
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    grant = MagicMock()
    with patch.object(m.allowlist_repo, "grant", grant):
        r = client.post("/admin/allowlist/add", data={"email": "not-an-email"})
        assert r.status_code == 400
        grant.assert_not_called()


def test_admin_allowlist_revoke_revokes(mock_anthropic, monkeypatch):
    client, m = _authed_client(monkeypatch, user_id=_ADMIN_UUID)
    revoke = MagicMock()
    with patch.object(m.allowlist_repo, "revoke", revoke):
        r = client.post(
            "/admin/allowlist/revoke",
            data={"email": "dana@example.com"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        revoke.assert_called_once_with("dana@example.com")


@pytest.mark.parametrize("path,data", [
    ("/admin/allowlist/add", {"email": "x@y.com"}),
    ("/admin/allowlist/revoke", {"email": "x@y.com"}),
])
def test_admin_allowlist_routes_require_admin(mock_anthropic, monkeypatch, path, data):
    client, _m = _authed_client(monkeypatch, user_id=_NON_ADMIN_UUID)
    r = client.post(path, data=data)
    assert r.status_code == 403


def test_admin_post_access_request_status_requires_admin(mock_anthropic, monkeypatch):
    client, _m = _authed_client(monkeypatch, user_id=_NON_ADMIN_UUID)
    r = client.post(
        "/admin/access-requests/41/status",
        data={"status": "declined", "processed_note": "not a fit"},
    )
    assert r.status_code == 403
