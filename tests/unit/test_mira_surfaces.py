"""6a/6b/6d: the /mira/agenda, /mira/memory, /mira/evals sub-surfaces.

Same client shape as test_mira_admin_gate.py: real middleware + templates,
repo methods patched (LIS_NO_DB mode has no usable conn).
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from datetime import datetime
from unittest.mock import patch

import pytest


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, session_uuid: str):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=session_uuid,
            email="u@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


@pytest.mark.parametrize("path", ["/mira/agenda", "/mira/memory", "/mira/evals"])
def test_non_admin_gets_404(monkeypatch, path):
    """Only under the emergency re-gate (LIS_MIRA_ADMIN_ONLY=1) —
    the surfaces are open to signed-in users since v2.1 slice 3."""
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    with patch.object(m.mira_repo, "list_agenda") as la, \
         patch.object(m.mira_repo, "list_memories") as lm, \
         patch.object(m.mira_repo, "list_proposed_evals") as le:
        r = client.get(path)
    assert r.status_code == 404
    la.assert_not_called()
    lm.assert_not_called()
    le.assert_not_called()


def test_non_admin_post_agenda_404s(monkeypatch):
    """Same env-flip contract as the GET surfaces above."""
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    with patch.object(m.mira_repo, "add_agenda_item") as add:
        r = client.post("/mira/agenda", data={"title": "x", "kind": "question"})
    assert r.status_code == 404
    add.assert_not_called()


def _admin_get(monkeypatch, path, repo_method, rows):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, repo_method, return_value=rows), \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        return client.get(path)


def test_admin_agenda_renders_items(monkeypatch):
    r = _admin_get(
        monkeypatch,
        "/mira/agenda",
        "list_agenda",
        [
            {
                "id": "a1",
                "kind": "experiment",
                "title": "Rerun PARROT audit",
                "status": "open",
                "why": "replication first",
                "due_at": None,
                "created_at": datetime(2026, 7, 20, 12, 0),
            }
        ],
    )
    assert r.status_code == 200
    assert "Rerun PARROT audit" in r.text
    assert "replication first" in r.text


def test_admin_agenda_empty_state(monkeypatch):
    r = _admin_get(monkeypatch, "/mira/agenda", "list_agenda", [])
    assert r.status_code == 200
    assert "Nothing on the agenda yet" in r.text


def test_admin_memory_renders_rows(monkeypatch):
    r = _admin_get(
        monkeypatch,
        "/mira/memory",
        "list_memories",
        [
            {
                "id": "m1",
                "category": "goal",
                "content": "Ship the capstone by July 8",
                "created_at": datetime(2026, 7, 19, 9, 0),
            }
        ],
    )
    assert r.status_code == 200
    assert "Ship the capstone by July 8" in r.text


def test_admin_evals_empty_state(monkeypatch):
    r = _admin_get(monkeypatch, "/mira/evals", "list_proposed_evals", [])
    assert r.status_code == 200
    assert "No proposed evals yet" in r.text


def test_admin_evals_renders_condition_table(monkeypatch):
    """6d: hypothesis + falsifier + the A/B/C condition table + provenance
    chip + title all render from the enriched row shape."""
    r = _admin_get(
        monkeypatch,
        "/mira/evals",
        "list_proposed_evals",
        [
            {
                "id": "e1",
                "hypothesis": "Capability drops when the model infers eval.",
                "falsifier": "Gap disappears under a capability control.",
                "conditions": [
                    {"label": "A · overt", "framing": "This is a capability evaluation."},
                    {"label": "C · control", "framing": "Framing held out."},
                ],
                "status": "draft",
                "meta": {
                    "title": "Sandbagging under eval-framing",
                    "inspect_path": "evals/mira/sandbagging_framing.py",
                },
                "created_at": datetime(2026, 7, 22, 10, 0),
            }
        ],
    )
    assert r.status_code == 200
    assert "Sandbagging under eval-framing" in r.text  # meta.title
    assert "Falsifier:" in r.text
    assert "A · overt" in r.text and "C · control" in r.text  # condition table
    assert "Framing held out." in r.text
    assert "✦ MIRA" in r.text  # provenance chip
    assert "evals/mira/sandbagging_framing.py" in r.text  # inspect path


def test_admin_post_agenda_persists_and_redirects(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, "add_agenda_item", return_value="a1") as add:
        r = client.post(
            "/mira/agenda",
            data={"title": "  New question  ", "kind": "question", "why": ""},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/mira/agenda"
    add.assert_called_once_with(
        user_id=_ADMIN_UUID, kind="question", title="New question", why=None
    )


def test_admin_post_agenda_bad_kind_falls_back(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, "add_agenda_item", return_value="a1") as add:
        r = client.post(
            "/mira/agenda",
            data={"title": "x", "kind": "nonsense"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert add.call_args.kwargs["kind"] == "question"


def test_admin_post_memory_persists_and_redirects(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, "add_memory", return_value="m1") as add:
        r = client.post(
            "/mira/memory",
            data={"content": "Prefers terse feedback", "category": "preference"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/mira/memory"
    add.assert_called_once_with(
        user_id=_ADMIN_UUID, category="preference", content="Prefers terse feedback"
    )


def test_admin_post_agenda_blank_title_skips_insert(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.mira_repo, "add_agenda_item") as add:
        r = client.post(
            "/mira/agenda", data={"title": "   "}, follow_redirects=False
        )
    assert r.status_code == 303
    add.assert_not_called()
