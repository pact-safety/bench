"""Daily mode (path / remix): recommendation, scheduler behavior,
settings persistence, and the adopt-if-unset rule on assessment results.
"""

from __future__ import annotations

import random
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import assessment as assess_service
from app.services.assessment import AXES, recommended_daily_mode


_USER_UUID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Recommendation thresholds
# ---------------------------------------------------------------------------


def test_empty_scores_recommend_path():
    assert recommended_daily_mode({}) == "path"


def test_weak_scores_recommend_path():
    assert recommended_daily_mode({a: 1 / 3 for a in AXES}) == "path"


def test_strong_scores_recommend_remix():
    assert recommended_daily_mode({a: 2.5 / 3 for a in AXES}) == "remix"


def test_threshold_is_mean_over_all_axes():
    """One strong axis can't flip the recommendation — the mean over
    every axis has to clear 2/3."""
    scores = {a: 0.0 for a in AXES}
    scores[AXES[0]] = 1.0
    assert recommended_daily_mode(scores) == "path"


@pytest.mark.parametrize(
    ("score", "expected"),
    [(2 / 3 - 0.001, "path"), (2 / 3, "remix"), (1.0, "remix")],
)
def test_normalized_recommendation_boundary(score, expected):
    assert recommended_daily_mode({a: score for a in AXES}) == expected


def _strong_assessment_responses():
    responses = []
    while question := assess_service.pick_next([r.question_id for r in responses]):
        option = max(question.options, key=lambda option: sum(option.scores.values()))
        responses.append(SimpleNamespace(
            question_id=question.id, axis_scores=option.scores,
        ))
    return responses


def _strong_assessment_scores():
    return assess_service.aggregate_scores(_strong_assessment_responses())


def test_strong_completed_assessment_recommends_remix():
    # Use the quiz's real normalized output, including unassessed axes.
    assert recommended_daily_mode(_strong_assessment_scores()) == "remix"


# ---------------------------------------------------------------------------
# Scheduler: remix shuffles order, keeps membership + constraints
# ---------------------------------------------------------------------------


def _problems(n: int):
    from app.models import Problem

    return [
        Problem(
            id=i + 1, slug=f"p{i+1}", title=f"P{i+1}", difficulty="easy",
            time_bucket=10, problem_type="code_compose", is_warmup=False,
            domain_tags=[], structural_tags=["algo"], competency_tags=[],
            jd_signal_tags=[], content_md="", version=1, em_mode="full",
            em_prompts={}, references=[],
        )
        for i in range(n)
    ]


def _build(remix_rng=None):
    from app.config import load_config
    from app.services.scheduler import ReviewStrategy

    cfg = load_config()
    strategy = ReviewStrategy(cfg.scheduler, now=datetime(2026, 7, 20, 12, 0, 0))
    return strategy.build(
        _problems(12), {}, {}, size=5, remix_rng=remix_rng
    )


def test_path_mode_is_deterministic():
    a = [s.problem.id for s in _build()]
    b = [s.problem.id for s in _build()]
    assert a == b


def test_remix_shuffles_but_membership_is_sane():
    baseline = [s.problem.id for s in _build()]
    remixed = [s.problem.id for s in _build(remix_rng=random.Random(42))]
    assert len(remixed) == len(baseline)
    assert len(set(remixed)) == len(remixed)  # no duplicates
    # With 12 identical-scored problems and a fixed seed, the shuffled
    # order must differ from the deterministic one.
    assert remixed != baseline


def test_remix_is_reproducible_per_seed():
    a = [s.problem.id for s in _build(remix_rng=random.Random(7))]
    b = [s.problem.id for s in _build(remix_rng=random.Random(7))]
    assert a == b


# ---------------------------------------------------------------------------
# Settings persistence (mirrors the theme handler contract)
# ---------------------------------------------------------------------------


def _signed_in_client(monkeypatch, *, settings: dict | None = None):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    store = dict(settings or {})
    monkeypatch.setattr(m, "_user_settings", lambda _uid: dict(store))
    saved: dict = {}

    def _save(_uid, s):
        saved.clear()
        saved.update(s)

    monkeypatch.setattr(m, "_save_user_settings", _save)
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="op@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m, saved


def test_saving_remix_persists(monkeypatch):
    client, _m, saved = _signed_in_client(monkeypatch)
    r = client.post(
        "/settings/daily-mode", data={"daily_mode": "remix"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert saved.get("daily_mode") == "remix"


def test_saving_empty_clears_to_path_default(monkeypatch):
    client, _m, saved = _signed_in_client(monkeypatch, settings={"daily_mode": "remix"})
    r = client.post(
        "/settings/daily-mode", data={"daily_mode": ""}, follow_redirects=False
    )
    assert r.status_code == 303
    assert "daily_mode" not in saved


def test_unknown_mode_rejected(monkeypatch):
    client, _m, saved = _signed_in_client(monkeypatch)
    r = client.post(
        "/settings/daily-mode", data={"daily_mode": "chaos"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert "daily_mode" not in saved


# ---------------------------------------------------------------------------
# Assessment result: adopt-if-unset, never override an explicit choice
# ---------------------------------------------------------------------------


def _completed_run(scores: dict):
    run = MagicMock()
    run.id = 1
    run.user_id = _USER_UUID
    run.completed_at = datetime(2026, 7, 20, 10, 0, 0)
    run.final_scores = scores
    return run


def test_strong_result_adopts_remix_when_unset(monkeypatch):
    client, m, saved = _signed_in_client(monkeypatch, settings={})
    run = _completed_run(_strong_assessment_scores())
    with patch.object(m.assessment_repo, "get_run", return_value=run), \
         patch.object(m.assessment_repo, "responses_for_run", return_value=_strong_assessment_responses()), \
         patch.object(m, "_suggested_problem_for_scores", return_value=None):
        r = client.get("/assess/1/result")
    assert r.status_code == 200
    assert saved.get("daily_mode") == "remix"
    assert "Remix" in r.text


def test_result_never_overrides_explicit_choice(monkeypatch):
    """A retake with weak scores must not strip an explicit remix choice
    (and vice versa) — the recommendation only fills the void."""
    client, m, saved = _signed_in_client(
        monkeypatch, settings={"daily_mode": "remix"}
    )
    run = _completed_run({a: 0.5 for a in AXES})
    with patch.object(m.assessment_repo, "get_run", return_value=run), \
         patch.object(m.assessment_repo, "responses_for_run", return_value=_strong_assessment_responses()), \
         patch.object(m, "_suggested_problem_for_scores", return_value=None):
        r = client.get("/assess/1/result")
    assert r.status_code == 200
    assert saved == {}  # nothing written


def test_weak_result_recommends_path_without_storing(monkeypatch):
    """Path is the absent-key default — recommending it stores nothing."""
    client, m, saved = _signed_in_client(monkeypatch, settings={})
    run = _completed_run({a: 0.5 for a in AXES})
    with patch.object(m.assessment_repo, "get_run", return_value=run), \
         patch.object(m.assessment_repo, "responses_for_run", return_value=_strong_assessment_responses()), \
         patch.object(m, "_suggested_problem_for_scores", return_value=None):
        r = client.get("/assess/1/result")
    assert r.status_code == 200
    assert saved == {}
    assert "Path" in r.text
