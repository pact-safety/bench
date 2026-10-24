"""Observability wiring — Sentry first, others later.

Initialized once at app import time from `app/main.py`. Reads its DSN
from the `SENTRY_DSN` env var (loaded via `app/env.py`, which sees
`.env.local` and shell exports).

Design choices:

- **Sentry only for v1 obs.** Better Stack / PostHog / Resend are
  deferred until the app is deployed multi-user. They add no value to
  a local single-user dev tool, and each one adds a failure mode.
- **Soft-fail on missing DSN.** If `SENTRY_DSN` isn't set we log a
  one-line notice at startup and return — the app continues running.
  Local dev without a Sentry account stays cheap.
- **Performance sampling at 10%.** Traces are cheap on Sentry's free
  tier; 10% is enough to spot p95 outliers without burning the budget.
- **Release tagging from pyproject version.** So errors can be
  attributed to the version that introduced them.
- **PII off by default.** `send_default_pii=False` to keep user
  notes/code out of the error reports. We attach problem slug, route
  name, and HTTP method via tags instead.
"""

from __future__ import annotations

import os
from pathlib import Path


def _read_version() -> str:
    """Read the version from pyproject.toml without adding a dependency."""
    pp = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        for line in pp.read_text().splitlines():
            if line.strip().startswith("version ="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


def init_sentry() -> bool:
    """Initialize Sentry if a DSN is configured. Returns True if the
    SDK was set up (DSN present + import succeeded), False otherwise.

    Idempotent: callers can invoke at module import without worrying
    about double-init."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        # SDK isn't installed in this venv — silent no-op. The app
        # still runs; we just don't ship errors anywhere.
        return False

    environment = os.environ.get("SENTRY_ENVIRONMENT", "local")
    release = os.environ.get("SENTRY_RELEASE", _read_version())
    # Traces sample rate: lower in prod to control cost, full in local
    # so a single user's flow is fully captured for debugging.
    traces_sample_rate = float(
        os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0" if environment == "local" else "0.1")
    )
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        # PII off: user-written notes, code, JD text, and feedback all
        # contain things the user wouldn't want in a third-party
        # error tracker. We tag routes + slugs separately.
        send_default_pii=False,
        # Drop the body/headers from event payloads. The route + status
        # code are enough to find a bug.
        max_request_body_size="never",
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )
    # NOT set here. This used to stamp every event with a hardcoded
    # {"id": "default", "username": "li"}, which was right when bench was
    # single-tenant and is wrong now that other people sign in — it files
    # their errors under the operator. `set_request_user` is called per
    # request from the session middleware instead.
    return True


def crash_for_test() -> None:
    """Diagnostic helper — wired to `GET /__sentry/test` in main.py when
    Sentry is initialized. Raises an unhandled exception so you can
    verify the event makes it to your Sentry inbox."""
    raise RuntimeError("Sentry test — this exception is intentional.")


# ---------------------------------------------------------------------------
# LLM attribution (BEN-145)
#
# Sentry already traces the HTTP transaction, and every LLM call happens
# synchronously inside one — so the *duration* is already visible. What was
# missing is attribution: which model answered, how many tokens it cost, and
# which surface asked. Without that a slow p95 on /problem/<slug> is just a
# slow route.
#
# This hooks the one place every LLM service already funnels through —
# `spend_cap.record_usage_for` — so all ten surfaces are covered without
# touching any of them.
# ---------------------------------------------------------------------------


def note_llm_usage(resp: object, *, service: str | None = None) -> None:
    """Attach model + token counts to the active Sentry span.

    Called from `spend_cap.record_usage_for`, which every LLM-touching
    service already calls after a successful completion.

    Never raises. Observability that can break a user's response is worse
    than no observability — this is bookkeeping, not a feature.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        in_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        model = str(getattr(resp, "model", "") or "unknown")

        data = {
            "llm.model": model,
            "llm.tokens.input": in_tokens,
            "llm.tokens.output": out_tokens,
            "llm.tokens.total": in_tokens + out_tokens,
        }
        if service:
            data["llm.service"] = service

        span = sentry_sdk.get_current_span()
        if span is not None:
            for k, v in data.items():
                span.set_data(k, v)

        # A breadcrumb as well as span data: a request that makes several
        # LLM calls (Mira with a tool loop, a review after a hint) shows
        # each one in order on the error report, not just the last.
        sentry_sdk.add_breadcrumb(
            category="llm",
            level="info",
            message=f"{model} {in_tokens}+{out_tokens} tok",
            data=data,
        )
    except Exception:  # noqa: BLE001 — see docstring
        return


def note_llm_fallback(service: str, reason: str) -> None:
    """Record that a surface took its deterministic path instead of the LLM.

    The fallbacks are silent by design — the user gets a canned hint rather
    than an error — which means a broken API key or an exhausted spend cap
    looks exactly like normal operation from the outside. This is the signal
    that tells them apart.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        span = sentry_sdk.get_current_span()
        if span is not None:
            span.set_data("llm.fallback", f"{service}:{reason}")
        sentry_sdk.add_breadcrumb(
            category="llm.fallback",
            level="warning",
            message=f"{service} fell back ({reason})",
            data={"llm.service": service, "llm.fallback_reason": reason},
        )
    except Exception:  # noqa: BLE001
        return


def set_request_user(user_id: str | None, email: str | None = None) -> None:
    """Scope Sentry events to the signed-in user.

    `init_sentry` used to stamp every event with a hardcoded
    `{"id": "default", "username": "li"}`. That was accurate when bench was
    single-tenant; with alpha users it means every one of their errors is
    filed under the operator, which makes "is this affecting anyone but me?"
    unanswerable.

    Only the opaque user id is sent. Email is accepted for local/dev
    convenience but is NOT forwarded — `send_default_pii=False` is a
    deliberate choice and this would quietly undo it.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        sentry_sdk.set_user({"id": user_id} if user_id else None)
    except Exception:  # noqa: BLE001
        return
