import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")

import json
from unittest.mock import MagicMock

import pytest

from app.repositories.mira_repository import MiraRepository

TOKEN = "11111111-1111-4111-8111-111111111111"

def repository(*rows):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = rows
    cur.fetchall.return_value = []
    return MiraRepository(conn), conn, cur


def test_owned_session_is_locked_before_checking_stage_and_writing():
    repo, conn, cur = repository({"id": "session", "meta": {"mode": "coach"}})
    result = repo.append_coach_note(user_id="owner", session_id="session",
        stage="frame", content="My plan", coach_context={})
    assert (result.session_id, result.status) == ("session", "saved")
    queries = [call.args[0] for call in cur.execute.call_args_list]
    assert "user_id = %s" in queries[0] and "FOR UPDATE" in queries[0]
    assert "SELECT" in queries[1] and "mira_turns" in queries[1]
    assert "INSERT INTO mira_turns" in queries[2]
    conn.transaction.assert_called_once()
    conn.commit.assert_not_called()


@pytest.mark.parametrize("content,status", [("Saved plan", "duplicate"), ("Other plan", "stale")])
def test_stale_stage_never_appends_even_when_route_precheck_was_current(content, status):
    repo, _, cur = repository({"id": "session", "meta": {"mode": "coach"}})
    cur.fetchall.return_value = [{"provider_used": "coach:frame", "content": "Saved plan"}]
    result = repo.append_coach_note(user_id="owner", session_id="session",
        stage="frame", content=content, coach_context={})
    assert result.status == status
    assert all("INSERT" not in call.args[0] for call in cur.execute.call_args_list)


@pytest.mark.parametrize("row,status", [(None, "missing"), ({"id": "session", "meta": {}}, "readonly")])
def test_missing_foreign_or_legacy_session_cannot_be_written(row, status):
    repo, _, cur = repository(row)
    result = repo.append_coach_note(user_id="owner", session_id="session",
        stage="frame", content="My plan", coach_context={})
    assert result.status == status
    assert cur.execute.call_count == 1


def test_first_note_locks_context_and_creates_with_token_inside_transaction():
    repo, conn, cur = repository(None, {"id": "session", "meta": {"mode": "coach"}})
    result = repo.append_coach_note(user_id="owner", stage="frame", content="My plan",
        coach_context={"kind": "problem", "slug": "attention"}, request_token=TOKEN, force_new=True)
    assert result.status == "saved"
    queries = [call.args[0] for call in cur.execute.call_args_list]
    assert "pg_advisory_xact_lock" in queries[0]
    assert "coach_request_token" in queries[1]
    assert "INSERT INTO mira_sessions" in queries[2]
    meta = json.loads(cur.execute.call_args_list[2].args[1][1])
    assert meta["coach_request_token"] == TOKEN
    assert meta["context"] == {"kind": "problem", "slug": "attention"}
    conn.commit.assert_not_called()


def test_explicit_new_requires_retry_token():
    repo, conn, _ = repository()
    with pytest.raises(ValueError):
        repo.append_coach_note(user_id="owner", stage="frame", content="My plan",
            coach_context={}, force_new=True)
    conn.transaction.assert_not_called()


@pytest.mark.parametrize("token", ["arbitrary", "x" * 36, "x" * 10000])
def test_invalid_token_never_reaches_database(token):
    repo, conn, _ = repository()
    with pytest.raises(ValueError):
        repo.append_coach_note(user_id="owner", stage="frame", content="My plan",
            coach_context={}, request_token=token)
    conn.transaction.assert_not_called()


@pytest.mark.parametrize("stage,content,status", [
    ("frame", "Saved plan", "duplicate"),
    ("attempt", "Next step", "saved"),
    ("frame", "Conflicting plan", "stale"),
])
def test_only_accepted_duplicate_first_note_remembers_retry_alias(stage, content, status):
    repo, conn, cur = repository(None, {"id": "session", "meta": {"mode": "coach"}})
    cur.fetchall.return_value = [{"provider_used": "coach:frame", "content": "Saved plan"}]
    result = repo.append_coach_note(user_id="owner", stage=stage, content=content,
        coach_context={}, request_token=TOKEN)
    assert result.status == status
    remembers = [call for call in cur.execute.call_args_list if "UPDATE mira_sessions" in call.args[0]]
    assert len(remembers) == (stage == "frame" and status == "duplicate")
    if remembers:
        assert "coach_request_tokens" in remembers[0].args[0]
        assert TOKEN in remembers[0].args[1]
    conn.commit.assert_not_called()


def test_completed_session_is_resolved_by_accepted_alias_before_new_session_decision():
    repo, _, cur = repository({"id": "session", "meta": {"mode": "coach", "coach_request_tokens": [TOKEN]}})
    cur.fetchall.return_value = [
        {"provider_used": "coach:reflect", "content": "Finished"},
        {"provider_used": "coach:frame", "content": "Saved plan"},
    ]
    result = repo.append_coach_note(user_id="owner", stage="frame", content="Saved plan",
        coach_context={}, request_token=TOKEN)
    assert (result.session_id, result.status) == ("session", "duplicate")
    lookup = cur.execute.call_args_list[1]
    assert "coach_request_tokens" in lookup.args[0]
    assert all("INSERT" not in call.args[0] for call in cur.execute.call_args_list)
