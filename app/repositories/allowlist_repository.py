"""Repository for `allowlist_entries` — the DB-backed sign-in allowlist.

Approving an access request (or adding an email directly) in the admin
UI writes here; `app/services/access.py` unions these emails with the
env-var allowlist at session-check time, so a grant takes effect
without a deploy. Rows are soft-revoked (`revoked_at`) so grant
history stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from ._pg import naive_utc


@dataclass(frozen=True)
class AllowlistEntry:
    id: int
    email: str
    note: str | None
    added_by: str | None
    access_request_id: int | None
    created_at: datetime | None
    revoked_at: datetime | None


def _row_to_entry(r: dict) -> AllowlistEntry:
    return AllowlistEntry(
        id=r["id"],
        email=r["email"],
        note=r["note"],
        added_by=str(r["added_by"]) if r["added_by"] else None,
        access_request_id=r["access_request_id"],
        created_at=naive_utc(r["created_at"]),
        revoked_at=naive_utc(r["revoked_at"]),
    )


class AllowlistRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def grant(
        self,
        email: str,
        *,
        added_by: str | None = None,
        access_request_id: int | None = None,
        note: str | None = None,
    ) -> None:
        # Upsert so re-granting a previously revoked email reactivates
        # the same row instead of tripping the UNIQUE constraint.
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO allowlist_entries (email, note, added_by, access_request_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                   SET revoked_at = NULL,
                       note = COALESCE(EXCLUDED.note, allowlist_entries.note),
                       added_by = COALESCE(EXCLUDED.added_by, allowlist_entries.added_by),
                       access_request_id = COALESCE(
                           EXCLUDED.access_request_id,
                           allowlist_entries.access_request_id
                       )
                """,
                (email.strip().lower(), note, added_by, access_request_id),
            )
        self.conn.commit()

    def revoke(self, email: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE allowlist_entries
                   SET revoked_at = NOW()
                 WHERE email = %s AND revoked_at IS NULL
                """,
                (email.strip().lower(),),
            )
        self.conn.commit()

    def active_emails(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT email FROM allowlist_entries WHERE revoked_at IS NULL"
            )
            return {r["email"] for r in cur.fetchall()}

    def list_active(self, limit: int = 500) -> list[AllowlistEntry]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM allowlist_entries
                 WHERE revoked_at IS NULL
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (limit,),
            )
            return [_row_to_entry(r) for r in cur.fetchall()]
