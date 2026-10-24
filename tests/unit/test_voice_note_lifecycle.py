"""Regression guard for voice-note.js recognizer lifecycle.

The dictation bug in issue #80 was a browser-event ordering problem in
client-side JS (SpeechRecognition `error`/`end` races). We keep the
behavioral regression test in Node's built-in test runner and invoke it
from pytest so it stays in the normal unit test suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for JS lifecycle test")
def test_voice_note_lifecycle_regression_guard():
    repo_root = Path(__file__).resolve().parents[2]
    test_file = repo_root / "tests" / "unit" / "voice-note.lifecycle.test.mjs"

    proc = subprocess.run(
        ["node", "--test", str(test_file)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, (
        "node lifecycle test failed\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
