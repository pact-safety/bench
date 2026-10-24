"""Transactional email — currently used only for operator alerts on
new access requests.

Provider: Resend (https://resend.com). Single HTTPS POST per email,
no SDK to vendor. Free tier is 3k/mo / 100/day which is comfortably
above the volume we'd ever see from access-request submissions.

Design choice: this module is *soft-fail*. If `RESEND_API_KEY` isn't
set, or the HTTP request errors, the function logs a warning and
returns `False`. It does NOT raise. Rationale: an access request
already persisted to Postgres is the source of truth — failing the
user's form submit because we couldn't ping Resend would be silly.
The operator can still review pending requests directly in the DB.

Tested via the FakeMailer monkeypatch in `tests/unit/test_notifications.py`
so the production path stays exercised but unit tests don't dial
Resend."""

from __future__ import annotations

import logging
import os
from typing import Any

import urllib.error
import urllib.request


_log = logging.getLogger(__name__)


def send_operator_email(*, subject: str, body_text: str) -> bool:
    """Send a plain-text email to the operator (OPERATOR_NOTIFY_EMAIL).

    Returns True on success, False on any failure (missing key,
    HTTP error, JSON shape from Resend changed). Never raises so
    request-handling code doesn't need a try/except around it.

    Required env:
        RESEND_API_KEY            — Resend's API key (`re_...`)
        OPERATOR_NOTIFY_EMAIL     — destination address
        OPERATOR_NOTIFY_FROM      — verified-domain sender on Resend.
                                    Defaults to `bench@libearden.dev`
                                    which we'll need to set up SPF/DKIM
                                    for in Cloudflare before this works.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addr = os.environ.get("OPERATOR_NOTIFY_EMAIL", "").strip()
    from_addr = os.environ.get("OPERATOR_NOTIFY_FROM", "bench@libearden.dev").strip()

    if not api_key or not to_addr:
        _log.info(
            "skip operator email (RESEND_API_KEY=%s, OPERATOR_NOTIFY_EMAIL=%s)",
            "set" if api_key else "missing",
            "set" if to_addr else "missing",
        )
        return False

    return _post_resend(
        api_key=api_key,
        payload={
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
            "text": body_text,
        },
    )


def _post_resend(*, api_key: str, payload: dict[str, Any]) -> bool:
    """One HTTPS POST to Resend's /emails endpoint. Stdlib only so we
    don't pull `requests` in for a single call."""
    import json
    data = json.dumps(payload).encode("utf-8")
    # Explicit User-Agent: Resend's API sits behind Cloudflare, and CF
    # bot-detection (error 1010) rejects Python's default UA
    # ("Python-urllib/3.x") because it matches a known-bot pattern.
    # A real-looking identifier passes the check. Including the app
    # name + a contact URL is also good citizenship — the receiving
    # operator can see who sent the request.
    req = urllib.request.Request(
        url="https://api.resend.com/emails",
        method="POST",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "lis-bench/1.0 (+https://bench.libearden.dev) "
                "python-urllib"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if 200 <= resp.status < 300:
                return True
            _log.warning("Resend returned non-2xx: %s", resp.status)
            return False
    except urllib.error.HTTPError as e:
        _log.warning("Resend HTTPError %s: %s", e.code, e.read()[:200])
        return False
    except Exception as e:
        _log.warning("Resend send failed: %s", e)
        return False


def format_access_request_email(*, name: str, email: str,
                                github_handle: str | None,
                                note: str | None,
                                ip: str | None,
                                request_id: int) -> tuple[str, str]:
    """Build (subject, body_text) for the operator's notification.

    Kept as a separate function so we can unit-test the formatting
    without hitting the network."""
    subject = f"Bench access request — {name} <{email}>"
    lines = [
        f"Someone requested access to bench (request #{request_id}).",
        "",
        f"  Name:    {name}",
        f"  Email:   {email}",
    ]
    if github_handle:
        lines.append(f"  GitHub:  {github_handle}")
    if note:
        lines.append("")
        lines.append("Note:")
        for ln in note.splitlines():
            lines.append(f"  {ln}")
    if ip:
        lines.append("")
        lines.append(f"  IP:      {ip}")
    lines.extend([
        "",
        "To grant access:",
        f'  flyctl secrets set -a lis-bench LIS_ALLOWED_EMAILS="...,{email}"',
        "",
        "(then `flyctl secrets list -a lis-bench` to confirm it deployed.)",
        "",
        f"Review all pending: SELECT * FROM access_requests WHERE status='pending' ORDER BY created_at DESC;",
    ])
    return subject, "\n".join(lines)
