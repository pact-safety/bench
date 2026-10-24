"""Tests for the DB-backed allowlist union in app.services.access
(Bench v2 invite flow).

Contract being pinned:
  - env vars and the DB source are UNION'd — either admits
  - a DB-only allowlist still counts as "enabled" (gate closes even
    with no env vars set)
  - a failing DB source fails CLOSED (contributes nothing) without
    breaking the env-var back-door
  - the admin gate is deliberately NOT widened by DB entries
"""

from __future__ import annotations

import pytest

from app.services import access


@pytest.fixture(autouse=True)
def _clean_slate(monkeypatch):
    """No env allowlist, and restore whatever DB source app.main may
    have registered (pytest shares one process across test files)."""
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    prev = access._db_email_source
    yield
    access.set_db_email_source(prev)


def test_no_source_registered_means_no_restriction():
    access.set_db_email_source(None)
    assert access.allowlist_enabled() is False
    assert access.is_allowed("any-uid", "any@example.com") is True


def test_db_only_allowlist_enables_the_gate():
    access.set_db_email_source(lambda: {"dana@example.com"})
    assert access.allowlist_enabled() is True
    assert access.is_allowed(None, "dana@example.com") is True
    assert access.is_allowed(None, "stranger@example.com") is False


def test_db_and_env_are_unioned(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "li@example.com")
    access.set_db_email_source(lambda: {"dana@example.com"})
    assert access.is_allowed(None, "li@example.com") is True
    assert access.is_allowed(None, "dana@example.com") is True
    assert access.is_allowed(None, "stranger@example.com") is False


def test_db_source_normalizes_case_and_whitespace():
    access.set_db_email_source(lambda: {"  MiXeD@Case.COM "})
    assert access.is_allowed(None, "mixed@case.com") is True
    assert access.is_allowed(None, "MIXED@CASE.COM") is True


def test_failing_source_fails_closed_but_env_backdoor_survives(monkeypatch):
    def _boom() -> set[str]:
        raise RuntimeError("db down")

    access.set_db_email_source(_boom)
    # DB contributes nothing...
    assert access.db_allowed_emails() == set()
    # ...with no env vars the gate is simply off (local-dev shape)...
    assert access.allowlist_enabled() is False
    # ...and with env vars set, the operator still gets in while the
    # DB-granted user is (correctly) rejected until the DB is back.
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "li@example.com")
    assert access.is_allowed(None, "li@example.com") is True
    assert access.is_allowed(None, "dana@example.com") is False


def test_db_entries_do_not_grant_admin(monkeypatch):
    """A DB grant admits the user but must never widen the admin gate:
    is_admin stays env-UUID-only by design."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "operator-uuid")
    access.set_db_email_source(lambda: {"dana@example.com"})
    assert access.is_allowed(None, "dana@example.com") is True
    assert access.is_admin("dana@example.com") is False
    assert access.admin_user_ids() == {"operator-uuid"}
