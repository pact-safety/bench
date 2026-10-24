from copy import deepcopy
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.repositories.track_assessment_repository import (
    AssessmentConflictError, AssessmentHistoryFullError, TrackAssessmentRepository,
)


OWNER = '11111111-1111-1111-1111-111111111111'
SPEC = {'id': 'arena-foundations', 'version': 'v1', 'track_slug': 'arena_3', 'section_idx': 0,
        'practical_required': []}
RESPONSES = {'answers': 'A detailed explanation and a new example.',
             'artifact_url': '', 'transcript_confirmed': False}


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', 'unit-test-only-track-assessment-key-0001')


def repository(settings=None):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {'settings_json': deepcopy(settings or {})}
    return TrackAssessmentRepository(conn), conn, cur


def submit(repo, request_id=None, **kwargs):
    return repo.submit(OWNER, request_id or str(uuid4()), SPEC,
                       kwargs.pop('responses', RESPONSES),
                       kwargs.pop('modality', 'written'), kwargs.pop('assistance', 'none'), **kwargs)


def test_submission_locks_owner_merges_only_assessment_key_and_invalidates(monkeypatch):
    from app import cache
    invalidate = MagicMock()
    monkeypatch.setattr(cache, 'invalidate', invalidate)
    repo, conn, cur = repository({'theme': 'light', 'active_track': {'slug': 'arena_3'}})
    record = submit(repo)
    assert record['state'] == 'pending' and record['user_id'] == OWNER
    assert record['responses'] == RESPONSES
    calls = [call.args for call in cur.execute.call_args_list]
    assert 'public.users' in calls[0][0] and 'FOR UPDATE' in calls[0][0]
    assert calls[0][1] == (OWNER,)
    assert 'jsonb_set' in calls[1][0] and 'track_assessments' in calls[1][0]
    assert calls[1][1][-1] == OWNER
    conn.transaction.assert_called_once()
    conn.commit.assert_not_called()
    invalidate.assert_called_once_with(f'user_settings:{OWNER}')


def test_retry_returns_original_but_changed_payload_conflicts():
    repo, _, _ = repository()
    original = submit(repo)
    repo, _, cur = repository({'track_assessments': [original]})
    assert submit(repo, original['id']) == original
    assert cur.execute.call_count == 1
    with pytest.raises(AssessmentConflictError):
        submit(repo, original['id'], responses={**RESPONSES, 'answers': 'Different'})


def test_history_limit_rejects_new_submission_but_allows_exact_retry(monkeypatch):
    import app.repositories.track_assessment_repository as module
    monkeypatch.setattr(module, 'MAX_SUBMISSIONS', 1)
    repo, _, _ = repository()
    original = submit(repo)
    repo, _, cur = repository({'track_assessments': [original]})
    with pytest.raises(AssessmentHistoryFullError):
        submit(repo)
    assert submit(repo, original['id']) == original
    assert not any('UPDATE' in c.args[0] and 'SET settings' in c.args[0]
                   for c in cur.execute.call_args_list)


@pytest.mark.parametrize('kwargs', [
    {'request_id': 'bad'}, {'modality': 'audio-file'}, {'assistance': 'invented'},
    {'modality': 'oral'}, {'responses': {**RESPONSES, 'answers': ' '}},
    {'responses': {**RESPONSES, 'answers': 'x' * 12001}},
    {'responses': {**RESPONSES, 'artifact_url': 'javascript:alert(1)'}},
    {'responses': {**RESPONSES, 'audio': 'not stored'}},
])
def test_invalid_submission_never_opens_transaction(kwargs):
    repo, conn, _ = repository()
    with pytest.raises(ValueError):
        submit(repo, **kwargs)
    conn.transaction.assert_not_called()


def test_owner_lookup_and_missing_user():
    repo, _, cur = repository()
    cur.fetchone.return_value = None
    assert repo.get(OWNER, str(uuid4())) is None
    assert cur.execute.call_args.args[1] == (OWNER,)
    with pytest.raises(ValueError, match='user'):
        submit(repo)


def test_review_evaluates_server_side_and_rejects_conflicting_retry(monkeypatch):
    import app.services.track_exams as exams
    review = {'reviewer_id': 'reviewer', 'verdict': 'approved', 'scores': {'explain': 4},
              'evidence': {'explain': 'A detailed explanation'}, 'review_type': 'human'}
    evaluate = MagicMock(return_value=review)
    monkeypatch.setattr(exams, 'evaluate_review', evaluate)
    repo, _, _ = repository()
    pending = submit(repo)
    repo, _, _ = repository({'track_assessments': [pending]})
    checked = repo.review(OWNER, pending['id'], 'reviewer', SPEC,
                          review['scores'], review['evidence'], {})
    assert checked['state'] == 'reviewed'
    assert checked['review']['verdict'] == 'approved'
    evaluate.assert_called_once_with(SPEC, review['scores'], review['evidence'], 'reviewer')
    repo, _, cur = repository({'track_assessments': [checked]})
    assert repo.review(OWNER, pending['id'], 'reviewer', SPEC,
                       review['scores'], review['evidence'], {}) == checked
    assert cur.execute.call_count == 1
    with pytest.raises(AssessmentConflictError):
        repo.review(OWNER, pending['id'], 'reviewer', SPEC,
                    {'explain': 0}, review['evidence'], {})


def test_stale_review_cannot_rewrite_submission(monkeypatch):
    repo, _, _ = repository()
    pending = submit(repo)
    repo, _, cur = repository({'track_assessments': [pending]})
    with pytest.raises(AssessmentConflictError, match='version'):
        repo.review(OWNER, pending['id'], 'reviewer', {**SPEC, 'version': 'v2'}, {}, {}, {})
    assert cur.execute.call_count == 1


def test_duplicate_review_with_original_whitespace_is_idempotent():
    spec = {**SPEC, 'criteria': [{'id': 'explain', 'essential': True}], 'threshold': 80}
    evidence = {'explain': '  A detailed explanation  '}
    repo, _, _ = repository()
    pending = repo.submit(OWNER, str(uuid4()), spec, RESPONSES)
    repo, _, _ = repository({'track_assessments': [pending]})
    reviewed = repo.review(OWNER, pending['id'], 'reviewer', spec, {'explain': 4}, evidence, {})
    repo, _, _ = repository({'track_assessments': [reviewed]})
    assert repo.review(OWNER, pending['id'], 'reviewer', spec, {'explain': 4}, evidence, {}) == reviewed


def test_failed_commit_does_not_invalidate_cache(monkeypatch):
    from app import cache
    invalidated = MagicMock()
    monkeypatch.setattr(cache, 'invalidate', invalidated)
    repo, conn, _ = repository()
    conn.transaction.return_value.__exit__.side_effect = RuntimeError('commit failed')
    with pytest.raises(RuntimeError):
        submit(repo)
    invalidated.assert_not_called()


def test_tampered_pending_record_cannot_be_reviewed_or_retried():
    repo, _, _ = repository()
    pending = submit(repo)
    pending['responses']['answers'] = 'Tampered response'
    repo, _, cur = repository({'track_assessments': [pending]})
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.review(OWNER, pending['id'], 'reviewer', SPEC, {}, {}, {})
    with pytest.raises(AssessmentConflictError, match='integrity'):
        submit(repo, pending['id'], responses=pending['responses'])
    assert not any('SET settings_json' in c.args[0] for c in cur.execute.call_args_list)


def test_signed_record_copied_to_another_owner_cannot_be_reviewed():
    from app.services.track_assessment_integrity import sign_record
    repo, _, _ = repository()
    pending = submit(repo)
    pending['user_id'] = 'different-owner'
    pending = sign_record(pending)
    repo, _, _ = repository({'track_assessments': [pending]})
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.review(OWNER, pending['id'], 'reviewer', SPEC, {}, {}, {})


def test_review_refreshes_signature_and_tampered_review_cannot_retry():
    from app.services.track_assessment_integrity import verify_record
    spec = {**SPEC, 'criteria': [{'id': 'explain', 'essential': True}], 'threshold': 80}
    repo, _, _ = repository()
    pending = repo.submit(OWNER, str(uuid4()), spec, RESPONSES)
    repo, _, _ = repository({'track_assessments': [pending]})
    reviewed = repo.review(OWNER, pending['id'], 'reviewer', spec, {'explain': 4},
                           {'explain': 'A detailed explanation'}, {})
    assert verify_record(reviewed, OWNER)
    assert reviewed['integrity_signature'] != pending['integrity_signature']
    reviewed['review']['scores']['explain'] = 0
    repo, _, _ = repository({'track_assessments': [reviewed]})
    with pytest.raises(AssessmentConflictError, match='integrity'):
        repo.review(OWNER, pending['id'], 'reviewer', spec, {'explain': 0},
                    {'explain': 'A detailed explanation'}, {})
