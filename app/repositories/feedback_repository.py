from __future__ import annotations

import re

import psycopg

from ..models import Feedback
from ._pg import naive_utc, uuid_str


def _row_to_feedback(r: dict) -> Feedback:
    return Feedback(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        url=r["url"],
        page_title=r["page_title"],
        theme=r["theme"],
        viewport_width=r["viewport_width"],
        body=r["body"],
        status=r["status"],
        created_at=naive_utc(r["created_at"]),
        processed_at=naive_utc(r["processed_at"]),
        processing_notes=r["processing_notes"],
        # GH-promotion fields (LIS-301). Migration 004 adds the columns;
        # rows from before that migration return None via .get().
        gh_issue_url=r.get("gh_issue_url"),
        gh_issue_number=r.get("gh_issue_number"),
        promoted_at=naive_utc(r.get("promoted_at")),
        promoted_by=uuid_str(r["promoted_by"]) if r.get("promoted_by") else None,
    )


class FeedbackRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        user_id: str,
        url: str,
        body: str,
        page_title: str | None = None,
        theme: str | None = None,
        viewport_width: int | None = None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback (user_id, url, page_title, theme, viewport_width, body)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, url, page_title, theme, viewport_width, body),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def request_track(self, user_id: str, slug: str, title: str) -> int:
        """Save one curriculum-access request per owner and slug, in any status."""
        if (not isinstance(slug, str) or len(slug) > 100
                or not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", slug)):
            raise ValueError("Invalid track slug.")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Invalid track title.")
        url = f"/tracks/{slug}#request-track"
        body = f"Track access request: {slug}"
        with self.conn.transaction(), self.conn.cursor() as cur:
            # A first request has no feedback row to lock. Serializing on the
            # owner also prevents concurrent tabs from creating duplicates.
            cur.execute("SELECT id FROM public.users WHERE id = %s FOR UPDATE", (user_id,))
            if cur.fetchone() is None:
                raise ValueError("Request user does not exist.")
            cur.execute("SELECT id FROM feedback WHERE user_id = %s AND url = %s AND body = %s "
                        "ORDER BY id LIMIT 1", (user_id, url, body))
            existing = cur.fetchone()
            if existing is not None:
                return existing["id"]
            cur.execute("INSERT INTO feedback (user_id, url, page_title, body) "
                        "VALUES (%s, %s, %s, %s) RETURNING id", (user_id, url, title.strip(), body))
            return cur.fetchone()["id"]

    def get(self, fb_id: int) -> Feedback | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM feedback WHERE id = %s", (fb_id,))
            r = cur.fetchone()
        return _row_to_feedback(r) if r else None

    def list_for_user(
        self, user_id: str, status: str | None = None, limit: int = 200
    ) -> list[Feedback]:
        with self.conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM feedback WHERE user_id = %s AND status = %s "
                    "ORDER BY id DESC LIMIT %s",
                    (user_id, status, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM feedback WHERE user_id = %s "
                    "ORDER BY id DESC LIMIT %s",
                    (user_id, limit),
                )
            rows = cur.fetchall()
        return [_row_to_feedback(r) for r in rows]

    def set_status(
        self, fb_id: int, status: str, processing_notes: str | None = None
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE feedback
                   SET status = %s,
                       processed_at = NOW(),
                       processing_notes = COALESCE(%s, processing_notes)
                 WHERE id = %s
                """,
                (status, processing_notes, fb_id),
            )
        self.conn.commit()

    # ---------- LIS-301: GitHub Issues promotion --------------------------

    def list_all(self, status: str | None = None, limit: int = 200) -> list[Feedback]:
        """Admin-only: list feedback from EVERY user. The standard
        `list_for_user` scopes to one user (good for users seeing their
        own); this lets the operator see what alpha/beta visitors are
        submitting."""
        with self.conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM feedback WHERE status = %s "
                    "ORDER BY id DESC LIMIT %s",
                    (status, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM feedback ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        return [_row_to_feedback(r) for r in rows]

    def list_all_closed(self, limit: int = 100) -> list[Feedback]:
        """Admin-only "closed" tab: union of archived + dismissed across
        every user. Mirrors the per-user `closed` bucket in main.py."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM feedback
                 WHERE status IN ('archived','dismissed')
                 ORDER BY COALESCE(processed_at, created_at) DESC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [_row_to_feedback(r) for r in rows]

    def counts_all(self) -> dict[str, int]:
        """Admin-view counts: total by status across all users."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS n FROM feedback GROUP BY status"
            )
            rows = cur.fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        return {
            "open": by_status.get("open", 0),
            "backlog": by_status.get("backlog", 0),
            "closed": by_status.get("archived", 0) + by_status.get("dismissed", 0),
        }

    def claim_promotion(self, *, fb_id: int, promoted_by: str) -> bool:
        # Commit before contacting GitHub: a crash or ambiguous response must
        # leave a durable claim that prevents another issue-create attempt.
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE feedback SET promoted_at = NOW(), promoted_by = %s
                     WHERE id = %s AND gh_issue_url IS NULL
                       AND gh_issue_number IS NULL AND promoted_at IS NULL
                    RETURNING id
                    """,
                    (promoted_by, fb_id),
                )
                claimed = cur.fetchone() is not None
        return claimed

    def mark_promoted(
        self,
        fb_id: int,
        gh_issue_url: str,
        gh_issue_number: int,
        promoted_by: str,
    ) -> bool:
        """Finalize a claimed promotion without replacing an existing link."""
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE feedback
                       SET gh_issue_url = %s, gh_issue_number = %s,
                           promoted_by = %s
                     WHERE id = %s AND promoted_at IS NOT NULL
                       AND (gh_issue_url IS NULL OR
                            (gh_issue_url = %s AND gh_issue_number = %s))
                    RETURNING id
                    """,
                    (gh_issue_url, gh_issue_number, promoted_by, fb_id,
                     gh_issue_url, gh_issue_number),
                )
                linked = cur.fetchone() is not None
        return linked

    # ---- Image attachments (migration 015) --------------------------------

    def insert_attachment(
        self,
        *,
        feedback_id: int,
        user_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback_attachments
                    (feedback_id, user_id, filename, content_type, byte_size, bytes)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (feedback_id, user_id, filename, content_type, len(data), data),
            )
            return cur.fetchone()["id"]

    def attachments_meta(self, feedback_ids: list[int]) -> dict[int, list[dict]]:
        """Metadata only (no bytes) for rendering thumbnails/links in the
        inbox. Returns {feedback_id: [{id, filename, content_type,
        byte_size}, ...]} for every id that has attachments."""
        if not feedback_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, feedback_id, filename, content_type, byte_size
                  FROM feedback_attachments
                 WHERE feedback_id = ANY(%s)
                 ORDER BY id
                """,
                (feedback_ids,),
            )
            rows = cur.fetchall()
        out: dict[int, list[dict]] = {}
        for r in rows:
            out.setdefault(r["feedback_id"], []).append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "content_type": r["content_type"],
                    "byte_size": r["byte_size"],
                }
            )
        return out

    def get_attachment(self, attachment_id: int) -> dict | None:
        """Full row including bytes; caller does the ownership check."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM feedback_attachments WHERE id = %s",
                (attachment_id,),
            )
            r = cur.fetchone()
        return dict(r) if r else None
