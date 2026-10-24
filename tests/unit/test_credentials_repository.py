"""Unit tests for CredentialsRepository history/listing helpers."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.repositories.credentials_repository import CredentialsRepository


def _mock_cursor(conn: MagicMock) -> MagicMock:
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return cur


def test_list_completed_for_user_queries_newest_first_with_limit():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        {
            "id": 22,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "started_at": datetime(2026, 5, 18, 10, 0, 0),
            "completed_at": datetime(2026, 5, 18, 10, 2, 0),
            "status_text": "uploaded",
        },
        {
            "id": 17,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "started_at": datetime(2026, 5, 17, 11, 0, 0),
            "completed_at": datetime(2026, 5, 17, 11, 2, 0),
            "status_text": "uploaded",
        },
    ]

    repo = CredentialsRepository(conn)
    runs = repo.list_completed_for_user("11111111-1111-1111-1111-111111111111", limit=10)

    assert [r.id for r in runs] == [22, 17]

    sql, params = cur.execute.call_args.args
    assert "FROM credential_runs WHERE user_id = %s" in sql
    assert "completed_at IS NOT NULL" in sql
    assert "ORDER BY completed_at DESC, id DESC" in sql
    assert "LIMIT %s" in sql
    assert params == ("11111111-1111-1111-1111-111111111111", 10)


def test_list_completed_for_user_clamps_limit_bounds():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = []

    repo = CredentialsRepository(conn)

    repo.list_completed_for_user("11111111-1111-1111-1111-111111111111", limit=0)
    _, params_low = cur.execute.call_args.args
    assert params_low == ("11111111-1111-1111-1111-111111111111", 1)

    repo.list_completed_for_user("11111111-1111-1111-1111-111111111111", limit=999)
    _, params_high = cur.execute.call_args.args
    assert params_high == ("11111111-1111-1111-1111-111111111111", 100)


def test_first_files_by_run_uses_one_query_and_returns_map():
    """Batched first-file lookup avoids N+1 round-trips."""
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        {
            "id": 100, "run_id": 11, "filename": "resume.pdf",
            "content_type": "application/pdf", "byte_size": 2048,
            "sha256": "abc", "extracted_text": "text",
            "uploaded_at": datetime(2026, 5, 18, 9, 1, 0),
        },
        {
            "id": 101, "run_id": 14, "filename": "cv.pdf",
            "content_type": "application/pdf", "byte_size": 1024,
            "sha256": "def", "extracted_text": "text",
            "uploaded_at": datetime(2026, 5, 18, 9, 2, 0),
        },
    ]
    repo = CredentialsRepository(conn)
    result = repo.first_files_by_run([11, 14])

    assert cur.execute.call_count == 1  # ONE round-trip, not two
    assert set(result.keys()) == {11, 14}
    assert result[11].filename == "resume.pdf"
    assert result[14].filename == "cv.pdf"


def test_first_files_by_run_empty_input_skips_query():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    repo = CredentialsRepository(conn)
    result = repo.first_files_by_run([])
    assert result == {}
    cur.execute.assert_not_called()


def test_latest_assessments_by_run_uses_one_query_and_returns_map():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    cur.fetchall.return_value = [
        {
            "id": 5, "run_id": 11,
            "inferred_axis_scores_json": '{"debugging": 0.9}',
            "summary_md": "ok", "rationale_json": "{}",
            "method": "llm", "model_used": "claude-haiku-4-5",
            "created_at": datetime(2026, 5, 18, 9, 3, 0),
        },
    ]
    repo = CredentialsRepository(conn)
    result = repo.latest_assessments_by_run([11, 14])
    assert cur.execute.call_count == 1
    assert list(result.keys()) == [11]
    assert result[11].inferred_axis_scores == {"debugging": 0.9}


def test_latest_assessments_by_run_empty_input_skips_query():
    conn = MagicMock()
    cur = _mock_cursor(conn)
    repo = CredentialsRepository(conn)
    assert repo.latest_assessments_by_run([]) == {}
    cur.execute.assert_not_called()
