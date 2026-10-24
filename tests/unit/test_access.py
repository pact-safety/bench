"""Tests for app.services.access — personal-access allowlist.

These tests pin the contract for the env-driven, single-tenant gate.
Particularly important: empty allowlist must mean "no restriction"
(so local dev / fresh installs don't silently lock the operator out)
AND a non-empty allowlist must reject by default (so the operator
can't accidentally leave the box open by typo'ing the user id).
"""

from __future__ import annotations

import pytest

from app.services import access


# --- Default state: empty allowlist = no restriction --------------------


def test_allowlist_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    assert access.allowlist_enabled() is False
    # With the allowlist off, every identity is allowed.
    assert access.is_allowed("any-uid", "any@example.com") is True


def test_allowlist_disabled_when_only_whitespace(monkeypatch):
    """Operator might set the var to spaces/commas by accident. That's
    still 'no allowlist' — we treat it the same as unset."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "   ,  ")
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "")
    assert access.allowlist_enabled() is False


# --- Allowlist enabled: only known identities pass -----------------------


def test_allowlist_enabled_admits_known_uid(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "00000000-0000-0000-0000-000000000001")
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    assert access.allowlist_enabled() is True
    assert access.is_allowed("00000000-0000-0000-0000-000000000001", None) is True


def test_allowlist_enabled_admits_known_email(monkeypatch):
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "li@example.com")
    assert access.is_allowed(None, "li@example.com") is True


def test_allowlist_enabled_rejects_unknown(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "li@example.com")
    # Different UUID + different email = blocked.
    assert access.is_allowed("ffffffff-ffff-ffff-ffff-ffffffffffff", "attacker@evil.com") is False


def test_allowlist_either_var_suffices(monkeypatch):
    """The two vars OR — operator can configure whichever's most
    convenient. Matching either admits."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "uid-1,uid-2")
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "li@example.com,backup@example.com")
    # Matches user_id, not email
    assert access.is_allowed("uid-1", "stranger@example.com") is True
    # Matches email, not user_id
    assert access.is_allowed("not-on-list", "backup@example.com") is True


def test_allowlist_case_insensitive(monkeypatch):
    """Email casing varies (Gmail accepts both). Match should be
    case-insensitive on both sides."""
    monkeypatch.setenv("LIS_ALLOWED_EMAILS", "Li@Example.com")
    assert access.is_allowed(None, "li@example.com") is True
    assert access.is_allowed(None, "LI@EXAMPLE.COM") is True


def test_allowlist_csv_parses_multiple(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "uid-1, uid-2 ,uid-3")
    assert access.allowed_user_ids() == {"uid-1", "uid-2", "uid-3"}


def test_allowlist_rejects_falsy_inputs(monkeypatch):
    """An empty user_id / email shouldn't match anything even if the
    allowlist itself has empty entries."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", "real-uid")
    assert access.is_allowed("", "") is False
    assert access.is_allowed(None, None) is False
