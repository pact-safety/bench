from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request


def request(path='/'):
    req = Request({'type': 'http', 'method': 'GET', 'path': path, 'headers': []})
    req.state.user_session = SimpleNamespace(user_id='owner-a')
    req.state.user_settings = {}
    return req


def test_snapshot_uses_owned_saved_evidence_and_preserves_measured_zero(monkeypatch):
    import app.main as m
    run = SimpleNamespace(id=7, final_scores={'transformer_internals': 0, 'debugging': .8,
        'ai_governance_strategy': 0}, completed_at=datetime(2026, 9, 25), started_at=None)
    responses = Mock(return_value=[SimpleNamespace(question_id='historic',
        axis_scores={'transformer_internals': 0, 'debugging': 2})])
    monkeypatch.setattr(m.assessment_repo, 'responses_for_run', responses)
    scores, coverage = m._assessment_snapshot('owner-a', run)
    assert scores == {'transformer_internals': 0, 'debugging': .8}
    assert 'ai_governance_strategy' in coverage['unknown_axes']
    assert coverage['assessed_at'] == run.completed_at
    responses.assert_called_once_with(7, user_id='owner-a')


def test_missing_assessment_does_not_query_responses(monkeypatch):
    import app.main as m
    responses = Mock()
    monkeypatch.setattr(m.assessment_repo, 'responses_for_run', responses)
    assert m._assessment_snapshot('owner-a', None) == ({}, None)
    responses.assert_not_called()


def test_recommendation_falls_through_exhausted_measured_axis(monkeypatch):
    import app.main as m
    problem = SimpleNamespace(id=99, slug='available')
    monkeypatch.setattr(m.assess_service, 'suggested_slugs_for_axis',
        lambda axis: {'debugging': ['exhausted'], 'transformer_internals': ['available']}.get(axis, []))
    monkeypatch.setattr(m.problem_repo, 'get_by_slug', lambda slug: problem if slug == 'available' else None)
    result = m._suggested_problem_for_scores('owner-a', {'debugging': .1, 'transformer_internals': .3}, attempts=[])
    assert result['problem'] == problem
    assert result['axis'] == 'transformer_internals'


@pytest.mark.parametrize(('kind', 'submitted', 'expected'), [
    ('received', '', 'inbound'), ('received', 'outbound', 'inbound'),
    ('sent', '', 'outbound'), ('sent', 'inbound', 'outbound'),
    ('meeting', '', None), ('call', 'inbound', 'inbound'), ('note', '', None),
])
def test_interaction_kind_supplies_unambiguous_direction(monkeypatch, kind, submitted, expected):
    import app.main as m
    monkeypatch.setattr(m.contacts_repo, 'get', Mock(return_value=object()))
    add = Mock()
    monkeypatch.setattr(m.contacts_repo, 'add_interaction', add)
    response = m.connecting_log_interaction(request(), 3, kind=kind, direction=submitted, occurred_at='', notes='')
    assert response.status_code == 303
    assert add.call_args.kwargs['direction'] == expected


@pytest.mark.parametrize('available', [True, False])
def test_legacy_writing_reading_resolves_owned_slug_without_mutating_saved_refs(monkeypatch, available):
    import app.main as m
    refs = [{'kind': 'reading', 'id': 42, 'title': 'Saved reading'}]
    writing = SimpleNamespace(user_id='owner-a', source_refs=refs)
    monkeypatch.setattr(m.writing_repo, 'get', Mock(return_value=writing))
    get_content = Mock(return_value=SimpleNamespace(slug='actual-reading') if available else None)
    monkeypatch.setattr(m.content_repo, 'get_by_id', get_content)
    monkeypatch.setattr(m.templates, 'TemplateResponse', lambda req, name, ctx: ctx)
    ctx = m.writings_show(request(), 1)
    assert ctx['source_refs'][0].get('slug') == ('actual-reading' if available else None)
    assert refs == [{'kind': 'reading', 'id': 42, 'title': 'Saved reading'}]
    get_content.assert_called_once_with(42, user_id='owner-a')


@pytest.mark.skip(reason="MIRA stubbed as coming soon")
def test_mira_first_note_context_failure_preserves_original_form_fields(monkeypatch):
    from tests.unit.test_mira_coach_launch import _coach
    from tests.unit.test_mira_coach_atomic_routes import field
    client, m, _ = _coach(monkeypatch)
    monkeypatch.setattr(m, '_mira_coach_context', Mock(side_effect=RuntimeError('catalogue unavailable')))
    response = client.post('/mira/coach', data={'message': 'Keep my plan', 'stage': 'frame',
        'problem': 'selected-problem', 'track': 'selected-track', 'section': '4'})
    assert response.status_code == 503
    assert field(response, 'problem') == 'selected-problem'
    assert field(response, 'track') == 'selected-track'
    assert field(response, 'section') == '4'
    assert 'Keep my plan' in response.text
    m.mira_repo.append_coach_note.assert_not_called()
