"""Template-shape coverage for /aim stand layout + axis linkage (#142)."""

from __future__ import annotations

import re
from datetime import datetime
from unittest.mock import patch
from types import SimpleNamespace


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch, *, user_settings: dict | None = None):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    settings = dict(user_settings or {})
    monkeypatch.setattr(m, "_user_settings", lambda _uid: dict(settings))
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
        id=7,
        user_id=_USER_UUID,
        started_at=now,
        completed_at=now,
        final_scores={axis: 0.52 for axis in m.assess_service.AXES},
    )


def _credential_run(*, run_id: int, completed_at: datetime):
    from app.models import CredentialRun

    return CredentialRun(
        id=run_id,
        user_id=_USER_UUID,
        started_at=completed_at,
        completed_at=completed_at,
        status_text="uploaded",
    )


def _credential_assessment(*, run_id: int, scores: dict[str, float]):
    from app.models import CredentialAssessment

    return CredentialAssessment(
        id=run_id,
        run_id=run_id,
        inferred_axis_scores=scores,
        summary_md="",
        rationale={},
        method="keyword_fallback",
        model_used=None,
        created_at=datetime(2026, 5, 18, 9, 5, 0),
    )


def _render_aim_with_latest_assessment(
    monkeypatch,
    *,
    user_settings: dict | None = None,
    credential_runs=None,
    credential_assessments_by_run_id=None,
):
    client, m = _signed_in_client(monkeypatch, user_settings=user_settings)
    latest = _latest_assessment_run(m)
    credential_runs = credential_runs or []
    credential_assessments_by_run_id = credential_assessments_by_run_id or {}

    with patch.object(m.assessment_repo, "latest_completed", return_value=latest), \
         patch.object(m.assessment_repo, "responses_for_run", return_value=_saved_assessment_responses(m)), \
         patch.object(m, "_suggested_problem_for_scores", return_value=None), \
         patch.object(m.jd_repo, "list_for_user", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m.credentials_repo, "list_completed_for_user", return_value=credential_runs), \
         patch.object(m.credentials_repo, "first_files_by_run", return_value={}), \
         patch.object(
             m.credentials_repo,
             "latest_assessments_by_run",
             side_effect=lambda run_ids: {
                 rid: credential_assessments_by_run_id[rid]
                 for rid in run_ids
                 if rid in credential_assessments_by_run_id
             },
         ):
        return client.get("/aim", follow_redirects=False)


def test_aim_stand_section_renders_two_column_grid_with_axis_linkage_attrs(monkeypatch):
    r = _render_aim_with_latest_assessment(monkeypatch)

    assert r.status_code == 200
    assert 'class="aim-stand-grid page__section"' in r.text
    assert 'class="aim-stand-grid__chart"' in r.text
    assert 'class="aim-stand-grid__axes"' in r.text
    assert 'data-axis="transformer_internals" data-chart-axis="transformer"' in r.text
    assert 'data-axis="ai_governance_strategy" data-chart-axis="eval_data"' in r.text


def test_skill_chart_template_exposes_data_axis_targets_for_hover_highlighting(monkeypatch):
    r = _render_aim_with_latest_assessment(monkeypatch)

    assert r.status_code == 200

    for chart_axis in ("transformer", "training", "decoding", "eval_data", "systems"):
        assert re.search(
            rf'class="stat-pentagon__value-edge"\s+data-axis="{chart_axis}"',
            r.text,
        )
        assert re.search(
            rf'<circle class="stat-pentagon__dot[^\"]*"\s+data-axis="{chart_axis}"',
            r.text,
        )
        assert re.search(
            rf'<g class="stat-badge[^\"]*" data-axis="{chart_axis}"',
            r.text,
        )


def test_aim_stand_evidence_panel_renders_for_active_signal_with_latest_credential_axes(monkeypatch):
    run_new = _credential_run(run_id=17, completed_at=datetime(2026, 5, 18, 9, 0, 0))
    run_old = _credential_run(run_id=13, completed_at=datetime(2026, 5, 16, 9, 0, 0))

    r = _render_aim_with_latest_assessment(
        monkeypatch,
        user_settings={
            "imposter_signal": {
                "state": "mild",
                "triggering_axes": ["training_mechanics", "ai_governance_strategy"],
            }
        },
        credential_runs=[run_new, run_old],
        credential_assessments_by_run_id={
            17: _credential_assessment(
                run_id=17,
                scores={
                    "debugging": 0.93,
                    "data_pipeline": 0.82,
                    "eval_design": 0.74,
                    "algorithmic": 0.45,
                },
            ),
            13: _credential_assessment(
                run_id=13,
                scores={
                    "training_mechanics": 0.99,
                    "tokenization": 0.88,
                    "eval_design": 0.40,
                },
            ),
        },
    )

    assert r.status_code == 200
    assert "What your credentials say" in r.text
    assert 'href="/credentials/17"' in r.text

    panel_start = r.text.index("What your credentials say")
    panel_end = r.text.index("See the full credential analysis", panel_start)
    panel_html = r.text[panel_start:panel_end]

    # Top credential axes come from the latest run and stay score-desc.
    debug_idx = panel_html.index("Debugging real ML code")
    pipeline_idx = panel_html.index("Data pipelines")
    eval_idx = panel_html.index("Eval design")
    assert debug_idx < pipeline_idx < eval_idx

    # Triggering axes reflect the signal payload order.
    training_idx = panel_html.index("Training loop mechanics")
    gov_idx = panel_html.index("AGI strategy &amp; governance")
    assert training_idx < gov_idx

    assert "imposter syndrome" not in r.text.lower()


def test_aim_stand_evidence_panel_hidden_for_active_signal_without_credentials(monkeypatch):
    r = _render_aim_with_latest_assessment(
        monkeypatch,
        user_settings={
            "imposter_signal": {
                "state": "strong",
                "triggering_axes": ["debugging"],
            }
        },
        credential_runs=[],
    )

    assert r.status_code == 200
    assert "What your credentials say" not in r.text


def test_aim_stand_evidence_panel_hidden_when_signal_is_none(monkeypatch):
    run = _credential_run(run_id=21, completed_at=datetime(2026, 5, 18, 9, 0, 0))

    r = _render_aim_with_latest_assessment(
        monkeypatch,
        user_settings={
            "imposter_signal": {
                "state": "none",
                "triggering_axes": ["debugging"],
            }
        },
        credential_runs=[run],
        credential_assessments_by_run_id={
            21: _credential_assessment(
                run_id=21,
                scores={
                    "debugging": 0.91,
                    "eval_design": 0.83,
                    "data_pipeline": 0.72,
                },
            )
        },
    )

    assert r.status_code == 200
    assert "What your credentials say" not in r.text
