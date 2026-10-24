"""Top-level pytest fixtures.

The biggest lever here is `mock_anthropic` — a fixture that replaces
the `anthropic.Anthropic` client with a fake whose `messages.create`
returns canned, programmable responses. With this in place, every
LLM-touching service (hints, review, hamming, jd parse, credentials)
is unit-testable without burning real API credits, and shape bugs
like `problem.prompt_md` (vs `content_md`) get caught immediately.

Layout:
  tests/unit/         — fast, no DB, no network. Run on every save.
  tests/integration/  — opt-in via `pytest -m integration`. Touches
                        real Postgres + real Anthropic (if keys set).

Run all unit tests:  .venv/bin/pytest
Run integration:     .venv/bin/pytest -m integration
Run one file:        .venv/bin/pytest tests/unit/test_hints.py
Run one test:        .venv/bin/pytest tests/unit/test_hints.py::test_tier_one
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# Make `import app...` work in tests regardless of how pytest is invoked.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Skip the startup content+problem loader during tests — it makes
# ~75 round-trips to Supabase, which would push test suite from <1s
# to 70+s. Tests that need real content set up their own fixtures or
# get marked @pytest.mark.integration. Must be set BEFORE the first
# `from app.main import ...` anywhere in the test process.
os.environ.setdefault("LIS_SKIP_STARTUP_LOAD", "1")

# Skip the eager `conn = connect()` at module import. With LIS_NO_DB=1,
# app/db.py returns a strict sentinel that raises on cursor() access.
# Unit tests that mock at the repo level never reach the conn; tests
# that DO reach it get a clear actionable error. Means CI runners
# without a real Postgres can still import app.main. If a local dev
# has DATABASE_URL set and wants real DB tests, they can opt out by
# `export LIS_NO_DB=0` before pytest.
if os.environ.get("DATABASE_URL", "").strip() == "":
    os.environ.setdefault("LIS_NO_DB", "1")


@pytest.fixture(autouse=True)
def _clear_app_cache():
    """Drop the in-process cache before every test so one test's
    cached value doesn't leak into another. Cheap (just a dict clear)."""
    try:
        from app import cache
        cache.clear_all()
    except ImportError:
        pass
    yield


@pytest.fixture(autouse=True)
def _db_free_home_repos(monkeypatch):
    """Keep the unit tier genuinely DB-free.

    Pages like the home dashboard call several repos' `list_for_user_since` /
    `list_progress_since` directly (see `_render_rest_home`). Render-focused
    tests — theme, glass, daily-flow — mock `_user_settings` but NOT those
    repo calls, so under the strict no-DB sentinel (`LIS_NO_DB=1`, no
    `DATABASE_URL`) a render reaches the raw conn and raises. Historically a
    stray `DATABASE_URL` masked this; CI has none, so it surfaced as a
    deploy-blocking flake once test ordering shifted.

    Default those list methods to `[]` so a render never needs Postgres. Any
    test that asserts on their output overrides with its own monkeypatch,
    which is applied after this fixture and therefore wins.
    """
    if os.environ.get("LIS_NO_DB") != "1":
        yield
        return
    try:
        import app.main as m
    except Exception:
        yield
        return
    for repo_name, method in (
        ("attempt_repo", "list_for_user_since"),
        ("content_repo", "list_progress_since"),
        ("writing_repo", "list_for_user_since"),
        ("reflection_repo", "list_for_user_since"),
        ("assessment_repo", "completed_since"),
        ("credentials_repo", "completed_since"),
    ):
        repo = getattr(m, repo_name, None)
        if repo is not None and hasattr(repo, method):
            monkeypatch.setattr(repo, method, lambda *a, **k: [], raising=False)
    yield


# --- Anthropic mock ---------------------------------------------------------

class _FakeContentBlock:
    """Mimics anthropic's response.content[i].text shape."""
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    """Mimics anthropic's response.usage.{input,output}_tokens shape.
    Used by the spend-cap shim (app.services.spend_cap.record_usage_for)
    to bump the user's daily counter. Tests that want to exercise the
    cap recording path can read/override these defaults."""
    def __init__(self, input_tokens: int = 100, output_tokens: int = 200) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, text: str, *, input_tokens: int = 100, output_tokens: int = 200) -> None:
        self.content = [_FakeContentBlock(text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)


class FakeAnthropicClient:
    """Drop-in replacement for `anthropic.Anthropic()`.

    Pre-load `responses` (a list of strings) to control what
    `client.messages.create(...)` returns on successive calls. Each
    call pops the next response off the queue. If the queue is empty,
    the default response fires (configurable).

    Inspect `calls` to assert the LLM was invoked with the expected
    model / system prompt / message structure.
    """

    def __init__(self) -> None:
        self.responses: list[str] = []
        self.default_response: str = '{"hint": "(default fake response)"}'
        self.calls: list[dict[str, Any]] = []
        self.messages = self  # so client.messages.create works

    def queue(self, text: str) -> None:
        """Queue a response for the next `messages.create` call."""
        self.responses.append(text)

    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict]):
        """Records the call, returns the next queued response."""
        self.calls.append({
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        })
        text = self.responses.pop(0) if self.responses else self.default_response
        return _FakeResponse(text)


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Replace `anthropic.Anthropic` with FakeAnthropicClient.

    Also sets ANTHROPIC_API_KEY so service code that checks
    `os.environ.get("ANTHROPIC_API_KEY")` takes the LLM branch.
    """
    fake = FakeAnthropicClient()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")

    # Each service module imports Anthropic locally inside the function
    # (e.g. `from anthropic import Anthropic` then `client = Anthropic()`).
    # We monkeypatch the class so `Anthropic()` returns our fake.
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **kw: fake)
    return fake


# --- Sample dataclasses -----------------------------------------------------

@pytest.fixture
def sample_problem():
    """A minimal but real Problem dataclass. Used by hint/review tests
    so they exercise the same attribute-access surface as production
    code (the kind of test that catches `problem.prompt_md` typos)."""
    from app.models import Problem
    return Problem(
        id=1,
        slug="test-problem",
        title="Test Problem — implement softmax",
        difficulty="medium",
        time_bucket=30,
        problem_type="code_compose",
        is_warmup=False,
        domain_tags=["transformer"],
        structural_tags=["compose"],
        competency_tags=[],
        jd_signal_tags=["transformer"],
        content_md="Implement a numerically-stable softmax. Subtract the max before exp.",
        starter_code_python="def softmax(x):\n    pass\n",
        reference_solution_python="def softmax(x):\n    import torch\n    return torch.softmax(x, dim=-1)\n",
        key_insight="subtract max(x) before exp() to avoid overflow",
        pitfalls_md="forgetting to subtract max",
        test_code_python="",
        version=1,
        em_mode="full",
        em_prompts={},
        references=[],
    )


@pytest.fixture
def sample_attempt():
    """A representative completed Attempt — has notes in every phase,
    a confidence value, and a passing test. Mirrors what reviews
    consume."""
    from app.models import Attempt
    return Attempt(
        id=42,
        user_id="00000000-0000-0000-0000-000000000001",
        problem_id=1,
        problem_version=1,
        started_at=datetime(2026, 5, 14, 10, 0, 0),
        ended_at=datetime(2026, 5, 14, 10, 25, 0),
        language_used="python",
        final_code="def softmax(x):\n    x = x - x.max()\n    return torch.softmax(x, dim=-1)\n",
        solved_without_lookup=True,
        confidence_1_to_5=4,
        time_to_first_edit_seconds=60,
        edit_count=12,
        looked_at_solution=False,
        looked_at_pitfalls=False,
        test_passed=True,
        test_output="ok",
        notes_md="trap: forgetting the max subtraction",
        explore_notes="shapes: x is (batch, vocab)",
        brainstorm_notes="two approaches: torch.softmax vs hand-roll exp/sum",
        plan_notes="hand-roll for the practice; subtract max first",
        verify_notes="tested with all-zeros, large positives",
        time_per_phase={"explore": 60, "plan": 90, "implement": 600, "verify": 60},
        interview_mode=False,
        hints_used={"plan": 1},
    )
