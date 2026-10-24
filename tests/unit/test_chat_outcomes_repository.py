"""Tests for ChatOutcomesRepository (migration 009 / PR A cutover).

Mocks the psycopg cursor + connection rather than spinning up a real
Postgres. Matches the pattern in test_credentials_repository.py.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.repositories.chat_outcomes_repository import ChatOutcomesRepository


_USER = "11111111-1111-1111-1111-111111111111"


def _mock_cursor(conn: MagicMock) -> MagicMock:
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return cur


def _row(*, id="aaaa-0000", user_id=_USER, slug="bench",
         decisions="d", next_actions="n",
         chat_url=None, created_at=None, source="mcp"):
    return {
        "id": id,
        "user_id": user_id,
        "initiative_slug": slug,
        "decisions": decisions,
        "next_actions": next_actions,
        "chat_url": chat_url,
        "created_at": created_at or datetime(2026, 5, 25, 10, 0, 0),
        "source": source,
    }


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------


def test_insert_writes_one_row_and_returns_uuid():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "new-uuid"}

    repo = ChatOutcomesRepository(conn)
    new_id = repo.insert(
        user_id=_USER,
        initiative_slug="bench",
        decisions="Picked /focus",
        next_actions="Ship it",
        chat_url="https://claude.ai/chat/abc",
        source="mcp",
    )

    assert new_id == "new-uuid"
    sql = cur.execute.call_args[0][0]
    assert "INSERT INTO chat_outcomes" in sql
    params = cur.execute.call_args[0][1]
    assert params[0] == _USER
    assert params[1] == "bench"
    assert params[2] == "Picked /focus"
    assert params[3] == "Ship it"
    assert params[4] == "https://claude.ai/chat/abc"
    assert params[5] == "mcp"
    conn.commit.assert_called_once()


def test_insert_normalizes_empty_chat_url_to_none():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "x"}
    repo = ChatOutcomesRepository(conn)
    repo.insert(
        user_id=_USER, initiative_slug="bench",
        decisions="d", next_actions="", chat_url="",
    )
    assert cur.execute.call_args[0][1][4] is None


def test_insert_strips_initiative_slug_whitespace():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "x"}
    repo = ChatOutcomesRepository(conn)
    repo.insert(
        user_id=_USER, initiative_slug="  bench  ",
        decisions="d", next_actions="",
    )
    assert cur.execute.call_args[0][1][1] == "bench"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_constrains_on_user_id():
    """Defense-in-depth: a get() must scope to the caller's user_id."""
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = _row(id="target")

    repo = ChatOutcomesRepository(conn)
    out = repo.get("target", user_id=_USER)
    assert out is not None
    sql = cur.execute.call_args[0][0]
    assert "id = %s AND user_id = %s" in sql
    params = cur.execute.call_args[0][1]
    assert params == ("target", _USER)


def test_get_returns_none_when_row_absent():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = None
    repo = ChatOutcomesRepository(conn)
    assert repo.get("nope", user_id=_USER) is None


# ---------------------------------------------------------------------------
# list_for_user
# ---------------------------------------------------------------------------


def test_list_for_user_filters_by_initiative_when_set():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [_row(id="1"), _row(id="2")]

    repo = ChatOutcomesRepository(conn)
    rows = repo.list_for_user(_USER, initiative_slug="bench", limit=10)

    sql = cur.execute.call_args[0][0]
    assert "initiative_slug = %s" in sql
    params = cur.execute.call_args[0][1]
    assert params == (_USER, "bench", 10)
    assert len(rows) == 2


def test_list_for_user_omits_filter_when_unset():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []

    repo = ChatOutcomesRepository(conn)
    repo.list_for_user(_USER, limit=20)

    sql = cur.execute.call_args[0][0]
    assert "initiative_slug = %s" not in sql
    params = cur.execute.call_args[0][1]
    assert params == (_USER, 20)


def test_list_for_user_clamps_limit_to_500():
    """Defense against runaway limit values."""
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    repo = ChatOutcomesRepository(conn)
    repo.list_for_user(_USER, limit=10_000)
    params = cur.execute.call_args[0][1]
    assert params[-1] == 500


# ---------------------------------------------------------------------------
# initiatives_with_counts + latest_per_initiative
# ---------------------------------------------------------------------------


def test_initiatives_with_counts_sorted_by_count_desc_then_slug():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        {"initiative_slug": "capstone", "n": 1},
        {"initiative_slug": "bench", "n": 5},
        {"initiative_slug": "anthropic-fellows", "n": 1},
    ]
    repo = ChatOutcomesRepository(conn)
    out = repo.initiatives_with_counts(_USER)
    assert out == [("bench", 5), ("anthropic-fellows", 1), ("capstone", 1)]


def test_latest_per_initiative_uses_distinct_on():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        _row(id="b-latest", slug="bench"),
        _row(id="c-latest", slug="capstone"),
    ]
    repo = ChatOutcomesRepository(conn)
    out = repo.latest_per_initiative(_USER)
    sql = cur.execute.call_args[0][0]
    assert "DISTINCT ON (initiative_slug)" in sql
    assert set(out.keys()) == {"bench", "capstone"}
    assert out["bench"].id == "b-latest"


def test_count_for_user_returns_integer():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"n": 42}
    repo = ChatOutcomesRepository(conn)
    assert repo.count_for_user(_USER) == 42
