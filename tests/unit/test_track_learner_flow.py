from copy import deepcopy
from unittest.mock import Mock
from tests.unit.test_tracks_routes import _signed_in_client


def test_track_checks_do_not_call_exercise_review(monkeypatch):
    import app.main as m
    from tests.unit.test_tracks_routes import _sample_tracks
    review = Mock(side_effect=AssertionError('not a real exercise attempt'))
    monkeypatch.setattr(m.review_service, 'review_attempt', review)
    questions = m._track_socratic_questions_for_section(track=_sample_tracks()['arena_3'], idx=0, user_id='learner')
    assert questions
    review.assert_not_called()


def test_pending_track_cannot_activate_or_edit_saved_progress(monkeypatch):
    settings = {'active_track': {'slug': 'prework', 'checkpoint_passed_sections': []}}
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m
    monkeypatch.setattr(m.tracks_service, 'is_available_track', lambda slug: slug == 'arena_3', raising=False)
    before = deepcopy(settings)
    for path, data in [('/activate', {}), ('/sections/0/session', {'stopping_point': 'changed'}), ('/sections/0/complete', {'checkpoint_pass': 1})]:
        response = client.post('/tracks/prework' + path, data=data, follow_redirects=False)
        assert response.status_code == 409
    assert settings == before


def test_notes_precede_sections_and_locked_links_are_absent(monkeypatch):
    client = _signed_in_client(monkeypatch, {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': []}})
    html = client.get('/tracks/arena_3').text
    assert html.index('Track notes') < html.index('id="section-0"')
    assert 'href="https://example.com/0.2"' not in html
    assert 'Locked' in html
    assert '0.1 Prerequisites' in html


def test_pending_catalog_has_request_not_activation(monkeypatch):
    client = _signed_in_client(monkeypatch, {})
    import app.main as m
    monkeypatch.setattr(m.tracks_service, 'is_available_track', lambda slug: slug == 'arena_3', raising=False)
    html = client.get('/tracks').text
    assert 'Request this track' in html
    assert 'action="/tracks/prework/activate"' not in html


def test_old_answer_survives_but_cannot_complete_updated_check(monkeypatch):
    settings = {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': [],
        'checkpoint_questions_per_section': {'0': ['What is your Explore plan?']},
        'checkpoint_response_per_section': {'0': {'answers': 'My old answer', 'confidence': 'clear'}}}}
    client = _signed_in_client(monkeypatch, settings)
    html = client.get('/tracks/arena_3/sections/0').text
    assert 'My old answer' in html
    assert 'What is your Explore plan?' not in html
    result = client.post('/tracks/arena_3/sections/0/complete', data={'checkpoint_pass': 1}, follow_redirects=False)
    assert result.status_code == 409
    assert settings['active_track']['checkpoint_response_per_section']['0']['answers'] == 'My old answer'


def test_stale_tab_submission_is_saved_without_current_credit(monkeypatch):
    settings = {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': []}}
    client = _signed_in_client(monkeypatch, settings)
    result = client.post('/tracks/arena_3/sections/0/feedback', data={'answers': 'Answer from old tab', 'confidence': 'clear', 'check_version': 'old-version'}, follow_redirects=False)
    assert result.status_code == 303
    record = settings['active_track']['checkpoint_response_per_section']['0']
    assert record['answers'] == 'Answer from old tab'
    assert record['check_version'] == 'old-version'
    assert client.post('/tracks/arena_3/sections/0/complete', data={'checkpoint_pass': 1}, follow_redirects=False).status_code == 409


def test_request_track_uses_feedback_inbox_and_preserves_progress(monkeypatch):
    settings = {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': [0]}}
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m
    monkeypatch.setattr(m.tracks_service, 'is_available_track', lambda slug: slug == 'arena_3')
    request = Mock(return_value=123)
    monkeypatch.setattr(m.feedback_repo, 'request_track', request, raising=False)
    before = deepcopy(settings)
    result = client.post('/tracks/prework/request', follow_redirects=False)
    assert result.status_code == 303
    assert result.headers['location'] == '/feedback/inbox'
    assert request.call_args.args[1:] == ('prework', 'Prework')
    assert settings == before


def test_pending_track_drafts_cannot_be_published_or_discarded(monkeypatch):
    import app.main as m
    from app.services import content_drafts
    client = _signed_in_client(monkeypatch, {})
    monkeypatch.setattr(m.tracks_service, 'is_available_track', lambda slug: slug == 'arena_3')
    promote, discard = Mock(), Mock()
    monkeypatch.setattr(content_drafts, 'promote', promote)
    monkeypatch.setattr(content_drafts, 'discard', discard)
    for operation in ('promote', 'discard'):
        response = client.post('/tracks/prework/sections/0/drafts/reading/prework-s00-reading-draft/' + operation, follow_redirects=False)
        assert response.status_code == 409
    promote.assert_not_called()
    discard.assert_not_called()


def test_stale_tab_cannot_replace_a_current_answer(monkeypatch):
    from app.services.track_checks import questions_version
    from tests.unit.test_tracks_routes import _sample_tracks
    version = questions_version(_sample_tracks()['arena_3'], 0)
    current = {'answers': 'Current explanation', 'confidence': 'clear', 'check_version': version}
    settings = {'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': [], 'checkpoint_response_per_section': {'0': current}}}
    client = _signed_in_client(monkeypatch, settings)
    response = client.post('/tracks/arena_3/sections/0/feedback', data={'answers': 'Stale explanation', 'confidence': 'uncertain', 'check_version': 'old'}, follow_redirects=False)
    assert response.status_code == 303
    saved = settings['active_track']['checkpoint_response_per_section']['0']
    assert saved['answers'] == 'Current explanation'
    assert saved['check_version'] == version
    assert saved['previous_checks'][-1]['answers'] == 'Stale explanation'
    assert client.post('/tracks/arena_3/sections/0/complete', data={'checkpoint_pass': 1}, follow_redirects=False).status_code == 303
    assert settings['active_track']['checkpoint_passed_sections'] == [0]
