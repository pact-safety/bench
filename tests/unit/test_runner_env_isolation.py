"""BEN-139: user-code runners must not leak server secrets into the child env.

The load-bearing test is `test_submitted_code_cannot_read_secret` — it sets a
fake ANTHROPIC_API_KEY in the parent, submits code that dumps os.environ, and
asserts the secret never appears in the output the submitter sees.
"""

from __future__ import annotations

import os

from app.runners import _sandbox
from app.runners.python_runner import run_python_tests


def test_safe_env_drops_unlisted_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = _sandbox.safe_env(keep=("PATH",))
    assert env == {"PATH": "/usr/bin"}
    assert "ANTHROPIC_API_KEY" not in env
    assert "DATABASE_URL" not in env


def test_python_env_keeps_toolchain_drops_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-other")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt")
    env = _sandbox.python_env("/tmp/sbx")
    for secret in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SUPABASE_JWT_SECRET"):
        assert secret not in env
    assert env["HOME"] == "/tmp/sbx"  # override applied


def test_rust_env_keeps_cargo_prefixes(monkeypatch):
    monkeypatch.setenv("CARGO_HOME", "/home/app/.cargo")
    monkeypatch.setenv("RUSTUP_HOME", "/home/app/.rustup")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = _sandbox.rust_env()
    assert env.get("CARGO_HOME") == "/home/app/.cargo"
    assert env.get("RUSTUP_HOME") == "/home/app/.rustup"
    assert "ANTHROPIC_API_KEY" not in env


def test_submitted_code_cannot_read_secret(monkeypatch):
    """End-to-end: a submission dumping os.environ must not expose the key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-LEAK-CANARY-12345")  # gitleaks:allow (canary)
    submission = "import os\nprint('ENV_DUMP', dict(os.environ))\n"
    result = run_python_tests(submission, tests="", timeout=10)
    assert "sk-LEAK-CANARY-12345" not in result.output  # gitleaks:allow (canary)
    assert "ANTHROPIC_API_KEY" not in result.output


def test_runner_still_executes_normally(monkeypatch):
    """The scrub must not break a legitimate submission."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    result = run_python_tests("print('hello from sandbox')", tests="", timeout=10)
    assert "hello from sandbox" in result.output
