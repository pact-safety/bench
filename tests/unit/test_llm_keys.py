"""BYO-key routing (app/services/llm_keys) + the spend-cap bypass.

The contract that protects both wallets:
  - no config / 'bench' / no repo → house client, cap applies
  - own key → client built with THAT key (and gateway base_url when
    set), cap does NOT apply (their wallet, not the operator's)
  - BYO config with an unusable key → LlmKeyError, so services take
    their offline fallback — the house key is never silently
    substituted for a broken user key
  - route lookup blowing up (DB blip) → house client (availability)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import llm_keys


class _FakeRepo:
    def __init__(self, provider="bench", key=None, base_url=None, secret_id=None):
        self._route = (provider, key, base_url)
        self._cfg = MagicMock(
            provider=provider,
            vault_secret_id=secret_id,
            base_url=base_url,
        )
        self.provider = provider

    def get(self, user_id):
        return None if self.provider == "none" else self._cfg

    def route_for(self, user_id):
        return self._route


@pytest.fixture(autouse=True)
def _restore_repo():
    prev = llm_keys._repo
    yield
    llm_keys.set_repo(prev)


def test_no_repo_or_no_user_uses_house_client(mock_anthropic):
    llm_keys.set_repo(None)
    assert llm_keys.client_for(None) is mock_anthropic
    assert llm_keys.client_for("some-uid") is mock_anthropic
    assert llm_keys.has_user_key("some-uid") is False


def test_bench_provider_uses_house_client(mock_anthropic):
    llm_keys.set_repo(_FakeRepo(provider="bench"))
    assert llm_keys.client_for("uid") is mock_anthropic
    assert llm_keys.has_user_key("uid") is False


def test_user_key_builds_client_with_key_and_base_url(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, **kw):
            captured.update(kw)

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    llm_keys.set_repo(
        _FakeRepo(provider="omniroute", key="sk-user-1234",
                  base_url="https://gw.example.com", secret_id="sid")
    )
    llm_keys.client_for("uid")
    assert captured == {"api_key": "sk-user-1234", "base_url": "https://gw.example.com"}


def test_anthropic_direct_omits_base_url(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, **kw):
            captured.update(kw)

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    llm_keys.set_repo(_FakeRepo(provider="anthropic", key="sk-user-1234", secret_id="sid"))
    llm_keys.client_for("uid")
    assert captured == {"api_key": "sk-user-1234"}


def test_unusable_user_key_raises_never_house_falls_back(mock_anthropic):
    """Vault row gone / key empty: services must take their offline
    fallback, not the operator's key."""
    llm_keys.set_repo(_FakeRepo(provider="omniroute", key=None, secret_id="sid"))
    with pytest.raises(llm_keys.LlmKeyError):
        llm_keys.client_for("uid")


def test_route_lookup_error_falls_back_to_house(mock_anthropic):
    repo = _FakeRepo()
    repo.route_for = MagicMock(side_effect=RuntimeError("db down"))
    llm_keys.set_repo(repo)
    assert llm_keys.client_for("uid") is mock_anthropic


def test_has_user_key_true_only_with_stored_secret():
    llm_keys.set_repo(_FakeRepo(provider="omniroute", secret_id="sid"))
    assert llm_keys.has_user_key("uid") is True
    llm_keys.set_repo(_FakeRepo(provider="omniroute", secret_id=None))
    assert llm_keys.has_user_key("uid") is False


def test_spend_cap_bypassed_for_byo_key(monkeypatch):
    """over_cap_for must return False for a BYO-key user even when the
    counter is far over the cap — the cap protects the operator's
    wallet, and this is not the operator's wallet."""
    from app.services import spend_cap

    llm_keys.set_repo(_FakeRepo(provider="anthropic", secret_id="sid"))
    monkeypatch.setattr(
        spend_cap, "_try_load_settings",
        lambda uid: {"anthropic_today": {"date": "2026-08-18", "tokens": 10**9}},
    )
    assert spend_cap.over_cap_for("uid", "hint") is False


def test_spend_cap_still_applies_without_byo_key(monkeypatch):
    from app.services import security, spend_cap

    llm_keys.set_repo(_FakeRepo(provider="bench"))
    over = {"seen": None}

    def _fake_over_cap(settings):
        over["seen"] = settings
        return True

    monkeypatch.setattr(spend_cap, "_try_load_settings", lambda uid: {"x": 1})
    monkeypatch.setattr(security, "over_cap", _fake_over_cap)
    assert spend_cap.over_cap_for("uid", "hint") is True
    assert over["seen"] == {"x": 1}
