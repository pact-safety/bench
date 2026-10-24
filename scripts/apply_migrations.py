#!/usr/bin/env python3
"""Apply unapplied migrations from `migrations_pg/` to a Postgres DB.

This is the explicit, operator-driven complement to the implicit
``apply_migrations()`` call in ``app/main.py``. Use it when:

* Production has drifted from ``schema_migrations`` (the situation that
  prompted writing this script — prod had only 001-002 recorded despite
  many later migrations being in the repo).
* You want a transparent "preview what would happen" pass before
  letting the startup hook run.
* You need richer logging than the bare ``cur.execute(sql)`` the
  startup hook does today.

Why standalone rather than "fix the startup hook":
1. Migrations as an *explicit deploy step* is better than silent at
   container boot. A deploy step that errors stops the deploy; a boot
   hook that errors kills traffic.
2. This script can be re-run safely (every migration in
   ``migrations_pg/`` is idempotent — IF NOT EXISTS / IF EXISTS guards
   throughout) which lets the operator reconcile drift without
   redeploying.
3. The startup hook stays in place as a safety net for fresh dev DBs
   and for environments where the operator forgets to run this.

Usage::

    # Apply against $DATABASE_URL (set in env)
    python scripts/apply_migrations.py

    # Dry run — list pending migrations, change nothing
    python scripts/apply_migrations.py --dry-run

    # Verbose — log SQL preview per migration
    python scripts/apply_migrations.py --verbose

    # Override the URL inline
    python scripts/apply_migrations.py --database-url postgresql://...

Exits non-zero on any error; printable per-migration summary on success.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


_REPO_ROOT = Path(__file__).resolve().parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "migrations_pg"


def _connect(database_url: str) -> psycopg.Connection:
    """Match the connection config production uses (autocommit + no
    auto-prepare). Keeps this script's behavior aligned with the live
    app so any quirks reproduce here instead of in prod."""
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        prepare_threshold=None,
    )


def _ensure_schema_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _applied_set(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {r["filename"] for r in cur.fetchall()}


def _pending_files() -> list[Path]:
    return sorted(_MIGRATIONS_DIR.glob("*.sql"))


def _apply_one(
    conn: psycopg.Connection,
    path: Path,
    *,
    verbose: bool,
) -> float:
    """Apply one migration. Returns elapsed seconds. Raises on error
    (with the offending file name in the message)."""
    sql = path.read_text()
    if verbose:
        preview = "\n  ".join(sql.splitlines()[:8])
        print(f"  preview:\n  {preview}\n  ...")

    started = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s) "
                "ON CONFLICT (filename) DO NOTHING",
                (path.name,),
            )
    except Exception as exc:  # noqa: BLE001 — re-raise with context
        elapsed = time.monotonic() - started
        # Print FIRST so the failure is visible even if the re-raise
        # gets swallowed somewhere upstream.
        print(
            f"  ✗ FAILED {path.name} after {elapsed*1000:.0f}ms: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
    return time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "").strip(),
        help="Postgres URL. Defaults to $DATABASE_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List pending migrations without applying any.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print first lines of each migration before applying.",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(
            "ERROR: DATABASE_URL not set. Pass --database-url or export it.",
            file=sys.stderr,
        )
        return 2

    print(f"migrations dir : {_MIGRATIONS_DIR}")
    print(f"database url   : {_redact(args.database_url)}")
    print()

    with _connect(args.database_url) as conn:
        _ensure_schema_migrations_table(conn)
        applied = _applied_set(conn)

        all_files = _pending_files()
        pending = [p for p in all_files if p.name not in applied]

        print(f"in schema_migrations  : {len(applied)} file(s)")
        for name in sorted(applied):
            print(f"  ✓ {name}")
        print()
        print(f"pending application   : {len(pending)} file(s)")
        for p in pending:
            print(f"  · {p.name}")
        print()

        if not pending:
            print("nothing to do — all migrations already applied.")
            return 0

        if args.dry_run:
            print("--dry-run: not applying. Re-run without --dry-run to apply.")
            return 0

        # Apply in lexical order.
        total_started = time.monotonic()
        for path in pending:
            print(f"applying {path.name} ...")
            elapsed = _apply_one(conn, path, verbose=args.verbose)
            print(f"  ✓ applied {path.name} in {elapsed*1000:.0f}ms")
        total_elapsed = time.monotonic() - total_started
        print()
        print(
            f"done. {len(pending)} migration(s) applied in "
            f"{total_elapsed*1000:.0f}ms total."
        )

    return 0


def _redact(url: str) -> str:
    """Hide the password in a Postgres URL for safe stdout printing."""
    import re

    # Match `postgresql://user:PASSWORD@host` and replace PASSWORD with `***`.
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


if __name__ == "__main__":
    sys.exit(main())
