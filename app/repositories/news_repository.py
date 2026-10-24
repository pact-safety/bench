"""Repository for news_items + feed_health (migration 012).

Used by:
- ``app/services/news_poller.py`` for ingestion (upsert by URL,
  feed-health bookkeeping).
- ``app/main.py`` /news route for read + pin/dismiss actions.

Phase 1 keeps queries SQL-direct; per-axis filtering / "recent in your
axes" lands in Phase 2 once axes_json is populated.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg

from ..models import NewsFeedHealth, NewsItem
from ._pg import jsonb, naive_utc


def _row_to_news_item(r: dict) -> NewsItem:
    return NewsItem(
        id=r["id"],
        source=r["source"],
        title=r["title"],
        url=r["url"],
        summary=r.get("summary"),
        published_at=naive_utc(r["published_at"]),
        fetched_at=naive_utc(r["fetched_at"]),
        axes_json=jsonb(r.get("axes_json")) or [],
        is_pinned=bool(r.get("is_pinned", False)),
        is_dismissed=bool(r.get("is_dismissed", False)),
    )


def _row_to_feed_health(r: dict) -> NewsFeedHealth:
    return NewsFeedHealth(
        feed_slug=r["feed_slug"],
        last_success_at=naive_utc(r["last_success_at"]) if r["last_success_at"] else None,
        last_failure_at=naive_utc(r["last_failure_at"]) if r["last_failure_at"] else None,
        last_error_message=r.get("last_error_message"),
        consecutive_failures=int(r.get("consecutive_failures", 0)),
        last_items_seen=int(r.get("last_items_seen", 0)),
        last_items_inserted=int(r.get("last_items_inserted", 0)),
    )


class NewsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # ----- news_items -----------------------------------------------

    def insert_if_new(self, item: NewsItem) -> bool:
        """Insert one item; return True if a new row was inserted,
        False if the URL was already present (dedup hit).

        Uses ``ON CONFLICT (url) DO NOTHING`` so the dedup is atomic
        and we don't race on parallel pollers (single-tenant today;
        future-proof anyway).
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_items
                  (source, title, url, summary, published_at, fetched_at, axes_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
                RETURNING id
                """,
                (
                    item.source,
                    item.title,
                    item.url,
                    item.summary,
                    item.published_at,
                    item.fetched_at,
                    json.dumps(item.axes_json or []),
                ),
            )
            new_row = cur.fetchone()
        self.conn.commit()
        return new_row is not None

    def list_recent(
        self,
        *,
        limit: int = 100,
        source: str | None = None,
        include_dismissed: bool = False,
    ) -> list[NewsItem]:
        """Newest-first, with pinned items always on top.

        - ``source``: optional feed-slug filter
        - ``include_dismissed``: by default dismissed items are hidden
        """
        params: list[Any] = []
        where = []
        if not include_dismissed:
            where.append("is_dismissed = FALSE")
        if source:
            where.append("source = %s")
            params.append(source)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM news_items
                {clause}
                ORDER BY is_pinned DESC, published_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
        return [_row_to_news_item(r) for r in rows]

    def get(self, item_id: int) -> NewsItem | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM news_items WHERE id = %s", (item_id,))
            r = cur.fetchone()
        return _row_to_news_item(r) if r else None

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE news_items SET is_pinned = %s WHERE id = %s",
                (bool(pinned), item_id),
            )
        self.conn.commit()

    def set_dismissed(self, item_id: int, dismissed: bool) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE news_items SET is_dismissed = %s WHERE id = %s",
                (bool(dismissed), item_id),
            )
        self.conn.commit()

    def list_sources_present(self) -> list[str]:
        """Distinct source slugs that have any item — used by the
        /news filter chips so we only show sources with content."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, COUNT(*) AS n
                  FROM news_items
                 WHERE is_dismissed = FALSE
                 GROUP BY source
                 ORDER BY n DESC, source
                """
            )
            return [r["source"] for r in cur.fetchall()]

    # ----- feed_health ----------------------------------------------

    def record_feed_success(
        self,
        feed_slug: str,
        *,
        now: datetime,
        items_seen: int,
        items_inserted: int,
    ) -> None:
        """Upsert: clear failure state, record last success + counters."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feed_health
                  (feed_slug, last_success_at, last_failure_at, last_error_message,
                   consecutive_failures, last_items_seen, last_items_inserted)
                VALUES (%s, %s, NULL, NULL, 0, %s, %s)
                ON CONFLICT (feed_slug) DO UPDATE SET
                  last_success_at = EXCLUDED.last_success_at,
                  consecutive_failures = 0,
                  last_items_seen = EXCLUDED.last_items_seen,
                  last_items_inserted = EXCLUDED.last_items_inserted
                """,
                (feed_slug, now, items_seen, items_inserted),
            )
        self.conn.commit()

    def record_feed_failure(
        self,
        feed_slug: str,
        *,
        now: datetime,
        error: str,
    ) -> None:
        """Upsert: bump consecutive_failures, capture error message."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feed_health
                  (feed_slug, last_failure_at, last_error_message, consecutive_failures)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (feed_slug) DO UPDATE SET
                  last_failure_at = EXCLUDED.last_failure_at,
                  last_error_message = EXCLUDED.last_error_message,
                  consecutive_failures = feed_health.consecutive_failures + 1
                """,
                (feed_slug, now, error[:1000]),
            )
        self.conn.commit()

    def list_feed_health(self) -> list[NewsFeedHealth]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM feed_health
                 ORDER BY consecutive_failures DESC, feed_slug
                """
            )
            return [_row_to_feed_health(r) for r in cur.fetchall()]
