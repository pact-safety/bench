from __future__ import annotations

import json
from datetime import datetime

import psycopg

from ..models import Writing
from ._pg import jsonb, naive_utc, uuid_str


def _row_to_writing(r: dict) -> Writing:
    return Writing(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        title=r["title"] or "",
        body_md=r["body_md"] or "",
        source_refs=jsonb(r.get("source_refs_json")) or [],
        status=r["status"],
        word_count=r["word_count"] or 0,
        created_at=naive_utc(r["created_at"]),
        updated_at=naive_utc(r["updated_at"]),
        published_at=naive_utc(r["published_at"]),
        # Migration 011: NULL on pre-migration rows.
        initiative_slug=r.get("initiative_slug"),
    )


def _word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w])


class WritingRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        user_id: str,
        title: str,
        body_md: str,
        source_refs: list[dict] | None = None,
        initiative_slug: str | None = None,
    ) -> int:
        # Layered fallback so the app survives DBs lagging on migration 011.
        try:
            return self._insert_with_initiative(
                user_id=user_id,
                title=title,
                body_md=body_md,
                source_refs=source_refs,
                initiative_slug=initiative_slug,
            )
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()
            return self._insert_legacy(
                user_id=user_id,
                title=title,
                body_md=body_md,
                source_refs=source_refs,
            )

    def _insert_with_initiative(
        self,
        *,
        user_id: str,
        title: str,
        body_md: str,
        source_refs: list[dict] | None,
        initiative_slug: str | None,
    ) -> int:
        """Migration-011 insert path: includes initiative_slug."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO writings
                  (user_id, title, body_md, source_refs_json, word_count, initiative_slug)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    title,
                    body_md,
                    json.dumps(source_refs or []),
                    _word_count(body_md),
                    initiative_slug,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def _insert_legacy(
        self,
        *,
        user_id: str,
        title: str,
        body_md: str,
        source_refs: list[dict] | None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO writings (user_id, title, body_md, source_refs_json, word_count)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    title,
                    body_md,
                    json.dumps(source_refs or []),
                    _word_count(body_md),
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def update(
        self,
        writing_id: int,
        title: str | None = None,
        body_md: str | None = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT title, body_md FROM writings WHERE id = %s",
                (writing_id,),
            )
            r = cur.fetchone()
            if r is None:
                return
            new_title = title if title is not None else r["title"]
            new_body = body_md if body_md is not None else r["body_md"]
            cur.execute(
                """
                UPDATE writings
                   SET title = %s, body_md = %s, word_count = %s, updated_at = NOW()
                 WHERE id = %s
                """,
                (new_title, new_body, _word_count(new_body), writing_id),
            )
        self.conn.commit()

    def save_with_status(
        self, writing_id: int, *, user_id: str, title: str, body_md: str, status: str,
    ) -> bool:
        # The connection autocommits: one statement keeps publishing/archiving
        # atomic with the editor contents, even if the request fails midway.
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE writings SET title = %s, body_md = %s, word_count = %s,
                    status = %s, updated_at = NOW(),
                    published_at = CASE WHEN %s = 'published'
                        THEN COALESCE(published_at, NOW()) ELSE published_at END
                WHERE id = %s AND user_id = %s
                """,
                (title, body_md, _word_count(body_md), status, status, writing_id, user_id),
            )
            saved = cur.rowcount > 0
        self.conn.commit()
        return saved

    def set_status(self, writing_id: int, status: str) -> None:
        with self.conn.cursor() as cur:
            if status == "published":
                cur.execute(
                    "UPDATE writings SET status = %s, "
                    "published_at = COALESCE(published_at, NOW()), "
                    "updated_at = NOW() WHERE id = %s",
                    (status, writing_id),
                )
            else:
                cur.execute(
                    "UPDATE writings SET status = %s, updated_at = NOW() WHERE id = %s",
                    (status, writing_id),
                )
        self.conn.commit()

    def get(self, writing_id: int) -> Writing | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM writings WHERE id = %s", (writing_id,))
            r = cur.fetchone()
        return _row_to_writing(r) if r else None

    def delete(self, writing_id: int, *, user_id: str) -> bool:
        """Permanently delete a writing row owned by ``user_id``.

        Returns True when a row was deleted, False when no matching row
        existed (caller decides 404 vs. no-op). The user_id guard in the
        WHERE clause is defense-in-depth alongside the route-level
        ownership check.

        No cascade concerns: no FKs reference ``writings``.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM writings WHERE id = %s AND user_id = %s",
                (writing_id, user_id),
            )
            deleted = cur.rowcount
        self.conn.commit()
        return deleted > 0

    def list_for_user(self, user_id: str, status: str | None = None) -> list[Writing]:
        with self.conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM writings WHERE user_id = %s AND status = %s "
                    "ORDER BY updated_at DESC",
                    (user_id, status),
                )
            else:
                cur.execute(
                    "SELECT * FROM writings WHERE user_id = %s AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (user_id,),
                )
            rows = cur.fetchall()
        return [_row_to_writing(r) for r in rows]

    def list_for_user_since(self, user_id: str, since: datetime) -> list[Writing]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM writings WHERE user_id = %s "
                "AND status != 'archived' "
                "AND updated_at >= %s "
                "ORDER BY updated_at DESC",
                (user_id, since),
            )
            rows = cur.fetchall()
        return [_row_to_writing(r) for r in rows]

    def active_draft_today(self, user_id: str) -> Writing | None:
        """Returns the most recently-updated draft modified today (UTC)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM writings
                 WHERE user_id = %s
                   AND status = 'draft'
                   AND (updated_at AT TIME ZONE 'UTC')::date = (NOW() AT TIME ZONE 'UTC')::date
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (user_id,),
            )
            r = cur.fetchone()
        return _row_to_writing(r) if r else None
