"""Promotion claims survive failures and serialize across database connections."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from app.repositories.feedback_repository import FeedbackRepository

pytestmark = pytest.mark.integration
ACTOR = '11111111-1111-1111-1111-111111111111'


@pytest.fixture
def database():
    dsn = os.environ.get('E2E_DATABASE_URL', '')
    if not dsn:
        pytest.skip('Set E2E_DATABASE_URL to disposable local Postgres; DATABASE_URL is never used')
    parsed = urlsplit(dsn)
    if parsed.scheme not in {'postgres', 'postgresql'} or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or parsed.query:
        pytest.fail('E2E_DATABASE_URL must be loopback PostgreSQL without connection overrides')
    schema = 'feedback_claim_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            conn.execute('CREATE TABLE feedback (id BIGINT PRIMARY KEY, gh_issue_url TEXT, gh_issue_number INTEGER, promoted_at TIMESTAMPTZ, promoted_by UUID)')
            conn.execute('INSERT INTO feedback (id) VALUES (7)')
            yield dsn, schema, conn
        finally:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_concurrent_claim_has_one_winner_and_is_committed(database):
    dsn, schema, observer = database
    barrier = Barrier(2)
    def claim():
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            barrier.wait(timeout=5)
            return FeedbackRepository(conn).claim_promotion(fb_id=7, promoted_by=ACTOR)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]
    row = observer.execute('SELECT * FROM feedback WHERE id=7').fetchone()
    assert row['promoted_at'] is not None
    assert str(row['promoted_by']) == ACTOR
    assert row['gh_issue_url'] is None
    # A later process must not retry a claim left by a crashed/uncertain sender.
    assert FeedbackRepository(observer).claim_promotion(fb_id=7, promoted_by=ACTOR) is False


def test_finalization_does_not_overwrite_a_different_link(database):
    _, _, conn = database
    repo = FeedbackRepository(conn)
    assert repo.claim_promotion(fb_id=7, promoted_by=ACTOR)
    kwargs = dict(fb_id=7, gh_issue_url='https://github.com/test/repo/issues/9', gh_issue_number=9, promoted_by=ACTOR)
    assert repo.mark_promoted(**kwargs)
    assert repo.mark_promoted(**kwargs)
    assert repo.mark_promoted(**{**kwargs, 'gh_issue_url': 'https://github.com/test/repo/issues/10', 'gh_issue_number': 10}) is False
    assert conn.execute('SELECT gh_issue_number FROM feedback WHERE id=7').fetchone()['gh_issue_number'] == 9
