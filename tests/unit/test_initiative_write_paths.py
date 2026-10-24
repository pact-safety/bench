"""Integration-ish tests for per-attempt initiative tagging on writes.

Covers the four write paths that pick up `settings.active_initiative`
plus the `/settings/initiative` POST handler that sets it.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _init(slug: str, title: str, status: str = "active"):
    """Minimal stand-in — the settings route only reads slug/title/status."""
    return SimpleNamespace(slug=slug, title=title, status=status)


# Fixed fixture set. Initiatives are per-user data (gitignored; a fresh
# clone ships only the example template), so these tests must NOT read the
# real content/initiatives/ directory or they break for everyone but the
# author. These slugs are fixtures, not seed data.
_FIXTURE_INITIATIVES = [
    _init("bench", "Bench Product Development"),
    _init("capstone", "MSCS Sycophancy Capstone"),
    _init("anthropic-fellows", "Anthropic Fellows Application", status="done"),
]


@pytest.fixture(autouse=True)
def _stub_initiatives(monkeypatch):
    """Serve the fixture set to every caller of load_initiatives() — both
    the /settings route and initiative_picker resolve through the same
    module attribute."""
    from app.services import initiatives as initiatives_module

    monkeypatch.setattr(
        initiatives_module, "load_initiatives", lambda: list(_FIXTURE_INITIATIVES)
    )


def _signed_in_client(monkeypatch, *, settings: dict | None = None):
    """Reusable signed-in TestClient. Optional settings dict patches
    the user's settings_json read so we can exercise different
    active_initiative states."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: (settings or {}).copy())
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="op@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m


# ---------------------------------------------------------------------------
# /settings: GET renders dropdown
# ---------------------------------------------------------------------------


def _patch_settings_page_repo_calls(m):
    """The /settings GET handler reads assessment_repo.latest_completed
    for the skill-profile panel. Tests for this PR don't care about
    that data; mock it to None so the route renders without touching
    the (LIS_NO_DB=1) sentinel connection in CI."""
    return patch.object(m.assessment_repo, "latest_completed", return_value=None)


def test_settings_get_renders_active_initiative_dropdown(monkeypatch):
    """Active initiatives in the repo show up as options; the current
    settings value is selected."""
    client, m = _signed_in_client(
        monkeypatch, settings={"active_initiative": "bench"}
    )

    with _patch_settings_page_repo_calls(m):
        r = client.get("/settings")

    assert r.status_code == 200
    # Section header + the "none" sentinel option are always present.
    assert "Active initiative" in r.text
    assert "— none (leave activity unassigned) —" in r.text
    # bench is an active initiative in the seed data; should appear as
    # an <option> with the selected attribute since settings points at it.
    assert 'value="bench"' in r.text
    assert "Bench Product Development" in r.text


def test_settings_get_marks_no_default_when_settings_empty(monkeypatch):
    """The empty-value option should be selected when no active
    initiative is set."""
    client, m = _signed_in_client(monkeypatch, settings={})

    with _patch_settings_page_repo_calls(m):
        r = client.get("/settings")

    assert r.status_code == 200
    # The empty option is selected (i.e., appears with `selected` attr).
    assert '<option value="" selected' in r.text or 'value=""\n            selected' in r.text


def test_settings_get_excludes_done_initiatives_from_dropdown(monkeypatch):
    """A `done` initiative (e.g., anthropic-fellows after rejection)
    must NOT appear as a selectable option. Otherwise the operator
    could re-tag fresh activity to a closed initiative through the
    very UI we're adding."""
    client, m = _signed_in_client(monkeypatch, settings={})

    with _patch_settings_page_repo_calls(m):
        r = client.get("/settings")

    assert r.status_code == 200
    # anthropic-fellows is `done` in the seed data — must not be an
    # option value. (It can appear in other parts of the page if it's
    # referenced elsewhere; the test is specific to <option value=>.)
    assert 'value="anthropic-fellows"' not in r.text


# ---------------------------------------------------------------------------
# /settings/initiative: POST persists and validates
# ---------------------------------------------------------------------------


def test_settings_initiative_post_persists_valid_slug(monkeypatch):
    """Submitting a valid active slug saves to settings_json."""
    saved: dict = {}

    def fake_save(uid, s):
        saved.update(s)

    client, m = _signed_in_client(monkeypatch, settings={})
    monkeypatch.setattr(m, "_save_user_settings", fake_save)

    r = client.post(
        "/settings/initiative",
        data={"active_initiative": "capstone"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    assert saved.get("active_initiative") == "capstone"


def test_settings_initiative_post_empty_string_clears_default(monkeypatch):
    """Submitting empty value should REMOVE active_initiative from
    settings rather than leaving an empty string."""
    saved: dict = {}

    def fake_save(uid, s):
        saved.update({"_keys": list(s.keys()), "_settings": s})

    client, m = _signed_in_client(
        monkeypatch, settings={"active_initiative": "bench", "other_key": "X"}
    )
    monkeypatch.setattr(m, "_save_user_settings", fake_save)

    r = client.post(
        "/settings/initiative",
        data={"active_initiative": ""},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert "active_initiative" not in saved["_keys"]
    # Other settings keys are preserved.
    assert saved["_settings"].get("other_key") == "X"


def test_settings_initiative_post_rejects_unknown_slug(monkeypatch):
    """Stale or hand-typed slugs that don't match any active
    initiative get rejected with 400. Persistence is the strict
    boundary — we never want settings to carry an invalid slug."""
    saved_calls: list = []

    def fake_save(uid, s):
        saved_calls.append(s)

    client, m = _signed_in_client(monkeypatch, settings={})
    monkeypatch.setattr(m, "_save_user_settings", fake_save)

    r = client.post(
        "/settings/initiative",
        data={"active_initiative": "hallucinated-slug"},
        follow_redirects=False,
    )

    assert r.status_code == 400
    assert "hallucinated-slug" in r.text
    # No save happened.
    assert saved_calls == []


def test_settings_initiative_post_rejects_done_initiative(monkeypatch):
    """Even though anthropic-fellows is a real slug, it's `done` —
    can't be the active default."""
    saved_calls: list = []

    def fake_save(uid, s):
        saved_calls.append(s)

    client, m = _signed_in_client(monkeypatch, settings={})
    monkeypatch.setattr(m, "_save_user_settings", fake_save)

    r = client.post(
        "/settings/initiative",
        data={"active_initiative": "anthropic-fellows"},
        follow_redirects=False,
    )

    assert r.status_code == 400
    assert saved_calls == []


# ---------------------------------------------------------------------------
# Write paths: /writings + /reflect/generate use the picker
# ---------------------------------------------------------------------------


def test_writings_post_tags_from_settings_active_initiative(monkeypatch):
    """POST /writings inserts with initiative_slug=settings.active_initiative."""
    client, m = _signed_in_client(
        monkeypatch, settings={"active_initiative": "bench"}
    )

    insert_calls: dict = {}

    def fake_insert(uid, *, title, body_md, source_refs, initiative_slug=None):
        insert_calls["uid"] = uid
        insert_calls["title"] = title
        insert_calls["initiative_slug"] = initiative_slug
        return 555

    with patch.object(m.writing_repo, "insert", side_effect=fake_insert), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.content_repo, "all_by_kind", return_value=[]), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]):
        r = client.post("/writings", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/writings/555"
    assert insert_calls["initiative_slug"] == "bench"


def test_writings_post_tags_none_when_no_active_initiative(monkeypatch):
    """No active_initiative + no form override → initiative_slug=None
    (the row records 'unassigned')."""
    client, m = _signed_in_client(monkeypatch, settings={})

    insert_calls: dict = {}

    def fake_insert(uid, *, title, body_md, source_refs, initiative_slug=None):
        insert_calls["initiative_slug"] = initiative_slug
        return 1

    with patch.object(m.writing_repo, "insert", side_effect=fake_insert), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.content_repo, "all_by_kind", return_value=[]), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]):
        client.post("/writings", follow_redirects=False)

    assert insert_calls["initiative_slug"] is None


def test_writings_post_form_override_wins_over_settings(monkeypatch):
    """Explicit form value overrides settings.active_initiative."""
    client, m = _signed_in_client(
        monkeypatch, settings={"active_initiative": "bench"}
    )

    insert_calls: dict = {}

    def fake_insert(uid, *, title, body_md, source_refs, initiative_slug=None):
        insert_calls["initiative_slug"] = initiative_slug
        return 1

    with patch.object(m.writing_repo, "insert", side_effect=fake_insert), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.content_repo, "all_by_kind", return_value=[]), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]):
        client.post(
            "/writings",
            data={"initiative_slug": "capstone"},
            follow_redirects=False,
        )

    assert insert_calls["initiative_slug"] == "capstone"


def test_writings_post_rejects_unknown_override(monkeypatch):
    """Invalid form override → 400, no insert."""
    client, m = _signed_in_client(monkeypatch, settings={})

    with patch.object(m.writing_repo, "insert") as fake_insert, \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.content_repo, "all_by_kind", return_value=[]), \
         patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]):
        r = client.post(
            "/writings",
            data={"initiative_slug": "no-such-slug"},
            follow_redirects=False,
        )

    assert r.status_code == 400
    fake_insert.assert_not_called()


def test_reflect_generate_tags_from_settings_active_initiative(monkeypatch):
    """/reflect/generate sets reflection.initiative_slug from settings."""
    client, m = _signed_in_client(
        monkeypatch, settings={"active_initiative": "capstone"}
    )

    captured: dict = {}

    def fake_insert(refl):
        captured["initiative_slug"] = refl.initiative_slug
        return 99

    fake_week = SimpleNamespace(
        attempts=0, attempts_passed=0, reflections=0, content_completed=0,
        writings=0, last_attempt_at=None, last_reflection_at=None,
    )

    with patch.object(m.reflection_repo, "insert", side_effect=fake_insert), \
         patch.object(m, "_build_week_summary", return_value=fake_week), \
         patch(
             "app.services.hamming.generate",
             return_value={
                 "prompts": [{"label": "X", "prompt": "Y"}],
                 "summary": "ok",
                 "method": "claude",
                 "model_used": "claude-haiku-4-5",
             },
         ):
        r = client.post("/reflect/generate", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/reflect/99"
    assert captured["initiative_slug"] == "capstone"
