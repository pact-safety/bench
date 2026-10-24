from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import Request
from app.auth import UserSession
from app.models import (
    AssessmentResponse,
    AssessmentRun,
    CredentialAssessment,
    CredentialRun,
)


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch, settings: dict):
    """Create an authenticated TestClient with in-memory settings."""
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.auth as auth_module
    import app.main as m
    from fastapi.testclient import TestClient

    def _save(_uid: str, next_settings: dict) -> None:
        payload = dict(next_settings)
        settings.clear()
        settings.update(payload)

    monkeypatch.setattr(m, "_user_settings", lambda _uid: settings)
    monkeypatch.setattr(m, "_save_user_settings", _save)
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="test@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def test_assess_complete_redirects_to_intercept_when_detector_fires(monkeypatch):
    settings: dict = {}
    client, m = _signed_in_client(monkeypatch, settings)

    run = AssessmentRun(
        id=17,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 18, 10, 0, 0),
        completed_at=datetime(2026, 5, 18, 10, 3, 0),
        final_scores={"debugging": 0.2, "eval_design": 0.3},
    )
    responses = [
        AssessmentResponse(
            id=1,
            run_id=17,
            question_id="q01-calibration",
            answer_index=3,
            axis_scores={"debugging": 0},
            answered_at=datetime(2026, 5, 18, 10, 0, 30),
        ),
        AssessmentResponse(
            id=2,
            run_id=17,
            question_id="q02-attention-shape",
            answer_index=0,
            axis_scores={"eval_design": 1},
            answered_at=datetime(2026, 5, 18, 10, 1, 0),
        ),
    ]
    captured_detect_inputs: dict = {}

    def _fake_detect(**kwargs):
        captured_detect_inputs.update(kwargs)
        return m.imposter_service.ImposterSignal(
            state="mild",
            not_sure_rate=0.5,
            credential_gap=None,
            triggering_axes=["debugging"],
            detected_at=kwargs.get("now"),
        )

    monkeypatch.setattr(m.assessment_repo, "get_run", lambda _run_id, *, user_id: run)
    monkeypatch.setattr(m.assessment_repo, "responses_for_run", lambda _run_id, *, user_id: responses)
    monkeypatch.setattr(m.credentials_repo, "latest_completed", lambda _uid: None)
    monkeypatch.setattr(m.imposter_service, "detect", _fake_detect)

    r = client.get("/assess/17/complete", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers.get("location") == "/onboarding/imposter-intercept"
    assert settings["imposter_signal"]["state"] == "mild"
    assert captured_detect_inputs["quiz_answers"] == ["not_sure", "yes"]
    assert captured_detect_inputs["assessment_scores"] == {"debugging": 0.2, "eval_design": 0.3}
    assert captured_detect_inputs["credential_scores"] is None
    assert isinstance(captured_detect_inputs["now"], datetime)


def test_assess_complete_redirects_home_when_detector_state_none(monkeypatch):
    settings: dict = {}
    client, m = _signed_in_client(monkeypatch, settings)

    run = AssessmentRun(
        id=18,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 18, 10, 0, 0),
        completed_at=datetime(2026, 5, 18, 10, 4, 0),
        final_scores={"debugging": 0.5},
    )

    monkeypatch.setattr(m.assessment_repo, "get_run", lambda _run_id, *, user_id: run)
    monkeypatch.setattr(m.assessment_repo, "responses_for_run", lambda _run_id, *, user_id: [])
    monkeypatch.setattr(m.credentials_repo, "latest_completed", lambda _uid: None)
    monkeypatch.setattr(
        m.imposter_service,
        "detect",
        lambda **kwargs: m.imposter_service.ImposterSignal(
            state="none",
            not_sure_rate=0.0,
            credential_gap=None,
            triggering_axes=[],
            detected_at=None,
        ),
    )

    r = client.get("/assess/18/complete", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    assert settings["imposter_signal"]["state"] == "none"


def test_intercept_template_shows_triggering_axes_and_avoids_banned_phrase(monkeypatch):
    settings = {
        "imposter_signal": {
            "state": "mild",
            "not_sure_rate": 0.5,
            "credential_gap": 0.22,
            "triggering_axes": ["debugging", "eval_design", "algorithmic"],
            "detected_at": "2026-05-18T10:05:00",
        }
    }
    client, m = _signed_in_client(monkeypatch, settings)
    monkeypatch.setattr(m.assessment_repo, "responses_for_run", lambda *a, **k: [
        SimpleNamespace(question_id="historical-question", axis_scores={
            "debugging": 1, "eval_design": 1, "algorithmic": 1,
        }),
    ])

    monkeypatch.setattr(
        m.assessment_repo,
        "latest_completed",
        lambda _uid: AssessmentRun(
            id=19,
            user_id=_USER_UUID,
            started_at=datetime(2026, 5, 18, 10, 0, 0),
            completed_at=datetime(2026, 5, 18, 10, 5, 0),
            final_scores={
                "debugging": 0.35,
                "eval_design": 0.30,
                "algorithmic": 0.25,
            },
        ),
    )
    monkeypatch.setattr(
        m.credentials_repo,
        "latest_completed",
        lambda _uid: CredentialRun(
            id=77,
            user_id=_USER_UUID,
            started_at=datetime(2026, 5, 18, 9, 50, 0),
            completed_at=datetime(2026, 5, 18, 9, 59, 0),
            status_text="ok",
        ),
    )
    monkeypatch.setattr(
        m.credentials_repo,
        "latest_assessment",
        lambda _run_id: CredentialAssessment(
            id=55,
            run_id=77,
            inferred_axis_scores={
                "debugging": 0.64,
                "eval_design": 0.53,
                "algorithmic": 0.51,
            },
            summary_md=None,
            rationale={},
            method="keyword_fallback",
            model_used=None,
            created_at=datetime(2026, 5, 18, 9, 59, 30),
        ),
    )

    r = client.get("/onboarding/imposter-intercept", follow_redirects=False)

    assert r.status_code == 200
    assert "Debugging real ML code" in r.text
    assert "Eval design" in r.text
    assert "Algorithmic patterns" in r.text
    assert "lower than what your credentials suggest." in r.text
    assert "Continue to Today" in r.text
    assert "imposter syndrome" not in r.text.lower()


def test_home_calls_maybe_decay_and_persists_when_state_changes(monkeypatch):
    import app.main as m

    settings = {
        "onboarding_skipped": True,
        "imposter_signal": {"state": "mild"},
    }
    attempts: list = []
    saved_settings: list[tuple[str, dict]] = []
    maybe_decay_calls: dict[str, object] = {}

    # Rest-days landed after this test was authored. home() now early-returns
    # to the rest-day render path on Sat/Sun before reaching the imposter
    # decay check. Pin to a weekday so the test exercises its actual subject.
    monkeypatch.setattr(m, "_is_weekend_for_user", lambda *_a, **_k: False)
    monkeypatch.setattr(m.assessment_repo, "latest_completed", lambda _uid: None)
    monkeypatch.setattr(m.attempt_repo, "all_for_user", lambda _uid: attempts)
    monkeypatch.setattr(m.content_repo, "progress_for_user", lambda _uid: {})
    monkeypatch.setattr(m, "_active_jd", lambda _uid, settings=None: None)
    monkeypatch.setattr(m.writing_repo, "active_draft_today", lambda _uid: None)
    monkeypatch.setattr(
        m.content_repo,
        "all_by_kinds",
        lambda kinds, user_id=None: {kind: [] for kind in kinds},
    )
    monkeypatch.setattr(m, "_build_session", lambda uid, **kwargs: [])
    monkeypatch.setattr(m.content_repo, "axis_ratings_for_user", lambda _uid: {})
    monkeypatch.setattr(m, "_compute_next_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(m.problem_repo, "list_recent_for_user", lambda _uid, limit=5: [])
    monkeypatch.setattr(
        m,
        "_save_user_settings",
        lambda uid, payload: saved_settings.append((uid, dict(payload))),
    )

    def _fake_maybe_decay(passed_settings, passed_attempts):
        maybe_decay_calls["settings"] = passed_settings
        maybe_decay_calls["attempts"] = passed_attempts
        return True

    monkeypatch.setattr(m.imposter_service, "maybe_decay", _fake_maybe_decay)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )
    request.state.user_session = SimpleNamespace(user_id=_USER_UUID)
    request.state.user_settings = settings

    response = m.home(request)

    assert response.status_code == 200
    assert maybe_decay_calls["settings"] is settings
    assert maybe_decay_calls["attempts"] == attempts
    assert len(saved_settings) == 1
    assert saved_settings[0][0] == _USER_UUID
