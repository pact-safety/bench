"""Run against disposable local Postgres via E2E_DATABASE_URL.

Each test gets its own schema; no Supabase account or provider is involved.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from app.db import PooledConnection
from app.repositories.assessment_repository import AssessmentRepository
from app.services import assessment

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def local_database_url():
    # This suite only uses the throwaway E2E database, never the app database.
    dsn = os.environ.get("E2E_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Set E2E_DATABASE_URL to disposable local Postgres")
    parsed = urlsplit(dsn)
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.query):
        pytest.fail("E2E_DATABASE_URL must be loopback PostgreSQL without connection overrides")
    return dsn


@pytest.fixture
def repo(local_database_url):
    dsn = local_database_url
    schema = "assessment_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        pool = None
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            admin.execute("""
                CREATE TABLE assessment_runs (
                    id BIGSERIAL PRIMARY KEY, user_id UUID NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    final_scores_json JSONB NOT NULL DEFAULT '{}'
                )
            """)
            admin.execute("""
                CREATE TABLE assessment_responses (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES assessment_runs(id),
                    question_id TEXT NOT NULL, answer_index INTEGER NOT NULL,
                    axis_scores_json JSONB NOT NULL DEFAULT '{}',
                    answered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            pool = ConnectionPool(dsn, min_size=2, max_size=4, kwargs={
                "autocommit": True, "row_factory": dict_row,
                "options": f"-c search_path={schema}",
            })
            pool.wait(timeout=10)
            yield AssessmentRepository(PooledConnection(pool))
        finally:
            if pool is not None:
                pool.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_two_accounts_cannot_read_or_mutate_each_others_run(repo):
    owner, outsider = str(uuid4()), str(uuid4())
    run_id = repo.start_run(owner)
    q = assessment.Q_CALIBRATION
    repo.record_response(run_id, q.id, 0, user_id=owner)
    before = repo.responses_for_run(run_id, user_id=owner)
    assert repo.get_run(run_id, user_id=outsider) is None
    assert repo.responses_for_run(run_id, user_id=outsider) == []
    assert repo.record_response(run_id, q.id, 3, user_id=outsider) is None
    assert repo.complete_run(run_id, user_id=outsider) is False
    assert repo.responses_for_run(run_id, user_id=owner) == before
    assert repo.get_run(run_id, user_id=owner).completed_at is None


def test_simultaneous_answers_and_completions_keep_one_response_and_result(repo):
    owner = str(uuid4())
    run_id = repo.start_run(owner)
    ids = []
    for _ in range(assessment.MAX_QUESTIONS - 1):
        question = assessment.pick_next(ids)
        assert question is not None
        repo.record_response(run_id, question.id, 0, user_id=owner)
        ids.append(question.id)
    question = assessment.pick_next(ids)
    assert question is not None
    barrier = Barrier(2)

    def answer():
        barrier.wait(timeout=5)
        try:
            return repo.record_response(run_id, question.id, 0, user_id=owner)
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as workers:
        answers = list(workers.map(lambda _: answer(), range(2)))
    assert answers.count("stale") == 1
    assert sum(isinstance(value, int) for value in answers) == 1
    responses = repo.responses_for_run(run_id, user_id=owner)
    assert len(responses) == len({r.question_id for r in responses}) == assessment.MAX_QUESTIONS
    # Check the raw table too: the history API intentionally deduplicates old rows.
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM assessment_responses WHERE run_id = %s", (run_id,))
        assert cur.fetchone()["count"] == assessment.MAX_QUESTIONS

    barrier = Barrier(2)

    def complete():
        barrier.wait(timeout=5)
        return repo.complete_run(run_id, user_id=owner)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: complete(), range(2)))
    assert sorted(results) == [False, True]
    saved = repo.get_run(run_id, user_id=owner)
    assert saved.completed_at is not None
    assert saved.final_scores == assessment.aggregate_scores(responses)
    assert repo.record_response(run_id, question.id, 3, user_id=owner) is None
    assert repo.complete_run(run_id, user_id=owner) is False
    assert repo.get_run(run_id, user_id=owner) == saved
