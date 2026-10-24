"""First-run onboarding strips (design handoff 1b).

Contract pinned here:
  - the server picks at most ONE tip per surface — the first unseen
  - dismissals persist to settings_json (never client state) and the
    endpoint answers HTMX with two out-of-band slot fragments, no-JS
    with a 303 back to a LOCAL path only
  - the global toggle kills every strip everywhere
  - a surface with no inventory renders an empty slot (zero box)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import onboarding_bubbles as ob


# ---------- pure state -------------------------------------------------------


def test_fresh_user_gets_first_tip_with_counter():
    s = ob.bubble_state({}, "problem")
    assert s.current is not None
    assert (s.current.id, s.current.index, s.current.total) == ("phase_rail", 1, 2)
    assert s.current.anchor == "phase_rail"


def test_partially_seen_surface_advances_to_next_tip():
    settings = ob.mark({}, "problem", "phase_rail", "seen")
    s = ob.bubble_state(settings, "problem")
    assert s.current.id == "editor"
    assert (s.current.index, s.current.total) == (2, 2)


def test_fully_seen_surface_shows_nothing():
    settings = ob.mark({}, "problem", "phase_rail", "seen")
    settings = ob.mark(settings, "problem", "editor", "seen")
    assert ob.bubble_state(settings, "problem").current is None


def test_skip_marks_the_whole_surface():
    settings = ob.mark({}, "problem", "phase_rail", "skip")
    assert ob.bubble_state(settings, "problem").current is None
    # Other surfaces untouched.
    assert ob.bubble_state(settings, "today").current is not None


def test_global_toggle_hides_everything_without_erasing_progress():
    settings = ob.mark({}, "problem", "phase_rail", "seen")
    settings = ob.set_enabled(settings, False)
    assert ob.tips_enabled(settings) is False
    assert ob.bubble_state(settings, "today").current is None
    settings = ob.set_enabled(settings, True)
    # Progress survived the off/on cycle.
    assert ob.bubble_state(settings, "problem").current.id == "editor"


def test_unknown_surface_is_a_noop_state():
    assert ob.bubble_state({}, "nope").current is None


def test_mark_rejects_unknown_surface_and_action():
    with pytest.raises(ValueError):
        ob.mark({}, "nope", "x", "seen")
    with pytest.raises(ValueError):
        ob.mark({}, "problem", "phase_rail", "explode")


def test_mark_does_not_mutate_input():
    original: dict = {}
    ob.mark(original, "problem", "phase_rail", "seen")
    assert original == {}


def test_inventory_respects_the_three_tip_page_budget():
    for surface, tips in ob.INVENTORY.items():
        assert 1 <= len(tips) <= 3, surface


# ---------- routes -----------------------------------------------------------

_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    store = {"settings": {}}
    monkeypatch.setattr(m, "_user_settings", lambda _uid: store["settings"])
    monkeypatch.setattr(
        m, "_save_user_settings",
        lambda _uid, s: store.update(settings=s),
    )
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID, email="u@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m, store


def test_dismiss_htmx_returns_oob_slots_and_persists(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    r = client.post(
        "/settings/bubbles",
        data={"surface": "problem", "tip": "phase_rail",
              "action": "seen", "next": "/problems/x"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    # The dismissed slot comes back empty, the next tip lands in ITS slot.
    assert 'id="ob-slot-problem-phase_rail"' in r.text
    assert 'id="ob-slot-problem-editor"' in r.text
    assert "hx-swap-oob" in r.text
    assert "The editor unlocks when Plan has content." in r.text
    # The next strip's detached owners must advance with it, preserving the
    # original return path rather than the dismissal endpoint's URL.
    assert 'id="ob-bubble-form-seen"' in r.text
    assert 'id="ob-bubble-form-skip"' in r.text
    assert 'name="tip" value="editor"' in r.text
    assert 'name="next" value="/problems/x"' in r.text
    assert 'name="action" value="seen"' in r.text
    assert 'name="action" value="skip"' in r.text
    assert store["settings"][ob.KEY]["seen"]["problem"] == ["phase_rail"]


def test_dismiss_last_tip_returns_only_the_emptied_slot(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    store["settings"] = ob.mark({}, "problem", "phase_rail", "seen")
    r = client.post(
        "/settings/bubbles",
        data={"surface": "problem", "tip": "editor", "action": "seen"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert 'id="ob-slot-problem-editor"' in r.text
    assert "ob-bubble__kicker" not in r.text  # nothing left to show


def test_dismiss_no_js_303s_back_to_local_path_only(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    r = client.post(
        "/settings/bubbles",
        data={"surface": "today", "tip": "next_rep",
              "action": "seen", "next": "/"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r = client.post(
        "/settings/bubbles",
        data={"surface": "today", "tip": "next_rep",
              "action": "seen", "next": "https://evil.example.com/"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"  # open-redirect guard

    r = client.post(
        "/settings/bubbles",
        data={"surface": "today", "tip": "next_rep",
              "action": "seen", "next": "//evil.example.com"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/"


def test_dismiss_bad_surface_400s(mock_anthropic, monkeypatch):
    client, _m, _store = _client(monkeypatch)
    r = client.post("/settings/bubbles", data={"surface": "nope", "tip": "x"})
    assert r.status_code == 400


def test_enabled_toggle_204_for_htmx_303_otherwise(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    r = client.post(
        "/settings/bubbles/enabled",
        data={"enabled": "0"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204
    assert store["settings"][ob.KEY]["enabled"] is False

    r = client.post(
        "/settings/bubbles/enabled",
        data={"enabled": "1", "next": "/settings"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert store["settings"][ob.KEY]["enabled"] is True


def test_settings_page_renders_strip_toggle_and_then_neither(mock_anthropic, monkeypatch):
    client, m, store = _client(monkeypatch)
    with patch.object(m, "assessment_repo") as ar, \
         patch.object(m.llm_config_repo, "get", return_value=None):
        ar.latest_completed.return_value = None
        r = client.get("/settings")
        assert r.status_code == 200
        assert "tip 1 of 2 — provider keys" in r.text
        assert 'aria-pressed="true"' in r.text  # tips on

        # Seen + toggled off → no strip, toggle reads off.
        store["settings"] = ob.set_enabled(
            ob.mark(store["settings"], "settings", "provider", "seen"), False
        )
        r = client.get("/settings")
        assert "ob-bubble__kicker" not in r.text
        assert 'aria-pressed="false"' in r.text
