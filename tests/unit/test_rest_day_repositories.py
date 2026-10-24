"""Query-shape tests for rest-day recap repository helpers."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.content_repository import ContentRepository
from app.repositories.credentials_repository import CredentialsRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.repositories.writing_repository import WritingRepository


_USER_ID = "11111111-1111-1111-1111-111111111111"


def _mock_cursor(conn: MagicMock) -> MagicMock:
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return cur


def test_attempt_list_for_user_since_filters_by_start_time():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = AttemptRepository(conn)
    assert repo.list_for_user_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM attempts" in sql
    assert "user_id = %s" in sql
    assert "started_at >= %s" in sql
    assert "ORDER BY started_at DESC" in sql
    assert params == (_USER_ID, since)


def test_content_list_progress_since_only_returns_completed_rows():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = ContentRepository(conn)
    assert repo.list_progress_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM content_progress" in sql
    assert "status = 'completed'" in sql
    assert "checked_at IS NOT NULL" in sql
    assert "checked_at >= %s" in sql
    assert "ORDER BY checked_at DESC" in sql
    assert "ci.created_by_user_id = %s" in sql
    assert params == (_USER_ID, since, _USER_ID)


def test_writing_list_for_user_since_orders_by_recent_updates():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = WritingRepository(conn)
    assert repo.list_for_user_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM writings" in sql
    assert "status != 'archived'" in sql
    assert "updated_at >= %s" in sql
    assert "ORDER BY updated_at DESC" in sql
    assert params == (_USER_ID, since)


def test_reflection_list_for_user_since_filters_by_generated_at():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = ReflectionRepository(conn)
    assert repo.list_for_user_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM reflections" in sql
    assert "generated_at >= %s" in sql
    assert "ORDER BY generated_at DESC" in sql
    assert params == (_USER_ID, since)


def test_assessment_completed_since_returns_completed_runs_only():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = AssessmentRepository(conn)
    assert repo.completed_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM assessment_runs" in sql
    assert "completed_at IS NOT NULL" in sql
    assert "completed_at >= %s" in sql
    assert "ORDER BY completed_at DESC" in sql
    assert params == (_USER_ID, since)


def test_credentials_completed_since_returns_recent_completed_runs():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []
    since = datetime(2026, 5, 11, 0, 0)

    repo = CredentialsRepository(conn)
    assert repo.completed_since(_USER_ID, since) == []

    sql, params = cur.execute.call_args.args
    assert "FROM credential_runs" in sql
    assert "completed_at IS NOT NULL" in sql
    assert "completed_at >= %s" in sql
    assert "ORDER BY completed_at DESC, id DESC" in sql
    assert params == (_USER_ID, since)
