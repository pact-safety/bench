"""Curriculum discovery should make the first practice block concrete."""

from copy import deepcopy

from tests.unit.test_tracks_routes import _signed_in_client


def test_onboarding_offers_curriculum_without_replacing_other_choices(monkeypatch):
    client = _signed_in_client(monkeypatch, {})
    response = client.get('/onboarding')

    assert response.status_code == 200
    assert 'Choose a curriculum' in response.text
    for action in ('/onboarding/start', '/onboarding/skip', '/onboarding/tracks'):
        assert f'action="{action}"' in response.text


def test_choose_curriculum_preserves_profile_and_track_progress(monkeypatch):
    settings = {
        'daily_mode': 'remix',
        'assessment_profile': {'algorithmic': 0.8},
        'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': [0]},
        'paused_tracks': {'prework': {'cursor': 1, 'completed_sections': [0]}},
    }
    before = deepcopy(settings)
    client = _signed_in_client(monkeypatch, settings)

    response = client.post('/onboarding/tracks', follow_redirects=False)

    assert response.status_code == 303
    assert response.headers['location'] == '/tracks'
    assert settings.pop('onboarding_skipped') is True
    assert settings == before


def test_tracks_offer_short_start_and_put_full_duration_on_detail(monkeypatch):
    client = _signed_in_client(monkeypatch, {})
    response = client.get('/tracks')

    assert response.status_code == 200
    assert 'Alignment curriculum' in response.text
    assert 'Warmup track' in response.text
    assert '0.1 Prerequisites' in response.text
    assert 'Read primer' in response.text
    assert 'Start with a 30-minute block' in response.text
    assert 'full estimate appears inside' in response.text
    assert 'Read notes and start' in response.text
    detail = client.get('/tracks/arena_3')
    assert '45 min' in detail.text
    assert 'start with ARENA 3.0' not in response.text
    assert 'architecture/tracks/' not in response.text
    assert 'content corpus' not in response.text


def test_discovery_preserves_active_and_resume_controls(monkeypatch):
    settings = {
        'active_track': {'slug': 'arena_3', 'checkpoint_passed_sections': [0]},
        'paused_tracks': {'prework': {'cursor': 0, 'checkpoint_passed_sections': []}},
    }
    before = deepcopy(settings)
    client = _signed_in_client(monkeypatch, settings)
    response = client.get('/tracks')

    assert response.status_code == 200
    assert 'href="/tracks/arena_3#section-1"' in response.text
    assert 'href="/tracks/prework"' in response.text
    assert 'Review and resume' in response.text
    assert 'action="/tracks/prework/activate"' not in response.text
    assert '1/2 core practice checks completed' in response.text
    assert settings == before
