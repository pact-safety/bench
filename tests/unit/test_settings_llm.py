"""Tests for the AI-provider settings panel (/settings/llm, BYO-key).

Security contract pinned here: the stored key NEVER round-trips to
the page (only its last-4 hint), 'bench' clears the stored key
(vault secret included, via delete_for), and validation failures
save nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

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
            email="user@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m


def _fake_cfg(provider="omniroute", hint="cdef", base_url="https://gw.example.com"):
    cfg = MagicMock()
    cfg.provider = provider
    cfg.key_hint = hint
    cfg.base_url = base_url
    cfg.vault_secret_id = "sid"
    return cfg


def test_settings_page_shows_panel_and_hint_but_never_the_key(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m, "assessment_repo") as ar, \
         patch.object(m.llm_config_repo, "get", return_value=_fake_cfg()):
        ar.latest_completed.return_value = None
        r = client.get("/settings")
    assert r.status_code == 200
    assert "AI provider" in r.text
    assert "cdef" in r.text            # the last-4 hint renders
    assert "sk-user" not in r.text     # no key material anywhere


def test_save_bench_clears_stored_key(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    delete_for = MagicMock()
    with patch.object(m.llm_config_repo, "delete_for", delete_for):
        r = client.post(
            "/settings/llm",
            data={"llm_provider": "bench"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    delete_for.assert_called_once_with(_USER_UUID)


def test_save_omniroute_stores_key_and_origin(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.llm_config_repo, "get", return_value=None), \
         patch.object(m.llm_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/llm",
            data={
                "llm_provider": "omniroute",
                "llm_api_key": "  sk-user-abcdef  ",
                "llm_base_url": "https://gw.example.com/",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    set_config.assert_called_once_with(
        _USER_UUID,
        provider="omniroute",
        api_key="sk-user-abcdef",
        base_url="https://gw.example.com",  # trailing slash trimmed
    )


def test_save_without_key_bounces_unless_one_is_stored(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.llm_config_repo, "get", return_value=None), \
         patch.object(m.llm_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/llm",
            data={"llm_provider": "anthropic", "llm_api_key": ""},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "llm_error=key" in r.headers["location"]
    set_config.assert_not_called()


def test_save_keeps_stored_key_when_field_left_blank(mock_anthropic, monkeypatch):
    """Provider/URL edits must not force re-entering the key."""
    client, m = _signed_in_client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.llm_config_repo, "get", return_value=_fake_cfg()), \
         patch.object(m.llm_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/llm",
            data={
                "llm_provider": "omniroute",
                "llm_api_key": "",
                "llm_base_url": "https://new-gw.example.com",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    set_config.assert_called_once_with(
        _USER_UUID,
        provider="omniroute",
        api_key=None,
        base_url="https://new-gw.example.com",
    )


def test_omniroute_requires_https_url(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.llm_config_repo, "get", return_value=None), \
         patch.object(m.llm_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/llm",
            data={
                "llm_provider": "omniroute",
                "llm_api_key": "sk-x",
                "llm_base_url": "http://insecure.example.com",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "llm_error=url" in r.headers["location"]
    set_config.assert_not_called()


def test_unknown_provider_rejected(mock_anthropic, monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    r = client.post("/settings/llm", data={"llm_provider": "evil"})
    assert r.status_code == 400
