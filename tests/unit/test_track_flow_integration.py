from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from app.services import tracks


def test_wrapper_passes_only_successes_and_shares_supplied_catalogue(monkeypatch):
    import app.main as m
    catalog = {
        1: SimpleNamespace(id=1, slug='failed'),
        2: SimpleNamespace(id=2, slug='passed'),
    }
    attempts = [SimpleNamespace(problem_id=1, test_passed=False, started_at=datetime.now()),
                SimpleNamespace(problem_id=2, test_passed=True, started_at=datetime.now())]
    capture = Mock(return_value=SimpleNamespace(kind='track_checkpoint'))
    monkeypatch.setattr(m.daily_flow_service, 'compute_next', capture)
    monkeypatch.setattr(m.problem_repo, 'all_core', Mock(side_effect=AssertionError('catalogue reloaded')))
    m._compute_next_action('learner', scored=[], daily_reading=None, daily_watch=None,
        daily_exercise=None, progress_by_id={}, attempts=attempts, active_writing=object(),
        last_reflection_at=datetime.now(), content_by_id={}, problems_by_id=catalog)
    kwargs = capture.call_args.kwargs
    assert kwargs['passing_problem_slugs'] == {'passed'}
    assert kwargs['available_problem_slugs'] == {'passed', 'failed'}
    assert kwargs['problems_by_id'] is catalog


def test_today_progress_uses_selected_unlocked_section(monkeypatch):
    import app.main as m
    track = tracks.Track(slug='parallel', title='Parallel', description='', source_url='', body_md='',
        chapters=(tracks.TrackChapter('Work', tuple(tracks.TrackSection(
            title=str(i), url='https://example.com', kind='external_reading', duration_min=30,
            domain_tags=(), axes=(), depends_on=()) for i in range(3))),))
    monkeypatch.setattr(m, 'get_track', lambda slug: track)
    monkeypatch.setattr(tracks, 'AVAILABLE_TRACK_SLUGS', ('parallel',))
    state = {'active_track': {'slug': 'parallel', 'checkpoint_passed_sections': [], 'preferred_section': 2}}
    progress = m._build_home_active_track_progress(settings=state)
    assert progress['passed_count'] == 0
    assert progress['next_section_number'] == 3
