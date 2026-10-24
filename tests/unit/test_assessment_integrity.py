from datetime import datetime
from types import SimpleNamespace as N
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.repositories.assessment_repository import AssessmentRepository
from app.services import assessment as assess

OWNER = "owner"


def response(q, choice=0):
    return N(question_id=q.id, axis_scores=q.options[choice].scores)


def test_duplicate_and_unknown_questions_do_not_end_quiz():
    assert assess.pick_next([assess.Q_CALIBRATION.id] * 10) is not None
    assert assess.pick_next(["unknown"] * 10) == assess.Q_CALIBRATION


def test_duplicate_responses_do_not_reweight_scores():
    first, second = assess.Q_POOL[:2]
    responses = [response(first), response(second, 3)]
    assert assess.aggregate_scores(responses + [response(first, 3)]) == assess.aggregate_scores(responses)


def repo_with_rows(*rows):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = rows
    cur.fetchall.return_value = []
    return AssessmentRepository(conn), conn, cur


def run_row(completed=False):
    return dict(id=7, user_id=OWNER, started_at=datetime(2026, 1, 1),
                completed_at=datetime(2026, 1, 2) if completed else None,
                final_scores_json={"debugging": .5} if completed else {})


def test_reads_require_owner_in_query():
    repo, _, cur = repo_with_rows(None)
    assert repo.get_run(7, user_id=OWNER) is None
    sql, params = cur.execute.call_args.args
    assert "user_id = %s" in sql and params == (7, OWNER)
    assert repo.responses_for_run(7, user_id=OWNER) == []
    sql, params = cur.execute.call_args.args
    assert "user_id = %s" in sql and params == (7, OWNER)


@pytest.mark.parametrize("row", [None, run_row(True)])
def test_answer_missing_or_completed_run_never_inserts(row):
    repo, conn, cur = repo_with_rows(row)
    assert repo.record_response(7, assess.Q_CALIBRATION.id, 0, user_id=OWNER) is None
    assert not any("INSERT" in call.args[0] for call in cur.execute.call_args_list)
    conn.transaction.assert_called_once()
    sql, params = cur.execute.call_args.args
    assert "FOR UPDATE" in sql and "user_id = %s" in sql
    assert params == (7, OWNER)


@pytest.mark.parametrize("qid,answer", [("q02-attention-shape", 0), ("q01-calibration", -1)])
def test_unexpected_or_invalid_answer_is_rejected(qid, answer):
    repo, _, cur = repo_with_rows(run_row())
    with pytest.raises(ValueError):
        repo.record_response(7, qid, answer, user_id=OWNER)
    assert not any("INSERT" in call.args[0] for call in cur.execute.call_args_list)


def test_duplicate_submission_cannot_add_response():
    repo, _, cur = repo_with_rows(run_row())
    cur.fetchall.return_value = [dict(id=1, run_id=7, question_id=assess.Q_CALIBRATION.id,
                                    answer_index=0, axis_scores_json=assess.Q_CALIBRATION.options[0].scores,
                                    answered_at=datetime(2026, 1, 1))]
    with pytest.raises(ValueError):
        repo.record_response(7, assess.Q_CALIBRATION.id, 3, user_id=OWNER)
    assert not any("INSERT" in call.args[0] for call in cur.execute.call_args_list)


@pytest.mark.parametrize("row", [None, run_row(), run_row(True)])
def test_completion_does_not_change_missing_empty_or_completed_run(row):
    repo, _, cur = repo_with_rows(row)
    repo.complete_run(7, user_id=OWNER)
    assert not any(call.args[0].startswith("UPDATE") for call in cur.execute.call_args_list)


@pytest.fixture
def routes(monkeypatch):
    import app.main as m
    repo = Mock()
    repo.get_run.return_value = N(id=7, user_id="someone-else", completed_at=None)
    repo.responses_for_run.return_value = []
    monkeypatch.setattr(m, "assessment_repo", repo)
    settings = Mock(return_value={})
    monkeypatch.setattr(m, "_user_settings", settings)
    app = FastAPI()

    @app.middleware("http")
    async def session(request: Request, call_next):
        request.state.user_session = N(user_id=OWNER)
        return await call_next(request)

    for path, handler, method in [("", m.assess_question, "GET"), ("/answer", m.assess_answer, "POST"),
                                  ("/result", m.assess_result, "GET"), ("/complete", m.assess_complete, "GET")]:
        app.add_api_route("/assess/{run_id}" + path, handler, methods=[method])
    return TestClient(app), repo, settings


@pytest.mark.parametrize("suffix,method", [("", "GET"), ("/answer", "POST"), ("/result", "GET"), ("/complete", "GET")])
def test_foreign_run_rejected_before_read_or_mutation(routes, suffix, method):
    client, repo, settings = routes
    result = client.request(method, "/assess/7" + suffix,
                            data={"question_id": "q01-calibration", "answer_index": 0}, follow_redirects=False)
    assert result.status_code == 404
    repo.get_run.assert_called_once_with(7, user_id=OWNER)
    repo.responses_for_run.assert_not_called()
    repo.record_response.assert_not_called()
    repo.complete_run.assert_not_called()
    settings.assert_not_called()


def test_unfinished_result_redirects_without_completion(routes):
    client, repo, settings = routes
    repo.get_run.return_value = N(id=7, user_id=OWNER, completed_at=None)
    result = client.get("/assess/7/result", follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == "/assess/7"
    repo.complete_run.assert_not_called()
    repo.responses_for_run.assert_not_called()
    settings.assert_not_called()


def rows_for_questions(questions):
    return [dict(id=i + 1, run_id=7, question_id=q.id, answer_index=0,
                 axis_scores_json=q.options[0].scores, answered_at=datetime(2026, 1, 1))
            for i, q in enumerate(questions)]


def test_valid_answer_uses_server_scores_and_owner_guard_under_lock():
    import json
    repo, conn, cur = repo_with_rows(run_row(), {"id": 11})
    assert repo.record_response(7, assess.Q_CALIBRATION.id, 0, user_id=OWNER) == 11
    statements = [call.args for call in cur.execute.call_args_list]
    assert "FOR UPDATE" in statements[0][0]
    assert "assessment_responses AS response" in statements[1][0]
    sql, params = statements[2]
    assert sql.startswith("INSERT")
    assert "user_id = %s AND completed_at IS NULL" in sql
    assert params == (assess.Q_CALIBRATION.id, 0,
                      json.dumps(assess.Q_CALIBRATION.options[0].scores), 7, OWNER)
    calls = [call[0] for call in conn.mock_calls]
    assert calls.index("transaction().__enter__") < calls.index("cursor().__enter__().execute")
    assert calls[-1] == "transaction().__exit__"
    conn.commit.assert_not_called()


def test_complete_run_requires_full_history_and_scores_it_under_lock():
    import json
    questions = []
    while (q := assess.pick_next([q.id for q in questions])) is not None:
        questions.append(q)
    repo, conn, cur = repo_with_rows(run_row())
    cur.fetchall.return_value = rows_for_questions(questions)
    assert repo.complete_run(7, user_id=OWNER) is True
    statements = [call.args for call in cur.execute.call_args_list]
    assert "FOR UPDATE" in statements[0][0]
    sql, params = statements[-1]
    assert sql.startswith("UPDATE") and "completed_at IS NULL" in sql
    assert params == (json.dumps(assess.aggregate_scores([response(q) for q in questions])), 7, OWNER)
    conn.transaction.assert_called_once()
    conn.commit.assert_not_called()


def test_nonempty_unfinished_run_cannot_complete():
    repo, _, cur = repo_with_rows(run_row())
    cur.fetchall.return_value = rows_for_questions([assess.Q_CALIBRATION] * 10)
    assert repo.complete_run(7, user_id=OWNER) is False
    assert not any(call.args[0].startswith("UPDATE") for call in cur.execute.call_args_list)


def test_response_history_keeps_first_submission():
    repo, _, cur = repo_with_rows()
    rows = rows_for_questions([assess.Q_CALIBRATION] * 2)
    rows[1]["answer_index"] = 3
    cur.fetchall.return_value = rows
    responses = repo.responses_for_run(7, user_id=OWNER)
    assert len(responses) == 1
    assert responses[0].answer_index == 0


@pytest.mark.parametrize("suffix,method", [("", "GET"), ("/answer", "POST"), ("/result", "GET"), ("/complete", "GET")])
def test_missing_run_has_same_response_as_foreign_run(routes, suffix, method):
    client, repo, _ = routes
    repo.get_run.return_value = None
    result = client.request(method, "/assess/7" + suffix,
                            data={"question_id": "q01-calibration", "answer_index": 0}, follow_redirects=False)
    assert result.status_code == 404
    repo.responses_for_run.assert_not_called()
    repo.record_response.assert_not_called()
    repo.complete_run.assert_not_called()


def test_stale_answer_returns_conflict(routes):
    client, repo, _ = routes
    repo.get_run.return_value = N(id=7, user_id=OWNER, completed_at=None)
    repo.record_response.side_effect = ValueError("Stale question")
    result = client.post("/assess/7/answer", data={"question_id": "q01-calibration", "answer_index": 0},
                         follow_redirects=False)
    assert result.status_code == 409
    repo.record_response.assert_called_once_with(7, "q01-calibration", 0, user_id=OWNER)
    repo.complete_run.assert_not_called()


def test_completed_run_answer_preserves_saved_result(routes):
    client, repo, _ = routes
    repo.get_run.return_value = N(id=7, user_id=OWNER, completed_at=datetime(2026, 1, 2))
    result = client.post("/assess/7/answer", data={"question_id": "q01-calibration", "answer_index": 0},
                         follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == "/assess/7/result"
    repo.record_response.assert_not_called()
    repo.complete_run.assert_not_called()
