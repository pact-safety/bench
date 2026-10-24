"""Spend cap enforcement around Anthropic API calls.

The pure-functional helpers in `security.py` (PR #32) implement the
counter (`get_today_usage`, `record_usage`, `over_cap`). This module
*wires* them to each LLM-touching service via two thin hooks:

  - `over_cap_for(user_id, service)` — call before `messages.create()`.
    Returns True if the user is at or over their daily token budget,
    in which case the service should return its deterministic offline
    fallback instead of hitting the API.
  - `record_usage_for(user_id, resp, service=...)` — call after a successful
    `messages.create()`. Reads `resp.usage.{input,output}_tokens` and
    bumps the counter in the user's `settings_json`.

Both are **best-effort**: any infrastructure glitch (settings load
fails, response shape unexpected) logs a warning and proceeds without
blocking the user. The cap is a circuit breaker against a runaway
loop, not a hard correctness boundary — preferring availability over
strict enforcement when the recording path itself is broken keeps the
app responsive during partial outages.

Why a separate module from `security.py`: the helpers there are pure
(no DB access, no app coupling). This module imports `app.main` for
the cached `_user_settings` / `_save_user_settings` machinery — a
late import to avoid a circular dependency. Keeping it out of
`security.py` means `security.py` stays unit-testable in isolation
and `spend_cap.py` carries the app-coupling caveat in one place.

`user_id=None` means "no cap, don't record". Use this from background
jobs, tests, or any LLM call not on a specific user's behalf — the
hooks become no-ops.
"""

from __future__ import annotations

import logging
from typing import Any

from . import security as _security


_log = logging.getLogger(__name__)


def over_cap_for(user_id: str | None, service: str) -> bool:
    """Pre-call gate. True if the user's already at or over today's
    cap; service callers should bypass the API and use their fallback.

    The settings-load is wrapped: a transient DB issue must not turn
    every hint into an over-cap response, so we fail open (return False)
    if we can't read the settings."""
    if not user_id:
        return False
    # BYO key (Bench v2): the cap is a circuit breaker for the
    # OPERATOR's wallet. A user routing through their own key spends
    # their own money — never gate them here. Checked at this single
    # chokepoint so no protected call site needs its own logic.
    from . import llm_keys

    if llm_keys.has_user_key(user_id):
        return False
    settings = _try_load_settings(user_id)
    if settings is None:
        return False
    is_over = _security.over_cap(settings)
    if is_over:
        _log.warning(
            "spend cap reached: user_id=%s service=%s usage=%d cap=%d",
            user_id, service,
            _security.get_today_usage(settings),
            _security.DEFAULT_DAILY_TOKEN_CAP,
        )
        # Sentry breadcrumb so operators can see cap hits without
        # opening logs. Best-effort.
        try:
            import sentry_sdk
            sentry_sdk.add_breadcrumb(
                category="spend_cap",
                message=f"cap hit for {service}",
                level="warning",
                data={
                    "user_id": user_id,
                    "service": service,
                    "usage": _security.get_today_usage(settings),
                    "cap": _security.DEFAULT_DAILY_TOKEN_CAP,
                },
            )
        except Exception:
            pass
    return is_over


def record_usage_for(
    user_id: str | None, resp: Any, service: str | None = None
) -> None:
    """Post-call bookkeeping. Pulls `resp.usage.input_tokens` +
    `output_tokens` and bumps the user's counter; when `service` is
    given, also writes one custody line to the audit ledger (BEN-144
    follow-up) and attributes the Sentry span (BEN-145).

    `service=None` means the caller owns its own ledger line (mira's
    `_audit_turn`) — no custody line is written here.

    Wrapped: bookkeeping failures must not break the user's response.
    If `resp` doesn't have a `.usage` attribute (e.g. some mock
    responses in tests), we silently return."""
    if not user_id:
        return
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        in_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total = in_tokens + out_tokens

        # BEN-145 — attribution for the active Sentry span. Deliberately
        # before the `total <= 0` bail: a zero-token response is exactly the
        # kind of thing worth seeing in a trace.
        try:
            from ..observability import note_llm_usage

            note_llm_usage(resp, service=service)
        except Exception:  # noqa: BLE001 — never break a user's response
            pass

        # BEN-144: one custody line per LLM call, written from the
        # chokepoint every service already routes through. Like the
        # Sentry note above, deliberately before the zero-token bail —
        # a zero-token call is exactly what a ledger should show.
        # `wallet` says whose money the call spent (BYO-key users pay
        # their own provider; the cap above only guards 'house').
        if service:
            try:
                from . import audit_log, llm_keys

                audit_log.record(
                    capability=service,
                    model=str(getattr(resp, "model", "") or "unknown"),
                    payload={
                        "wallet": "user" if llm_keys.has_user_key(user_id) else "house",
                    },
                    redaction_applied=[],
                    dropped=[],
                    usage={
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                    },
                )
            except Exception:  # noqa: BLE001 — never break a user's response
                pass

        if total <= 0:
            return
        settings = _try_load_settings(user_id)
        if settings is None:
            return
        _security.record_usage(settings, total)
        _try_save_settings(user_id, settings)
    except Exception as e:
        _log.warning("spend cap record failed: %s", e)


# ---------- Late-imported settings accessors --------------------------------
#
# `app.main` instantiates the cached `_user_settings` / `_save_user_settings`
# helpers we want to call here, but importing `app.main` at module load
# time would create a circular import (services are imported by main).
# Defer to the first call so the wiring resolves cleanly.


def _try_load_settings(user_id: str) -> dict | None:
    try:
        from ..main import _user_settings  # type: ignore[attr-defined]
        return _user_settings(user_id)
    except Exception as e:
        _log.warning("spend cap: could not load settings for %s: %s", user_id, e)
        return None


def _try_save_settings(user_id: str, settings: dict) -> None:
    try:
        from ..main import _save_user_settings  # type: ignore[attr-defined]
        _save_user_settings(user_id, settings)
    except Exception as e:
        _log.warning("spend cap: could not save settings for %s: %s", user_id, e)
