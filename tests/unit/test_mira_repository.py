"""Tests for MiraRepository (migration 014_mira).

Mocks the psycopg cursor + connection rather than spinning up Postgres —
the same pattern as test_chat_outcomes_repository.py. Also covers the
per-session turn cache + its prefix invalidation on append.
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


from datetime import datetime
from unittest.mock import MagicMock

from app import cache as _cache
from app.repositories.mira_repository import MiraRepository


_USER = "11111111-1111-1111-1111-111111111111"
_SESS = "22222222-2222-2222-2222-222222222222"


def _mock_cursor(conn: MagicMock) -> MagicMock:
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return cur


def _session_row(*, id=_SESS, user_id=_USER, modality="chat",
                 started_at=None, ended_at=None, title=None):
    return {
        "id": id,
        "user_id": user_id,
        "modality": modality,
        "started_at": started_at or datetime(2026, 6, 1, 9, 0, 0),
        "ended_at": ended_at,
        "title": title,
    }


def _turn_row(*, id="t1", session_id=_SESS, role="user", content="hi",
              created_at=None, tool_calls=None, citations=None,
              provider_used=None, latency_ms=None, interrupted=False):
    return {
        "id": id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": created_at or datetime(2026, 6, 1, 9, 1, 0),
        "tool_calls": tool_calls,
        "citations": citations,
        "provider_used": provider_used,
        "latency_ms": latency_ms,
        "interrupted": interrupted,
    }


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


def test_create_session_inserts_and_returns_uuid():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "new-sess"}

    repo = MiraRepository(conn)
    sid = repo.create_session(user_id=_USER, modality="chat", title=None)

    assert sid == "new-sess"
    sql = cur.execute.call_args[0][0]
    assert "INSERT INTO mira_sessions" in sql
    params = cur.execute.call_args[0][1]
    # 4th param is the meta jsonb ('{}' when no persona_key — added by
    # the MATS drill launcher).
    assert params == (_USER, "chat", None, "{}")
    conn.commit.assert_called_once()


def test_get_session_scopes_to_user_when_given():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = _session_row()

    repo = MiraRepository(conn)
    out = repo.get_session(_SESS, user_id=_USER)

    assert out is not None
    assert out.modality == "chat"
    sql = cur.execute.call_args[0][0]
    assert "id = %s AND user_id = %s" in sql
    assert cur.execute.call_args[0][1] == (_SESS, _USER)


def test_get_session_without_user_omits_scope():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = _session_row()
    repo = MiraRepository(conn)
    repo.get_session(_SESS)
    sql = cur.execute.call_args[0][0]
    assert "user_id" not in sql
    assert cur.execute.call_args[0][1] == (_SESS,)


def test_get_session_returns_none_when_absent():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = None
    repo = MiraRepository(conn)
    assert repo.get_session("nope", user_id=_USER) is None


def test_list_sessions_clamps_limit():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    repo = MiraRepository(conn)
    repo.list_sessions(_USER, limit=99999)
    assert cur.execute.call_args[0][1] == (_USER, 200)


# ---------------------------------------------------------------------------
# turns
# ---------------------------------------------------------------------------


def test_append_turn_inserts_and_serializes_jsonb():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "new-turn"}

    repo = MiraRepository(conn)
    tid = repo.append_turn(
        session_id=_SESS,
        role="assistant",
        content="hey Li",
        provider_used="anthropic",
        latency_ms={"total": 812},
    )

    assert tid == "new-turn"
    sql = cur.execute.call_args[0][0]
    assert "INSERT INTO mira_turns" in sql
    params = cur.execute.call_args[0][1]
    assert params[0] == _SESS
    assert params[1] == "assistant"
    assert params[2] == "hey Li"
    assert params[3] is None                      # tool_calls (none in 1a)
    assert params[4] is None                      # citations
    assert params[5] == "anthropic"
    assert params[6] == '{"total": 812}'          # latency_ms json-encoded
    assert params[7] is False                     # interrupted
    conn.commit.assert_called_once()


def test_list_turns_returns_chronological_and_clamps_limit():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        _turn_row(id="a", role="user", content="q"),
        _turn_row(id="b", role="assistant", content="a"),
    ]
    repo = MiraRepository(conn)
    turns = repo.list_turns(_SESS, limit=99999)

    assert [t.id for t in turns] == ["a", "b"]
    sql = cur.execute.call_args[0][0]
    assert "ORDER BY created_at ASC" in sql
    assert cur.execute.call_args[0][1] == (_SESS, 1000)


def test_list_turns_is_cached_until_append_invalidates():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [_turn_row(id="a")]
    repo = MiraRepository(conn)

    # First read hits the DB; second read is served from cache (one query).
    repo.list_turns(_SESS, limit=200)
    repo.list_turns(_SESS, limit=200)
    assert cur.execute.call_count == 1

    # Appending a turn invalidates this session's cached history.
    cur.fetchone.return_value = {"id": "x"}
    repo.append_turn(session_id=_SESS, role="user", content="new")

    # Next read goes back to the DB.
    repo.list_turns(_SESS, limit=200)
    select_calls = [c for c in cur.execute.call_args_list
                    if "SELECT" in c[0][0]]
    assert len(select_calls) == 2


def test_list_turns_cache_expires_for_cross_machine_writes(monkeypatch):
    # Another worker cannot invalidate this process's cached transcript.
    now = {"t": 1000.0}
    monkeypatch.setattr(_cache.time, "monotonic", lambda: now["t"])
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [_turn_row(id="a", content="first note")]
    repo = MiraRepository(conn)
    assert [turn.content for turn in repo.list_turns(_SESS)] == ["first note"]

    cur.fetchall.return_value = [
        _turn_row(id="a", content="first note"),
        _turn_row(id="b", content="note saved on another worker"),
    ]
    now["t"] += 29.0
    assert [turn.content for turn in repo.list_turns(_SESS)] == ["first note"]
    assert cur.execute.call_count == 1

    now["t"] += 1.0
    assert [turn.content for turn in repo.list_turns(_SESS)] == [
        "first note", "note saved on another worker",
    ]
    assert cur.execute.call_count == 2


def test_append_invalidates_only_its_own_session():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [_turn_row(id="a")]
    repo = MiraRepository(conn)

    other = "33333333-3333-3333-3333-333333333333"
    repo.list_turns(_SESS, limit=200)
    repo.list_turns(other, limit=200)
    assert cur.execute.call_count == 2

    cur.fetchone.return_value = {"id": "x"}
    repo.append_turn(session_id=_SESS, role="user", content="new")

    # _SESS history dropped; `other` still cached → only _SESS re-queries.
    repo.list_turns(_SESS, limit=200)
    repo.list_turns(other, limit=200)
    select_calls = [c for c in cur.execute.call_args_list
                    if "SELECT" in c[0][0]]
    assert len(select_calls) == 3  # 2 initial + 1 re-read of _SESS only


def test_create_coach_session_preserves_context_and_persona():
    import json
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "coach-sess"}
    context = {"kind": "track", "slug": "ml4good-prework-fall-2026", "section_idx": 11}
    MiraRepository(conn).create_session(user_id=_USER, persona_key="mira", coach_context=context)
    meta = json.loads(cur.execute.call_args[0][1][3])
    assert meta == {"persona_key": "mira", "mode": "coach", "context": context}


def test_context_free_coach_is_explicitly_marked():
    import json
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchone.return_value = {"id": "coach-sess"}
    MiraRepository(conn).create_session(user_id=_USER, coach_context={})
    assert json.loads(cur.execute.call_args[0][1][3]) == {"mode": "coach", "context": {}}


def test_long_conversation_returns_latest_window_in_chronological_order():
    # Execute the selection locally so this checks which rows survive LIMIT,
    # not just the order of a pre-scripted mock result. This SQL is portable.
    import sqlite3
    from contextlib import contextmanager

    db = sqlite3.connect(":memory:")
    db.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
    db.execute("CREATE TABLE mira_turns (id TEXT, session_id TEXT, role TEXT, content TEXT, created_at TEXT, tool_calls TEXT, citations TEXT, provider_used TEXT, latency_ms TEXT, interrupted BOOLEAN)")
    for i in range(12):
        db.execute("INSERT INTO mira_turns VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0)",
                   (str(i), _SESS, "user", f"turn-{i}", f"2026-06-01T09:{i:02d}:00"))

    class Cursor:
        def execute(self, sql, params):
            self.result = db.execute(sql.replace("%s", "?"), params)
        def fetchall(self):
            rows = self.result.fetchall()
            for row in rows:
                row["created_at"] = datetime.fromisoformat(row["created_at"])
            return rows

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    turns = MiraRepository(Connection()).list_turns(_SESS, limit=3)
    assert [turn.content for turn in turns] == ["turn-9", "turn-10", "turn-11"]
    db.close()


def test_fresh_turn_read_bypasses_stale_process_cache():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [_turn_row(id="a", content="old note")]
    repo = MiraRepository(conn)
    assert repo.list_turns(_SESS)[0].content == "old note"
    cur.fetchall.return_value = [_turn_row(id="b", content="new note on another worker")]
    assert repo.list_turns(_SESS)[0].content == "old note"
    fresh = repo.list_turns(_SESS, fresh=True)
    assert [turn.content for turn in fresh] == ["new note on another worker"]
    assert cur.execute.call_count == 2
