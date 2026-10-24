from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import secrets

import pytest

from app.services import track_exams, tracks


_USER_ID = '11111111-1111-1111-1111-111111111111'


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', secrets.token_hex(32))


def _eligible(track, records):
    from app.services.track_assessment_integrity import sign_record
    signed = [sign_record(r) if isinstance(r, dict) and r.get('user_id') else r
              for r in records] if isinstance(records, list) else records
    return track_exams.valid_exemptions(track, signed, user_id=_USER_ID)


@pytest.fixture
def catalog():
    return tracks.load_all_tracks(Path('content/tracks'))


def _review(spec, values=None):
    scores = {criterion['id']: 4 for criterion in spec['criteria']}
    scores.update(values or {})
    evidence = {key: 'Observed explanation and fresh application support this score.' for key in scores}
    return track_exams.evaluate_review(spec, scores, evidence, 'human-reviewer')


def _record(track, idx):
    spec = track_exams.spec_for_section(track, idx)
    return {
        'user_id': _USER_ID, 'id': '22222222-2222-4222-8222-222222222222',
        'track_slug': track.slug, 'section_idx': idx, 'spec_id': spec['id'],
        'spec_version': spec['version'], 'state': 'reviewed', 'modality': 'written',
        'assistance': 'none', 'responses': {'answers': 'Learner response', 'artifact_url': '', 'transcript_confirmed': False},
        'review': _review(spec),
        'practical_passed': {'verified_slugs': spec['practical_required'], 'checked_at': '2026-09-25T10:00:00Z'},
    }


def test_only_two_pilot_sections_have_specs(catalog):
    assert track_exams.spec_for_section(catalog['ml4good-prework-fall-2026'], 5)
    assert track_exams.spec_for_section(catalog['arena_3'], 0)
    for slug, idx in [('ml4good-prework-fall-2026', 0), ('arena_3', 1), ('arena_3', -1), ('arena_3', 999)]:
        assert track_exams.spec_for_section(catalog[slug], idx) is None


def test_specs_publish_explanation_application_and_complete_anchors(catalog):
    for slug, idx in [('ml4good-prework-fall-2026', 5), ('arena_3', 0)]:
        spec = track_exams.spec_for_section(catalog[slug], idx)
        assert spec['threshold'] == 80
        assert {q['kind'] for q in spec['questions']} == {'explanation', 'application'}
        assert len({q['id'] for q in spec['questions']}) == len(spec['questions'])
        assert len(spec['criteria']) == 4
        assert any(c['essential'] for c in spec['criteria'])
        assert all(set(c['anchors']) == set(range(5)) and all(c['anchors'].values()) for c in spec['criteria'])
        assert spec['practical_required'] == list(catalog[slug].all_sections[idx].cold_checkpoint)


def test_review_requires_eighty_percent_and_each_essential_at_least_three(catalog):
    spec = track_exams.spec_for_section(catalog['arena_3'], 0)
    ids = [c['id'] for c in spec['criteria']]
    assert _review(spec)['verdict'] == 'approved'
    assert _review(spec, dict.fromkeys(ids, 3))['verdict'] == 'not_approved'
    passing = dict.fromkeys(ids, 3)
    passing[ids[0]] = 4
    result = _review(spec, passing)
    assert result['percentage'] == 81.25
    assert result['verdict'] == 'approved'
    essential = next(c['id'] for c in spec['criteria'] if c['essential'])
    result = _review(spec, {essential: 2})
    assert result['percentage'] == 87.5
    assert result['verdict'] == 'not_approved'


@pytest.mark.parametrize('bad', [True, False, -1, 5, 3.0, '3', None])
def test_scores_require_exact_integers_in_range(catalog, bad):
    spec = track_exams.spec_for_section(catalog['arena_3'], 0)
    with pytest.raises(ValueError):
        _review(spec, {spec['criteria'][0]['id']: bad})


@pytest.mark.parametrize('field,mutation', [
    ('scores', lambda d: d.pop(next(iter(d)))),
    ('scores', lambda d: d.update(invented=4)),
    ('evidence', lambda d: d.pop(next(iter(d)))),
    ('evidence', lambda d: d.update(invented='extra')),
    ('evidence', lambda d: d.update({next(iter(d)): '  '})),
    ('evidence', lambda d: d.update({next(iter(d)): 42})),
])
def test_every_criterion_requires_exact_score_and_evidence(catalog, field, mutation):
    spec = track_exams.spec_for_section(catalog['arena_3'], 0)
    review = _review(spec)
    mutation(review[field])
    with pytest.raises(ValueError):
        track_exams.evaluate_review(spec, review['scores'], review['evidence'], 'reviewer')


@pytest.mark.parametrize('reviewer', ['', ' ', None, True])
def test_review_requires_human_reviewer_identity(catalog, reviewer):
    spec = track_exams.spec_for_section(catalog['arena_3'], 0)
    review = _review(spec)
    with pytest.raises(ValueError):
        track_exams.evaluate_review(spec, review['scores'], review['evidence'], reviewer)


def test_spec_version_changes_with_source_or_practical_requirements(catalog):
    track = catalog['arena_3']
    spec = track_exams.spec_for_section(track, 0)
    for section in [replace(track.all_sections[0], checkpoint='Revised target'),
                    replace(track.all_sections[0], cold_checkpoint=('new-practical',))]:
        chapter = replace(track.chapters[0], sections=(section,) + track.chapters[0].sections[1:])
        changed = replace(track, chapters=(chapter,) + track.chapters[1:])
        assert track_exams.spec_for_section(changed, 0)['version'] != spec['version']
    spec['criteria'][0]['anchors'][4] = 'Mutated'
    assert track_exams.spec_for_section(track, 0)['criteria'][0]['anchors'][4] != 'Mutated'


def test_exemptions_only_accept_current_valid_human_reviews(catalog):
    track = catalog['ml4good-prework-fall-2026']
    good = _record(track, 5)
    assert _eligible(track, [good]) == {5}
    for key, value in [('state', 'pending'), ('spec_version', 'old'), ('spec_id', 'wrong'),
                       ('track_slug', 'other'), ('section_idx', True), ('assistance', 'help')]:
        bad = deepcopy(good)
        bad[key] = value
        assert _eligible(track, [bad]) == set()
    for key, value in [('verdict', 'not_approved'), ('reviewer_id', ''), ('review_type', 'ai'),
                       ('scores', {}), ('evidence', {})]:
        bad = deepcopy(good)
        bad['review'][key] = value
        assert _eligible(track, [bad]) == set()
    forged = deepcopy(good)
    forged['review']['scores'] = dict.fromkeys(forged['review']['scores'], 0)
    assert _eligible(track, [forged]) == set()


def test_practical_pass_is_required_for_arena_but_not_atlas(catalog):
    for slug, idx, expected in [('arena_3', 0, set()), ('ml4good-prework-fall-2026', 5, {5})]:
        track = catalog[slug]
        record = _record(track, idx)
        record['practical_passed'] = {'verified_slugs': [], 'checked_at': '2026-09-25T10:00:00Z'}
        assert _eligible(track, [record]) == expected


@pytest.mark.parametrize('records', [None, {}, 'approved', [None, {}, {'section_idx': 5, 'review': True}]])
def test_malformed_records_fail_closed(catalog, records):
    assert _eligible(catalog['ml4good-prework-fall-2026'], records) == set()


@pytest.mark.parametrize('practical', [None, True, {}, {'verified_slugs': ['15-einsum-batched-matmul']}, {'verified_slugs': ['15-einsum-batched-matmul'], 'checked_at': 'not-a-time'}, {'verified_slugs': '15-einsum-batched-matmul', 'checked_at': '2026-09-25T10:00:00Z'}])
def test_practical_evidence_requires_verified_slugs_and_timestamp(catalog, practical):
    track = catalog['arena_3']
    record = _record(track, 0)
    record['practical_passed'] = practical
    assert _eligible(track, [record]) == set()


def test_oral_exemption_requires_learner_confirmed_transcript(catalog):
    track = catalog['ml4good-prework-fall-2026']
    record = _record(track, 5)
    record['modality'] = 'oral'
    assert _eligible(track, [record]) == set()
    record['responses']['transcript_confirmed'] = True
    assert _eligible(track, [record]) == {5}


@pytest.mark.parametrize('field,value', [('modality', []), ('section_idx', []), ('responses', []), ('review', []), ('assistance', 'notes')])
def test_malformed_or_assisted_record_fields_fail_closed(catalog, field, value):
    track = catalog['ml4good-prework-fall-2026']
    record = _record(track, 5)
    record[field] = value
    assert _eligible(track, [record]) == set()


@pytest.mark.parametrize('expected_owner', [None, '', ' ', False])
def test_exemptions_require_expected_owner_even_for_signed_approved_record(catalog, expected_owner):
    from app.services.track_assessment_integrity import sign_record
    track = catalog['ml4good-prework-fall-2026']
    signed = sign_record(_record(track, 5))
    assert track_exams.valid_exemptions(track, [signed], user_id=expected_owner) == set()


def test_exemptions_reject_unsigned_tampered_and_cross_owner_records(catalog):
    from app.services.track_assessment_integrity import sign_record
    track = catalog['ml4good-prework-fall-2026']
    unsigned = _record(track, 5)
    good = sign_record(unsigned)
    assert track_exams.valid_exemptions(track, [good], user_id=_USER_ID) == {5}
    assert track_exams.valid_exemptions(track, [unsigned], user_id=_USER_ID) == set()
    assert track_exams.valid_exemptions(track, [good], user_id='33333333-3333-4333-8333-333333333333') == set()
    changed = deepcopy(good)
    changed['responses']['answers'] = 'Substituted explanation'
    assert track_exams.valid_exemptions(track, [changed], user_id=_USER_ID) == set()
    moved = deepcopy(good)
    moved['user_id'] = '33333333-3333-4333-8333-333333333333'
    assert track_exams.valid_exemptions(track, [moved], user_id=moved['user_id']) == set()


def test_exemptions_fail_closed_without_signing_configuration(catalog, monkeypatch):
    from app.services.track_assessment_integrity import sign_record
    track = catalog['ml4good-prework-fall-2026']
    good = sign_record(_record(track, 5))
    monkeypatch.delenv('TRACK_ASSESSMENT_SIGNING_KEY')
    assert track_exams.valid_exemptions(track, [good], user_id=_USER_ID) == set()
