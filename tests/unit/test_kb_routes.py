"""/mira/kb routes (v2.1 slice 1): gate, upload flow, owner-scoped
delete, and the retrieval seam in rag.hybrid_search."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, session_uuid: str):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("LIS_MIRA_ADMIN_ONLY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=session_uuid,
            email="u@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _tiny_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("note.md", "hello vault")
    return buf.getvalue()


def test_kb_page_regated_by_env_flip(mock_anthropic, monkeypatch):
    client, _m = _client(monkeypatch, session_uuid=_USER_UUID)
    monkeypatch.setenv("LIS_MIRA_ADMIN_ONLY", "1")
    assert client.get("/mira/kb").status_code == 404
    r = client.post(
        "/mira/kb/upload",
        files={"vault_zip": ("vault.zip", _tiny_zip(), "application/zip")},
    )
    assert r.status_code == 404


def test_kb_page_lists_docs_and_search(mock_anthropic, monkeypatch):
    from app.repositories.kb_repository import KbDocument, KbSearchHit

    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    doc = KbDocument(
        id="d1", user_id=_ADMIN_UUID, source_url=f"vault://{_ADMIN_UUID}/a.md",
        source_kind="doc", title="KV caches", content_hash="h",
        ingested_at=None, chunk_count=3, content_bytes=1200,
    )
    hit = KbSearchHit(
        chunk_id="c1", document_id="d1", document_title="KV caches",
        section_path="Memory", content="the cache grows linearly", score=0.5,
    )
    with patch.object(m.kb_repo, "list_for_user", return_value=[doc]), \
         patch.object(m.kb_repo, "sparse_search", return_value=[hit]) as search:
        r = client.get("/mira/kb?q=cache")
    assert r.status_code == 200
    assert "KV caches" in r.text
    assert "the cache grows linearly" in r.text
    search.assert_called_once()
    assert search.call_args.args[1] == "cache"


def test_kb_upload_ingests_and_redirects_with_counts(mock_anthropic, monkeypatch):
    from app.services.kb_ingest import IngestResult

    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    fake_result = IngestResult(
        docs_seen=2, docs_ingested=2, docs_unchanged=0,
        docs_skipped=0, chunks_written=5, errors=[],
    )
    from app.services import kb_ingest as ki

    with patch.object(ki, "ingest_zip", return_value=fake_result) as ingest, \
         patch.object(ki, "check_quota", return_value=None):
        r = client.post(
            "/mira/kb/upload",
            files={"vault_zip": ("vault.zip", _tiny_zip(), "application/zip")},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "ingested=2" in r.headers["location"]
    ingest.assert_called_once()
    assert ingest.call_args.args[1] == _ADMIN_UUID  # ingests as the session user


def test_kb_upload_quota_refusal_bounces(mock_anthropic, monkeypatch):
    from app.services import kb_ingest as ki

    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(ki, "ingest_zip", side_effect=ki.VaultImportError("Vault quota reached")) as ingest:
        r = client.post(
            "/mira/kb/upload",
            files={"vault_zip": ("vault.zip", _tiny_zip(), "application/zip")},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "kb_error=" in r.headers["location"]
    ingest.assert_called_once()


def test_kb_upload_garbage_zip_is_a_user_error_not_500(mock_anthropic, monkeypatch):
    from app.services import kb_ingest as ki

    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(ki, "check_quota", return_value=None):
        r = client.post(
            "/mira/kb/upload",
            files={"vault_zip": ("vault.zip", b"not a zip", "application/zip")},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "kb_error=" in r.headers["location"]


def test_kb_delete_is_owner_scoped(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.kb_repo, "delete_document", return_value=True) as dele:
        r = client.post("/mira/kb/delete/d1", follow_redirects=False)
    assert r.status_code == 303
    dele.assert_called_once_with(_ADMIN_UUID, "d1")


# ---------- rag.hybrid_search seam -------------------------------------------


def test_hybrid_search_returns_sparse_hits_scoped_to_user():
    import asyncio

    from app.repositories.kb_repository import KbSearchHit
    from app.services import rag

    repo = MagicMock()
    repo.sparse_search.return_value = [
        KbSearchHit(
            chunk_id="c1", document_id="d1", document_title="T",
            section_path=None, content="hit", score=1.0,
        )
    ]
    prev = rag._kb_repo
    rag.set_kb_repo(repo)
    try:
        out = asyncio.run(rag.hybrid_search("query", k_final=3, user_id="uid-9"))
    finally:
        rag.set_kb_repo(prev)
    assert [c.id for c in out] == ["c1"]
    repo.sparse_search.assert_called_once_with("uid-9", "query", k=50)


def test_hybrid_search_empty_without_repo_or_on_error():
    import asyncio

    from app.services import rag

    prev = rag._kb_repo
    rag.set_kb_repo(None)
    try:
        assert asyncio.run(rag.hybrid_search("query")) == []
        broken = MagicMock()
        broken.sparse_search.side_effect = RuntimeError("db down")
        rag.set_kb_repo(broken)
        assert asyncio.run(rag.hybrid_search("query", user_id="u")) == []
    finally:
        rag.set_kb_repo(prev)
