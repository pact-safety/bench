"""Tests for app.services.security — deploy-hardening helpers.

LIS-280 changes (JWT verification, diagnostic gating, spend cap,
security headers) shouldn't regress silently. These pin the public
contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import security


# --- Diagnostics gating ----------------------------------------------------


def test_diagnostics_explicit_on(monkeypatch):
    monkeypatch.setenv("LIS_DIAGNOSTICS_ENABLED", "1")
    assert security.diagnostics_enabled() is True


def test_diagnostics_explicit_off(monkeypatch):
    monkeypatch.setenv("LIS_DIAGNOSTICS_ENABLED", "0")
    assert security.diagnostics_enabled() is False


def test_diagnostics_default_local(monkeypatch):
    monkeypatch.delenv("LIS_DIAGNOSTICS_ENABLED", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "local")
    assert security.diagnostics_enabled() is True


def test_diagnostics_default_prod_off(monkeypatch):
    """Production must default to OFF — even if someone forgets to set
    the explicit env var, the debug endpoints stay closed."""
    monkeypatch.delenv("LIS_DIAGNOSTICS_ENABLED", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")
    assert security.diagnostics_enabled() is False


# --- Spend cap ------------------------------------------------------------


def _iso(offset_hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).isoformat()


def _open(tokens: int) -> dict:
    """An open budget window (reset an hour out) holding `tokens`."""
    return {"anthropic_today": {"resets_at": _iso(1), "tokens": tokens}}


def test_get_usage_zero_when_no_state():
    assert security.get_today_usage({}) == 0
    assert security.get_today_usage({"unrelated": "data"}) == 0


def test_get_usage_zero_after_window_closes():
    """Once the reset instant has passed, the prior count must not carry."""
    settings = {"anthropic_today": {"resets_at": _iso(-1), "tokens": 99999}}
    assert security.get_today_usage(settings) == 0


def test_legacy_date_shape_reads_as_closed():
    """Pre-migration {date,tokens} rows have no resets_at → treated as a
    closed window (a one-time reset on rollout, never a stuck-full cap)."""
    settings = {"anthropic_today": {"date": "2000-01-01", "tokens": 99999}}
    assert security.get_today_usage(settings) == 0


def test_record_usage_starts_window():
    settings = {}
    out = security.record_usage(settings, 1000)
    assert out["anthropic_today"]["tokens"] == 1000
    # A fresh window carries a future UTC reset instant, not a date string.
    resets_at = datetime.fromisoformat(out["anthropic_today"]["resets_at"])
    assert resets_at > datetime.now(timezone.utc)


def test_record_usage_accumulates():
    settings = {}
    security.record_usage(settings, 1000)
    security.record_usage(settings, 500)
    assert settings["anthropic_today"]["tokens"] == 1500


def test_over_cap_triggers_at_threshold():
    settings = _open(100)
    assert security.over_cap(settings, cap=99) is True
    assert security.over_cap(settings, cap=100) is True
    assert security.over_cap(settings, cap=101) is False


def test_remaining_caps_floor_at_zero():
    settings = _open(500)
    assert security.remaining(settings, cap=1000) == 500
    assert security.remaining(settings, cap=400) == 0  # not negative


def test_reset_boundary_follows_display_tz():
    """The window closes at the next midnight in the user's display_tz —
    the same setting the banner shows."""
    # Kiritimati (UTC+14) and Baker Island (UTC-12) bracket the day line;
    # their next-midnight instants must differ, proving tz is honored.
    east = security.record_usage({"display_tz": "Pacific/Kiritimati"}, 1)
    west = security.record_usage({"display_tz": "Etc/GMT+12"}, 1)
    assert east["anthropic_today"]["resets_at"] != west["anthropic_today"]["resets_at"]


def test_tz_flip_cannot_reopen_window_early():
    """A user can't flip display_tz forward to force an early reset: an
    open window keeps its fixed UTC reset instant across further records."""
    settings = {
        "display_tz": "UTC",
        "anthropic_today": {"resets_at": _iso(3), "tokens": 100},
    }
    boundary = settings["anthropic_today"]["resets_at"]
    # Even after "moving" to a timezone where it's already tomorrow, the
    # still-open window keeps counting against the same boundary.
    settings["display_tz"] = "Pacific/Kiritimati"
    security.record_usage(settings, 50)
    assert settings["anthropic_today"]["tokens"] == 150
    assert settings["anthropic_today"]["resets_at"] == boundary


# --- Security headers -----------------------------------------------------


def test_security_headers_include_csp():
    h = security.build_security_headers(is_prod=False)
    assert "Content-Security-Policy" in h
    assert "default-src 'self'" in h["Content-Security-Policy"]
    # HTMX from unpkg must be allowed — it's the only CDN dependency.
    assert "unpkg.com" in h["Content-Security-Policy"]


def test_security_headers_microphone_allowed_for_self():
    """Web Speech needs microphone=(self) so the browser prompts."""
    h = security.build_security_headers(is_prod=False)
    assert "microphone=(self)" in h["Permissions-Policy"]


def test_security_headers_local_no_hsts():
    """HSTS in local dev would break HTTP testing — must NOT be set."""
    h = security.build_security_headers(is_prod=False)
    assert "Strict-Transport-Security" not in h


def test_security_headers_prod_has_hsts():
    h = security.build_security_headers(is_prod=True)
    assert "Strict-Transport-Security" in h
    assert "max-age=63072000" in h["Strict-Transport-Security"]


def test_security_headers_deny_iframe():
    """Defense against clickjacking. DENY > SAMEORIGIN here — we
    never embed the platform inside itself."""
    h = security.build_security_headers(is_prod=False)
    assert h["X-Frame-Options"] == "DENY"


def test_reader_frames_allow_only_atlas_and_preserve_other_boundaries():
    for is_prod in (False, True):
        headers = security.build_security_headers(is_prod=is_prod)
        directives = dict(part.strip().split(' ', 1) for part in headers['Content-Security-Policy'].split(';'))
        assert directives['frame-src'] == 'https://ai-safety-atlas.com'
        assert directives['default-src'] == "'self'"
        assert directives['connect-src'] == "'self'"
        assert directives['frame-ancestors'] == "'none'"
        assert headers['X-Frame-Options'] == 'DENY'
