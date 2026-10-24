import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")

"""Coaching preserves failed-save drafts and validated return-to-work context."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.repositories.mira_repository import CoachWriteResult
from tests.unit.test_mira_coach_launch import _coach
from tests.unit.test_mira_routes import _SESS, _USER_UUID
from tests.unit.test_tracks_routes import _sample_tracks


@pytest.mark.parametrize('existing', [False, True])
def test_failed_note_append_retains_draft_and_never_claims_saved(monkeypatch, existing):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'create_session', lambda **kw: _SESS)
    append = Mock(side_effect=RuntimeError('write failed'))
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', append)
    data = {'stage': 'frame', 'message': 'Keep this explanation after the failure.'}
    if existing:
        data['session_id'] = _SESS
    response = client.post('/mira/coach', data=data)
    assert response.status_code == 503
    assert 'Keep this explanation after the failure.' in response.text
    assert 'could not be confirmed saved' in response.text
    assert 'Reflection saved' not in response.text
    assert append.call_count == 1


def test_session_creation_failure_retains_first_draft(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    append = Mock(side_effect=RuntimeError('write failed'))
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', append)
    response = client.post('/mira/coach', data={'stage': 'frame', 'message': 'My unsaved plan'})
    assert response.status_code == 503
    assert 'My unsaved plan' in response.text
    append.assert_called_once()


def test_history_read_failure_never_restarts_coach_or_writes(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'list_turns', Mock(side_effect=RuntimeError('read failed')))
    save = Mock(side_effect=RuntimeError('read failed inside transaction'))
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', save)
    response = client.post('/mira/coach', data={'session_id': _SESS, 'stage': 'attempt', 'message': 'Keep this attempt through an outage'})
    assert response.status_code == 503
    assert 'Keep this attempt through an outage' in response.text
    assert 'value="frame"' not in response.text
    save.assert_called_once()


def test_problem_context_is_resolved_and_persisted_for_current_user(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    problem = SimpleNamespace(slug='matrix-shapes', title='Matrix shapes')
    monkeypatch.setattr(m.problem_repo, 'get_by_slug', lambda slug: problem if slug == problem.slug else None)
    save = Mock(return_value=CoachWriteResult(_SESS, "saved"))
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', save)
    page = client.get('/mira?problem=matrix-shapes')
    assert page.status_code == 200
    assert 'href="/problem/matrix-shapes"' in page.text
    response = client.post('/mira/coach', data={'problem': 'matrix-shapes', 'stage': 'frame', 'message': 'My shape constraints'}, follow_redirects=False)
    assert response.status_code == 303
    assert save.call_args.kwargs['user_id'] == _USER_UUID
    assert save.call_args.kwargs['coach_context'] == {'kind': 'problem', 'slug': 'matrix-shapes'}


def test_track_context_returns_to_exact_section_and_cannot_be_redirect_url(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m, 'get_track', lambda slug: _sample_tracks().get(slug))
    page = client.get('/mira?track=arena_3&section=1')
    assert page.status_code == 200
    assert 'href="/tracks/arena_3#section-1"' in page.text
    assert '0.2 Setup' in page.text
    for query in ('track=https://attacker.invalid&section=1', 'track=arena_3&section=999'):
        page = client.get('/mira?' + query)
        assert page.status_code == 200
        assert 'href="https://attacker.invalid' not in page.text
        assert 'Return to Your practice' in page.text


def test_resumed_context_is_owned_session_context_not_posted_override(monkeypatch):
    client, m, session = _coach(monkeypatch)
    session.meta['context'] = {'kind': 'problem', 'slug': 'matrix-shapes'}
    problem = SimpleNamespace(slug='matrix-shapes', title='Matrix shapes')
    monkeypatch.setattr(m.problem_repo, 'get_by_slug', lambda slug: problem if slug == problem.slug else None)
    response = client.post('/mira/coach', data={'session_id': _SESS, 'stage': 'bogus', 'message': 'Keep this draft', 'problem': 'other-problem'})
    assert response.status_code == 400
    assert 'href="/problem/matrix-shapes"' in response.text
    assert 'Keep this draft' in response.text


def test_session_lookup_outage_preserves_draft_without_creating_session(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m.mira_repo, 'get_session', Mock(side_effect=RuntimeError('read unavailable')))
    create = Mock()
    append = Mock()
    monkeypatch.setattr(m.mira_repo, 'create_session', create)
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', append)
    response = client.post('/mira/coach', data={'session_id': _SESS, 'stage': 'attempt', 'message': 'Keep my attempt if ownership lookup is down'})
    assert response.status_code == 503
    assert 'Keep my attempt if ownership lookup is down' in response.text
    assert f'value="{_SESS}"' in response.text
    create.assert_not_called()
    append.assert_not_called()
