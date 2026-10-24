"""Bounded vault parsing and retry-safe document persistence."""

import io
import sqlite3
import zipfile
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.repositories.kb_repository import KbRepository
from app.services import kb_ingest


def _zip(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files:
            archive.writestr(path, content)
    return out.getvalue()


def _repo(sizes=None):
    repo = MagicMock()
    repo.document_sizes_for_user.return_value = sizes or {}
    repo.upsert_document.return_value = ("doc", True)
    return repo


def test_distinct_top_level_folders_keep_distinct_note_paths():
    repo = _repo()
    kb_ingest.ingest_zip(repo, "u", _zip([("A/note.md", "a"), ("B/note.md", "b")]))
    assert [c.kwargs["source_url"] for c in repo.upsert_document.call_args_list] == [
        "vault://u/A/note.md", "vault://u/B/note.md"
    ]


def test_expansion_limit_rejects_before_read_or_write(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_EXPANDED_BYTES", 10, raising=False)
    repo = _repo()
    blob = _zip([("a.md", "a"), ("b.md", "x" * 11)])
    with pytest.raises(ValueError, match="expanded"):
        kb_ingest.ingest_zip(repo, "u", blob)
    repo.upsert_document.assert_not_called()


def test_skipped_members_are_not_decompressed(monkeypatch):
    original = zipfile.ZipFile.open
    opened = []

    def tracked(self, member, *args, **kwargs):
        opened.append(member.filename)
        return original(self, member, *args, **kwargs)

    blob = _zip([("vault/a.md", "a"), ("vault/photo.png", "bytes")])
    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    kb_ingest.ingest_zip(_repo(), "u", blob)
    assert opened == ["vault/a.md"]


def test_duplicate_paths_are_rejected_before_write():
    repo = _repo()
    with pytest.warns(UserWarning):
        blob = _zip([("a.md", "a"), ("a.md", "b")])
    with pytest.raises(ValueError, match="duplicate"):
        kb_ingest.ingest_zip(repo, "u", blob)
    repo.upsert_document.assert_not_called()


def test_full_vault_allows_identical_retry_and_smaller_replacement(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_DOCS", 1)
    monkeypatch.setattr(kb_ingest, "MAX_TOTAL_MB", 1)
    repo = _repo({"vault://u/a.md": 1024 * 1024})
    result = kb_ingest.ingest_zip(repo, "u", _zip([("a.md", "x")]))
    assert result.docs_ingested == 1


def test_quota_rejects_whole_archive_using_utf8_bytes(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_TOTAL_MB", 1)
    repo = _repo({"vault://u/existing.md": 1024 * 1024 - 3})
    with pytest.raises(ValueError, match="quota"):
        kb_ingest.ingest_zip(repo, "u", _zip([("a.md", "éé")]))
    repo.upsert_document.assert_not_called()


class _TransactionalConnection:
    """Use real SQL rollback in SQLite with only dialect syntax adapted."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE kb_documents (
                id TEXT PRIMARY KEY DEFAULT 'doc', user_id TEXT, source_url TEXT,
                source_kind TEXT, title TEXT, content_md TEXT, content_hash TEXT,
                ingested_at TEXT
            );
            CREATE TABLE kb_chunks (
                document_id TEXT, chunk_index INT, section_path TEXT,
                content TEXT, token_count INT
            );
        """)
        self.fail_chunks = False
        self.depth = 0

    @contextmanager
    def transaction(self):
        depth = self.depth
        self.depth += 1
        self.db.execute(f"SAVEPOINT txn_{depth}")
        try:
            yield
        except Exception:
            self.db.execute(f"ROLLBACK TO txn_{depth}")
            raise
        finally:
            self.db.execute(f"RELEASE txn_{depth}")
            self.depth -= 1

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, args=()):
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "").replace("NOW()", "CURRENT_TIMESTAMP")
        self.result = self.db.execute(sql, args)

    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.result.fetchall()]

    def executemany(self, sql, args):
        for values in args:
            self.execute(sql, values)
            if self.fail_chunks:
                raise RuntimeError("injected chunk write failure")

    def commit(self):
        self.db.commit()


def _save(repo, body="original", title="A"):
    return repo.upsert_document(
        user_id="u", source_url="vault://u/a.md", title=title,
        content_md=body, content_hash=body,
        chunks=[(0, None, body, 2), (1, "section", "second", 1)],
    )


@pytest.mark.parametrize("has_existing", [False, True])
def test_document_and_chunks_roll_back_together_then_retry(has_existing):
    conn = _TransactionalConnection()
    repo = KbRepository(conn)
    if has_existing:
        _save(repo)
    before = list(conn.db.execute("SELECT * FROM kb_documents")), list(conn.db.execute("SELECT * FROM kb_chunks"))
    conn.fail_chunks = True
    with pytest.raises(RuntimeError, match="injected"):
        _save(repo, body="updated")
    after = list(conn.db.execute("SELECT * FROM kb_documents")), list(conn.db.execute("SELECT * FROM kb_chunks"))
    assert after == before
    conn.fail_chunks = False
    assert _save(repo, body="updated")[1] is True
    assert _save(repo, body="updated")[1] is False


def test_matching_hash_repairs_historical_partial_chunks_and_title():
    conn = _TransactionalConnection()
    repo = KbRepository(conn)
    _save(repo)
    conn.db.execute("DELETE FROM kb_chunks WHERE chunk_index = 1")
    assert _save(repo)[1] is True
    assert conn.db.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0] == 2
    assert _save(repo, title="Renamed")[1] is True
    assert conn.db.execute("SELECT title FROM kb_documents").fetchone()[0] == "Renamed"


@pytest.mark.parametrize("paths", [[("../a.md", "a")], [("/a.md", "a")], [("a/../b.md", "a")]])
def test_ambiguous_note_paths_are_rejected_before_write(paths):
    repo = _repo()
    with pytest.raises(ValueError, match="path"):
        kb_ingest.ingest_zip(repo, "u", _zip(paths))
    repo.upsert_document.assert_not_called()


def test_member_count_rejects_before_writing(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_ARCHIVE_ENTRIES", 1)
    repo = _repo()
    with pytest.raises(ValueError, match="entries"):
        kb_ingest.ingest_zip(repo, "u", _zip([("a.md", "a"), ("img.png", "x")]))
    repo.upsert_document.assert_not_called()


def test_corrupt_late_member_rejects_before_writing(monkeypatch):
    blob = _zip([("a.md", "a"), ("b.md", "b")])
    original = zipfile.ZipFile.open

    def broken(self, member, *args, **kwargs):
        if member.filename == "b.md":
            raise zipfile.BadZipFile("injected late CRC failure")
        return original(self, member, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", broken)
    repo = _repo()
    with pytest.raises(ValueError, match="could not be read"):
        kb_ingest.ingest_zip(repo, "u", blob)
    repo.upsert_document.assert_not_called()


def test_replacements_release_quota_before_additions(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_TOTAL_MB", 1)
    repo = _repo({"vault://u/old.md": 1024 * 1024})
    result = kb_ingest.ingest_zip(repo, "u", _zip([("new.md", "new"), ("old.md", "old")]))
    assert result.docs_ingested == 2
    assert result.errors == []


def test_failed_shrinking_replacement_does_not_fund_addition(monkeypatch):
    monkeypatch.setattr(kb_ingest, "MAX_TOTAL_MB", 1)
    repo = _repo({"vault://u/old.md": 1024 * 1024})

    def fail_old(**kw):
        if kw["source_url"].endswith("old.md"):
            raise RuntimeError("failed shrinking replacement")
        return "doc", True

    repo.upsert_document.side_effect = fail_old
    result = kb_ingest.ingest_zip(repo, "u", _zip([("old.md", "old"), ("new.md", "new")]))
    assert result.docs_ingested == 0
    assert len(result.errors) == 2
    assert repo.upsert_document.call_count == 1


def test_invalid_deflate_is_a_safe_archive_error(monkeypatch):
    import zlib

    blob = _zip([("a.md", "a")])
    repo = _repo()
    monkeypatch.setattr(zipfile.ZipFile, "open", MagicMock(side_effect=zlib.error("bad stream")))
    with pytest.raises(kb_ingest.VaultImportError, match="could not be read"):
        kb_ingest.ingest_zip(repo, "u", blob)
    repo.upsert_document.assert_not_called()
