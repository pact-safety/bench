"""Unit coverage for signed-in settings profile routes."""

from __future__ import annotations


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    """Create a TestClient with auth/session mocked to a fixed user."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(m, "_save_user_settings", lambda _uid, _settings: None)
    monkeypatch.setattr(m.assessment_repo, "latest_completed", lambda _uid: None)

    monkeypatch.setattr(
        m.auth_module if hasattr(m, "auth_module") else __import__("app.auth", fromlist=["auth"]),
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="test@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client


def test_settings_profile_defaults_to_read_only_with_edit_button(monkeypatch):
    """Issue #124: /settings profile is read-only by default with an
    explicit Edit button."""
    client = _signed_in_client(monkeypatch)

    r = client.get("/settings", follow_redirects=False)
    assert r.status_code == 200
    assert '<div id="profile-readonly-view"' in r.text
    assert 'id="profile-readonly-view" hidden' not in r.text
    assert 'id="profile-edit-button"' in r.text
    assert 'aria-label="Edit profile settings"' in r.text
    assert 'action="/settings/profile"' in r.text
    assert 'id="profile-edit-form" hidden' in r.text
    assert 'name="display_email"' not in r.text
    assert 'href="https://github.com/settings/emails"' in r.text
    assert 'target="_blank"' in r.text
    assert 'rel="noopener"' in r.text


def test_settings_profile_validation_error_keeps_edit_mode_open(monkeypatch):
    """Validation bounce should reopen edit mode with the error visible."""
    client = _signed_in_client(monkeypatch)

    r = client.post(
        "/settings/profile",
        data={"display_name": "Li", "display_tz": "Mars/Olympus"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert loc.startswith("/settings?")
    assert "profile_error=tz" in loc

    r = client.get(loc, follow_redirects=False)
    assert r.status_code == 200
    assert 'id="profile-readonly-view" hidden' in r.text
    assert 'id="profile-edit-form" hidden' not in r.text
    assert "Not a recognized IANA timezone." in r.text
