"""Guards on the migration set.

Every rule here exists because the thing it forbids actually happened:

- A second directory that *looked* like migrations (`migrations/`, SQLite-era)
  sat next to the real one for months. A `pinned_at` migration was written
  into it and silently never ran — `app/main.py` applies `migrations_pg/`
  only — so the live database ended up with a column no migration created.
- Two migrations share the number 014. Harmless today because the runner
  sorts lexically, but "what's the next number" stopped having one answer.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PG = REPO / "migrations_pg"


def _migrations() -> list[Path]:
    return sorted(PG.glob("*.sql"))


def test_the_dead_sqlite_directory_stays_gone():
    """It was never applied, and its existence cost a silently-missing column."""
    assert not (REPO / "migrations").exists(), (
        "migrations/ is back. The app applies migrations_pg/ only "
        "(app/main.py), so anything written here never runs."
    )


def test_there_is_exactly_one_migration_directory():
    candidates = [
        d for d in REPO.iterdir()
        if d.is_dir() and "migration" in d.name.lower()
    ]
    assert [d.name for d in candidates] == ["migrations_pg"], (
        f"expected only migrations_pg/, found {[d.name for d in candidates]}"
    )


def test_every_migration_is_numbered():
    for m in _migrations():
        assert re.match(r"^\d{3}_", m.name), f"{m.name} has no NNN_ prefix"


def test_migration_numbers_are_unique():
    """014 is currently duplicated. This test is xfail rather than deleted so
    the debt stays visible — renumbering an applied migration would make the
    runner treat it as new and re-apply it, which is worse than the duplicate."""
    nums = Counter(m.name.split("_", 1)[0] for m in _migrations())
    dupes = {n: c for n, c in nums.items() if c > 1}
    if dupes == {"014": 2}:
        pytest.xfail(
            "known: 014_interview_phase_budgets.sql and 014_mira.sql share a "
            "number. Both are already applied; renumbering would re-run them."
        )
    assert not dupes, f"duplicate migration numbers: {dupes}"


def test_pinned_at_has_a_migration():
    """REGRESSION: the column existed in the live database while no migration
    created it, so a fresh database came up without it."""
    joined = "\n".join(m.read_text() for m in _migrations())
    assert "pinned_at" in joined, (
        "content_progress.pinned_at is read by the app but no migration "
        "creates it — a fresh database would be missing it"
    )


def test_new_migrations_are_idempotent():
    """Forward-looking: migrations from 019 on must survive being re-run.

    Not applied retroactively — the earlier files are already recorded as
    applied and rewriting them buys nothing. But this project has twice had a
    migration run out of band (`pinned_at` is why 019 exists at all), and
    `IF NOT EXISTS` is what makes that recoverable instead of a hard error on
    the next deploy.
    """
    offenders = []
    for m in _migrations():
        num = int(m.name.split("_", 1)[0])
        if num < 19:
            continue
        for stmt in re.findall(
            r"^\s*(?:CREATE TABLE|CREATE INDEX|ALTER TABLE \w+ ADD COLUMN)\b[^\n;]*",
            m.read_text(), re.M | re.I,
        ):
            if "IF NOT EXISTS" not in stmt.upper():
                offenders.append(f"{m.name}: {stmt.strip()[:70]}")
    assert not offenders, (
        "new migrations must be idempotent (use IF NOT EXISTS):\n  "
        + "\n  ".join(offenders)
    )
