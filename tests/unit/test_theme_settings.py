"""Tests for the per-user UI theme.

A theme is stored as a bare `theme` key in `users.settings_json` and
rendered as `data-theme` on <html> by base.html. The CSS side is ~9
primitive overrides under `:root[data-theme="<key>"]`.
"""

from __future__ import annotations

from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch, *, settings: dict | None = None):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    store = dict(settings or {})
    monkeypatch.setattr(m, "_user_settings", lambda _uid: dict(store))
    saved: dict = {}

    def _save(_uid, s):
        saved.clear()
        saved.update(s)

    monkeypatch.setattr(m, "_save_user_settings", _save)
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
    return client, m, saved


# ---------------------------------------------------------------------------
# Persisting a choice
# ---------------------------------------------------------------------------


def test_saving_a_known_theme_persists_it(monkeypatch):
    client, _m, saved = _signed_in_client(monkeypatch)

    r = client.post(
        "/settings/theme", data={"theme": "hyperbolic"}, follow_redirects=False
    )

    assert r.status_code == 303
    assert saved.get("theme") == "hyperbolic"


def test_saving_empty_clears_back_to_default(monkeypatch):
    """The default (dark) is the absence of a key — not a stored value."""
    client, _m, saved = _signed_in_client(monkeypatch, settings={"theme": "hyperbolic"})

    r = client.post("/settings/theme", data={"theme": ""}, follow_redirects=False)

    assert r.status_code == 303
    assert "theme" not in saved


def test_unknown_theme_is_rejected(monkeypatch):
    """Guards the rendered data-theme attribute: a hand-crafted POST must
    not be able to inject an arbitrary value."""
    client, _m, saved = _signed_in_client(monkeypatch)

    r = client.post(
        "/settings/theme",
        data={"theme": '" onload="alert(1)'},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "theme" not in saved


def test_theme_keys_whitelist_matches_declared_themes(monkeypatch):
    import app.main as m

    assert "hyperbolic" in m.THEME_KEYS
    # The default is the empty key and must never be in the whitelist.
    assert "" not in m.THEME_KEYS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_saved_theme_renders_as_data_theme_on_html(monkeypatch):
    client, m, _saved = _signed_in_client(monkeypatch, settings={"theme": "hyperbolic"})

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")

    assert r.status_code == 200
    assert 'data-theme="hyperbolic"' in r.text


def test_default_renders_no_data_theme_attribute(monkeypatch):
    """Dark is :root, so the default must emit no attribute at all."""
    client, m, _saved = _signed_in_client(monkeypatch, settings={})

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")

    assert r.status_code == 200
    assert "data-theme=" not in r.text


def test_saved_theme_mirrors_into_localstorage(monkeypatch):
    """Signed-in pages force localStorage to the SAVED theme via Jinja —
    not by reading the DOM, which the head script may have painted from
    stale localStorage (that read-back loop made switching to dark
    impossible once another theme had ever been saved)."""
    client, m, _saved = _signed_in_client(monkeypatch, settings={"theme": "hyperbolic"})

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")

    assert 'localStorage.setItem("theme", "hyperbolic")' in r.text


def test_default_clears_stale_localstorage_and_attribute(monkeypatch):
    """Saved default (dark) must clear a stale localStorage theme AND
    strip the attribute the head script may have painted this load."""
    client, m, _saved = _signed_in_client(monkeypatch, settings={})

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")

    assert 'localStorage.removeItem("theme")' in r.text
    assert 'removeAttribute("data-theme")' in r.text


def test_settings_page_renders_theme_picker(monkeypatch):
    client, m, _saved = _signed_in_client(monkeypatch, settings={"theme": "hyperbolic"})

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/settings")

    assert r.status_code == 200
    assert 'action="/settings/theme"' in r.text
    assert 'value="hyperbolic"' in r.text
    assert "Hyperbolic Time Chamber" in r.text
