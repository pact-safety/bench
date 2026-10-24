from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.unit.test_tracks_routes import _signed_in_client, _USER_UUID


@pytest.fixture
def pilot(monkeypatch):
    import app.main as m
    from app.services import tracks
    settings = {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': []}}
    client = _signed_in_client(monkeypatch, settings)
    catalog = tracks.load_all_tracks(Path('content/tracks'))
    monkeypatch.setattr(tracks, '_tracks_by_slug', catalog)
    monkeypatch.setattr(m, '_tracks_by_slug', catalog)
    monkeypatch.setattr(tracks, 'AVAILABLE_TRACK_SLUGS', ('arena_3', 'ml4good-prework-fall-2026'))
    monkeypatch.setenv('LIS_ADMIN_USER_IDS', str(uuid4()))
    repo = SimpleNamespace(submit=Mock(), get=Mock(return_value=None), list_for_user=Mock(return_value=[]), pending_reviews=Mock(return_value=[]), review=Mock())
    monkeypatch.setattr(m, 'track_assessment_repo', repo, raising=False)
    return client, m, settings, repo


def test_exam_pilot_serves_same_questions_without_a_microphone(pilot):
    client, m, _, _ = pilot
    response = client.get('/tracks/arena_3/sections/0/exam')
    assert response.status_code == 200
    assert 'name="answers"' in response.text
    assert 'name="exam_version"' in response.text
    assert 'transcript_confirmed' in response.text
    assert '80' in response.text


def test_oral_without_confirmation_preserves_draft_and_does_not_submit(pilot):
    client, m, _, repo = pilot
    from app.services.track_exams import spec_for_section
    spec = spec_for_section(m.get_track('arena_3'), 0)
    response = client.post('/tracks/arena_3/sections/0/exam', data={'answers':'My unconfirmed transcript', 'modality':'oral', 'assistance':'none','exam_version':spec['version'],'request_id':str(uuid4())})
    assert response.status_code == 400
    assert 'My unconfirmed transcript' in response.text
    repo.submit.assert_not_called()


def test_stale_exam_draft_is_not_silently_upgraded(pilot):
    client, m, _, repo = pilot
    response = client.post('/tracks/arena_3/sections/0/exam', data={'answers':'My older answer', 'modality':'written','assistance':'none','exam_version':'old','request_id':str(uuid4())})
    assert response.status_code == 409
    assert 'My older answer' in response.text
    assert 'value="old"' in response.text
    repo.submit.assert_not_called()


def test_non_admin_review_routes_do_not_read_other_learners(pilot):
    client, m, _, repo = pilot
    response = client.get('/track-assessments/review?owner_id=other&attempt_id=attempt')
    assert response.status_code == 403
    response = client.post('/track-assessments/other/attempt/review', data={})
    assert response.status_code == 403
    repo.get.assert_not_called()
    repo.pending_reviews.assert_not_called()
    repo.review.assert_not_called()


def test_unknown_exam_never_becomes_generic_testout(pilot):
    client, _, _, repo = pilot
    assert client.get('/tracks/arena_3/sections/1/exam').status_code == 404
    repo.submit.assert_not_called()


def test_pending_submission_does_not_complete_practice_or_unlock(pilot):
    client, m, settings, repo = pilot
    from app.services.track_exams import spec_for_section
    spec = spec_for_section(m.get_track('arena_3'),0)
    rid = str(uuid4())
    repo.submit.return_value = {'id':rid,'state':'pending'}
    response = client.post('/tracks/arena_3/sections/0/exam', data={'answers':'My explanation and application','modality':'written','assistance':'none','exam_version':spec['version'],'request_id':rid}, follow_redirects=False)
    assert response.status_code == 303
    assert repo.submit.call_args.args[0] == _USER_UUID
    assert settings['active_track']['checkpoint_passed_sections'] == []


def _review_payload(pilot, monkeypatch):
    client, m, _, repo = pilot
    from app.services.track_exams import spec_for_section
    monkeypatch.setenv('LIS_ADMIN_USER_IDS', _USER_UUID)
    spec = spec_for_section(m.get_track('arena_3'), 0)
    owner, attempt = str(uuid4()), str(uuid4())
    record = dict(id=attempt, user_id=owner, track_slug='arena_3', section_idx=0,
                  spec_id=spec['id'], spec_version=spec['version'], state='pending',
                  modality='written', assistance='none',
                  responses={'answers':'I checked the tensor values.', 'artifact_url':''})
    repo.get.return_value = record
    form = {'exam_version':spec['version']}
    for criterion in spec['criteria']:
        form['score_' + criterion['id']] = '4'
        form['evidence_' + criterion['id']] = 'tensor values'
    return owner, attempt, spec, form


def test_review_uses_owner_practical_checks_and_valid_utc_evidence(pilot, monkeypatch):
    client, m, _, repo = pilot
    from app.repositories.track_assessment_repository import _practical
    owner, attempt, spec, form = _review_payload(pilot, monkeypatch)
    gate = Mock(return_value={'passed':True, 'items':[{'slug':s, 'passed':True} for s in spec['practical_required']]})
    monkeypatch.setattr(m, '_track_gate_status', gate)
    repo.review.side_effect = lambda *args: _practical(args[-1])
    response = client.post(f'/track-assessments/{owner}/{attempt}/review', data=form, follow_redirects=False)
    assert response.status_code == 303
    assert gate.call_args.args[1] == owner
    assert repo.review.call_args.args[:3] == (owner, attempt, _USER_UUID)
    assert repo.review.call_args.args[-1]['verified_slugs'] == spec['practical_required']


def test_review_does_not_trust_client_practical_claims(pilot, monkeypatch):
    client, m, _, repo = pilot
    owner, attempt, _, form = _review_payload(pilot, monkeypatch)
    monkeypatch.setattr(m, '_track_gate_status', lambda *args: {'passed':False, 'items':[]})
    form['practical_passed'] = 'true'
    response = client.post(f'/track-assessments/{owner}/{attempt}/review', data=form)
    assert response.status_code == 409
    assert 'tensor values' in response.text
    repo.review.assert_not_called()


def test_review_save_and_recovery_outage_preserves_escaped_draft(pilot, monkeypatch):
    client, m, _, repo = pilot
    owner, attempt, _, form = _review_payload(pilot, monkeypatch)
    record = repo.get.return_value
    repo.get.side_effect = [record, RuntimeError('read unavailable')]
    repo.review.side_effect = RuntimeError('write status unknown')
    monkeypatch.setattr(m, '_track_gate_status', lambda *args: None)
    form['evidence_axes'] = '<script>keep my draft</script>'
    response = client.post(f'/track-assessments/{owner}/{attempt}/review', data=form)
    assert response.status_code == 503
    assert '&lt;script&gt;keep my draft&lt;/script&gt;' in response.text
    assert '<script>keep my draft</script>' not in response.text
    assert 'no review has been recorded' not in response.text
    assert 'No submissions are waiting' not in response.text


def test_submission_outage_preserves_answers_and_retry_token(pilot):
    client, m, _, repo = pilot
    from app.services.track_exams import spec_for_section
    spec = spec_for_section(m.get_track('arena_3'), 0)
    request_id = str(uuid4())
    repo.submit.side_effect = RuntimeError('unknown commit status')
    repo.list_for_user.side_effect = RuntimeError('read unavailable')
    response = client.post('/tracks/arena_3/sections/0/exam', data={'answers':'My saved draft', 'modality':'written', 'assistance':'none', 'exam_version':spec['version'], 'request_id':request_id})
    assert response.status_code == 503
    assert 'My saved draft' in response.text
    assert f'value="{request_id}"' in response.text
