from __future__ import annotations

import json
from datetime import datetime

import psycopg

from .. import cache
from ..models import ContentItem, ContentProgress
from ._pg import jsonb, naive_utc, uuid_str


# A missing requester deliberately sees authored material only. Keep this
# predicate on SQL reads AND writes so forgotten route checks cannot grant access.
_VISIBLE = "(ci.source_kind = 'authored' OR (ci.source_kind = 'user' AND ci.created_by_user_id = %s))"
_ACCESSIBLE_ID = f"EXISTS (SELECT 1 FROM content_items ci WHERE ci.id = %s AND {_VISIBLE})"
_PROGRESS_VISIBLE = f"EXISTS (SELECT 1 FROM content_items ci WHERE ci.id = content_progress.content_id AND {_VISIBLE})"


def _row_to_item(r: dict) -> ContentItem:
    return ContentItem(
        id=r["id"],
        slug=r["slug"],
        kind=r["kind"],
        title=r["title"],
        source=r["source"],
        url=r["url"],
        duration_min=r["duration_min"],
        axes=jsonb(r.get("axes_json")) or [],
        domain_tags=jsonb(r.get("domain_tags_json")) or [],
        prerequisites=jsonb(r.get("prerequisites_json")) or [],
        content_md=r["content_md"],
        authored_by=r["authored_by"],
        authored_date=r["authored_date"],
        version=r["version_int"],
        source_kind=r.get("source_kind") or "authored",
        created_by_user_id=uuid_str(r.get("created_by_user_id")),
    )


def _row_to_progress(r: dict) -> ContentProgress:
    return ContentProgress(
        user_id=uuid_str(r["user_id"]),
        content_id=r["content_id"],
        status=r["status"],
        # Strip tz so this matches `datetime.utcnow()` comparisons in
        # _recent_content_axes and elsewhere. Bug-fix for a 500 on
        # /today/next that surfaced when a content_progress row was
        # tz-aware while horizon was naive.
        checked_at=naive_utc(r["checked_at"]),
        notes_md=r["notes_md"],
        favorited=bool(r.get("favorited_bool", False)),
        rating_1_to_5=r.get("rating_1_to_5"),
        # Migration 011: NULL on pre-migration rows. Write path lands in
        # PR #2; reads tolerate the column being absent.
        initiative_slug=r.get("initiative_slug"),
        # Migration 017 (BEN-135): recitation schedule. jsonb comes back as a
        # dict; absent/NULL on pre-migration rows → empty schedule.
        recitation_state=r.get("recitation_state") or {},
        last_recited_at=naive_utc(r.get("last_recited_at")),
        # Migration 027: Ng multi-pass reading state. Absent/NULL on
        # pre-migration rows → not started.
        paper_state=r.get("paper_state") or {},
    )


class ContentRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def hashes_by_slug(self) -> dict[str, str]:
        """{slug: content_hash} for every row, in one round-trip. Used
        by the startup loader to skip unchanged content."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT slug, content_hash FROM content_items WHERE source_kind = 'authored'"
            )
            rows = cur.fetchall()
        return {r["slug"]: r["content_hash"] or "" for r in rows}

    def upsert(self, item: ContentItem, *, content_hash: str = "") -> int:
        """INSERT-or-UPDATE authored content in one round-trip via
        ON CONFLICT. The user-row protection (don't clobber rows with
        `source_kind='user'`) is encoded as a `WHERE` clause on the
        DO UPDATE — Postgres skips the update for those rows but still
        returns the existing id."""
        cols = dict(
            slug=item.slug,
            kind=item.kind,
            title=item.title,
            source=item.source,
            url=item.url,
            duration_min=item.duration_min,
            axes_json=json.dumps(item.axes),
            domain_tags_json=json.dumps(item.domain_tags),
            prerequisites_json=json.dumps(item.prerequisites),
            content_md=item.content_md,
            authored_by=item.authored_by,
            authored_date=item.authored_date,
            version_int=item.version,
            source_kind="authored",
            content_hash=content_hash,
        )
        col_names = list(cols.keys())
        placeholders = ",".join(["%s"] * len(cols))
        update_clause = ",".join(f"{c} = EXCLUDED.{c}" for c in col_names if c != "slug")
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO content_items ({','.join(col_names)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (slug) DO UPDATE SET {update_clause} "
                f"  WHERE content_items.source_kind = 'authored' "
                f"RETURNING id",
                tuple(cols.values()),
            )
            row = cur.fetchone()
            if row is not None:
                new_id = row["id"]
            else:
                # WHERE excluded the update (user-row protection); fetch the
                # existing id without doing another upsert.
                cur.execute(
                    "SELECT id FROM content_items WHERE slug = %s", (item.slug,)
                )
                new_id = cur.fetchone()["id"]
        self.conn.commit()
        # Drop the by-kind / by-kinds cache buckets so the next read
        # picks up the new shape. Cheap (just dict ops).
        cache.invalidate_prefix("content_items:")
        return new_id

    def insert_user_item(
        self,
        *,
        user_id: str,
        slug: str,
        kind: str,
        title: str,
        source: str | None,
        url: str | None,
        duration_min: int | None,
        axes: list[str],
        notes_md: str | None,
    ) -> int:
        """Insert a user-pasted content row (DeepLearning.ai, BlueDot, etc.).
        Unique slug enforced by the schema; caller is responsible for
        producing a slug that won't collide (the route slugifies the
        title + a short suffix)."""
        cols = dict(
            slug=slug,
            kind=kind,
            title=title,
            source=source,
            url=url,
            duration_min=duration_min,
            axes_json=json.dumps(axes),
            prerequisites_json=json.dumps([]),
            content_md=notes_md,
            authored_by=None,
            authored_date=None,
            version_int=1,
            source_kind="user",
            created_by_user_id=user_id,
        )
        placeholders = ",".join(["%s"] * len(cols))
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO content_items ({','.join(cols.keys())}) "
                f"VALUES ({placeholders}) RETURNING id",
                tuple(cols.values()),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        cache.invalidate_prefix("content_items:")
        return new_id

    def slug_exists(self, slug: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM content_items WHERE slug = %s LIMIT 1", (slug,)
            )
            return cur.fetchone() is not None

    def all_by_kind(self, kind: str, user_id: str | None = None) -> list[ContentItem]:
        # Cached. content_items changes on author-upsert (startup
        # only) and user-add (/library/add); both invalidate.
        def _load():
            with self.conn.cursor() as cur:
                cur.execute(
                    f"SELECT ci.* FROM content_items ci WHERE kind = %s AND {_VISIBLE} ORDER BY id",
                    (kind, user_id),
                )
                rows = cur.fetchall()
            return [_row_to_item(r) for r in rows]
        return cache.get(f"content_items:by_kind:{user_id}:{kind}", loader=_load)

    def all_by_kinds(self, kinds: list[str], user_id: str | None = None) -> dict[str, list[ContentItem]]:
        """One round-trip for several kinds. The home route uses all
        four (reading/video/podcast/exercise); doing them in a single
        query saves ~600ms over the network. Cached — combined key
        covers any kind-tuple the caller might pass."""
        if not kinds:
            return {}
        key = f"content_items:by_kinds:{user_id}:" + ",".join(sorted(kinds))
        def _load():
            placeholders = ",".join(["%s"] * len(kinds))
            with self.conn.cursor() as cur:
                cur.execute(
                    f"SELECT ci.* FROM content_items ci WHERE kind IN ({placeholders}) AND {_VISIBLE} ORDER BY id",
                    (*kinds, user_id),
                )
                rows = cur.fetchall()
            out: dict[str, list[ContentItem]] = {k: [] for k in kinds}
            for r in rows:
                item = _row_to_item(r)
                out.setdefault(item.kind, []).append(item)
            return out
        return cache.get(key, loader=_load)

    def get_by_slug(self, slug: str, user_id: str | None = None) -> ContentItem | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT ci.* FROM content_items ci WHERE slug = %s AND {_VISIBLE}",
                (slug, user_id),
            )
            r = cur.fetchone()
        return _row_to_item(r) if r else None

    def get_by_id(self, content_id: int, user_id: str | None = None) -> ContentItem | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT ci.* FROM content_items ci WHERE id = %s AND {_VISIBLE}",
                (content_id, user_id),
            )
            r = cur.fetchone()
        return _row_to_item(r) if r else None

    def progress_for_user(self, user_id: str) -> dict[int, ContentProgress]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM content_progress WHERE user_id = %s AND {_PROGRESS_VISIBLE}",
                (user_id, user_id),
            )
            rows = cur.fetchall()
        return {r["content_id"]: _row_to_progress(r) for r in rows}

    def list_progress_since(self, user_id: str, since: datetime) -> list[ContentProgress]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM content_progress "
                "WHERE user_id = %s "
                "AND status = 'completed' "
                "AND checked_at IS NOT NULL "
                "AND checked_at >= %s "
                f"AND {_PROGRESS_VISIBLE} "
                "ORDER BY checked_at DESC",
                (user_id, since, user_id),
            )
            rows = cur.fetchall()
        return [_row_to_progress(r) for r in rows]

    def mark_completed(
        self,
        user_id: str,
        content_id: int,
        *,
        initiative_slug: str | None = None,
    ) -> None:
        """Mark a content item completed for this user.

        Per-attempt tagging (migration 011): when `initiative_slug` is
        provided, the row's initiative_slug column is stamped on first
        completion. On subsequent re-completions (e.g., operator
        un-checks + re-checks), the slug is overwritten — fresh
        completion = fresh attribution.

        Falls back to a slug-less UPSERT if the DB doesn't have the
        column yet (migration 011 not applied), so the app survives
        a deploy-before-migrate ordering.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO content_progress
                      (user_id, content_id, status, checked_at, initiative_slug)
                    SELECT %s, %s, 'completed', NOW(), %s
                    WHERE {_ACCESSIBLE_ID}
                    ON CONFLICT (user_id, content_id) DO UPDATE SET
                        status = 'completed',
                        checked_at = EXCLUDED.checked_at,
                        initiative_slug = EXCLUDED.initiative_slug
                    """,
                    (user_id, content_id, initiative_slug, content_id, user_id),
                )
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO content_progress (user_id, content_id, status, checked_at)
                    SELECT %s, %s, 'completed', NOW()
                    WHERE {_ACCESSIBLE_ID}
                    ON CONFLICT (user_id, content_id) DO UPDATE SET
                        status = 'completed',
                        checked_at = EXCLUDED.checked_at
                    """,
                    (user_id, content_id, content_id, user_id),
                )
        self.conn.commit()

    def mark_unread(self, user_id: str, content_id: int) -> None:
        # Don't blow away favorite/rating/notes — just reset status.
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO content_progress (user_id, content_id, status, checked_at)
                SELECT %s, %s, 'unread', NULL
                WHERE {_ACCESSIBLE_ID}
                ON CONFLICT (user_id, content_id) DO UPDATE SET
                    status = 'unread',
                    checked_at = NULL
                """,
                (user_id, content_id, content_id, user_id),
            )
        self.conn.commit()

    def toggle_favorite(self, user_id: str, content_id: int) -> bool:
        """Flip favorited_bool. Returns the new value."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO content_progress (user_id, content_id, status, favorited_bool)
                SELECT %s, %s, 'unread', TRUE
                WHERE {_ACCESSIBLE_ID}
                ON CONFLICT (user_id, content_id) DO UPDATE SET
                    favorited_bool = NOT content_progress.favorited_bool
                RETURNING favorited_bool
                """,
                (user_id, content_id, content_id, user_id),
            )
            row = cur.fetchone()
        self.conn.commit()
        return bool(row["favorited_bool"]) if row else False

    def set_rating(self, user_id: str, content_id: int, rating: int | None) -> None:
        if rating is not None and not (1 <= rating <= 5):
            raise ValueError("rating must be 1..5 or None")
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO content_progress (user_id, content_id, status, rating_1_to_5)
                SELECT %s, %s, 'unread', %s
                WHERE {_ACCESSIBLE_ID}
                ON CONFLICT (user_id, content_id) DO UPDATE SET
                    rating_1_to_5 = EXCLUDED.rating_1_to_5
                """,
                (user_id, content_id, rating, content_id, user_id),
            )
        self.conn.commit()

    # --- TTS audio cache (migration 018, BEN-135) -----------------------------
    # Owner-only by construction: every read filters WHERE user_id = requester,
    # so audio for content the operator owns is never reachable by another user.

    def get_tts_chunk(self, user_id: str, cache_key: str) -> dict | None:
        """Cached audio row (mime + bytes) for (user, key), or None on miss.
        Tolerates the table being absent (migration 018 not yet applied)."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT mime, audio FROM tts_cache "
                    "WHERE user_id = %s AND cache_key = %s "
                    f"AND EXISTS (SELECT 1 FROM content_items ci WHERE ci.id = tts_cache.content_id AND {_VISIBLE})",
                    (user_id, cache_key, user_id),
                )
                r = cur.fetchone()
        except psycopg.errors.UndefinedTable:
            self.conn.rollback()
            return None
        return dict(r) if r else None

    def put_tts_chunk(
        self,
        *,
        user_id: str,
        cache_key: str,
        content_id: int,
        chunk_ix: int,
        voice: str,
        mime: str,
        audio: bytes,
    ) -> None:
        """Store one rendered chunk. First-writer-wins on the (user, key) PK."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO tts_cache
                      (user_id, cache_key, content_id, chunk_ix, voice, mime, audio)
                    SELECT %s, %s, %s, %s, %s, %s, %s
                    WHERE {_ACCESSIBLE_ID}
                    ON CONFLICT (user_id, cache_key) DO NOTHING
                    """,
                    (user_id, cache_key, content_id, chunk_ix, voice, mime, audio, content_id, user_id),
                )
            self.conn.commit()
        except psycopg.errors.UndefinedTable:
            self.conn.rollback()

    def save_reflection(self, user_id: str, content_id: int, notes_md: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO content_progress (user_id, content_id, status, notes_md)
                SELECT %s, %s, 'unread', %s
                WHERE {_ACCESSIBLE_ID}
                ON CONFLICT (user_id, content_id) DO UPDATE SET
                    notes_md = EXCLUDED.notes_md
                """,
                (user_id, content_id, notes_md.strip() or None, content_id, user_id),
            )
        self.conn.commit()

    def save_recitation_state(
        self, user_id: str, content_id: int, state: dict
    ) -> None:
        """Persist the per-concept recitation schedule (migration 017).

        Upserts the whole recitation_state map for one (user, content) and
        stamps last_recited_at. New rows land as 'in_progress' (reciting is
        engaging with the material); existing rows keep their status.

        Degrades gracefully if migration 017 isn't applied yet (deploy-before-
        migrate) — the read path already tolerates the absent column, so the
        loop just doesn't persist a schedule rather than 500ing.
        """
        payload = json.dumps(state or {})
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO content_progress
                      (user_id, content_id, status, recitation_state, last_recited_at)
                    SELECT %s, %s, 'in_progress', %s, NOW()
                    WHERE {_ACCESSIBLE_ID}
                    ON CONFLICT (user_id, content_id) DO UPDATE SET
                        recitation_state = EXCLUDED.recitation_state,
                        last_recited_at = EXCLUDED.last_recited_at
                    """,
                    (user_id, content_id, payload, content_id, user_id),
                )
            self.conn.commit()
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()

    def save_paper_state(self, user_id: str, content_id: int, state: dict) -> None:
        """Persist the multi-pass reading state (migration 027).

        Same shape and same deploy-before-migrate tolerance as
        save_recitation_state: if 027 has not landed yet the loop simply
        does not persist rather than 500ing mid-read.
        """
        payload = json.dumps(state or {})
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO content_progress
                      (user_id, content_id, status, paper_state)
                    SELECT %s, %s, 'in_progress', %s
                    WHERE {_ACCESSIBLE_ID}
                    ON CONFLICT (user_id, content_id) DO UPDATE SET
                        paper_state = EXCLUDED.paper_state
                    """,
                    (user_id, content_id, payload, content_id, user_id),
                )
            self.conn.commit()
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()

    def favorites_for_user(self, user_id: str) -> list[ContentProgress]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM content_progress WHERE user_id = %s "
                f"AND favorited_bool = TRUE AND {_PROGRESS_VISIBLE} ORDER BY content_id",
                (user_id, user_id),
            )
            rows = cur.fetchall()
        return [_row_to_progress(r) for r in rows]

    def axis_ratings_for_user(self, user_id: str) -> dict[str, float]:
        """Per-axis average rating across all completed, rated content the
        user has consumed. Used by the daily picker to bias selection
        toward axes the user is signaling they get value from.

        SQL-side join: pull (rating, axes_json) per progress row, then
        compute mean per axis Python-side because axes are JSON-encoded.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ci.axes_json AS axes_json, cp.rating_1_to_5 AS r
                  FROM content_progress cp
                  JOIN content_items ci ON ci.id = cp.content_id
                 WHERE cp.user_id = %s
                   AND cp.rating_1_to_5 IS NOT NULL
                   AND {_VISIBLE}
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()
        sums: dict[str, list[int]] = {}
        for row in rows:
            axes = jsonb(row["axes_json"]) or []
            if not isinstance(axes, list):
                continue
            for a in axes:
                sums.setdefault(a, []).append(int(row["r"]))
        return {a: sum(vs) / len(vs) for a, vs in sums.items() if vs}
