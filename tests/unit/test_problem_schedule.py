"""Problem returns measure spaced, unassisted retrieval, not repeated runs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import daily_flow, problem_schedule as ps

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def attempt(**changes):
    values = dict(problem_id=7, test_passed=True, solved_without_lookup=True,
                  looked_at_solution=False, looked_at_pitfalls=False, hints_used=None)
    return SimpleNamespace(**(values | changes))


def test_passes_follow_ladder_and_cap_without_mutating_input():
    state = {}
    when = NOW
    for days in (1, 7, 30, 30):
        before = deepcopy(state)
        updated = ps.apply_attempt(state, attempt(), now=when)
        assert state == before
        entry = updated['7']
        assert entry['interval_days'] == days
        assert entry['due_at'] == (when + timedelta(days=days)).isoformat()
        assert entry['last_passed'] == when.isoformat()
        assert entry['misses'] == 0
        state = updated
        when += timedelta(days=days)


@pytest.mark.parametrize('gap', [timedelta(minutes=1), timedelta(days=3)])
def test_not_due_repeat_does_not_advance_or_postpone(gap):
    state = ps.apply_attempt({}, attempt(), now=NOW)
    state = ps.apply_attempt(state, attempt(), now=NOW + timedelta(days=1))
    assert ps.apply_attempt(state, attempt(), now=NOW + timedelta(days=1) + gap) == state


def test_return_on_due_day_can_advance_before_original_clock_time():
    state = ps.apply_attempt({}, attempt(), now=NOW)
    due_morning = NOW + timedelta(days=1, hours=-4)
    updated = ps.apply_attempt(state, attempt(), now=due_morning)['7']
    assert updated['interval_days'] == 7
    assert updated['due_at'] == (due_morning + timedelta(days=7)).isoformat()


@pytest.mark.parametrize('assistance', [
    {'looked_at_solution': True}, {'looked_at_pitfalls': True},
    {'hints_used': {'plan': 1}}, {'solved_without_lookup': False},
    {'solved_without_lookup': None},
])
def test_assisted_green_returns_tomorrow_without_retention_credit(assistance):
    state = ps.apply_attempt({}, attempt(), now=NOW)
    when = NOW + timedelta(days=2)
    entry = ps.apply_attempt(state, attempt(**assistance), now=when)['7']
    assert entry['interval_days'] == 1
    assert entry['due_at'] == (when + timedelta(days=1)).isoformat()
    assert entry['misses'] == 0


def test_returned_red_resets_and_same_day_green_cannot_promote_it():
    state = ps.apply_attempt({}, attempt(), now=NOW)
    state = ps.apply_attempt(state, attempt(), now=NOW + timedelta(days=1))
    when = NOW + timedelta(days=10)
    reset = ps.apply_attempt(state, attempt(test_passed=False), now=when)
    assert reset['7']['interval_days'] == 1
    assert reset['7']['due_at'] == (when + timedelta(days=1)).isoformat()
    assert reset['7']['misses'] == 1
    assert reset['7']['last_passed'] == state['7']['last_passed']
    assert ps.apply_attempt(reset, attempt(), now=when + timedelta(minutes=1)) == reset
    assert ps.apply_attempt({}, attempt(test_passed=False), now=NOW) == {}


def test_due_ids_are_ordered_ignore_invalid_and_use_utc_days():
    state = {'1': {'due_at': '2026-09-24T23:59:00+00:00'},
             '2': {'due_at': '2026-09-23T23:00:00+00:00'},
             '3': {'due_at': '2026-09-25T00:00:00+00:00'},
             '4': {'due_at': 'bad'}, '5': None,
             '6': {'due_at': '2026-09-25T01:00:00+08:00'}}
    assert ps.due_problem_ids(state, NOW.date()) == ['2', '6', '1']


def problem(pid):
    return SimpleNamespace(id=pid, slug=f'p{pid}', title=f'Problem {pid}',
                           time_bucket=30, difficulty='medium', is_warmup=False)


def test_due_problem_outside_scored_pool_outranks_fresh_reading_and_attempts():
    state = ps.apply_attempt({}, attempt(), now=NOW - timedelta(days=2))
    action = daily_flow.compute_next(
        today=NOW.date(), user_settings={'problem_schedule': state},
        problems_by_id={7: problem(7)}, scored_problems=[SimpleNamespace(problem=problem(8))],
        daily_reading=SimpleNamespace(title='Fresh reading'),
        attempts_today_problem_ids={8},
    )
    assert action.kind == 'practice'
    assert action.url == '/problem/p7'
    assert 'due again' in action.why.lower()
    assert 'lost' not in str(action.asdict()).lower()


def test_future_and_removed_problems_do_not_surface():
    state = ps.apply_attempt({}, attempt(), now=NOW)
    for catalogue, when in (({7: problem(7)}, NOW), ({}, NOW + timedelta(days=2))):
        action = daily_flow.compute_next(today=when.date(), user_settings={'problem_schedule': state},
                                         problems_by_id=catalogue)
        assert action.kind != 'practice'


def test_existing_track_and_recitation_precedence(monkeypatch):
    state = ps.apply_attempt({}, attempt(), now=NOW - timedelta(days=2))
    recite = daily_flow.NextAction('recite', 'Recite', 'Paper', '/content/p', 'due')
    track = daily_flow.NextAction('track_section', 'Read', 'Section', '/track/t', 'next')
    monkeypatch.setattr(daily_flow, '_due_recitation_action', lambda *args: recite)
    kwargs = dict(today=NOW.date(), user_settings={'problem_schedule': state},
                  problems_by_id={7: problem(7)})
    assert daily_flow.compute_next(**kwargs) == recite
    monkeypatch.setattr(daily_flow, '_next_action_for_track', lambda *args, **kwargs: track)
    kwargs['user_settings']['active_track'] = {'slug': 'track'}
    assert daily_flow.compute_next(**kwargs) == track


@pytest.mark.parametrize('passed,assistance,expected_days', [
    (True, {}, 7), (False, {}, 1), (True, {'hints_used_json': '{"plan": 1}'}, 1),
    (True, {'looked_at_pitfalls': '1'}, 1), (True, {'looked_at_solution': '1'}, 1),
])
def test_submit_persists_schedule_and_preserves_other_settings(monkeypatch, passed, assistance, expected_days):
    from tests.unit.test_submit_user_tests import _signed_in_client, _problem
    from app.runners.python_runner import RunResult

    client, m = _signed_in_client(monkeypatch)
    p = _problem('toy-problem')
    p.is_warmup = False
    stored = {'theme': 'light', 'active_track': {'slug': 'arena'},
              'problem_schedule': ps.apply_attempt({}, attempt(), now=NOW - timedelta(days=2))}
    monkeypatch.setattr(m, '_user_settings', lambda uid: deepcopy(stored))
    writes = []
    monkeypatch.setattr(m, '_save_user_settings', lambda uid, settings: writes.append((uid, deepcopy(settings))))
    monkeypatch.setattr(m.problem_repo, 'get_by_slug', lambda slug: p)
    monkeypatch.setattr(m, 'run_python_tests', lambda *args, **kwargs: RunResult(passed, 'ok', 0))
    monkeypatch.setattr(m.attempt_repo, 'insert', lambda a: 42)
    monkeypatch.setattr(m.review_service, 'review_attempt', lambda *args, **kwargs: dict(
        method='fallback', model_used=None, summary_md='', per_phase={}, overall_score=None, error_text=None))
    monkeypatch.setattr(m.attempt_review_repo, 'insert', lambda review: 1)
    monkeypatch.setattr(m.review_repo, 'get', lambda *args: None)
    monkeypatch.setattr(m.review_repo, 'upsert', lambda state: None)

    class FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return NOW.replace(tzinfo=None)

    monkeypatch.setattr(m, 'datetime', FrozenDatetime)
    response = client.post('/submit/toy-problem', data={
        'code': 'pass', 'started_at_iso': '2026-09-20T23:00:00-05:00', **assistance})
    assert response.status_code == 200
    assert len(writes) == 1
    assert writes[0][0] == '11111111-1111-1111-1111-111111111111'
    saved = writes[0][1]
    assert saved['theme'] == 'light'
    assert saved['active_track'] == stored['active_track']
    assert saved['problem_schedule']['7']['interval_days'] == expected_days
    assert saved['problem_schedule']['7']['due_at'] == (NOW + timedelta(days=expected_days)).isoformat()
    assert stored['problem_schedule']['7']['interval_days'] == 1


def test_next_action_wrapper_loads_full_catalogue_for_returns(monkeypatch):
    import app.main as m
    class FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return NOW.replace(tzinfo=None)

    monkeypatch.setattr(m, 'datetime', FrozenDatetime)
    p = problem(7)
    state = ps.apply_attempt({}, attempt(), now=NOW - timedelta(days=2))
    monkeypatch.setattr(m.problem_repo, 'all_core', lambda: [p])
    monkeypatch.setattr(m.problem_repo, 'all_warmups', lambda: [])
    monkeypatch.setattr(m.reflection_repo, 'list_for_user', lambda *args, **kwargs: [])
    monkeypatch.setattr(m.writing_repo, 'active_draft_today', lambda *args: None)
    action = m._compute_next_action('u', scored=[], daily_reading=None, daily_watch=None,
        daily_exercise=None, progress_by_id={}, attempts=[], user_settings={'problem_schedule': state})
    assert action.url == '/problem/p7'


def test_assisted_practice_brings_return_forward_but_never_postpones_it():
    state = ps.apply_attempt({}, attempt(), now=NOW)
    state = ps.apply_attempt(state, attempt(), now=NOW + timedelta(days=1))
    assisted = attempt(hints_used={'plan': 1})
    earlier = ps.apply_attempt(state, assisted, now=NOW + timedelta(days=2))
    assert earlier['7']['due_at'] == (NOW + timedelta(days=3)).isoformat()
    repeated = ps.apply_attempt(earlier, assisted, now=NOW + timedelta(days=2, hours=4))
    assert repeated['7']['due_at'] == earlier['7']['due_at']


def test_assisted_return_on_due_morning_clears_today():
    state = ps.apply_attempt({}, attempt(), now=NOW)
    when = NOW + timedelta(days=1, hours=-4)
    updated = ps.apply_attempt(state, attempt(hints_used={'plan': 1}), now=when)
    assert updated['7']['due_at'] == (when + timedelta(days=1)).isoformat()
    assert ps.due_problem_ids(updated, when.date()) == []
