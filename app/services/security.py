"""Deploy-hardening helpers (LIS-280).

Three concerns live here:

  1. Anthropic spend cap. A daily per-user token counter. Before every
     Sonnet/Haiku call, check; if the user is over the daily limit,
     return a friendly degrade (the LLM-touching service falls back
     to its offline path).

  2. Security headers middleware factory. Strict-Transport-Security,
     Content-Security-Policy, X-Frame-Options, etc. Applied on every
     response.

  3. Diagnostic-route gating. `/__sentry/*`, `/__claude/*` and friends
     should only be reachable when `LIS_DIAGNOSTICS_ENABLED=1`.

All three are pure-functional / decorator-shaped so they can be unit
tested without booting FastAPI.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - stdlib zoneinfo present on 3.9+
    ZoneInfo = None  # type: ignore[assignment,misc]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass


_UTC = timezone.utc


# --- Diagnostic gating ----------------------------------------------------


def diagnostics_enabled() -> bool:
    """`LIS_DIAGNOSTICS_ENABLED=1` opens the /__sentry/* and /__claude/*
    debug endpoints. Defaults OFF in production; defaults ON for local
    dev so the diagnostic toolkit works without ceremony.

    The env-var dance is so deploys can decide explicitly. Setting
    SENTRY_ENVIRONMENT=prod alone is NOT enough to flip this off —
    we want the decision recorded as its own setting.
    """
    explicit = os.environ.get("LIS_DIAGNOSTICS_ENABLED")
    if explicit is not None:
        return explicit.strip() in ("1", "true", "yes")
    # Defaults: off in production, on everywhere else.
    return os.environ.get("SENTRY_ENVIRONMENT", "local").lower() not in ("prod", "production")


# --- Anthropic spend cap --------------------------------------------------

# Default daily token budget. Pulled into config later if needed; for
# now a single platform-wide cap is fine since this is single-user.
# 200k tokens at sonnet-4-5 prices is ~$3/day — generous for one
# person, cheap as a circuit breaker.
DEFAULT_DAILY_TOKEN_CAP = int(os.environ.get("ANTHROPIC_DAILY_TOKEN_CAP", "200000"))


def _safe_zone(tz_name: str | None):
    """User's display_tz → tzinfo, falling back to UTC for blank/unknown
    values. The cap must never crash on a bad tz string."""
    if not tz_name or ZoneInfo is None:
        return _UTC
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return _UTC


def _next_local_midnight_utc(settings: dict[str, Any] | None) -> str:
    """The UTC instant of the next midnight in the user's display_tz.

    Stored as UTC so a later timezone change can't move an already-open
    budget window: the window closes at a fixed instant, computed once when
    it opened. This is what stops a user from flipping display_tz forward to
    force an early reset and slip past the daily cap."""
    tz = _safe_zone((settings or {}).get("display_tz"))
    now_local = datetime.now(tz)
    tomorrow = (now_local + timedelta(days=1)).date()
    midnight_local = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=tz)
    return midnight_local.astimezone(_UTC).isoformat()


def _window_open(state: dict[str, Any]) -> bool:
    """True while the stored budget window hasn't reached its reset instant.
    A missing/invalid resets_at — including the pre-migration {date,tokens}
    shape — reads as closed, so the counter resets once on rollout (harmless:
    the user just gets a fresh budget)."""
    raw = state.get("resets_at")
    if not raw:
        return False
    try:
        resets_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return False
    if resets_at.tzinfo is None:
        resets_at = resets_at.replace(tzinfo=_UTC)
    return datetime.now(_UTC) < resets_at


def get_today_usage(settings: dict[str, Any]) -> int:
    """Read the current budget window's token count. Returns 0 once the
    window has closed — auto-reset at the user's local midnight."""
    state = (settings or {}).get("anthropic_today") or {}
    if not _window_open(state):
        return 0
    try:
        return int(state.get("tokens", 0))
    except (TypeError, ValueError):
        return 0


def record_usage(settings: dict[str, Any], tokens: int) -> dict[str, Any]:
    """Mutates+returns the settings dict with the current window's token
    count incremented. Opens a fresh window (resets_at = next local
    midnight, as a fixed UTC instant) when the previous one has closed.
    Caller persists via _save_user_settings()."""
    state = (settings or {}).get("anthropic_today") or {}
    if _window_open(state):
        resets_at = state["resets_at"]
        cur = get_today_usage(settings)
    else:
        resets_at = _next_local_midnight_utc(settings)
        cur = 0
    settings["anthropic_today"] = {
        "resets_at": resets_at,
        "tokens": cur + max(0, int(tokens)),
    }
    return settings


def over_cap(settings: dict[str, Any], cap: int | None = None) -> bool:
    """True if today's accumulated usage is at or over the cap."""
    return get_today_usage(settings) >= (cap if cap is not None else DEFAULT_DAILY_TOKEN_CAP)


def remaining(settings: dict[str, Any], cap: int | None = None) -> int:
    """How many tokens the user has left in today's budget."""
    limit = cap if cap is not None else DEFAULT_DAILY_TOKEN_CAP
    return max(0, limit - get_today_usage(settings))


# --- Security headers middleware ------------------------------------------


def build_security_headers(*, is_prod: bool) -> dict[str, str]:
    """Return the set of security headers to attach on every response.

    Split as a pure function so it's trivially testable and so the
    middleware can read it once at startup. CSP is intentionally
    permissive enough to allow:
      - htmx.org from unpkg (the only CDN this app uses)
      - inline scripts/styles (we use a handful of inline tags in
        base.html for theme bootstrap; tightening this would require
        moving them to nonce'd external files)
      - data: URIs for the SVG favicon
    """
    csp_parts = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://unpkg.com",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-src https://ai-safety-atlas.com",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    headers = {
        "Content-Security-Policy": "; ".join(csp_parts),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": (
            # We DO use the microphone for voice notes; allow self
            # (Web Speech needs the permissions header set or browsers
            # block the prompt). Camera + geolocation = denied.
            "microphone=(self), camera=(), geolocation=()"
        ),
    }
    if is_prod:
        # 2-year HSTS with preload eligibility. Only set in production
        # — local dev over HTTP should never see this (the cookie
        # `secure` flag pivots on the same env signal).
        headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
    return headers
