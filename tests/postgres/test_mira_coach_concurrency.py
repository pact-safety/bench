"""Coaching writes use only disposable loopback Postgres, without providers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from app.db import PooledConnection
from app.repositories.mira_repository import MiraRepository
from tests.postgres.test_assessment_account_isolation import local_database_url

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(local_database_url):
    schema = "mira_coach_test_" + uuid4().hex
    with psycopg.connect(local_database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        pool = None
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            admin.execute("""
                CREATE TABLE mira_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL,
                    modality TEXT NOT NULL, title TEXT, meta JSONB NOT NULL DEFAULT '{}',
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ended_at TIMESTAMPTZ
                )
            """)
            admin.execute("""
                CREATE TABLE mira_turns (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id UUID REFERENCES mira_sessions(id), role TEXT NOT NULL,
                    content TEXT NOT NULL CHECK (content <> '__fail__'), provider_used TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), tool_calls JSONB,
                    citations JSONB, latency_ms JSONB, interrupted BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            pool = ConnectionPool(local_database_url, min_size=2, max_size=4, kwargs={
                "autocommit": True, "row_factory": dict_row,
                "options": f"-c search_path={schema}",
            })
            pool.wait(timeout=10)
            yield MiraRepository(PooledConnection(pool))
        finally:
            if pool is not None:
                pool.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def concurrent(*calls):
    barrier = Barrier(len(calls))

    def invoke(call):
        barrier.wait(timeout=5)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as workers:
        return list(workers.map(invoke, calls))


def test_concurrent_first_submits_and_retries_save_one_session_and_note(repo):
    owner = str(uuid4())
    first_token, second_token = str(uuid4()), str(uuid4())

    def submit(token):
        return repo.append_coach_note(user_id=owner, stage="frame", content="My plan",
            coach_context={"kind": "problem", "slug": "attention"}, request_token=token)

    results = concurrent(lambda: submit(first_token), lambda: submit(second_token))
    assert sorted(r.status for r in results) == ["duplicate", "saved"]
    assert len({r.session_id for r in results}) == 1
    assert len(repo.list_sessions(owner)) == 1
    assert len(repo.list_turns(results[0].session_id, fresh=True)) == 1
    assert submit(first_token).status == "duplicate"
    session_id = results[0].session_id
    for stage in ("attempt", "check", "reflect"):
        result = repo.append_coach_note(user_id=owner, session_id=session_id,
            stage=stage, content=f"My {stage}", coach_context={"kind": "problem", "slug": "attention"})
        assert result.status == "saved"
    # Both accepted first forms keep their identity after completion, including
    # the losing writer's different token. Neither replay starts another run.
    for token in (first_token, second_token):
        retry = submit(token)
        assert (retry.session_id, retry.status) == (session_id, "duplicate")
    assert len(repo.list_sessions(owner)) == 1
    assert len(repo.list_turns(session_id, fresh=True)) == 4


def test_concurrent_stage_posts_preserve_first_writer_and_conflict_other_draft(repo):
    owner = str(uuid4())
    first = repo.append_coach_note(user_id=owner, stage="frame", content="Goal", coach_context={})

    def submit(content):
        return repo.append_coach_note(user_id=owner, session_id=first.session_id,
            stage="attempt", content=content, coach_context={})

    results = concurrent(lambda: submit("Plan A"), lambda: submit("Plan B"))
    assert sorted(r.status for r in results) == ["saved", "stale"]
    turns = repo.list_turns(first.session_id, fresh=True)
    assert len(turns) == 2
    assert {t.provider_used for t in turns} == {"coach:frame", "coach:attempt"}


def test_explicit_new_retry_deduplicates_but_new_tokens_create_distinct_sessions(repo):
    owner = str(uuid4())
    first_token, second_token = str(uuid4()), str(uuid4())

    def submit(token):
        return repo.append_coach_note(user_id=owner, stage="frame", content="Goal",
            coach_context={}, request_token=token, force_new=True)

    results = concurrent(lambda: submit(first_token), lambda: submit(first_token))
    assert sorted(r.status for r in results) == ["duplicate", "saved"]
    another = submit(second_token)
    assert another.status == "saved"
    assert another.session_id != results[0].session_id
    assert len(repo.list_sessions(owner)) == 2


def test_foreign_and_legacy_sessions_reject_writes_and_failed_create_rolls_back(repo):
    owner, outsider = str(uuid4()), str(uuid4())
    session_id = repo.create_session(user_id=owner)
    for uid, expected in ((owner, "readonly"), (outsider, "missing")):
        result = repo.append_coach_note(user_id=uid, session_id=session_id,
            stage="frame", content="Goal", coach_context={})
        assert result.status == expected
    assert repo.list_turns(session_id, fresh=True) == []
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.append_coach_note(user_id=owner, stage="frame", content="__fail__",
            coach_context={}, request_token=str(uuid4()), force_new=True)
    assert len(repo.list_sessions(owner)) == 1


def test_stage_order_follows_locked_writes_not_transaction_start_time(repo):
    owner = str(uuid4())
    session_id = repo.create_session(user_id=owner, coach_context={})
    with repo.conn.transaction():
        with repo.conn.cursor() as cur:
            cur.execute("SELECT now()")
        with ThreadPoolExecutor(max_workers=1) as worker:
            result = worker.submit(repo.append_coach_note, user_id=owner,
                session_id=session_id, stage="frame", content="Goal", coach_context={}).result(timeout=5)
            assert result.status == "saved"
        assert repo.append_coach_note(user_id=owner, session_id=session_id,
            stage="attempt", content="Plan", coach_context={}).status == "saved"
    assert [t.provider_used for t in repo.list_turns(session_id, fresh=True)] == ["coach:frame", "coach:attempt"]
    assert repo.append_coach_note(user_id=owner, session_id=session_id,
        stage="check", content="Test", coach_context={}).status == "saved"


def test_new_session_order_follows_creation_not_transaction_start_time(repo):
    owner = str(uuid4())
    with repo.conn.transaction():
        with repo.conn.cursor() as cur:
            cur.execute("SELECT now()")
        with ThreadPoolExecutor(max_workers=1) as worker:
            earlier = worker.submit(repo.append_coach_note, user_id=owner,
                stage="frame", content="Earlier plan", coach_context={},
                request_token=str(uuid4()), force_new=True).result(timeout=5)
        later = repo.append_coach_note(user_id=owner, stage="frame",
            content="Later plan", coach_context={}, request_token=str(uuid4()), force_new=True)
    assert repo.list_sessions(owner)[0].id == later.session_id
    assert later.session_id != earlier.session_id
    resumed = repo.append_coach_note(user_id=owner, stage="attempt", content="Next step",
        coach_context={}, request_token=str(uuid4()))
    assert resumed.status == "saved"
    assert resumed.session_id == later.session_id
