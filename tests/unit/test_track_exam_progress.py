"""Reviewed exemptions guide study without fabricating practice completions."""
from copy import deepcopy
from datetime import date
import secrets

import pytest

from app.services import daily_flow, track_exams, tracks
from app.services.track_content import item_slug
from tests.unit.test_track_exam_routes import pilot
from tests.unit.test_tracks_routes import _USER_UUID


def _approved(track):
    spec = track_exams.spec_for_section(track, 0)
    answer = 'Independent explanation, fresh application, and numerical validation.'
    scores = {c['id']: 4 for c in spec['criteria']}
    review = track_exams.evaluate_review(spec, scores, dict.fromkeys(scores, answer), 'human-reviewer')
    from app.services.track_assessment_integrity import sign_record
    return sign_record({
        'id': '22222222-2222-4222-8222-222222222222', 'user_id': _USER_UUID,
        'track_slug': track.slug, 'section_idx': 0, 'spec_id': spec['id'],
        'spec_version': spec['version'], 'state': 'reviewed', 'modality': 'written',
        'assistance': 'none', 'responses': {'answers': answer, 'artifact_url': '', 'transcript_confirmed': False},
        'submitted_at': '2026-09-25T10:00:00Z',
        'review': {**review, 'reviewed_at': '2026-09-25T11:00:00Z'},
        'practical_passed': {'verified_slugs': spec['practical_required'], 'checked_at': '2026-09-25T11:00:00Z'},
    })


@pytest.fixture
def progress(pilot, monkeypatch):
    client, main, settings, _ = pilot
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', secrets.token_hex(32))
    monkeypatch.setattr(tracks, 'AVAILABLE_TRACK_SLUGS', ('ml4good-prework-fall-2026', 'arena_3'))
    # Practical proof is already in the server-issued assessment record. Avoid
    # unrelated exercise/catalog DB reads while checking curriculum navigation.
    monkeypatch.setattr(main, '_track_gate_status', lambda *_: None)
    monkeypatch.setattr(main, '_track_prep_items', lambda *_: [])
    track = main.get_track('arena_3')
    settings['track_assessments'] = [_approved(track)]
    return client, main, settings, track


def _rows(response):
    return [row for chapter in response.context['chapter_rows'] for row in chapter['sections']]


def _next(settings, track):
    slugs = set(track.all_sections[0].cold_checkpoint)
    return daily_flow.compute_next(today=date(2026, 9, 25), user_settings=settings, user_id=_USER_UUID,
                                   passing_problem_slugs=slugs, available_problem_slugs=slugs)


def test_approved_exemption_advances_all_surfaces_without_practice_credit(progress):
    client, main, settings, track = progress
    before = deepcopy(settings)
    action = _next(settings, track)
    assert action.kind == 'track_section'
    assert action.title == track.all_sections[1].title
    assert action.url == f"/content/{item_slug(track.slug, track.all_sections[1].url)}"

    detail = client.get('/tracks/arena_3')
    assert detail.status_code == 200
    rows = _rows(detail)
    assert rows[0]['exemption'] and not rows[0]['is_completed']
    assert not rows[0]['is_future']
    assert rows[1]['is_current'] and rows[1]['is_unlocked']
    assert not rows[2]['is_unlocked']
    assert detail.context['completed_count'] == 0
    assert detail.context['exempt_count'] == 1
    first_section = detail.text.split('id="section-0"', 1)[1].split('id="section-1"', 1)[0]
    assert 'Tested out' in first_section
    assert 'Locked — complete the prerequisites first.' not in first_section

    index = client.get('/tracks')
    assert index.status_code == 200
    active = index.context['active_row']
    assert active['cursor'] == 1
    assert active['completed_count'] == 0 and active['exempt_count'] == 1
    assert 'href="/tracks/arena_3#section-1"' in index.text

    home = main._build_home_active_track_progress(settings=settings, user_id=_USER_UUID)
    assert home['next_section_number'] == 2
    assert home['passed_count'] == 0 and home['exempt_count'] == 1
    materials = main._active_track_materials(settings, user_id=_USER_UUID)
    assert materials['cards']['exercise']['idx'] == 1
    assert materials['completed_count'] == 0 and materials['exempt_count'] == 1
    assert settings == before


@pytest.mark.parametrize('ineligible', ['pending', 'stale', 'assisted', 'missing_practical'])
def test_ineligible_assessment_does_not_unlock_or_advance(progress, ineligible):
    client, main, settings, track = progress
    record = settings['track_assessments'][0]
    if ineligible == 'pending':
        record['state'] = 'pending'
        record.pop('review')
    elif ineligible == 'stale':
        record['spec_version'] = 'previous-rubric'
    elif ineligible == 'assisted':
        record['assistance'] = 'notes'
    else:
        record['practical_passed']['verified_slugs'] = []
    from app.services.track_assessment_integrity import sign_record
    settings['track_assessments'][0] = sign_record(record)
    before = deepcopy(settings)
    assert _next(settings, track).title == track.all_sections[0].title
    detail = client.get('/tracks/arena_3')
    assert detail.status_code == 200
    rows = _rows(detail)
    assert rows[0]['is_current'] and not rows[0]['exemption']
    assert not rows[1]['is_unlocked']
    assert detail.context['completed_count'] == detail.context['exempt_count'] == 0
    assert client.get('/tracks').context['active_row']['cursor'] == 0
    assert main._build_home_active_track_progress(settings=settings, user_id=_USER_UUID)['next_section_number'] == 1
    assert main._active_track_materials(settings, user_id=_USER_UUID)['cards']['exercise']['idx'] == 0
    assert settings == before


def test_focus_pause_switch_and_resume_preserve_exemption_and_practice_history(progress):
    client, main, settings, track = progress
    evidence = deepcopy(settings['track_assessments'])
    assert client.post('/tracks/arena_3/sections/1/focus', follow_redirects=False).status_code == 303
    assert settings['active_track']['preferred_section'] == 1
    assert settings['active_track']['cursor'] == 1
    assert settings['active_track']['checkpoint_passed_sections'] == []
    assert settings['active_track']['completed_sections'] == []
    assert settings['active_track']['checkpoint_passed_at_per_section'] == {}
    saved = deepcopy(settings['active_track'])

    assert client.post('/tracks/ml4good-prework-fall-2026/activate', follow_redirects=False).status_code == 303
    assert settings['paused_tracks']['arena_3'] == saved
    assert client.post('/tracks/clear-active', follow_redirects=False).status_code == 303
    assert client.post('/tracks/arena_3/activate', follow_redirects=False).status_code == 303
    assert settings['active_track'] == saved
    assert settings['track_assessments'] == evidence
    assert _next(settings, track).title == track.all_sections[1].title
    assert _rows(client.get('/tracks/arena_3'))[1]['is_current']
    assert main._build_home_active_track_progress(settings=settings, user_id=_USER_UUID)['passed_count'] == 0


@pytest.mark.parametrize('invalid', ['tampered', 'cross_owner'])
def test_bad_signature_or_owner_never_advances_study(progress, invalid):
    client, main, settings, track = progress
    record = settings['track_assessments'][0]
    if invalid == 'tampered':
        record['responses']['answers'] = 'Changed after review'
    else:
        from app.services.track_assessment_integrity import sign_record
        record['user_id'] = '33333333-3333-4333-8333-333333333333'
        settings['track_assessments'][0] = sign_record(record)
    assert _next(settings, track).title == track.all_sections[0].title
    rows = _rows(client.get('/tracks/arena_3'))
    assert rows[0]['is_current'] and not rows[1]['is_unlocked']
    assert main._build_home_active_track_progress(settings=settings, user_id=_USER_UUID)['exempt_count'] == 0
