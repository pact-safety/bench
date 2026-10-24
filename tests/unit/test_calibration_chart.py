"""Template + route coverage for calibration scatter on /aim."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from unittest.mock import patch
from types import SimpleNamespace


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {"display_tz": "UTC"})
    monkeypatch.setattr(
        m.auth_module if hasattr(m, "auth_module") else __import__("app.auth", fromlist=["auth"]),
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


def _saved_assessment_responses(m):
    responses = []
    while question := m.assess_service.pick_next([r.question_id for r in responses]):
        responses.append(SimpleNamespace(
            question_id=question.id, axis_scores=question.options[0].scores,
        ))
    return responses


def _latest_assessment_run(m):
    from app.models import AssessmentRun

    now = datetime(2026, 5, 18, 9, 0, 0)
    return AssessmentRun(
        id=77,
        user_id=_USER_UUID,
        started_at=now,
        completed_at=now,
        final_scores={axis: 0.55 for axis in m.assess_service.AXES},
    )


def _reflection(*, idx: int, predicted: int | None, actual: int | None, gap: str | None = None):
    from app.models import Reflection

    calibration_json = None
    if predicted is not None or actual is not None or gap is not None:
        calibration_json = {}
        if predicted is not None:
            calibration_json["predicted_pct"] = predicted
        if actual is not None:
            calibration_json["actual_pct"] = actual
        if gap is not None:
            calibration_json["gap_md"] = gap

    base = datetime(2026, 5, 10, 8, 0, 0)
    return Reflection(
        id=idx,
        user_id=_USER_UUID,
        period_start=base - timedelta(days=7),
        period_end=base,
        generated_at=base + timedelta(days=idx),
        prompts=[{"label": "Calibration", "prompt": "Predict vs actual."}],
        response_md=f"Reflection prose #{idx}",
        response_updated_at=None,
        summary_md=f"Summary #{idx}",
        method="keyword_fallback",
        model_used=None,
        calibration_json=calibration_json,
    )


def _render_aim(monkeypatch, *, reflections):
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.assessment_repo, "latest_completed", return_value=_latest_assessment_run(m)), \
         patch.object(m.assessment_repo, "responses_for_run", return_value=_saved_assessment_responses(m)), \
         patch.object(m, "_suggested_problem_for_scores", return_value=None), \
         patch.object(m.jd_repo, "list_for_user", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user", return_value=reflections), \
         patch.object(m.credentials_repo, "list_completed_for_user", return_value=[]):
        return client.get("/aim", follow_redirects=False)


def test_calibration_chart_section_hidden_without_valid_points(monkeypatch):
    """When no valid calibration points exist, the SVG chart itself is
    NOT rendered, but a Pattern-C empty-state explainer IS rendered
    (added in the zero-state polish round)."""
    r = _render_aim(
        monkeypatch,
        reflections=[
            _reflection(idx=1, predicted=None, actual=None),
            _reflection(idx=2, predicted=40, actual=None),
            _reflection(idx=3, predicted=140, actual=40),
        ],
    )

    assert r.status_code == 200
    # The chart SVG is hidden
    assert "aim-calibration-chart__point" not in r.text
    assert 'class="aim-calibration-chart"' not in r.text
    # But the empty-state explainer IS rendered
    assert 'class="page__section aim-calibration aim-calibration--empty"' in r.text
    assert "No calibration data yet" in r.text


def test_calibration_chart_empty_state_links_to_reflect(monkeypatch):
    """The empty-state copy directs the operator to /reflect — that's
    where the calibration data originates."""
    r = _render_aim(monkeypatch, reflections=[])

    assert r.status_code == 200
    assert "No calibration data yet" in r.text
    assert 'href="/reflect"' in r.text


def test_aim_jds_empty_state_explains_what_jds_do(monkeypatch):
    """When no JDs exist yet, render the explainer block describing
    what the bench does with a parsed JD."""
    r = _render_aim(monkeypatch, reflections=[])

    assert r.status_code == 200
    assert "No JDs added yet" in r.text
    assert "axis weights" in r.text
    assert "iterator/amplifier/connector profile fit" in r.text


def test_aim_credentials_empty_state_explains_imposter_signal_use(monkeypatch):
    """When no credentials uploaded, render the explainer block tying
    the upload action to the imposter-signal detection downstream."""
    r = _render_aim(monkeypatch, reflections=[])

    assert r.status_code == 200
    assert "No credentials uploaded yet" in r.text
    assert "axis evidence" in r.text
    assert "imposter-signal detector" in r.text


def test_calibration_chart_renders_single_point_when_one_valid_payload_exists(monkeypatch):
    r = _render_aim(
        monkeypatch,
        reflections=[_reflection(idx=1, predicted=55, actual=63, gap="Slightly underestimated")],
    )

    assert r.status_code == 200
    assert "Calibration over time" in r.text
    assert "Each reflection asks one calibration check (predicted vs actual). Over time the gap should narrow. This is the chart." in r.text
    assert "Closer to the diagonal = better-calibrated forecasts." in r.text
    assert len(re.findall(r'class="aim-calibration-chart__point"', r.text)) == 1


def test_calibration_chart_renders_multiple_points_for_trend_case(monkeypatch):
    reflections = [
        _reflection(idx=1, predicted=80, actual=40),
        _reflection(idx=2, predicted=75, actual=55),
        _reflection(idx=3, predicted=70, actual=62),
        _reflection(idx=4, predicted=65, actual=63),
        _reflection(idx=5, predicted=60, actual=61),
        _reflection(idx=6, predicted=58, actual=60),
    ]

    r = _render_aim(monkeypatch, reflections=reflections)

    assert r.status_code == 200
    assert len(re.findall(r'class="aim-calibration-chart__point"', r.text)) == 6

    opacities = re.findall(
        r'class="aim-calibration-chart__point"[^>]*opacity="([0-9.]+)"',
        r.text,
    )
    assert len(set(opacities)) >= 2


def test_calibration_chart_uses_expected_svg_coordinates_for_known_input(monkeypatch):
    r = _render_aim(
        monkeypatch,
        reflections=[_reflection(idx=1, predicted=25, actual=75)],
    )

    assert r.status_code == 200
    assert re.search(
        r'class="aim-calibration-chart__point"[^>]*data-predicted="25"[^>]*data-actual="75"[^>]*data-x="108(?:\.0+)?"[^>]*data-y="88(?:\.0+)?"',
        r.text,
    )
