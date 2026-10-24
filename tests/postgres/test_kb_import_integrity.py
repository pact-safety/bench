"""KB transaction gates against an explicit disposable loopback PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import pytest

from app.db import PooledConnection
from app.repositories.kb_repository import KbRepository
from app.services import kb_ingest

pytestmark = pytest.mark.integration


@pytest.fixture
def repo():
    dsn = os.environ.get("E2E_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Set E2E_DATABASE_URL to disposable local Postgres; DATABASE_URL is never used")
    parsed = urlsplit(dsn)
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.query):
        pytest.fail("E2E_DATABASE_URL must be loopback PostgreSQL without connection overrides")
    schema = "kb_import_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        pool = None
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            admin.execute("""
                CREATE TABLE kb_documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID,
                    source_url TEXT UNIQUE NOT NULL, source_kind TEXT NOT NULL,
                    title TEXT NOT NULL, content_md TEXT NOT NULL,
                    content_hash TEXT NOT NULL, ingested_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            admin.execute("""
                CREATE TABLE kb_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES kb_documents(id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL, section_path TEXT, content TEXT NOT NULL,
                    token_count INT,
                    CONSTRAINT injected_chunk_failure CHECK (content <> 'REJECT_THIS_CHUNK')
                )
            """)
            pool = ConnectionPool(dsn, min_size=2, max_size=4, kwargs={
                "autocommit": True, "row_factory": dict_row,
                "options": f"-c search_path={schema} -c statement_timeout=10000",
            })
            pool.wait(timeout=10)
            yield KbRepository(PooledConnection(pool))
        finally:
            if pool is not None:
                pool.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def snapshot(repo):
    with repo.conn.cursor() as cur:
        cur.execute("SELECT * FROM kb_documents ORDER BY source_url")
        docs = cur.fetchall()
        cur.execute("SELECT * FROM kb_chunks ORDER BY document_id, chunk_index")
        return docs, cur.fetchall()


def upsert(repo, owner, source, body, *, title="Note"):
    return repo.upsert_document(
        user_id=owner, source_url=source, title=title, content_md=body,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        chunks=kb_ingest.chunk_markdown(body),
    )


def test_failed_chunk_replacement_keeps_old_document_and_retry_succeeds(repo):
    owner = str(uuid4())
    source = kb_ingest.vault_source_url(owner, "note.md")
    doc_id, changed = upsert(repo, owner, source, "# Original\nStored old text")
    assert changed
    before = snapshot(repo)
    with pytest.raises(psycopg.errors.CheckViolation):
        upsert(repo, owner, source,
               "# New\nFirst replacement chunk\n\n# Failure\nREJECT_THIS_CHUNK", title="Changed")
    # Including IDs and timestamps detects a delete/reinsert disguised as rollback.
    assert snapshot(repo) == before
    assert upsert(repo, owner, source, "# New\nSuccessful replacement", title="Changed") == (doc_id, True)
    docs, chunks = snapshot(repo)
    assert docs[0]["content_md"] == "# New\nSuccessful replacement"
    assert docs[0]["title"] == "Changed"
    assert [chunk["content"] for chunk in chunks] == ["Successful replacement"]


def test_failed_new_note_rolls_back_and_does_not_poison_next_note(repo):
    owner = str(uuid4())
    # Imports now apply smaller byte deltas first. Keep the good note larger
    # so it still exercises a successful savepoint after the failed note.
    good_body = "Surviving note. " * 12
    result = kb_ingest.ingest_entries(repo, owner, [
        ("bad.md", b"# First\nWritten before failure\n# Second\nREJECT_THIS_CHUNK"),
        ("good.md", good_body.encode()),
    ])
    assert result.docs_ingested == 1
    assert len(result.errors) == 1
    docs, chunks = snapshot(repo)
    assert [doc["source_url"] for doc in docs] == [kb_ingest.vault_source_url(owner, "good.md")]
    assert [chunk["content"] for chunk in chunks] == [good_body.strip()]


@pytest.mark.parametrize("damage", ["missing", "partial", "wrong_content"])
def test_same_hash_retry_repairs_historical_incomplete_chunks(repo, damage):
    owner = str(uuid4())
    body = "# One\nFirst section\n# Two\nSecond section"
    source = kb_ingest.vault_source_url(owner, "note.md")
    doc_id, _ = upsert(repo, owner, source, body, title="note")
    # Simulate the old autocommit implementation having persisted its hash
    # before a chunk write failed, including equal-count stale content.
    with repo.conn.cursor() as cur:
        if damage == "missing":
            cur.execute("DELETE FROM kb_chunks WHERE document_id = %s", (doc_id,))
        elif damage == "partial":
            cur.execute("DELETE FROM kb_chunks WHERE document_id = %s AND chunk_index = 1", (doc_id,))
        else:
            cur.execute("UPDATE kb_chunks SET content = 'stale' WHERE document_id = %s", (doc_id,))
    result = kb_ingest.ingest_entries(repo, owner, [("note.md", body.encode())])
    assert not result.errors
    assert result.docs_ingested == 1
    assert result.docs_unchanged == 0
    docs, chunks = snapshot(repo)
    assert str(docs[0]["id"]) == doc_id
    assert [(c["chunk_index"], c["section_path"], c["content"], c["token_count"])
            for c in chunks] == kb_ingest.chunk_markdown(body)
    repaired = snapshot(repo)
    repeated = kb_ingest.ingest_entries(repo, owner, [("note.md", body.encode())])
    assert repeated.docs_unchanged == 1
    assert snapshot(repo) == repaired


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("same_hash", [False, True])
def test_upsert_refuses_foreign_and_shared_documents(repo, shared, same_hash):
    owner, outsider = str(uuid4()), str(uuid4())
    source = kb_ingest.vault_source_url(owner, "private.md")
    doc_id, _ = upsert(repo, owner, source, "Private original")
    if shared:
        with repo.conn.cursor() as cur:
            cur.execute("UPDATE kb_documents SET user_id = NULL WHERE id = %s", (doc_id,))
    before = snapshot(repo)
    with pytest.raises(PermissionError):
        upsert(repo, outsider, source, "Private original" if same_hash else "Overwrite", title="Stolen")
    assert snapshot(repo) == before
    assert repo.delete_document(outsider, doc_id) is False
    assert repo.list_for_user(outsider) == []
    assert snapshot(repo) == before


@pytest.mark.parametrize("quota", ["documents", "bytes"])
def test_concurrent_same_user_imports_cannot_both_spend_remaining_quota(repo, monkeypatch, quota):
    owner = str(uuid4())
    monkeypatch.setattr(kb_ingest, "MAX_DOCS", 1 if quota == "documents" else 10)
    monkeypatch.setattr(kb_ingest, "MAX_TOTAL_MB", 1)
    # Each byte-case note fits by itself, but together their UTF-8 bytes
    # exceed the cap while their character counts remain below it.
    body = ("é" * 300_000).encode() if quota == "bytes" else b"A short note"
    with repo.conn.cursor() as cur:
        # Hold the first write open after its quota read. Without the owner
        # transaction lock the second reader sees spare capacity too.
        cur.execute("""
            CREATE FUNCTION delay_kb_insert() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_sleep(0.2); RETURN NEW; END $$
        """)
        cur.execute("""
            CREATE TRIGGER delay_kb_insert BEFORE INSERT ON kb_documents
            FOR EACH ROW EXECUTE FUNCTION delay_kb_insert()
        """)
    barrier = Barrier(2)

    def ingest(index):
        barrier.wait(timeout=5)
        try:
            return kb_ingest.ingest_entries(repo, owner, [(f"note-{index}.md", body)])
        except kb_ingest.VaultImportError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(ingest, range(2)))
    refused = [result for result in results if isinstance(result, kb_ingest.VaultImportError)]
    accepted = [result for result in results if isinstance(result, kb_ingest.IngestResult)]
    assert len(refused) == len(accepted) == 1
    assert "quota" in str(refused[0]).lower()
    assert accepted[0].docs_ingested == 1
    assert not accepted[0].errors
    docs, chunks = snapshot(repo)
    assert len(docs) == len(chunks) == 1
    assert repo.totals_for_user(owner) == (1, len(body))
    # A different owner has an independent quota, even with the same path.
    other = kb_ingest.ingest_entries(repo, str(uuid4()), [("note-0.md", body)])
    assert other.docs_ingested == 1
    assert not other.errors
