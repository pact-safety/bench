from datetime import datetime
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

from tests.unit.test_imposter_onboarding_flow import _signed_in_client, _USER_UUID


def assessment(monkeypatch, m, responses):
    run = N(id=7, user_id=_USER_UUID, started_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1), final_scores={
            "debugging": 0.0, "ai_safety_fundamentals": 0.0,
        })
    monkeypatch.setattr(m.assessment_repo, 'get_run', lambda *a, **k: run)
    monkeypatch.setattr(m.assessment_repo, 'latest_completed', lambda *a, **k: run)
    monkeypatch.setattr(m.assessment_repo, 'responses_for_run', lambda *a, **k: responses)
    return run


def test_finishing_assessment_cannot_infer_credential_gap_from_unknown_axes(monkeypatch):
    settings = {}
    client, m = _signed_in_client(monkeypatch, settings)
    assessment(monkeypatch, m, [])
    monkeypatch.setattr(m, '_latest_credential_scores', lambda uid: {
        'debugging': 1.0, 'ai_safety_fundamentals': 1.0,
    })
    response = client.get('/assess/7/complete', follow_redirects=False)
    assert response.headers['location'] == '/'
    assert settings['imposter_signal']['state'] == 'none'
    assert settings['imposter_signal']['credential_gap'] is None


def test_finishing_retains_measured_zero_and_independent_unsure_answers(monkeypatch):
    settings = {}
    client, m = _signed_in_client(monkeypatch, settings)
    assessment(monkeypatch, m, [N(question_id='q01-calibration', answer_index=3,
        axis_scores={'debugging': 0})])
    monkeypatch.setattr(m, '_latest_credential_scores', lambda uid: {
        'debugging': 0.0, 'ai_safety_fundamentals': 1.0,
    })
    response = client.get('/assess/7/complete', follow_redirects=False)
    assert response.headers['location'] == '/onboarding/imposter-intercept'
    assert settings['imposter_signal']['not_sure_rate'] == 1.0
    assert settings['imposter_signal']['credential_gap'] == 0.0
    assert settings['imposter_signal']['triggering_axes'] == []


def test_intercept_filters_historical_triggers_and_credential_fallback(monkeypatch):
    import app.main as m
    rows = m._imposter_axes_for_intercept(
        signal={'triggering_axes': ['ai_safety_fundamentals']},
        assessment_scores={'debugging': 0.0},
        credential_scores={'debugging': 0.5, 'ai_safety_fundamentals': 1.0},
    )
    assert [row['axis'] for row in rows] == ['debugging']
    assert rows[0]['self_pct'] == 0


def test_intercept_route_passes_only_measured_scores(monkeypatch):
    settings = {'imposter_signal': {'state': 'mild', 'credential_gap': 1.0, 'not_sure_rate': 0.5,
        'triggering_axes': ['ai_safety_fundamentals']}}
    client, m = _signed_in_client(monkeypatch, settings)
    assessment(monkeypatch, m, [N(question_id='old-question', axis_scores={'debugging': 0})])
    monkeypatch.setattr(m, '_latest_credential_scores', lambda uid: {'ai_safety_fundamentals': 1.0})
    build = Mock(return_value=[])
    monkeypatch.setattr(m, '_imposter_axes_for_intercept', build)
    response = client.get('/onboarding/imposter-intercept')
    assert response.status_code == 200
    assert build.call_args.kwargs['assessment_scores'] == {'debugging': 0.0}


def test_stale_gap_only_intercept_does_not_invent_unsure_answers(monkeypatch):
    settings = {'imposter_signal': {'state': 'mild', 'credential_gap': 1.0,
        'not_sure_rate': 0.0, 'triggering_axes': ['ai_safety_fundamentals']}}
    client, m = _signed_in_client(monkeypatch, settings)
    assessment(monkeypatch, m, [N(question_id='old-question', axis_scores={'debugging': 0})])
    monkeypatch.setattr(m, '_latest_credential_scores', lambda uid: {'ai_safety_fundamentals': 1.0})
    response = client.get('/onboarding/imposter-intercept', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/'


@pytest.mark.parametrize('current_gap,unsure_rate,expected', [
    (0.01, 0.0, 'redirect'),
    (0.25, 0.0, 'mild'),
    (0.25, 0.9, 'mild'),
    (0.0, 0.9, 'unsure'),
])
def test_intercept_severity_uses_current_measured_gap_not_historical_unknowns(
    monkeypatch, current_gap, unsure_rate, expected,
):
    settings = {'imposter_signal': {'state': 'strong', 'credential_gap': 0.9,
        'not_sure_rate': unsure_rate, 'triggering_axes': ['ai_safety_fundamentals']}}
    before = dict(settings['imposter_signal'])
    client, m = _signed_in_client(monkeypatch, settings)
    assessment(monkeypatch, m, [N(question_id='old-question', axis_scores={'debugging': 0})])
    monkeypatch.setattr(m, '_latest_credential_scores', lambda uid: {
        'debugging': current_gap, 'ai_safety_fundamentals': 1.0,
    })
    response = client.get('/onboarding/imposter-intercept', follow_redirects=False)
    if expected == 'redirect':
        assert response.status_code == 303
        assert response.headers['location'] == '/'
    else:
        assert response.status_code == 200
        assert 'much lower.' not in response.text
        if expected == 'mild':
            assert 'lower than what your credentials suggest.' in response.text
            assert response.context['has_credential_gap']
        else:
            assert 'You chose "not sure" often' in response.text
            assert not response.context['has_credential_gap']
    assert settings['imposter_signal'] == before


@pytest.mark.parametrize('measured', [True, False])
def test_credential_gap_omits_unknowns_and_does_not_claim_missing_data_aligns(monkeypatch, measured):
    client, m = _signed_in_client(monkeypatch, {})
    responses = [N(question_id='old-question', axis_scores={'debugging': 0})] if measured else []
    assessment(monkeypatch, m, responses)
    monkeypatch.setattr(m.credentials_repo, 'get_run', lambda rid: N(id=rid, user_id=_USER_UUID))
    monkeypatch.setattr(m.credentials_repo, 'latest_assessment', lambda rid: N(
        inferred_axis_scores={'debugging': 0.5, 'ai_safety_fundamentals': 1.0},
        summary_md='Saved analysis', method='keyword_fallback', model_used=None,
    ))
    monkeypatch.setattr(m.attempt_repo, 'all_for_user', lambda uid: [])
    monkeypatch.setattr(m.problem_repo, 'get_by_slug', lambda slug: None)
    response = client.get('/credentials/9/gap')
    assert response.status_code == 200
    assert response.context['user_scores'] == ({'debugging': 0.0} if measured else {})
    assert response.context['gap'] == ({'debugging': 0.5} if measured else {})
    assert 'Not assessed' in response.text
    assert 'aligned with what the credentials suggest' not in response.text
    assert 'No significant positive gaps detected' not in response.text
