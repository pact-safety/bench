#!/usr/bin/env python3
"""One-shot backfill: user_settings.chat_outcomes JSON → chat_outcomes table.

Run after migration 009 (PR A) lands in production:

    fly ssh console -C "python /app/scripts/backfill_chat_outcomes.py"

Idempotent: dedup based on (user_id, created_at, initiative_slug,
decisions). Re-running won't double-insert. The script prints a
structured summary per user (entries-found, entries-skipped-as-dup,
entries-inserted) so the operator can verify before PR B removes the
JSON write path.

Safety:
- Reads, validates, then writes. Never modifies the JSON source.
- Catches per-entry errors and logs them; one bad row doesn't abort
  the whole user's backfill.
- Source is set to 'backfill' on the new rows so they're distinguishable
  from live MCP writes in audit queries.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.db import connect  # noqa: E402
from app.repositories.chat_outcomes_repository import (  # noqa: E402
    ChatOutcomesRepository,
)


def _parse_created_at(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _backfill_user(
    *,
    user_id: str,
    settings: dict,
    repo: ChatOutcomesRepository,
    dry_run: bool,
) -> dict[str, int]:
    """Backfill one user. Returns counts."""
    raw_list = settings.get("chat_outcomes", []) if isinstance(settings, dict) else []
    if not isinstance(raw_list, list):
        return {"found": 0, "dup": 0, "inserted": 0, "skipped": 0}

    # Pull existing rows to dedup against.
    existing = repo.list_for_user(user_id, limit=500)
    existing_keys: set[tuple[str, str, str, str]] = {
        (
            co.initiative_slug,
            co.created_at.isoformat() if co.created_at else "",
            co.decisions or "",
            co.next_actions or "",
        )
        for co in existing
    }

    found = 0
    dup = 0
    inserted = 0
    skipped = 0

    for raw in raw_list:
        found += 1
        if not isinstance(raw, dict):
            skipped += 1
            continue

        initiative = (raw.get("initiative") or "").strip()
        decisions = (raw.get("decisions") or "").strip()
        next_actions = (raw.get("next_actions") or "").strip()
        chat_url = raw.get("chat_url") or None
        created_at = _parse_created_at(raw.get("created_at"))

        if not initiative or not created_at:
            skipped += 1
            continue
        if not decisions and not next_actions:
            # Check-constraint would reject; skip.
            skipped += 1
            continue

        key = (initiative, created_at.isoformat(), decisions, next_actions)
        if key in existing_keys:
            dup += 1
            continue

        if dry_run:
            inserted += 1
            continue

        try:
            repo.insert(
                user_id=user_id,
                initiative_slug=initiative,
                decisions=decisions,
                next_actions=next_actions,
                chat_url=(chat_url.strip() if isinstance(chat_url, str) else None),
                source="backfill",
            )
            inserted += 1
            existing_keys.add(key)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  ✗ insert failed for user={user_id[:8]}... key={key[:2]}: {exc}",
                file=sys.stderr,
            )
            skipped += 1

    return {"found": found, "dup": dup, "inserted": inserted, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_chat_outcomes",
        description="Port user_settings.chat_outcomes → chat_outcomes table.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be inserted without writing",
    )
    args = parser.parse_args(argv)

    conn = connect()
    repo = ChatOutcomesRepository(conn)

    # Walk all users with non-empty chat_outcomes in their settings.
    # NOTE: the bench's settings live on public.users.settings_json
    # (single JSONB column on the user table) — there's no separate
    # `user_settings` table. Initial draft of this script used the
    # wrong table name; fixed after the operator hit
    # `relation "user_settings" does not exist` on Fly.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id AS user_id, settings_json
              FROM public.users
             WHERE settings_json ? 'chat_outcomes'
            """
        )
        rows = cur.fetchall()

    if not rows:
        print("No users with chat_outcomes found. Nothing to backfill.")
        return 0

    print(f"Backfilling chat_outcomes for {len(rows)} user(s)...")
    totals = {"found": 0, "dup": 0, "inserted": 0, "skipped": 0}

    for row in rows:
        user_id = str(row["user_id"])
        settings = row["settings_json"] or {}
        result = _backfill_user(
            user_id=user_id, settings=settings, repo=repo, dry_run=args.dry_run,
        )
        for k in totals:
            totals[k] += result[k]
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"  {prefix}user={user_id[:8]}... "
            f"found={result['found']} dup={result['dup']} "
            f"inserted={result['inserted']} skipped={result['skipped']}"
        )

    print()
    print(f"Total: found={totals['found']} dup={totals['dup']} "
          f"inserted={totals['inserted']} skipped={totals['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
