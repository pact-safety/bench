"""Environment scrubbing for user-code runners (BEN-139).

`run_python_tests` / `run_rust_tests` exec attacker-controlled code in a
subprocess. Without an explicit `env=`, that child inherits the FULL server
environment — including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`,
`SUPABASE_*` and every other Fly secret — and the runner returns the child's
stdout to the submitter. A one-line `import os; print(os.environ)` would then
exfiltrate every secret. This module builds a minimal allowlisted env so the
child sees only what the toolchain needs and none of the secrets.

Scope note: this closes the secret-exfiltration path only. Unbounded memory,
CPU beyond the wall-clock timeout, filesystem reach, and network egress are
NOT addressed here — that's the heavier sandbox (separate low-priv user /
container / gVisor with `--network none`) tracked as BEN-139 remediation, kept
separate because it needs calibration against real torch submissions on the
512MB machine.
"""

from __future__ import annotations

import os


def safe_env(
    *,
    keep: tuple[str, ...] = (),
    keep_prefixes: tuple[str, ...] = (),
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """An env dict containing ONLY explicitly allowlisted keys.

    Everything not named in ``keep`` / matching ``keep_prefixes`` is dropped —
    a strict allowlist, so a newly added secret is excluded by default rather
    than needing to be remembered. ``overrides`` are applied last.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in keep or any(key.startswith(p) for p in keep_prefixes):
            env[key] = value
    if overrides:
        env.update({k: v for k, v in overrides.items() if v is not None})
    return env


# The Python child needs an interpreter path + locale; torch/numpy resolve
# from the server interpreter's own sys.path, not the env, so nothing else is
# required. HOME/TMPDIR are pointed at the throwaway sandbox dir.
def python_env(sandbox_dir: str) -> dict[str, str]:
    return safe_env(
        keep=("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"),
        overrides={
            "HOME": sandbox_dir,
            "TMPDIR": sandbox_dir,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )


# cargo/rustup live under $HOME (or $CARGO_HOME/$RUSTUP_HOME), so the real HOME
# and any CARGO_*/RUSTUP_*/RUST* vars must survive; none of those are secrets.
def rust_env() -> dict[str, str]:
    return safe_env(
        keep=("PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "TZ"),
        keep_prefixes=("CARGO", "RUSTUP", "RUST"),
    )
