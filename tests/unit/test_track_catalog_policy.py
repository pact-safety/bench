from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.services import daily_flow, tracks


@pytest.fixture
def catalog(monkeypatch):
    catalog = tracks.load_all_tracks(Path(__file__).resolve().parents[2] / 'content/tracks')
    monkeypatch.setattr(tracks, '_tracks_by_slug', catalog)
    return catalog


def test_only_audited_tracks_are_available_without_deleting_catalog(catalog):
    assert [track.slug for track in tracks.available_tracks()] == [
        'ml4good-prework-fall-2026', 'arena_3',
    ]
    for slug in ('mats', 'mechinterp', 'structy', 'future-track'):
        assert not tracks.is_available_track(slug)
        assert tracks.get_available_track(slug) is None
    assert tracks.get_track('mats') is catalog['mats']
    assert tracks.get_available_track('arena_3') is catalog['arena_3']


def test_pending_track_is_not_a_today_recommendation_and_progress_is_preserved(catalog):
    catalog['mats'] = replace(catalog['ml4good-prework-fall-2026'], slug='mats')
    state = {'active_track': {'slug': 'mats', 'checkpoint_passed_sections': [0]}}
    action = daily_flow.compute_next(today=date(2026, 10, 1), user_settings=state)
    assert action.kind not in {'track_section', 'track_checkpoint'}
    assert state == {'active_track': {'slug': 'mats', 'checkpoint_passed_sections': [0]}}


def test_ml4good_recommended_start_does_not_renumber_or_override_dependencies(catalog):
    track = catalog['ml4good-prework-fall-2026']
    before = track.all_sections
    assert track.total_sections == 18
    assert 'Capabilities' in before[5].title
    assert tracks.next_section_index(track, set()) == 5
    assert tracks.next_section_index(track, {5}) == 6
    assert tracks.next_section_index(track, {5, 6, 7, 8, 9}) == 10
    assert tracks.next_section_index(track, {5, 6, 7, 8, 9, 10}) == 0
    assert tracks.next_section_index(track, set(), 0) == 0
    assert tracks.next_section_index(track, set(), 2) == 5
    assert tracks.dependencies_for(track, 2) == (1,)
    assert track.all_sections == before
    assert set(tracks.recommended_section_indices(track)) == set(range(18))


def test_recommended_start_still_respects_new_dependencies(catalog):
    track = catalog['ml4good-prework-fall-2026']
    chapters = tuple(replace(chapter, sections=tuple(
        replace(section, depends_on=(0,)) if section is track.all_sections[5] else section
        for section in chapter.sections
    )) for chapter in track.chapters)
    changed = replace(track, chapters=chapters)
    assert tracks.next_section_index(changed, set()) != 5


def test_named_missing_prerequisites_match_unlock_policy(catalog):
    track = catalog['ml4good-prework-fall-2026']
    assert tracks.missing_prerequisites(track, 2, set()) == ((1, track.all_sections[1].title),)
    assert tracks.missing_prerequisites(track, 2, {1}) == ()
    assert tracks.is_unlocked(track, 2, {1})


def authored_track(tmp_path, sections):
    raw = {'slug': 'custom', 'title': 'Custom', 'chapters': [{'title': 'Chapter',
        'sections': [dict(title=f'Section {index}', **section) for index, section in enumerate(sections)]}]}
    (tmp_path / 'custom.md').write_text('---\n' + yaml.safe_dump(raw) + '---\n')
    return tracks.load_all_tracks(tmp_path)['custom']


@pytest.mark.parametrize('sections,match', [
    ([{'depends_on': [1]}, {'depends_on': [0]}], 'cycle'),
    ([{'depends_on': [1]}, {}], 'cycle'),
    ([{'depends_on': [2]}], 'missing section'),
    ([{'depends_on': [True]}], 'integer'),
    ([{'depends_on': [0.5]}], 'integer'),
])
def test_invalid_dependency_graphs_are_rejected(tmp_path, sections, match):
    with pytest.raises(ValueError, match=match):
        authored_track(tmp_path, sections)


def test_authored_check_questions_preserve_exact_text_and_order(tmp_path):
    track = authored_track(tmp_path, [{'check_questions': [' Explain this. ', 'Give an example.']}, {}])
    assert track.all_sections[0].check_questions == ('Explain this.', 'Give an example.')
    assert track.all_sections[1].check_questions == ()


@pytest.mark.parametrize('questions', ['one question', [1], [False]])
def test_authored_check_questions_validate_shape(tmp_path, questions):
    with pytest.raises(ValueError, match='check_questions'):
        authored_track(tmp_path, [{'check_questions': questions}])
