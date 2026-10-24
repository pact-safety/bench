from dataclasses import replace
from pathlib import Path

import pytest

from app.services import track_checks, tracks


@pytest.fixture
def catalog():
    return tracks.load_all_tracks(Path('content/tracks'))


def test_ml4good_checks_cover_every_section_with_authored_questions(catalog):
    track = catalog['ml4good-prework-fall-2026']
    assert track.total_sections == 18
    for idx, section in enumerate(track.all_sections):
        questions = track_checks.questions_for_section(track, idx)
        assert len(questions) >= 3
        assert questions == list(section.check_questions)
        assert all('?' in question for question in questions)
    assert len({tuple(track_checks.questions_for_section(track, idx)) for idx in range(18)}) == 18


def test_atlas_checks_address_each_chapters_subject(catalog):
    track = catalog['ml4good-prework-fall-2026']
    for idx, topic in [(5, 'scaling'), (6, 'misuse'), (7, 'strategy'), (8, 'governance')]:
        text = ' '.join(track_checks.questions_for_section(track, idx)).lower()
        assert topic in text
        assert 'your plan' not in text
        assert 'quality of your' not in text
        assert 'explore phase' not in text


def test_arena_rehearses_authored_checkpoint_without_claiming_completed_work(catalog):
    track = catalog['arena_3']
    for idx, section in enumerate(track.all_sections):
        questions = track_checks.questions_for_section(track, idx)
        assert section.checkpoint in questions[0]
        assert 'checkpoint rehearsal' in questions[0].lower()
        assert 'your implementation' not in ' '.join(questions).lower()
    assert track_checks.questions_for_section(track, 0) != track_checks.questions_for_section(track, 1)


def test_authored_questions_are_copied_and_deterministic(catalog):
    track = catalog['ml4good-prework-fall-2026']
    original = track_checks.questions_for_section(track, 5)
    track_checks.questions_for_section(track, 5).clear()
    assert track_checks.questions_for_section(track, 5) == original


def test_version_changes_when_authored_question_or_checkpoint_changes(catalog):
    track = catalog['ml4good-prework-fall-2026']
    version = track_checks.questions_version(track, 0)
    assert version.startswith(track_checks.CHECK_VERSION + ':')
    assert version == track_checks.questions_version(track, 0)
    section = track.all_sections[0]
    for changed in (
        replace(section, check_questions=('A revised question?',)),
        replace(section, checkpoint='A revised capability'),
    ):
        chapter = replace(track.chapters[0], sections=(changed,) + track.chapters[0].sections[1:])
        revised = replace(track, chapters=(chapter,) + track.chapters[1:])
        assert track_checks.questions_version(revised, 0) != version


@pytest.mark.parametrize('idx', [-1, 999])
def test_invalid_section_has_no_check(catalog, idx):
    track = catalog['ml4good-prework-fall-2026']
    assert track_checks.questions_for_section(track, idx) == []
    assert track_checks.questions_version(track, idx) == ''


def test_starting_guidance_prioritizes_orientation_reading_and_targeted_refreshers(catalog):
    body = catalog['ml4good-prework-fall-2026'].body_md
    assert 'Start with orientation and reading' in body
    assert 'Capabilities' in body
    assert 'targeted refresher' in body
    assert 'Open the introductory Colab notebook. Spend' not in body
