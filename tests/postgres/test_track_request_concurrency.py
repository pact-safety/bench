"""Track requests exercise real transactions in a disposable local schema."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from app.db import PooledConnection
from app.repositories.feedback_repository import FeedbackRepository
from tests.postgres.test_assessment_account_isolation import local_database_url

pytestmark = pytest.mark.integration


class IsolatedUserCursor(psycopg.Cursor):
    def execute(self, query, params=None, **kwargs):
        # Keep hard-qualified account reads inside this test's schema. All
        # locking and request SQL still executes against real PostgreSQL.
        if isinstance(query, str):
            query = query.replace('public.users', 'users')
        return super().execute(query, params, **kwargs)


@pytest.fixture
def accounts(local_database_url):
    schema = 'track_request_test_' + uuid4().hex
    owner, other = str(uuid4()), str(uuid4())
    with psycopg.connect(local_database_url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        pool = None
        try:
            admin.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            admin.execute('CREATE TABLE users (id UUID PRIMARY KEY)')
            admin.execute('INSERT INTO users (id) VALUES (%s), (%s)', (owner, other))
            admin.execute("""
                CREATE TABLE feedback (
                    id BIGSERIAL PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id),
                    url TEXT, page_title TEXT, theme TEXT, viewport_width INTEGER,
                    body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    processed_at TIMESTAMPTZ, processing_notes TEXT
                )
            """)
            pool = ConnectionPool(local_database_url, min_size=2, max_size=4, kwargs={
                'autocommit': True, 'row_factory': dict_row, 'cursor_factory': IsolatedUserCursor,
                'options': f'-c search_path={schema}',
            })
            pool.wait(timeout=10)
            yield FeedbackRepository(PooledConnection(pool)), owner, other
        finally:
            if pool is not None:
                pool.close()
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_concurrent_requests_make_one_owned_feedback_row(accounts):
    repo, owner, _ = accounts
    barrier = Barrier(2)

    def request():
        barrier.wait(timeout=5)
        return repo.request_track(owner, 'mechinterp', 'Mechanistic interpretability')

    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(lambda _: request(), range(2)))
    assert ids[0] == ids[1]
    rows = repo.list_for_user(owner)
    assert len(rows) == 1
    assert rows[0].id == ids[0]
    assert rows[0].status == 'open'
    assert rows[0].body == 'Track access request: mechinterp'


def test_requests_are_separate_by_owner_and_slug_and_reuse_closed_requests(accounts):
    repo, owner, other = accounts
    first = repo.request_track(owner, 'mechinterp', 'Original name')
    assert repo.request_track(other, 'mechinterp', 'Original name') != first
    assert repo.request_track(owner, 'mats', 'MATS') != first
    repo.set_status(first, 'archived', 'Review complete')
    assert repo.request_track(owner, 'mechinterp', 'New name') == first
    saved = repo.get(first)
    assert saved.status == 'archived'
    assert saved.processing_notes == 'Review complete'
    assert saved.page_title == 'Original name'
    assert len(repo.list_for_user(owner)) == 2
    assert len(repo.list_for_user(other)) == 1


def test_missing_owner_cannot_insert_feedback(accounts):
    repo, _, _ = accounts
    missing = str(uuid4())
    with pytest.raises(ValueError, match='user'):
        repo.request_track(missing, 'mats', 'MATS')
    assert repo.list_for_user(missing) == []
