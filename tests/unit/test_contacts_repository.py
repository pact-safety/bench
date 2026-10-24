"""Owner-scoped query contracts for Connect history and relationship state."""

from datetime import datetime
from unittest.mock import MagicMock

from app.repositories.contacts_repository import ContactsRepository


_USER = "11111111-1111-1111-1111-111111111111"
_ORDER = "occurred_at DESC, created_at DESC, id DESC"


def _repo():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    return ContactsRepository(conn), cur


def _row(*, kind="received"):
    return {
        "id": 8,
        "contact_id": 4,
        "user_id": _USER,
        "occurred_at": datetime(2026, 9, 1),
        "created_at": datetime(2026, 9, 2),
        "kind": kind,
        "direction": "inbound" if kind == "received" else None,
        "notes": "Remember to ask about their paper.",
    }


def _query(cur):
    sql, params = cur.execute.call_args.args
    return " ".join(sql.split()), params


def test_history_preserves_private_notes_and_orders_ties_within_owner():
    repo, cur = _repo()
    cur.fetchall.return_value = [_row(kind="note"), _row()]

    history = repo.list_interactions_for_contact(4, user_id=_USER, limit=50)

    sql, params = _query(cur)
    assert "WHERE contact_id = %s AND user_id = %s" in sql
    assert "kind" not in sql
    assert f"ORDER BY {_ORDER} LIMIT %s" in sql
    assert params == (4, _USER, 50)
    assert [item.kind for item in history] == ["note", "received"]


def test_latest_per_contact_ignores_notes_before_selecting_within_owner():
    repo, cur = _repo()
    cur.fetchall.return_value = [_row()]

    latest = repo.latest_interaction_by_contact(_USER)

    sql, params = _query(cur)
    assert "SELECT DISTINCT ON (contact_id)" in sql
    assert "WHERE user_id = %s AND kind <> 'note'" in sql
    assert f"ORDER BY contact_id, {_ORDER}" in sql
    assert params == (_USER,)
    assert latest[4].id == 8
    assert latest[4].direction == "inbound"


def test_latest_for_contact_queries_actual_touch_without_history_limit():
    repo, cur = _repo()
    cur.fetchone.return_value = _row()

    latest = repo.latest_interaction_for_contact(4, user_id=_USER)

    sql, params = _query(cur)
    assert "WHERE contact_id = %s AND user_id = %s AND kind <> 'note'" in sql
    assert f"ORDER BY {_ORDER} LIMIT 1" in sql
    assert params == (4, _USER)
    assert latest.id == 8
    assert latest.direction == "inbound"


def test_latest_for_contact_returns_none_without_actual_touch():
    repo, cur = _repo()
    cur.fetchone.return_value = None

    assert repo.latest_interaction_for_contact(4, user_id=_USER) is None
