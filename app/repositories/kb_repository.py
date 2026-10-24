"""Repository for `kb_documents` / `kb_chunks` — MIRA's knowledge base,
now carrying per-user Obsidian vaults alongside the (future) shared
canon (v2.1, migration 023).

Ownership model: `user_id IS NULL` = shared canon, visible to every
user's retrieval; non-NULL = that user's private vault. Every read in
this repo scopes to `user_id = %s OR user_id IS NULL`; every mutation
requires the owning user. Vault content is user data: never surfaced
to other users, deleted with the account (kb_documents is in
_DELETE_ACCOUNT_TABLES_ORDER; chunks cascade).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import psycopg

from ._pg import naive_utc


@dataclass(frozen=True)
class KbDocument:
    id: str
    user_id: str | None
    source_url: str
    source_kind: str
    title: str
    content_hash: str
    ingested_at: datetime | None
    chunk_count: int
    content_bytes: int


@dataclass(frozen=True)
class KbSearchHit:
    chunk_id: str
    document_id: str
    document_title: str
    section_path: str | None
    content: str
    score: float


def _row_to_doc(r: dict) -> KbDocument:
    return KbDocument(
        id=str(r["id"]),
        user_id=str(r["user_id"]) if r.get("user_id") else None,
        source_url=r["source_url"],
        source_kind=r["source_kind"],
        title=r["title"],
        content_hash=r["content_hash"],
        ingested_at=naive_utc(r["ingested_at"]),
        chunk_count=int(r.get("chunk_count") or 0),
        content_bytes=int(r.get("content_bytes") or 0),
    )


class KbRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    @contextmanager
    def import_transaction(self, user_id: str):
        """Serialize one owner's quota check and import across processes."""
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"kb-import:{user_id}",),
                )
            yield

    def document_sizes_for_user(self, user_id: str) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT source_url, octet_length(content_md) AS content_bytes "
                "FROM kb_documents WHERE user_id = %s",
                (user_id,),
            )
            return {row["source_url"]: int(row["content_bytes"] or 0) for row in cur.fetchall()}

    def upsert_document(
        self,
        *,
        user_id: str,
        source_url: str,
        title: str,
        content_md: str,
        content_hash: str,
        chunks: list[tuple[int, str | None, str, int]],
        source_kind: str = "doc",
    ) -> tuple[str, bool]:
        """Atomically save a note and its chunks; return (doc_id, changed)."""
        # The hash is only a completion marker when all retrieval chunks are
        # durable. A savepoint lets the enclosing import continue on failure.
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id, content_hash, user_id, title FROM kb_documents "
                    "WHERE source_url = %s FOR UPDATE",
                    (source_url,),
                )
                row = cur.fetchone()
                if row is not None:
                    if str(row["user_id"]) != user_id:
                        raise PermissionError("document belongs to another user")
                    doc_id = str(row["id"])
                    if row["content_hash"] == content_hash and row["title"] == title:
                        cur.execute(
                            "SELECT chunk_index, section_path, content, token_count "
                            "FROM kb_chunks WHERE document_id = %s ORDER BY chunk_index",
                            (doc_id,),
                        )
                        stored = [(c["chunk_index"], c["section_path"], c["content"], c["token_count"])
                                  for c in cur.fetchall()]
                        # Older imports could leave a matching hash with zero
                        # or partial chunks. Retry repairs those rows in place.
                        if stored == chunks:
                            return doc_id, False
                    cur.execute(
                        """
                        UPDATE kb_documents
                           SET title = %s, content_md = %s, content_hash = %s,
                               ingested_at = NOW()
                         WHERE id = %s
                        """,
                        (title, content_md, content_hash, row["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO kb_documents
                            (user_id, source_url, source_kind, title, content_md, content_hash)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (user_id, source_url, source_kind, title, content_md, content_hash),
                    )
                    doc_id = str(cur.fetchone()["id"])
            self.replace_chunks(doc_id, chunks)
        return doc_id, True

    def replace_chunks(
        self,
        document_id: str,
        chunks: list[tuple[int, str | None, str, int]],
    ) -> None:
        """chunks: (chunk_index, section_path, content, token_count)."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute("DELETE FROM kb_chunks WHERE document_id = %s", (document_id,))
            cur.executemany(
                """
                INSERT INTO kb_chunks
                    (document_id, chunk_index, section_path, content, token_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [(document_id, ix, sp, content, tc) for ix, sp, content, tc in chunks],
            )

    def list_for_user(self, user_id: str, limit: int = 500) -> list[KbDocument]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.user_id, d.source_url, d.source_kind, d.title,
                       d.content_hash, d.ingested_at,
                       COUNT(c.id) AS chunk_count,
                       COALESCE(octet_length(d.content_md), 0) AS content_bytes
                  FROM kb_documents d
             LEFT JOIN kb_chunks c ON c.document_id = d.id
                 WHERE d.user_id = %s
              GROUP BY d.id
              ORDER BY d.ingested_at DESC
                 LIMIT %s
                """,
                (user_id, limit),
            )
            return [_row_to_doc(r) for r in cur.fetchall()]

    def totals_for_user(self, user_id: str) -> tuple[int, int]:
        """(doc_count, total_content_bytes) — the quota inputs."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(octet_length(content_md)), 0) AS b
                  FROM kb_documents WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        return int(row["n"]), int(row["b"])

    def delete_document(self, user_id: str, document_id: str) -> bool:
        """Owner-scoped delete; chunks cascade. Returns True if a row
        was actually removed."""
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kb_documents WHERE id = %s AND user_id = %s",
                (document_id, user_id),
            )
            deleted = cur.rowcount > 0
        self.conn.commit()
        return deleted

    def delete_all_for_user(self, user_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM kb_documents WHERE user_id = %s", (user_id,))
            n = cur.rowcount
        self.conn.commit()
        return n

    def sparse_search(
        self, user_id: str | None, query: str, k: int = 12
    ) -> list[KbSearchHit]:
        """ts_rank retrieval over the user's vault + the shared canon
        (user_id IS NULL). `user_id=None` = canon only (background
        contexts). The dense/RRF fusion in rag.hybrid_search layers on
        top of this once an embedding vendor lands."""
        q = (query or "").strip()
        if not q:
            return []
        if user_id:
            owner_clause = "(d.user_id = %s OR d.user_id IS NULL)"
            params = (q, user_id, q, k)
        else:
            owner_clause = "d.user_id IS NULL"
            params = (q, q, k)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT c.id AS chunk_id, c.document_id, c.section_path,
                       c.content, d.title AS document_title,
                       ts_rank(c.content_tsv, websearch_to_tsquery('english', %s)) AS score
                  FROM kb_chunks c
                  JOIN kb_documents d ON d.id = c.document_id
                 WHERE {owner_clause}
                   AND c.content_tsv @@ websearch_to_tsquery('english', %s)
              ORDER BY score DESC
                 LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
        return [
            KbSearchHit(
                chunk_id=str(r["chunk_id"]),
                document_id=str(r["document_id"]),
                document_title=r["document_title"],
                section_path=r["section_path"],
                content=r["content"],
                score=float(r["score"]),
            )
            for r in rows
        ]
