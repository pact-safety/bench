"""Tests for the writings delete affordance + route."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.repositories.writing_repository import WritingRepository


_USER_UUID = "11111111-1111-1111-1111-111111111111"
_OTHER_UUID = "22222222-2222-2222-2222-222222222222"


def _writing(*, id_: int, user_id: str = _USER_UUID, title: str = "Draft", status: str = "draft"):
    return SimpleNamespace(
        id=id_,
        user_id=user_id,
        title=title,
        body_md="",
        source_refs=[],
        status=status,
        word_count=0,
        created_at=datetime(2026, 5, 24, 10, 0, 0),
        updated_at=datetime(2026, 5, 24, 10, 0, 0),
        published_at=None,
    )


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    import app.auth as auth_module
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
# Repo: delete()
# ---------------------------------------------------------------------------


def _mock_cursor(conn: MagicMock) -> MagicMock:
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return cur


def test_writing_repository_delete_uses_user_id_in_where_clause():
    """Defense in depth: even with route-level ownership checks, the
    DELETE statement must constrain on user_id."""
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.rowcount = 1

    repo = WritingRepository(conn)
    deleted = repo.delete(42, user_id=_USER_UUID)

    assert deleted is True
    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args[0]
    assert "DELETE FROM writings" in sql
    assert "user_id = %s" in sql
    assert params == (42, _USER_UUID)
    conn.commit.assert_called_once()


def test_writing_repository_delete_returns_false_when_no_row_matched():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.rowcount = 0

    repo = WritingRepository(conn)
    assert repo.delete(999, user_id=_USER_UUID) is False


# ---------------------------------------------------------------------------
# Route: POST /writings/{id}/delete
# ---------------------------------------------------------------------------


def test_writings_index_shows_delete_button_for_each_draft(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    drafts = [_writing(id_=11, title="My draft")]
    published: list = []

    def _list_for_user(uid, status=None):
        return drafts if status == "draft" else published

    with patch.object(m.writing_repo, "list_for_user", side_effect=_list_for_user):
        r = client.get("/writings", follow_redirects=False)

    assert r.status_code == 200
    assert 'action="/writings/11/delete"' in r.text
    # Confirm dialog is required to catch accidental clicks
    assert "Permanently delete this draft" in r.text


def test_delete_route_calls_repo_and_redirects_to_index(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    target = _writing(id_=11)
    deleted_with: dict[str, object] = {}

    def _fake_delete(writing_id, *, user_id):
        deleted_with["writing_id"] = writing_id
        deleted_with["user_id"] = user_id
        return True

    with patch.object(m.writing_repo, "get", return_value=target), \
         patch.object(m.writing_repo, "delete", side_effect=_fake_delete):
        r = client.post("/writings/11/delete", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/writings"
    assert deleted_with == {"writing_id": 11, "user_id": _USER_UUID}


def test_delete_route_404s_when_writing_missing(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.writing_repo, "get", return_value=None), \
         patch.object(m.writing_repo, "delete") as fake_delete:
        r = client.post("/writings/999/delete", follow_redirects=False)
    assert r.status_code == 404
    fake_delete.assert_not_called()


def test_delete_route_404s_when_writing_belongs_to_another_user(monkeypatch):
    """Cross-user delete attempts must 404 (avoid hint that the row exists)."""
    client, m = _signed_in_client(monkeypatch)
    not_yours = _writing(id_=11, user_id=_OTHER_UUID)
    with patch.object(m.writing_repo, "get", return_value=not_yours), \
         patch.object(m.writing_repo, "delete") as fake_delete:
        r = client.post("/writings/11/delete", follow_redirects=False)
    assert r.status_code == 404
    fake_delete.assert_not_called()
