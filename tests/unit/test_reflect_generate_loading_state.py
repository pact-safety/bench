"""Template-shape coverage for Reflect generate HTMX loading state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        m.auth_module if hasattr(m, "auth_module") else __import__("app.auth", fromlist=["auth"]),
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="test@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _week_summary():
    return SimpleNamespace(
        attempts=8,
        attempts_passed=6,
        attempts_with_hints=2,
        attempts_with_lookup=1,
        avg_confidence=3.9,
        content_finished=4,
        writings_drafted=1,
        writings_published=0,
        weakest_axes=[],
    )


def _render_reflect(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m, "_build_week_summary", return_value=_week_summary()):
        return client.get("/reflect", follow_redirects=False)


def test_reflect_generate_form_uses_htmx_request_and_disable_attrs(monkeypatch):
    r = _render_reflect(monkeypatch)

    assert r.status_code == 200
    assert 'id="reflect-gen-form"' in r.text
    assert 'hx-post="/reflect/generate"' in r.text
    assert 'hx-swap="none"' in r.text
    assert 'hx-indicator="#reflect-gen-indicator"' in r.text
    assert 'hx-disabled-elt="#reflect-gen-btn"' in r.text
    assert "hx-on::before-request=" in r.text
    assert "hx-on::after-request=" in r.text
    assert "hx-on::response-error=" in r.text


def test_reflect_generate_indicator_renders_spinner_and_live_region(monkeypatch):
    r = _render_reflect(monkeypatch)

    assert r.status_code == 200
    assert 'id="reflect-gen-btn" aria-busy="false"' in r.text
    assert 'id="reflect-gen-indicator"' in r.text
    assert 'class="reflect__gen-indicator htmx-indicator"' in r.text
    assert 'role="status"' in r.text
    assert 'aria-live="polite"' in r.text
    # Issue #301: the loading indicator changed from a spinner to a
    # shimmer skeleton. The aria-live + role=status contract is
    # unchanged so screen readers still get the announcement; the
    # skeleton container is aria-hidden so the four shimmer lines
    # don't pollute the spoken output.
    assert 'class="reflect__gen-skeleton" aria-hidden="true"' in r.text
    assert 'reflect__gen-skeleton-line--lg' in r.text
    assert 'reflect__gen-skeleton-line--md' in r.text
    assert 'reflect__gen-skeleton-line--sm' in r.text
    assert 'reflect__gen-skeleton-line--xs' in r.text
    assert "Sonnet is thinking" in r.text


# ---------------------------------------------------------------------------
# First-reflection callout (zero-state Pattern C gap #2)
# ---------------------------------------------------------------------------


def _empty_week_summary():
    """Genuinely first-time state: zero activity in the rolling window."""
    return SimpleNamespace(
        attempts=0,
        attempts_passed=0,
        attempts_with_hints=0,
        attempts_with_lookup=0,
        avg_confidence=None,
        content_finished=0,
        writings_drafted=0,
        writings_published=0,
        weakest_axes=[],
    )


def test_reflect_renders_first_time_callout_with_no_data_and_no_history(monkeypatch):
    """First reflection with zero past reflections AND zero recent
    activity → render the 'First reflection?' callout explaining that
    Hamming needs material to reflect on."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m, "_build_week_summary", return_value=_empty_week_summary()):
        r = client.get("/reflect", follow_redirects=False)

    assert r.status_code == 200
    assert "First reflection?" in r.text
    assert "Skip for now" in r.text
    assert "Generate anyway" in r.text
    assert "Read the framing first" in r.text


def test_reflect_hides_first_time_callout_when_history_exists(monkeypatch):
    """If there's any prior reflection, the operator is not first-time."""
    from datetime import datetime, timezone
    client, m = _signed_in_client(monkeypatch)
    prior_reflection = SimpleNamespace(
        id=1,
        generated_at=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        period_start=datetime(2026, 5, 13, tzinfo=timezone.utc),
        period_end=datetime(2026, 5, 20, tzinfo=timezone.utc),
        prompts=[], response_md=None, response_updated_at=None,
        method="claude", model_used=None, summary_md="prior summary",
        calibration_json=None, pregenerated=False,
    )

    with patch.object(m.reflection_repo, "list_for_user", return_value=[prior_reflection]), \
         patch.object(m, "_build_week_summary", return_value=_empty_week_summary()):
        r = client.get("/reflect", follow_redirects=False)

    assert r.status_code == 200
    assert "First reflection?" not in r.text


def test_reflect_hides_first_time_callout_when_activity_exists(monkeypatch):
    """No prior reflection but some recent activity → not first-time;
    the 'This week, in numbers' panel already has content."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m, "_build_week_summary", return_value=_week_summary()):
        r = client.get("/reflect", follow_redirects=False)

    assert r.status_code == 200
    assert "First reflection?" not in r.text
