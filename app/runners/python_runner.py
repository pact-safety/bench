"""Run a Python submission against its test script in a subprocess.

The test code is appended to the submission and run via the same Python
interpreter as the server. We rely on the user's local env for torch /
numpy. If they aren't installed, the test surfaces an ImportError in the
output, which is correct: the user needs them installed to attempt the
ML problems.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ._sandbox import python_env


_RESULT_MARKER = "__LIS_RESULT__"


@dataclass
class RunResult:
    passed: bool
    output: str
    duration_seconds: float
    hidden_passed: bool | None = None
    user_passed: bool | None = None


def _build_script(submission: str, hidden_tests: str, user_tests: str | None) -> str:
    return "\n".join(
        [
            "import json as _json",
            "import traceback as _traceback",
            "",
            "def _run_block(label, code):",
            "    try:",
            "        exec(compile(code, f'<{label}>', 'exec'), globals(), globals())",
            "        return True",
            "    except Exception:",
            "        print(f'[{label}] failed:')",
            "        _traceback.print_exc()",
            "        return False",
            "",
            f"_submission = {submission!r}",
            f"_hidden_tests = {hidden_tests!r}",
            f"_user_tests = {user_tests!r}",
            "",
            "_submission_ok = _run_block('submission', _submission)",
            "if _submission_ok:",
            "    _user_passed = _run_block('user-tests', _user_tests) if _user_tests else None",
            "    _hidden_passed = _run_block('hidden-tests', _hidden_tests)",
            "else:",
            "    _user_passed = False if _user_tests else None",
            "    _hidden_passed = False",
            "",
            "print('__LIS_RESULT__' + _json.dumps({'hidden_passed': _hidden_passed, 'user_passed': _user_passed}))",
            "if not (_hidden_passed and (_user_passed is not False)):",
            "    raise SystemExit(1)",
        ]
    )


def _extract_flags(output: str, *, has_user_tests: bool) -> tuple[bool | None, bool | None, str]:
    payload: str | None = None
    kept: list[str] = []
    for line in output.splitlines():
        if line.startswith(_RESULT_MARKER):
            payload = line[len(_RESULT_MARKER):]
            continue
        kept.append(line)
    cleaned = "\n".join(kept)

    if not payload:
        return None, None, cleaned
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, None, cleaned

    hidden_passed = data.get("hidden_passed")
    user_passed = data.get("user_passed")
    if hidden_passed is not None:
        hidden_passed = bool(hidden_passed)
    if user_passed is not None:
        user_passed = bool(user_passed)
    if not has_user_tests:
        user_passed = None
    return hidden_passed, user_passed, cleaned


def run_python_tests(
    submission: str,
    tests: str,
    timeout: int,
    user_tests: str | None = None,
) -> RunResult:
    normalized_user_tests = user_tests if user_tests and user_tests.strip() else None
    body = _build_script(submission, tests, normalized_user_tests)
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "run.py"
        f.write_text(body)
        try:
            proc = subprocess.run(
                [sys.executable, str(f)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                # BEN-139: strict env allowlist so submitted code can't read
                # server secrets (ANTHROPIC_API_KEY etc.) out of os.environ.
                env=python_env(tmpdir),
            )
        except subprocess.TimeoutExpired as e:
            user_passed = False if normalized_user_tests else None
            return RunResult(
                passed=False,
                output=f"Timed out after {timeout}s.\n{(e.stdout or '') + (e.stderr or '')}",
                duration_seconds=float(timeout),
                hidden_passed=False,
                user_passed=user_passed,
            )
    output = (proc.stdout or "") + (proc.stderr or "")
    hidden_passed, user_passed, clean_output = _extract_flags(
        output,
        has_user_tests=bool(normalized_user_tests),
    )

    if hidden_passed is None:
        hidden_passed = proc.returncode == 0
    if normalized_user_tests:
        if user_passed is None:
            user_passed = proc.returncode == 0
    else:
        user_passed = None

    passed = bool(hidden_passed) and (user_passed is not False)
    return RunResult(
        passed=passed,
        output=clean_output,
        duration_seconds=0.0,
        hidden_passed=hidden_passed,
        user_passed=user_passed,
    )
