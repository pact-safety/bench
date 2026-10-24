"""Repository for `access_requests` — visitors asking the operator
to be added to the allowlist (LIS-280 single-tenant story).

Public flow writes rows via `insert`; admin triage reads by status and
stamps a decision via `set_status`. Since Bench v2 the grant itself is
in-band: the admin route pairs `set_status` with an
`allowlist_repository` grant/revoke, so approval takes effect without
a deploy (env vars remain the bootstrap/back-door)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

from ._pg import naive_utc


@dataclass(frozen=True)
class AccessRequest:
    id: int
    name: str
    email: str
    github_handle: str | None
    note: str | None
    ip: str | None
    user_agent: str | None
    status: str
    created_at: datetime | None
    processed_at: datetime | None
    processed_note: str | None


def _row_to_req(r: dict) -> AccessRequest:
    return AccessRequest(
        id=r["id"],
        name=r["name"],
        email=r["email"],
        github_handle=r["github_handle"],
        note=r["note"],
        ip=r["ip"],
        user_agent=r["user_agent"],
        status=r["status"],
        created_at=naive_utc(r["created_at"]),
        processed_at=naive_utc(r["processed_at"]),
        processed_note=r["processed_note"],
    )


class AccessRequestRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        name: str,
        email: str,
        github_handle: str | None,
        note: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO access_requests
                    (name, email, github_handle, note, ip, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, email, github_handle, note, ip, user_agent),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def get(self, req_id: int) -> AccessRequest | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM access_requests WHERE id = %s", (req_id,))
            row = cur.fetchone()
        return _row_to_req(row) if row else None

    def has_recent_pending(self, email: str, within: timedelta = timedelta(minutes=5)) -> bool:
        """Soft dedupe: is there already a pending request from this
        email in the last `within`? Used to make the public form
        idempotent against accidental double-submits and to soften
        the rate-limit error message."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM access_requests
                WHERE lower(email) = lower(%s)
                  AND status = 'pending'
                  AND created_at >= NOW() - %s::interval
                LIMIT 1
                """,
                (email, f"{int(within.total_seconds())} seconds"),
            )
            return cur.fetchone() is not None

    def list_recent(
        self,
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> list[AccessRequest]:
        with self.conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    SELECT * FROM access_requests
                     WHERE status = %s
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    (status, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM access_requests
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return [_row_to_req(r) for r in cur.fetchall()]

    def counts_by_status(self) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS n FROM access_requests GROUP BY status"
            )
            rows = cur.fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        return {
            "pending": by_status.get("pending", 0),
            "granted": by_status.get("granted", 0),
            "declined": by_status.get("declined", 0),
        }

    def set_status(
        self,
        req_id: int,
        status: str,
        processed_note: str | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE access_requests
                   SET status = %s,
                       processed_at = NOW(),
                       processed_note = COALESCE(%s, processed_note)
                 WHERE id = %s
                """,
                (status, processed_note, req_id),
            )
        self.conn.commit()
