"""Run a Rust submission via `cargo test`.

Each Rust-flagged problem ships a crate template in
`content/rust/<slug>/`. We copy that template to a temp dir, overwrite
`src/lib.rs` (or whichever file the template says to overwrite via
`SUBMISSION_TARGET` in `Cargo.toml`'s metadata, or default `src/lib.rs`)
with the user's submission, then `cargo test`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ._sandbox import rust_env


@dataclass
class RunResult:
    passed: bool
    output: str
    duration_seconds: float
    hidden_passed: bool | None = None
    user_passed: bool | None = None


def run_rust_tests(
    crate_template_dir: Path,
    submission: str,
    timeout: int,
    user_tests: str | None = None,
) -> RunResult:
    normalized_user_tests = user_tests if user_tests and user_tests.strip() else None
    if not crate_template_dir.exists():
        return RunResult(
            False,
            f"Rust crate template not found: {crate_template_dir}",
            0.0,
            hidden_passed=False,
            user_passed=False if normalized_user_tests else None,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        dst = Path(tmpdir) / "crate"
        shutil.copytree(crate_template_dir, dst)
        target = dst / "src" / "lib.rs"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(submission)

        try:
            hidden_proc = subprocess.run(
                ["cargo", "test", "--quiet"],
                cwd=dst,
                capture_output=True,
                text=True,
                timeout=timeout,
                # BEN-139: scrubbed env (keeps PATH/HOME/CARGO*/RUSTUP* for the
                # toolchain, drops server secrets).
                env=rust_env(),
            )
        except subprocess.TimeoutExpired as e:
            user_passed = False if normalized_user_tests else None
            return RunResult(
                passed=False,
                output=f"cargo test timed out after {timeout}s.\n{(e.stdout or '') + (e.stderr or '')}",
                duration_seconds=float(timeout),
                hidden_passed=False,
                user_passed=user_passed,
            )
        except FileNotFoundError:
            user_passed = False if normalized_user_tests else None
            return RunResult(
                False,
                "cargo not found on PATH. Install rustup.",
                0.0,
                hidden_passed=False,
                user_passed=user_passed,
            )

        hidden_output = (hidden_proc.stdout or "") + (hidden_proc.stderr or "")
        hidden_passed = hidden_proc.returncode == 0
        if not normalized_user_tests:
            return RunResult(
                passed=hidden_passed,
                output=hidden_output,
                duration_seconds=0.0,
                hidden_passed=hidden_passed,
                user_passed=None,
            )

        user_tests_file = dst / "tests" / "user_tests.rs"
        user_tests_file.parent.mkdir(parents=True, exist_ok=True)
        user_tests_file.write_text(normalized_user_tests)
        try:
            user_proc = subprocess.run(
                ["cargo", "test", "--quiet", "--test", "user_tests"],
                cwd=dst,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=rust_env(),  # BEN-139: same scrubbed env
            )
        except subprocess.TimeoutExpired as e:
            output = "\n\n".join(
                part for part in [
                    f"[hidden tests]\n{hidden_output}".strip(),
                    f"[your tests]\ncargo test --test user_tests timed out after {timeout}s.\n{(e.stdout or '') + (e.stderr or '')}".strip(),
                ]
                if part
            )
            return RunResult(
                passed=False,
                output=output,
                duration_seconds=float(timeout),
                hidden_passed=hidden_passed,
                user_passed=False,
            )
        except FileNotFoundError:
            output = "\n\n".join(
                part for part in [
                    f"[hidden tests]\n{hidden_output}".strip(),
                    "[your tests]\ncargo not found on PATH. Install rustup.",
                ]
                if part
            )
            return RunResult(
                passed=False,
                output=output,
                duration_seconds=0.0,
                hidden_passed=hidden_passed,
                user_passed=False,
            )

        user_output = (user_proc.stdout or "") + (user_proc.stderr or "")
        user_passed = user_proc.returncode == 0
        combined_output = "\n\n".join(
            part for part in [
                f"[hidden tests]\n{hidden_output}".strip(),
                f"[your tests]\n{user_output}".strip(),
            ]
            if part
        )
        return RunResult(
            passed=hidden_passed and user_passed,
            output=combined_output,
            duration_seconds=0.0,
            hidden_passed=hidden_passed,
            user_passed=user_passed,
        )
