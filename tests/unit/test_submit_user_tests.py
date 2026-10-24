"""Submit-route coverage for optional user-written tests."""

from __future__ import annotations

import base64
import json
import time


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _client():
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app), m


def _set_fake_session_cookie(client, *, user_id: str = _USER_UUID) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": user_id,
                "email": "test@example.com",
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


def _problem(slug: str):
    from app.models import Problem

    return Problem(
        id=7,
        slug=slug,
        title="Toy problem",
        difficulty="easy",
        time_bucket=10,
        problem_type="code_compose",
        is_warmup=True,
        domain_tags=[],
        structural_tags=[],
        competency_tags=[],
        jd_signal_tags=[],
        content_md="",
        test_code_python="assert add_one(1) == 2",
        version=1,
        em_mode="full",
        em_prompts={},
        references=[],
    )


def test_submit_roundtrips_user_tests_to_runner_and_attempt(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    problem = _problem("toy-problem")
    monkeypatch.setattr(m.problem_repo, "get_by_slug", lambda _slug: problem)

    captured: dict[str, object] = {}

    def fake_run_python_tests(submission, tests, timeout, user_tests=None):
        from app.runners.python_runner import RunResult

        captured["runner"] = {
            "submission": submission,
            "tests": tests,
            "timeout": timeout,
            "user_tests": user_tests,
        }
        return RunResult(
            passed=False,
            output="user test failed",
            duration_seconds=0.0,
            hidden_passed=True,
            user_passed=False,
        )

    monkeypatch.setattr(m, "run_python_tests", fake_run_python_tests)

    def fake_insert(attempt):
        captured["attempt"] = attempt
        return 42

    monkeypatch.setattr(m.attempt_repo, "insert", fake_insert)

    user_tests_code = "assert add_one(0) == 9"
    resp = client.post(
        "/submit/toy-problem",
        data={
            "code": "def add_one(x):\n    return x + 1\n",
            "language": "python",
            "user_tests_code": user_tests_code,
        },
    )

    assert resp.status_code == 200
    assert captured["runner"]["user_tests"] == user_tests_code
    assert captured["attempt"].user_tests_code == user_tests_code
    assert "result--partial" in resp.text
    assert "Solution passed hidden tests, but your tests failed." in resp.text
