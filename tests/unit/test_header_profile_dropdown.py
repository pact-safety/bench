from __future__ import annotations

import base64
import json
import time


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_NON_ADMIN_UUID = "22222222-2222-2222-2222-222222222222"


def _client():
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app), m


def _set_fake_session_cookie(client, *, user_id: str, email: str) -> None:
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


def _authed_client(monkeypatch, *, user_id: str, email: str, admin_uuid: str = _ADMIN_UUID):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", admin_uuid)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=user_id, email=email)
    return client


def test_admin_header_profile_dropdown_shows_admin_links(mock_anthropic, monkeypatch):
    client = _authed_client(
        monkeypatch,
        user_id=_ADMIN_UUID,
        email="admin@example.com",
    )

    response = client.get("/request-access")

    assert response.status_code == 200
    assert "Signed in as" in response.text
    assert "admin@example.com" in response.text
    assert 'href="/admin/access-requests"' in response.text
    assert ">Access requests<" in response.text
    # Feedback inbox moved out of the dropdown into a dedicated
    # top-nav icon button. It still links to /feedback/inbox but is
    # surfaced as an icon with aria-label="Feedback inbox".
    assert 'href="/feedback/inbox"' in response.text
    assert 'aria-label="Feedback inbox' in response.text
    # The icon may render with the badge modifier appended when the open
    # queue is non-empty (`class="header-icon header-icon--has-badge"`),
    # so match the open-quote prefix rather than the closed literal.
    assert 'class="header-icon' in response.text
    assert 'href="/admin/diag/recent-events"' in response.text
    assert ">Recent events<" in response.text


def test_non_admin_header_profile_dropdown_hides_admin_links(mock_anthropic, monkeypatch):
    client = _authed_client(
        monkeypatch,
        user_id=_NON_ADMIN_UUID,
        email="member@example.com",
    )

    response = client.get("/request-access")

    assert response.status_code == 200
    assert "Signed in as" in response.text
    assert "member@example.com" in response.text
    assert "Access requests" not in response.text
    # Inbox icon + dropdown link both admin-gated; non-admin shouldn't
    # see "Feedback inbox" as a label anywhere. The floating-feedback
    # widget's JS does carry "/feedback/inbox" as a literal in its
    # success-message template (rendered post-submit, for everyone),
    # so we check the icon's specific markup absence rather than the
    # bare URL substring.
    assert "Feedback inbox" not in response.text
    assert 'class="header-icon' not in response.text
    assert "Recent events" not in response.text


def test_admin_inbox_icon_replaces_settings_panel(mock_anthropic, monkeypatch):
    """Two structural properties from the 2026-05-27 operator request:
    (a) the icon button is the canonical inbox affordance, and
    (b) /settings no longer renders the old Feedback-inbox panel."""
    client = _authed_client(
        monkeypatch,
        user_id=_ADMIN_UUID,
        email="admin@example.com",
    )

    # (a) icon present on any page that renders base.html.
    home = client.get("/request-access")
    assert home.status_code == 200
    # The icon may render with the badge modifier appended when the open
    # queue is non-empty (`class="header-icon header-icon--has-badge"`),
    # so match the open-quote prefix rather than the closed literal.
    assert 'class="header-icon' in home.text
    assert 'aria-label="Feedback inbox' in home.text

    # (b) /settings doesn't render an h2 titled "Feedback inbox" anymore.
    # We can't easily render /settings here without more mock plumbing,
    # but the template-level absence is verifiable via the raw file:
    from pathlib import Path
    settings_html = Path("templates/settings.html").read_text()
    assert "<h2>Feedback inbox</h2>" not in settings_html


def test_header_profile_dropdown_signout_form_posts_to_logout(mock_anthropic, monkeypatch):
    client = _authed_client(
        monkeypatch,
        user_id=_NON_ADMIN_UUID,
        email="member@example.com",
    )

    response = client.get("/request-access")

    assert response.status_code == 200
    assert '<form method="post" action="/auth/logout" class="profile-menu__signout">' in response.text
