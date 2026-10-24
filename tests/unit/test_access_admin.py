"""Unit tests for the admin gate in app.services.access (LIS-301).

`is_admin(user_id)` must be:
  - False when neither LIS_ADMIN_USER_IDS nor LIS_ALLOWED_USER_IDS is set
    (multi-user dev mode — don't accidentally hand out admin)
  - True when user_id is in LIS_ADMIN_USER_IDS
  - True when LIS_ADMIN_USER_IDS is unset and user_id is in
    LIS_ALLOWED_USER_IDS (single-tenant fallback — common today)
  - Case-insensitive on the UUID comparison
  - False for None / empty user_id under any config
"""

from __future__ import annotations

import pytest

from app.services import access


@pytest.fixture(autouse=True)
def _clear_access_env(monkeypatch):
    """Each test starts with neither admin env var set."""
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)


def test_no_lists_set_means_no_admin():
    """Multi-user dev mode (no allowlist at all) MUST NOT default to
    admin = True. Defaulting to admin would expose the cross-user
    feedback inbox to whoever sets up local dev first."""
    assert access.is_admin("any-uuid") is False


def test_explicit_admin_user_id_wins(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", "uuid-a,uuid-b")
    assert access.is_admin("uuid-a") is True
    assert access.is_admin("uuid-b") is True
    assert access.is_admin("uuid-c") is False


def test_falls_back_to_allowed_user_ids_when_admin_unset(monkeypatch):
    """Single-tenant default: the allowlist IS the admin list."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "operator-uuid")
    assert access.is_admin("operator-uuid") is True


def test_admin_var_takes_precedence_over_allowed(monkeypatch):
    """If you set both, LIS_ADMIN_USER_IDS narrows the admin gate —
    an allowlisted-but-not-admin user must NOT pass."""
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", "operator-uuid")
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "operator-uuid,alpha-user-uuid")
    assert access.is_admin("operator-uuid") is True
    # Alpha user is allowed in (is_allowed) but NOT admin (is_admin).
    assert access.is_admin("alpha-user-uuid") is False
    assert access.is_allowed("alpha-user-uuid", None) is True


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", "AAAA-bbbb-cccc")
    assert access.is_admin("aaaa-BBBB-cccc") is True


def test_none_and_empty_never_admin(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", "uuid-a")
    assert access.is_admin(None) is False
    assert access.is_admin("") is False
    assert access.is_admin("   ") is False
