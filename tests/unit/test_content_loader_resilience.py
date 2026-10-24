"""Guards for the content loader.

Two regressions this locks down:

1. Every authored problem must use a `time_bucket` the DB schema allows
   (`migrations_pg/001_consolidated.sql`: CHECK time_bucket IN (5,10,30,60)).
   A bad value doesn't fail parsing — it fails at DB upsert time, which
   (because the loader runs at module import) crashed the whole app boot
   and failed the deploy health check. Catch it in CI instead.

2. `load_all_problems` must not let a single failing problem crash the
   entire load — one malformed/constraint-violating file should be
   skipped with a warning, not take the app down.
"""

from __future__ import annotations

from pathlib import Path

from app.content_loader import load_all_problems, parse_problem_file

# Mirror of the schema CHECK constraint on problems.time_bucket.
ALLOWED_TIME_BUCKETS = {5, 10, 30, 60}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTENT = _REPO_ROOT / "content"


def test_all_problems_use_schema_valid_time_bucket():
    """No authored problem may carry a time_bucket the DB will reject."""
    offenders = []
    for sub in ("problems", "warmups"):
        d = _CONTENT / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            p = parse_problem_file(f)
            if p.time_bucket not in ALLOWED_TIME_BUCKETS:
                offenders.append((f.name, p.time_bucket))
    assert not offenders, (
        "problems with time_bucket outside "
        f"{sorted(ALLOWED_TIME_BUCKETS)}: {offenders}"
    )


def test_loader_skips_a_failing_problem_instead_of_crashing():
    """A repo.upsert that raises on one problem must not abort the load."""

    class FlakyRepo:
        def __init__(self):
            self.upserted = []

        def hashes_by_slug(self):
            return {}  # nothing cached → every file is a fresh upsert

        def upsert(self, problem, content_hash):
            if problem.slug == "pair-sum":
                raise Exception("simulated constraint violation")
            self.upserted.append(problem.slug)

    repo = FlakyRepo()
    # Must not raise, and must have loaded the rest of the corpus.
    n = load_all_problems(_CONTENT, repo)
    assert n > 1
    assert "pair-sum" not in repo.upserted
    assert "warmest-reading" in repo.upserted
