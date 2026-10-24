"""Unit tests for app.services.notifications.

The send path is soft-fail (returns False on any error, never raises),
so the tests assert on the *format* of the outgoing email and the
*soft-fail behavior* when config is missing — not on Resend's actual
HTTP shape (which would need either a mock server or live creds)."""

from __future__ import annotations

import pytest

from app.services import notifications as nf


def test_format_email_includes_name_email_and_secret_command():
    """The operator email must surface the requester's identity and
    the exact `flyctl secrets set` command to allow them — that's
    the whole point of the alert."""
    subject, body = nf.format_access_request_email(
        name="Dana Researcher",
        email="dana@example.com",
        github_handle="@dana",
        note="Prepping for a research-engineer role at $LAB.",
        ip="203.0.113.7",
        request_id=42,
    )
    assert "Dana Researcher" in subject
    assert "dana@example.com" in subject
    assert "Dana Researcher" in body
    assert "dana@example.com" in body
    assert "@dana" in body
    assert "203.0.113.7" in body
    assert "Prepping for a research-engineer role" in body
    # The actionable line: copy-pasteable allowlist update.
    assert "LIS_ALLOWED_EMAILS" in body
    assert "dana@example.com" in body


def test_format_email_omits_optional_fields_when_missing():
    """Submitter only filled in name+email; the formatter shouldn't
    print empty 'GitHub:' or 'Note:' headers."""
    _, body = nf.format_access_request_email(
        name="Alex",
        email="a@x.com",
        github_handle=None,
        note=None,
        ip=None,
        request_id=1,
    )
    assert "GitHub:" not in body
    assert "Note:" not in body
    assert "IP:" not in body


def test_send_operator_email_skips_when_keys_missing(monkeypatch):
    """Without RESEND_API_KEY + OPERATOR_NOTIFY_EMAIL the function must
    return False (skip) and not attempt any HTTP call."""
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("OPERATOR_NOTIFY_EMAIL", raising=False)
    # If the function tried to POST, this would fail — there's no fake
    # server. The return False is the assertion.
    assert nf.send_operator_email(subject="x", body_text="y") is False


def test_send_operator_email_posts_when_configured(monkeypatch):
    """With both keys set the function calls _post_resend with the
    expected payload shape."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test_123")
    monkeypatch.setenv("OPERATOR_NOTIFY_EMAIL", "operator@example.com")
    monkeypatch.setenv("OPERATOR_NOTIFY_FROM", "bench@example.com")

    captured: dict = {}
    def _fake_post(*, api_key: str, payload: dict) -> bool:
        captured["api_key"] = api_key
        captured["payload"] = payload
        return True
    monkeypatch.setattr(nf, "_post_resend", _fake_post)

    assert nf.send_operator_email(subject="hi", body_text="body") is True
    assert captured["api_key"] == "re_test_123"
    assert captured["payload"]["to"] == ["operator@example.com"]
    assert captured["payload"]["from"] == "bench@example.com"
    assert captured["payload"]["subject"] == "hi"
    assert captured["payload"]["text"] == "body"
