"""Scheduler tests — Scorer components and ReviewStrategy.build.

These exercise the pure scoring logic. The recently-added
`easy_first_bias` (so onboarding-skipped users see easy problems
first) has explicit coverage because that's user-visible behavior
that could regress silently.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.config import SchedulerWeights
from app.models import Attempt, Problem, ReviewState
from app.services.scheduler import ReviewStrategy, Scorer


def _weights(**overrides) -> SchedulerWeights:
    base = dict(
        days_since=1.0, low_confidence=1.2, over_time=0.8,
        used_reference=0.6, topic_gap=0.5, never_attempted=2.5,
        content_aligned=1.5, content_aligned_recency_days=3,
        jd_aligned=1.5, used_hints=0.6,
        max_60min_per_session=1, require_category_span=True,
    )
    base.update(overrides)
    return SchedulerWeights(**base)


def _problem(*, id: int, slug: str, difficulty: str = "medium", time_bucket: int = 30,
             problem_type: str = "code_compose", is_warmup: bool = False,
             tags: tuple[str, ...] = ()) -> Problem:
    return Problem(
        id=id, slug=slug, title=slug, difficulty=difficulty,
        time_bucket=time_bucket, problem_type=problem_type,
        is_warmup=is_warmup, domain_tags=list(tags), structural_tags=[],
        competency_tags=[], jd_signal_tags=[], content_md="",
        version=1, em_mode="full", em_prompts={}, references=[],
    )


def test_scorer_never_attempted_gets_boost():
    s = Scorer(_weights(), datetime(2026, 5, 14))
    p = _problem(id=1, slug="p1")
    r = s.score(p, last_attempt=None, state=None, topic_last_seen={})
    assert r.components.get("never_attempted") == 2.5


def test_scorer_days_since_log_scaled():
    """Day 1 ≈ 0.3, day 7 ≈ 2.0, day 30 ≈ 3.4 per the inline comment."""
    now = datetime(2026, 5, 14)
    p = _problem(id=1, slug="p1")
    a = Attempt(
        id=1, user_id="u", problem_id=1, problem_version=1,
        started_at=now - timedelta(days=7), ended_at=None,
        language_used="python", final_code=None, solved_without_lookup=None,
        confidence_1_to_5=3, time_to_first_edit_seconds=None, edit_count=0,
        looked_at_solution=False, looked_at_pitfalls=False, test_passed=None,
        test_output=None, notes_md=None,
    )
    s = Scorer(_weights(), now)
    r = s.score(p, last_attempt=a, state=None, topic_last_seen={})
    assert 1.8 < r.components["days_since"] < 2.2


def test_scorer_low_confidence_bumps_back():
    now = datetime(2026, 5, 14)
    p = _problem(id=1, slug="p1")
    a = Attempt(
        id=1, user_id="u", problem_id=1, problem_version=1,
        started_at=now - timedelta(hours=1), ended_at=None,
        language_used="python", final_code=None, solved_without_lookup=None,
        confidence_1_to_5=1,  # lowest
        time_to_first_edit_seconds=None, edit_count=0,
        looked_at_solution=False, looked_at_pitfalls=False, test_passed=None,
        test_output=None, notes_md=None,
    )
    s = Scorer(_weights(), now)
    r = s.score(p, last_attempt=a, state=None, topic_last_seen={})
    # confidence 1 → low_confidence = 1.0 × weight (1.2)
    assert abs(r.components["low_confidence"] - 1.2) < 1e-6


def test_scorer_used_reference_penalty():
    now = datetime(2026, 5, 14)
    p = _problem(id=1, slug="p1")
    a = Attempt(
        id=1, user_id="u", problem_id=1, problem_version=1,
        started_at=now - timedelta(hours=1), ended_at=None,
        language_used="python", final_code=None, solved_without_lookup=None,
        confidence_1_to_5=3, time_to_first_edit_seconds=None, edit_count=0,
        looked_at_solution=True,  # peeked
        looked_at_pitfalls=False, test_passed=None,
        test_output=None, notes_md=None,
    )
    s = Scorer(_weights(), now)
    r = s.score(p, last_attempt=a, state=None, topic_last_seen={})
    assert r.components.get("used_reference") == 0.6


def test_scorer_used_hints_scales_with_tier():
    """hints_used={"plan": 3} → max tier 3 → full weight."""
    now = datetime(2026, 5, 14)
    p = _problem(id=1, slug="p1")
    a = Attempt(
        id=1, user_id="u", problem_id=1, problem_version=1,
        started_at=now - timedelta(hours=1), ended_at=None,
        language_used="python", final_code=None, solved_without_lookup=None,
        confidence_1_to_5=3, time_to_first_edit_seconds=None, edit_count=0,
        looked_at_solution=False, looked_at_pitfalls=False, test_passed=None,
        test_output=None, notes_md=None, hints_used={"plan": 3},
    )
    s = Scorer(_weights(), now)
    r = s.score(p, last_attempt=a, state=None, topic_last_seen={})
    assert abs(r.components["used_hints"] - 0.6) < 1e-6
    # Tier 1 only — gets 1/3 of the weight.
    a.hints_used = {"plan": 1}
    r = s.score(p, last_attempt=a, state=None, topic_last_seen={})
    assert abs(r.components["used_hints"] - 0.2) < 0.01


def test_scorer_easy_first_bias_favors_easy():
    """The recently-added bias: easy gets +1.0, medium +0.5, hard 0
    when bias=1.0. Verifies onboarding-skip lands on easy problems."""
    now = datetime(2026, 5, 14)
    s = Scorer(_weights(), now)
    easy = _problem(id=1, slug="e", difficulty="easy")
    med = _problem(id=2, slug="m", difficulty="medium")
    hard = _problem(id=3, slug="h", difficulty="hard")

    re_ = s.score(easy, None, None, {}, easy_first_bias=1.0)
    rm = s.score(med, None, None, {}, easy_first_bias=1.0)
    rh = s.score(hard, None, None, {}, easy_first_bias=1.0)

    assert re_.components["easy_first_bias"] == 1.0
    assert rm.components["easy_first_bias"] == 0.5
    assert "easy_first_bias" not in rh.components  # mult is 0

    # Total ordering: easy > medium > hard when never attempted + bias.
    assert re_.score > rm.score > rh.score


def test_scorer_easy_first_bias_zero_is_no_op():
    """Default bias=0 → no easy_first_bias component."""
    now = datetime(2026, 5, 14)
    s = Scorer(_weights(), now)
    easy = _problem(id=1, slug="e", difficulty="easy")
    r = s.score(easy, None, None, {})
    assert "easy_first_bias" not in r.components


def test_review_strategy_threads_easy_first_bias():
    """The build() public path correctly forwards the bias arg."""
    now = datetime(2026, 5, 14)
    weights = _weights()
    strategy = ReviewStrategy(weights, now=now)
    problems = [
        _problem(id=1, slug="easy-1", difficulty="easy"),
        _problem(id=2, slug="hard-1", difficulty="hard"),
        _problem(id=3, slug="easy-2", difficulty="easy", problem_type="code_debug"),
    ]
    result = strategy.build(
        problems=problems, attempts_by_problem={}, states_by_problem={},
        size=2, easy_first_bias=1.0,
    )
    chosen_slugs = [r.problem.slug for r in result]
    assert chosen_slugs[0].startswith("easy")  # easy comes first


def test_easy_first_bias_ramps_down_with_attempt_count():
    """Documents the schedule used in main.py's _build_session:
       0 attempts → 1.0, 5 → 0.5, 10 → 0, capped at 0 below."""
    def bias(n: int) -> float:
        return max(0.0, 1.0 - n / 10.0)
    assert bias(0) == 1.0
    assert bias(5) == 0.5
    assert abs(bias(7) - 0.3) < 1e-9
    assert bias(10) == 0.0
    assert bias(50) == 0.0


def test_review_strategy_no_bias_when_attempted():
    """With no bias, never_attempted dominates and difficulty doesn't
    matter — the natural v1 behavior."""
    now = datetime(2026, 5, 14)
    strategy = ReviewStrategy(_weights(), now=now)
    problems = [
        _problem(id=1, slug="hard", difficulty="hard"),
        _problem(id=2, slug="easy", difficulty="easy"),
    ]
    # No bias — both score 2.5 (never_attempted only). Stable sort,
    # so original order preserved.
    result = strategy.build(
        problems=problems, attempts_by_problem={}, states_by_problem={},
        size=2,
    )
    assert {r.problem.slug for r in result} == {"hard", "easy"}


@pytest.mark.parametrize("easy_first_bias", [0.0, 1.0])
def test_review_strategy_excludes_warmups_by_default(easy_first_bias):
    strategy = ReviewStrategy(_weights(), now=datetime(2026, 5, 14))
    warmup = _problem(id=1, slug="warmup", difficulty="easy", time_bucket=5, is_warmup=True)
    core = _problem(id=2, slug="core", difficulty="hard")

    result = strategy.build(
        [warmup, core], {}, {}, size=1, easy_first_bias=easy_first_bias,
    )

    assert [r.problem.id for r in result] == [core.id]


@pytest.mark.parametrize("easy_first_bias", [0.0, 1.0])
def test_review_strategy_keeps_warmups_when_explicitly_included(easy_first_bias):
    strategy = ReviewStrategy(_weights(), now=datetime(2026, 5, 14))
    warmup = _problem(id=1, slug="warmup", difficulty="easy", time_bucket=5, is_warmup=True)
    core = _problem(id=2, slug="core", difficulty="hard")

    result = strategy.build(
        [core, warmup], {}, {}, size=2,
        easy_first_bias=easy_first_bias, include_warmups=True,
    )

    assert {r.problem.id for r in result} == {warmup.id, core.id}
    if easy_first_bias:
        assert result[0].problem.id == warmup.id


@pytest.mark.parametrize(
    "attempt_count,force_warmups,expected_warmup",
    [(0, False, True), (3, False, True), (4, False, False),
     (10, False, False), (10, True, True)],
)
def test_build_session_warmup_eligibility(
    monkeypatch, sample_attempt, attempt_count, force_warmups, expected_warmup,
):
    import app.main as m

    warmup = _problem(id=1, slug="warmup", difficulty="easy", time_bucket=5, is_warmup=True)
    core = _problem(id=2, slug="core", difficulty="hard")
    # Prior attempts concern other problems, isolating onboarding eligibility
    # from recency and confidence scoring on today's candidates.
    attempts = [
        replace(sample_attempt, id=i + 1, problem_id=100 + i)
        for i in range(attempt_count)
    ]
    monkeypatch.setattr(m.problem_repo, "all_core", lambda: [core])
    monkeypatch.setattr(m.problem_repo, "all_warmups", lambda: [warmup])
    monkeypatch.setattr(m.review_repo, "all_for_user", lambda uid: [])
    monkeypatch.setattr(m, "_active_jd", lambda uid: None)
    monkeypatch.setattr(m, "_user_settings", lambda uid: {})

    result = m._build_session(
        "user", attempts=attempts, recent_content_axes=set(),
        include_warmups_in_pool=force_warmups,
    )

    assert (warmup.id in {r.problem.id for r in result}) is expected_warmup
    assert core.id in {r.problem.id for r in result}
    if attempt_count <= 3:
        assert result[0].problem.id == warmup.id
