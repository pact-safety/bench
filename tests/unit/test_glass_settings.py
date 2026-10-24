"""FRONTEND-1b: shared glassiness level (settings_json.glass_level)."""

from __future__ import annotations

from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _client(monkeypatch, *, settings: dict | None = None):
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
            user_id=_USER_UUID, email="op@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m, saved


def test_level_persists(monkeypatch):
    client, _m, saved = _client(monkeypatch)
    r = client.post("/settings/glass", data={"glass_level": "80"}, follow_redirects=False)
    assert r.status_code == 303
    assert saved.get("glass_level") == 80


def test_default_fifty_clears_key(monkeypatch):
    client, _m, saved = _client(monkeypatch, settings={"glass_level": 80})
    r = client.post("/settings/glass", data={"glass_level": "50"}, follow_redirects=False)
    assert r.status_code == 303
    assert "glass_level" not in saved


def test_out_of_range_clamps(monkeypatch):
    client, _m, saved = _client(monkeypatch)
    client.post("/settings/glass", data={"glass_level": "400"}, follow_redirects=False)
    assert saved.get("glass_level") == 100


def test_fetch_caller_gets_204(monkeypatch):
    client, _m, saved = _client(monkeypatch)
    r = client.post(
        "/settings/glass",
        data={"glass_level": "30"},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 204
    assert saved.get("glass_level") == 30


def test_html_inline_style_renders_for_hyperbolic(monkeypatch):
    """First paint carries the saved level: base.html derives the two
    glass vars server-side (same formulas as the island)."""
    client, m, _saved = _client(
        monkeypatch, settings={"theme": "hyperbolic", "glass_level": 100}
    )
    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")
    assert "--glass-alpha: 0.85" in r.text
    assert "--glass-blur: 32px" in r.text


def test_no_inline_style_on_dark_default(monkeypatch):
    client, m, _saved = _client(monkeypatch, settings={"glass_level": 100})
    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/login")
    assert "--glass-alpha" not in r.text  # glass is a chamber concept


def test_settings_page_renders_slider_only_for_hyperbolic(monkeypatch):
    client, m, _saved = _client(monkeypatch, settings={"theme": "hyperbolic"})
    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/settings")
    assert 'data-island="glass-slider"' in r.text
    assert 'action="/settings/glass"' in r.text

    client2, m2, _ = _client(monkeypatch, settings={})
    with patch.object(m2.assessment_repo, "latest_completed", return_value=None):
        r2 = client2.get("/settings")
    assert 'data-island="glass-slider"' not in r2.text
