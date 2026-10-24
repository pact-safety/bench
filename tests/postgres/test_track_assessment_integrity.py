"""Pilot assessments use real owner locks in isolated disposable PG schemas."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from app.db import PooledConnection
from app.repositories.track_assessment_repository import AssessmentConflictError, TrackAssessmentRepository
from tests.postgres.test_assessment_account_isolation import local_database_url
from tests.postgres.test_track_request_concurrency import IsolatedUserCursor

pytestmark = pytest.mark.integration
SPEC = {'id': 'arena-pilot', 'version': 'v1', 'track_slug': 'arena_3', 'section_idx': 0,
        'criteria': [{'id': 'reasoning', 'essential': True}], 'threshold': 80,
        'practical_required': []}
ANSWERS = {'answers': 'Named axes preserve their meanings across the computation.',
           'artifact_url': '', 'transcript_confirmed': False}
EVIDENCE = {'reasoning': 'Named axes preserve their meanings'}


@pytest.fixture
def accounts(local_database_url, monkeypatch):
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', 'postgres-test-only-assessment-signing-key-0001')
    schema = 'track_assessment_test_' + uuid4().hex
    owner, other = str(uuid4()), str(uuid4())
    with psycopg.connect(local_database_url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        pool = None
        try:
            admin.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            admin.execute("CREATE TABLE users (id UUID PRIMARY KEY, settings_json JSONB NOT NULL DEFAULT '{}')")
            admin.execute('INSERT INTO users (id) VALUES (%s), (%s)', (owner, other))
            pool = ConnectionPool(local_database_url, min_size=2, max_size=4, kwargs={
                'autocommit': True, 'row_factory': dict_row, 'cursor_factory': IsolatedUserCursor,
                'options': f'-c search_path={schema}',
            })
            pool.wait(timeout=10)
            yield TrackAssessmentRepository(PooledConnection(pool)), owner, other, admin
        finally:
            if pool is not None:
                pool.close()
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_concurrent_identical_submits_are_one_record_and_changed_payload_conflicts(accounts):
    repo, owner, _, _ = accounts
    request_id = str(uuid4())
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        return repo.submit(owner, request_id, SPEC, ANSWERS)

    with ThreadPoolExecutor(max_workers=2) as workers:
        records = list(workers.map(lambda _: submit(), range(2)))
    assert records[0] == records[1]
    assert repo.list_for_user(owner) == [records[0]]
    with pytest.raises(AssessmentConflictError):
        repo.submit(owner, request_id, SPEC, {**ANSWERS, 'answers': 'Changed response'})
    assert repo.get(owner, request_id) == records[0]


def test_distinct_concurrent_submissions_preserve_both_history_and_other_settings(accounts):
    repo, owner, _, admin = accounts
    admin.execute("UPDATE users SET settings_json = '{\"theme\":\"light\",\"active_track\":{\"slug\":\"arena_3\"}}' WHERE id=%s", (owner,))
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        return repo.submit(owner, str(uuid4()), SPEC, ANSWERS)

    with ThreadPoolExecutor(max_workers=2) as workers:
        records = list(workers.map(lambda _: submit(), range(2)))
    saved = admin.execute('SELECT settings_json FROM users WHERE id=%s', (owner,)).fetchone()[0]
    assert saved['theme'] == 'light' and saved['active_track'] == {'slug': 'arena_3'}
    assert {r['id'] for r in saved['track_assessments']} == {r['id'] for r in records}


def test_owner_boundaries_and_pending_queue(accounts):
    repo, owner, other, _ = accounts
    record = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    assert repo.get(other, record['id']) is None
    with pytest.raises(ValueError, match='not found'):
        repo.review(other, record['id'], other, SPEC, {'reasoning': 4}, EVIDENCE, {})
    assert repo.get(owner, record['id']) == record
    assert repo.pending_reviews() == [record]


def test_concurrent_reviews_are_immutable_and_exact_retry_is_idempotent(accounts):
    repo, owner, reviewer, _ = accounts
    record = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    barrier = Barrier(2)

    def review(score):
        barrier.wait(timeout=5)
        try:
            return repo.review(owner, record['id'], reviewer, SPEC, {'reasoning': score}, EVIDENCE, {})
        except AssessmentConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(review, (0, 4)))
    assert sum(result is not None for result in outcomes) == 1
    saved = repo.get(owner, record['id'])
    assert saved['state'] == 'reviewed'
    assert repo.review(owner, record['id'], reviewer, SPEC, saved['review']['scores'], EVIDENCE, {}) == saved
    assert repo.pending_reviews() == []


def test_review_rejects_stale_version_and_unsubstantiated_excerpt_without_writes(accounts):
    repo, owner, reviewer, _ = accounts
    record = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    with pytest.raises(AssessmentConflictError, match='version'):
        repo.review(owner, record['id'], reviewer, {**SPEC, 'version': 'new'}, {'reasoning': 4}, EVIDENCE, {})
    with pytest.raises(ValueError, match='excerpt'):
        repo.review(owner, record['id'], reviewer, SPEC, {'reasoning': 4}, {'reasoning': 'Invented evidence'}, {})
    assert repo.get(owner, record['id']) == record


def test_stale_general_settings_save_preserves_new_assessment(accounts, monkeypatch):
    import app.main as main

    repo, owner, _, admin = accounts
    monkeypatch.setattr(main, 'conn', repo.conn)
    stale = admin.execute('SELECT settings_json FROM users WHERE id=%s', (owner,)).fetchone()[0]
    record = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    main._save_user_settings(owner, {**stale, 'theme': 'light'})

    saved = admin.execute('SELECT settings_json FROM users WHERE id=%s', (owner,)).fetchone()[0]
    assert saved['theme'] == 'light'
    assert saved['track_assessments'] == [record]


def test_general_settings_cannot_forge_or_replace_assessments(accounts, monkeypatch):
    import app.main as main

    repo, owner, other, admin = accounts
    monkeypatch.setattr(main, 'conn', repo.conn)
    original = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    forged = {**original, 'state': 'reviewed', 'review': {'verdict': 'approved'}}
    for user_id in (owner, other):
        main._save_user_settings(user_id, {'theme': 'light', 'track_assessments': [forged]})

    assert repo.get(owner, original['id']) == original
    saved = admin.execute('SELECT settings_json FROM users WHERE id=%s', (other,)).fetchone()[0]
    assert saved == {'theme': 'light'}


def test_direct_database_edit_cannot_be_signed_by_a_later_review(accounts):
    from psycopg.types.json import Jsonb

    repo, owner, reviewer, admin = accounts
    submitted = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    tampered = {**submitted, 'responses': {**ANSWERS, 'answers': 'Forged learner work'}}
    admin.execute("UPDATE users SET settings_json = jsonb_set(settings_json, '{track_assessments}', %s) WHERE id=%s",
                  (Jsonb([tampered]), owner))
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.review(owner, submitted['id'], reviewer, SPEC, {'reasoning': 4}, {'reasoning': 'Forged learner work'}, {})
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.submit(owner, submitted['id'], SPEC, tampered['responses'])
    assert repo.get(owner, submitted['id'])['state'] == 'pending'


def test_signed_review_cannot_be_tampered_or_copied_between_accounts(accounts):
    from psycopg.types.json import Jsonb
    from app.services.track_assessment_integrity import verify_record

    repo, owner, reviewer, admin = accounts
    submitted = repo.submit(owner, str(uuid4()), SPEC, ANSWERS)
    reviewed = repo.review(owner, submitted['id'], reviewer, SPEC, {'reasoning': 4}, EVIDENCE, {})
    assert verify_record(reviewed, owner)
    admin.execute("UPDATE users SET settings_json = jsonb_set(settings_json, '{track_assessments}', %s) WHERE id=%s",
                  (Jsonb([reviewed]), reviewer))
    assert not verify_record(repo.get(reviewer, submitted['id']), reviewer)
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.review(reviewer, submitted['id'], reviewer, SPEC, {'reasoning': 4}, EVIDENCE, {})
    reviewed['review']['verdict'] = 'not_approved'
    admin.execute("UPDATE users SET settings_json = jsonb_set(settings_json, '{track_assessments}', %s) WHERE id=%s",
                  (Jsonb([reviewed]), owner))
    assert not verify_record(repo.get(owner, submitted['id']), owner)
