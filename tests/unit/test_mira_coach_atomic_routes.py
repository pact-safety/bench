import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")

import re
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.repositories.mira_repository import CoachWriteResult
from tests.unit.test_mira_coach_launch import _coach
from tests.unit.test_mira_routes import _SESS, _turn


def field(response, name):
    return re.search(rf'name="{name}" value="([^"]*)"', response.text).group(1)


def test_explicit_new_forms_have_distinct_tokens_and_forward_identity(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    first, second = client.get('/mira?new=1'), client.get('/mira?new=1')
    token = field(first, 'request_token')
    assert str(UUID(token)) == token
    assert token != field(second, 'request_token')
    assert field(first, 'force_new') == '1'
    assert field(first, 'session_id') == ''
    response = client.post('/mira/coach', data={
        'message': 'My plan', 'stage': 'frame', 'request_token': token, 'force_new': '1',
    }, follow_redirects=False)
    assert response.status_code == 303
    assert m.mira_repo.append_coach_note.call_args.kwargs['request_token'] == token
    assert m.mira_repo.append_coach_note.call_args.kwargs['force_new'] is True


@pytest.mark.parametrize('existing', [False, True])
def test_uncertain_save_keeps_token_session_stage_and_draft_for_retry(monkeypatch, existing):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', Mock(side_effect=RuntimeError('connection lost')))
    token = str(uuid4())
    data = {'message': 'Retain this unsent note', 'stage': 'attempt' if existing else 'frame',
            'request_token': token, 'force_new': '0' if existing else '1',
            'session_id': _SESS if existing else ''}
    response = client.post('/mira/coach', data=data)
    assert response.status_code == 503
    for name in ('request_token', 'session_id', 'stage', 'force_new'):
        assert field(response, name) == data[name]
    assert data['message'] in response.text


@pytest.mark.parametrize('status,code', [('saved', 303), ('duplicate', 303), ('missing', 404), ('readonly', 409)])
def test_repository_outcome_controls_http_response(monkeypatch, status, code):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', Mock(return_value=CoachWriteResult(_SESS, status)))
    response = client.post('/mira/coach', data={'session_id': _SESS,
        'message': 'My plan', 'stage': 'frame'}, follow_redirects=False)
    assert response.status_code == code
    if code == 303:
        assert response.headers['location'] == f'/mira/session/{_SESS}'


def test_conflicting_initial_submit_retains_draft_on_resolved_session(monkeypatch):
    turn = _turn('user', 'The winning plan', id='u1')
    turn.provider_used = 'coach:frame'
    client, m, _ = _coach(monkeypatch, [turn])
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', Mock(return_value=CoachWriteResult(_SESS, 'stale')))
    token = str(uuid4())
    response = client.post('/mira/coach', data={'message': 'My other plan',
        'stage': 'frame', 'request_token': token})
    assert response.status_code == 409
    assert field(response, 'session_id') == _SESS
    assert field(response, 'request_token') == token
    assert field(response, 'stage') == 'attempt'
    assert 'My other plan' in response.text
    assert 'advanced in another tab' in response.text


def test_invalid_request_identity_preserves_draft_and_reports_bad_form(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', Mock(side_effect=ValueError('bad token')))
    response = client.post('/mira/coach', data={'message': 'Keep my note',
        'stage': 'frame', 'request_token': 'invalid', 'force_new': '1'})
    assert response.status_code == 400
    assert 'Keep my note' in response.text
    assert 'form is out of date' in response.text
