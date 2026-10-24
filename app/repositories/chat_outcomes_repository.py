"""Repository for the chat_outcomes table (migration 009).

Replaces the user_settings.chat_outcomes JSON storage path used by
BEN-81 / PR #243. The cutover happens in PR A (this) — both this repo
AND the JSON path are wired during the verify window, then PR B
removes the JSON path.

API mirrors ``app/services/journal.py``'s shape so the call-site swap
is a small diff on the consumers (/decisions read, /focus last-decided
lookup, MCP log_chat_outcome write).

Indexes:
- ``(user_id, created_at DESC)`` — /decisions chronological feed
- ``(user_id, initiative_slug, created_at DESC)`` — /focus per-initiative
"""

from __future__ import annotations

from datetime import datetime

import psycopg

from ..models import ChatOutcome
from ._pg import naive_utc, uuid_str


def _row_to_chat_outcome(r: dict) -> ChatOutcome:
    return ChatOutcome(
        id=uuid_str(r["id"]),
        user_id=uuid_str(r["user_id"]),
        initiative_slug=r["initiative_slug"] or "",
        decisions=r["decisions"] or "",
        next_actions=r["next_actions"] or "",
        chat_url=r["chat_url"],
        created_at=naive_utc(r["created_at"]),
        source=r["source"] or "mcp",
    )


class ChatOutcomesRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        user_id: str,
        initiative_slug: str,
        decisions: str,
        next_actions: str,
        chat_url: str | None = None,
        source: str = "mcp",
    ) -> str:
        """Insert one chat outcome. Returns the new row's UUID.

        The check constraint on the table enforces that at least one of
        decisions/next_actions is non-empty; callers should pre-validate
        to give a cleaner error message than psycopg's IntegrityError.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_outcomes
                  (user_id, initiative_slug, decisions, next_actions, chat_url, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    initiative_slug.strip(),
                    decisions or "",
                    next_actions or "",
                    (chat_url or None),
                    source,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return uuid_str(new_id)

    def get(self, entry_id: str, *, user_id: str) -> ChatOutcome | None:
        """Single-entry lookup, user-scoped (defense-in-depth alongside
        the route's session check)."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM chat_outcomes WHERE id = %s AND user_id = %s",
                (entry_id, user_id),
            )
            row = cur.fetchone()
        return _row_to_chat_outcome(row) if row else None

    def list_for_user(
        self,
        user_id: str,
        *,
        initiative_slug: str | None = None,
        limit: int = 50,
    ) -> list[ChatOutcome]:
        """Reverse-chronological. Optional initiative filter. Capped at
        ``limit`` for unbounded-list defense."""
        safe_limit = max(1, min(int(limit), 500))
        with self.conn.cursor() as cur:
            if initiative_slug:
                cur.execute(
                    """
                    SELECT * FROM chat_outcomes
                     WHERE user_id = %s AND initiative_slug = %s
                     ORDER BY created_at DESC LIMIT %s
                    """,
                    (user_id, initiative_slug, safe_limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM chat_outcomes
                     WHERE user_id = %s
                     ORDER BY created_at DESC LIMIT %s
                    """,
                    (user_id, safe_limit),
                )
            rows = cur.fetchall()
        return [_row_to_chat_outcome(r) for r in rows]

    def initiatives_with_counts(self, user_id: str) -> list[tuple[str, int]]:
        """Return ``[(slug, count), ...]`` sorted by count desc then slug.
        Used for /decisions facet chips."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT initiative_slug, COUNT(*) AS n
                  FROM chat_outcomes
                 WHERE user_id = %s
              GROUP BY initiative_slug
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        # Sort by count desc, slug asc (tie-breaker)
        return sorted(
            ((r["initiative_slug"], int(r["n"])) for r in rows),
            key=lambda kv: (-kv[1], kv[0]),
        )

    def latest_per_initiative(self, user_id: str) -> dict[str, ChatOutcome]:
        """Return ``{slug: latest_chat_outcome}`` for /focus "last decided"
        lookup. One indexed query thanks to the per-initiative index +
        DISTINCT ON."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (initiative_slug) *
                  FROM chat_outcomes
                 WHERE user_id = %s
              ORDER BY initiative_slug, created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return {r["initiative_slug"]: _row_to_chat_outcome(r) for r in rows}

    def count_for_user(self, user_id: str) -> int:
        """Total row count for an operator. Used by /decisions header."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM chat_outcomes WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        return int(row["n"]) if row else 0
