"""Initialize the Postgres schema in your Supabase project.

Reads `DATABASE_URL` from .env.local, connects via psycopg, and runs
the consolidated DDL in `migrations_pg/001_consolidated.sql`. Idempotent
— every `CREATE TABLE` is `IF NOT EXISTS`, trigger functions use
`CREATE OR REPLACE`, and `DROP TRIGGER IF EXISTS` precedes the
trigger recreate.

Usage:

    .venv/bin/python scripts/init_supabase_schema.py

Verifies connectivity, runs the migration, then prints a summary of
how many tables now exist in the `public` schema.

Safety notes:
- Requires CITEXT extension. Supabase has it preinstalled but we
  CREATE EXTENSION IF NOT EXISTS to be explicit.
- The auth.users trigger is owned by `postgres` (SECURITY DEFINER)
  so it can write to public.users on signup events. Supabase's
  default role permissions support this.
- Does NOT touch the existing SQLite DB. Phase 2 handles export.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_env() -> None:
    """Load `.env.local` so DATABASE_URL is available without
    sourcing a shell. Mirrors app/env.py's loader logic."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.env import load_dotenv
    load_dotenv()


def _connect():
    """Connect to Postgres via DATABASE_URL. Surfaces clear errors
    for the two most common failure shapes:
      1. Empty env var
      2. Value isn't a Postgres URI (e.g. user pasted the bare project
         ref instead of the full connection string)
    psycopg's own error for #2 is `missing "=" after ... in connection
    info string`, which is technically correct but unhelpful."""
    import psycopg
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL not set in .env.local.", file=sys.stderr)
        print(
            "Get it from Supabase → Project Settings → Database → "
            "Connection string → URI tab → Session pooler mode.",
            file=sys.stderr,
        )
        sys.exit(2)
    if not (url.startswith("postgresql://") or url.startswith("postgres://")):
        print("ERROR: DATABASE_URL doesn't look like a Postgres URL.", file=sys.stderr)
        print(f"  Got: {url[:60]}{'…' if len(url) > 60 else ''}", file=sys.stderr)
        print(
            "  Expected: postgresql://postgres.<project-ref>:<password>@"
            "<region>.pooler.supabase.com:5432/postgres",
            file=sys.stderr,
        )
        print(
            "  Likely fix: in Supabase → Project Settings → Database → "
            "Connection string, click the URI tab, pick 'Session pooler' "
            "mode, copy the entire string, and substitute [YOUR-PASSWORD] "
            "with the DB password you set on project creation.",
            file=sys.stderr,
        )
        sys.exit(2)
    if "[YOUR-PASSWORD]" in url or "<password>" in url.lower():
        print(
            "ERROR: DATABASE_URL still contains a placeholder password.\n"
            "  Substitute [YOUR-PASSWORD] with the actual DB password from "
            "Supabase → Project Settings → Database → Database password.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return psycopg.connect(url, autocommit=True)
    except psycopg.OperationalError as e:
        msg = str(e)
        print(f"ERROR: couldn't connect to Postgres: {msg}", file=sys.stderr)
        if "password authentication failed" in msg.lower():
            print(
                "  → The password in DATABASE_URL is wrong. Reset it in "
                "Supabase → Project Settings → Database → Database password.",
                file=sys.stderr,
            )
        elif "could not translate host name" in msg.lower() or "name or service not known" in msg.lower():
            print(
                "  → The hostname in DATABASE_URL doesn't resolve. Check "
                "the region and that you copied the 'Session pooler' URI.",
                file=sys.stderr,
            )
        sys.exit(3)


def main() -> int:
    _load_env()
    wipe = "--wipe" in sys.argv[1:]

    repo_root = Path(__file__).resolve().parent.parent
    migrations_dir = repo_root / "migrations_pg"
    migration_paths = sorted(migrations_dir.glob("*.sql"))
    if not migration_paths:
        print(f"ERROR: no migrations found in {migrations_dir}", file=sys.stderr)
        return 1

    print(f"[init] Connecting to Postgres…")
    conn = _connect()
    print(f"[init] Connected.")

    with conn.cursor() as cur:
        if wipe:
            # Phase 1 recovery path. Drops everything in `public` so
            # we can re-init cleanly. Refuses if any non-test user row
            # has data — guards against accidentally wiping real
            # progress once we're past Phase 2.
            try:
                cur.execute("SELECT COUNT(*) FROM public.users WHERE NOT is_test")
                real_user_count = cur.fetchone()[0]
            except Exception:
                # Table doesn't exist (fresh project) — safe to wipe.
                real_user_count = 0
            if real_user_count > 0:
                print(
                    f"ERROR: --wipe blocked: public.users has "
                    f"{real_user_count} non-test row(s). Manual "
                    "intervention required if you really mean it.",
                    file=sys.stderr,
                )
                return 4
            print("[init] --wipe: dropping public schema…")
            cur.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            # Restore Supabase's default grants on the schema so the
            # PostgREST API / Auth / etc. can still read.
            cur.execute(
                "GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;"
            )
            cur.execute(
                "GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;"
            )
            cur.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT ALL ON TABLES TO postgres, anon, authenticated, service_role;"
            )
            print("[init] --wipe: done.")

        # CITEXT extension MUST be created after a wipe (DROP SCHEMA
        # public CASCADE drops extensions installed in that schema).
        # IF NOT EXISTS is no-op on a fresh project where it was never
        # there, and re-install after a wipe. Used by users.email.
        cur.execute("CREATE EXTENSION IF NOT EXISTS citext;")

        print(f"[init] Running {len(migration_paths)} migration(s)…")
        for path in migration_paths:
            print(f"[init]   → {path.name}")
            cur.execute(path.read_text())
    print("[init] Migrations ran.")

    # Summary: count tables in `public` so we can verify everything
    # we expected landed.
    expected = {
        "users", "problems", "attempts", "review_state", "sessions",
        "problem_revisions", "assessment_runs", "assessment_responses",
        "content_items", "content_progress",
        "credential_runs", "credential_files", "credential_assessments",
        "attempt_reviews", "jds", "feedback", "writings", "reflections",
        "sources", "notes",
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        present = {r[0] for r in cur.fetchall()}
    missing = expected - present
    extra = present - expected
    print(f"[init] tables in public: {len(present)}/{len(expected)} expected.")
    if missing:
        print(f"[init] MISSING: {sorted(missing)}", file=sys.stderr)
    if extra:
        print(f"[init] (also present, not in expected set): {sorted(extra)}")
    if missing:
        return 1
    print("[init] OK. Phase 1 schema is live in Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
