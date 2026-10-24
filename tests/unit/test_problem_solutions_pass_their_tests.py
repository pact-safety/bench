"""Every authored problem's `## Solution` must pass its own `## Tests`.

This matters most for cold-checkpoint problems: those now GATE track
progress, so a problem whose tests can't pass its own solution doesn't just
annoy a learner, it hard-blocks the section behind it.

Problems whose code needs a dependency the unit tier doesn't install (torch,
in particular) are skipped rather than failed — the unit tier is DB-free and
GPU-free by design. Numpy/stdlib problems all run for real.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

PROBLEMS = sorted(Path("content/problems").glob("*.md"))

# Whether a problem runs here depends on what the unit tier actually has
# installed, which differs between a dev machine and CI (CI is deliberately
# lean — no numpy, no torch). So detect importability rather than keeping a
# denylist that silently rots.


def _section_code(text: str, heading: str) -> str | None:
    """First fenced python block under `## <heading>`."""
    m = re.search(rf"^##\s+{heading}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return None
    # Older problems use a bare fence; newer ones tag it python.
    block = re.search(r"```(?:python|py)?\n(.*?)```", m.group(1), re.S)
    return block.group(1) if block else None


def _missing_imports(code: str) -> list[str]:
    """Top-level modules the code imports that this interpreter can't load."""
    mods = set(re.findall(r"^\s*import\s+([A-Za-z_][\w]*)", code, re.M))
    mods |= set(re.findall(r"^\s*from\s+([A-Za-z_][\w]*)", code, re.M))
    missing = []
    for mod in sorted(mods):
        try:
            if importlib.util.find_spec(mod) is None:
                missing.append(mod)
        except (ImportError, ValueError):
            missing.append(mod)
    return missing


@pytest.mark.parametrize("path", PROBLEMS, ids=lambda p: p.stem)
def test_solution_passes_its_own_tests(path: Path):
    text = path.read_text()
    solution = _section_code(text, "Solution")
    tests = _section_code(text, "Tests")

    if solution is None or tests is None:
        pytest.skip(f"{path.stem}: no fenced Solution/Tests pair")
    missing = sorted(set(_missing_imports(solution)) | set(_missing_imports(tests)))
    if missing:
        pytest.skip(f"{path.stem}: needs {', '.join(missing)} — not in the unit tier")

    ns: dict = {}
    try:
        exec(compile(solution, f"{path.stem}:Solution", "exec"), ns)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{path.stem}: Solution failed to load — {type(exc).__name__}: {exc}")

    # Two authored styles, both valid: bare module-level asserts (which run
    # here, during exec) and `def test_*()` functions (called below).
    try:
        exec(compile(tests, f"{path.stem}:Tests", "exec"), ns)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"{path.stem}: Tests failed against the authored solution — "
            f"{type(exc).__name__}: {exc}"
        )

    for name, fn in list(ns.items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"{path.stem}: {name} failed against the authored "
                f"solution — {type(exc).__name__}: {exc}"
            )
