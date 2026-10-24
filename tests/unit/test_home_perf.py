"""Round-trip count regression guard for home().

A subtle perf bug bit us: `home()` was calling `attempt_repo.all_for_user`
5 times, `_user_settings` 3 times, and `all_by_kind` 4 times. Each is
a ~150ms Supabase round-trip, so the page took 4-5 seconds. We
refactored to fetch each once + use a batch `all_by_kinds`.

This test counts cursor.execute() calls during a representative
home() invocation. If a future refactor re-introduces redundant
fetches, the count goes up and CI flags it before the user feels it.

The test uses a *full* fake stack — no real Postgres, no Sonnet, no
Supabase. It verifies the data-flow shape, not the data correctness;
correctness lives in the per-repository tests."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# Generous ceiling. The tight number today is ~8-10; we set 14 so a
# minor change can land without test fiddling but a true regression
# (say, re-adding one redundant fetch loop) trips it.
MAX_ROUND_TRIPS = 14


def _fake_problem(*, id: int, slug: str = "p", difficulty: str = "easy",
                  is_warmup: bool = False):
    from app.models import Problem
    return Problem(
        id=id, slug=slug, title=slug, difficulty=difficulty,
        time_bucket=30, problem_type="code_compose", is_warmup=is_warmup,
        domain_tags=[], structural_tags=[], competency_tags=[],
        jd_signal_tags=[], content_md="", version=1, em_mode="full",
        em_prompts={}, references=[],
    )


def _build_fake_repos(execute_counter):
    """Construct the repo instances main.py expects, but with their
    methods replaced by fast in-memory stubs. Each stub increments
    `execute_counter` once per call — that's our proxy for round-trips."""
    def count(*a, **kw):
        execute_counter["n"] += 1

    repos = MagicMock()

    # ProblemRepository.all_core / all_warmups / list_recent_for_user
    repos.problem.all_core = MagicMock(
        side_effect=lambda: (count() or [_fake_problem(id=1, slug="01-easy"), _fake_problem(id=2, slug="02-easy")])  # type: ignore
    )
    repos.problem.all_warmups = MagicMock(side_effect=lambda: (count() or []))
    repos.problem.list_recent_for_user = MagicMock(side_effect=lambda uid, limit=5: (count() or []))

    # AttemptRepository.all_for_user — the big one
    repos.attempt.all_for_user = MagicMock(side_effect=lambda uid: (count() or []))

    # ReviewStateRepository
    repos.review.all_for_user = MagicMock(side_effect=lambda uid: (count() or []))

    # ContentRepository batch + others
    repos.content.all_by_kinds = MagicMock(
        side_effect=lambda kinds: (count() or {k: [] for k in kinds})
    )
    repos.content.progress_for_user = MagicMock(side_effect=lambda uid: (count() or {}))
    repos.content.axis_ratings_for_user = MagicMock(side_effect=lambda uid: (count() or {}))
    repos.content.get_by_id = MagicMock(side_effect=lambda cid: (count() or None))

    repos.assessment.latest_completed = MagicMock(side_effect=lambda uid: (count() or None))

    repos.writing.active_draft_today = MagicMock(side_effect=lambda uid: (count() or None))

    repos.reflection.list_for_user = MagicMock(side_effect=lambda uid, limit=1: (count() or []))

    repos.jd.get = MagicMock(side_effect=lambda jid: (count() or None))

    return repos


def test_home_does_not_explode_into_round_trips(mock_anthropic):
    """REGRESSION GUARD: stub every repo + count execute() calls."""
    counter = {"n": 0}

    def count():
        counter["n"] += 1

    # `side_effect=lambda: (count() or [...])` calls count() then
    # returns the list. Wire up the lambdas to use the closure.
    import app.main as m

    # Patch each repo method directly on the module.
    # Each "call" is one round-trip (sometimes more in reality, but
    # for redundancy detection 1-call-per-method is the right proxy).
    with patch.object(m.problem_repo, "all_core", side_effect=lambda: (count() or [_fake_problem(id=1, slug="01"), _fake_problem(id=2, slug="02")])), \
         patch.object(m.problem_repo, "all_warmups", side_effect=lambda: (count() or [])), \
         patch.object(m.problem_repo, "list_recent_for_user", side_effect=lambda uid, limit=5: (count() or [])), \
         patch.object(m, "_is_weekend_for_user", return_value=False), \
         patch.object(m.attempt_repo, "all_for_user", side_effect=lambda uid: (count() or [])), \
         patch.object(m.review_repo, "all_for_user", side_effect=lambda uid: (count() or [])), \
         patch.object(m.content_repo, "all_by_kinds", side_effect=lambda kinds: (count() or {k: [] for k in kinds})), \
         patch.object(m.content_repo, "progress_for_user", side_effect=lambda uid: (count() or {})), \
         patch.object(m.content_repo, "axis_ratings_for_user", side_effect=lambda uid: (count() or {})), \
         patch.object(m.content_repo, "get_by_id", side_effect=lambda cid: (count() or None)), \
         patch.object(m.assessment_repo, "latest_completed", side_effect=lambda uid: (count() or None)), \
         patch.object(m.writing_repo, "active_draft_today", side_effect=lambda uid: (count() or None)), \
         patch.object(m.reflection_repo, "list_for_user", side_effect=lambda uid, limit=1: (count() or [])), \
         patch.object(m.jd_repo, "get", side_effect=lambda jid: (count() or None)), \
         patch.object(m, "_user_settings", side_effect=lambda uid: (count() or {})):

        from fastapi.testclient import TestClient
        client = TestClient(m.app)

        # Mint a fake auth cookie so the middleware lets us through.
        import base64, json, time
        hdr = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
        pl = base64.urlsafe_b64encode(json.dumps({
            "sub": "test-uuid", "email": "t@x.com",
            "exp": int(time.time()) + 3600,
        }).encode()).rstrip(b"=").decode()
        client.cookies.set("sb-access-token", f"{hdr}.{pl}.sig")

        # _user_settings is patched above so the middleware path doesn't
        # reach the raw `conn` cursor — that matters in no-DB CI where
        # the conn is a strict sentinel that raises on cursor() access.
        r = client.get("/", follow_redirects=False)

    # `/` may redirect to /onboarding (latest=None and no skip) — that's
    # OK; we still want to count what got fetched before the redirect.
    assert r.status_code in (200, 303), f"got {r.status_code}: {r.text[:200]}"
    assert counter["n"] <= MAX_ROUND_TRIPS, (
        f"home() made {counter['n']} round-trips; threshold is {MAX_ROUND_TRIPS}. "
        f"A new redundant fetch slipped in — check home() and its helpers "
        f"for repeated repo calls and pass pre-fetched data through args."
    )
