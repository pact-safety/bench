"""Git-repo vault sync (v2.1 slice 5).

Pins: repo-input normalization, the fetch's custody details (bare
bearer header + the CF User-Agent rule), tarball ingestion through the
SAME shared loop as zip uploads (root-strip + subdir filter), sync_user
result recording on success and failure, and the route contract
(connect saves-then-syncs inline; errors bounce with a message; the
local KB never breaks).
"""

from __future__ import annotations

import io
import json
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from app.services import kb_git_sync, kb_ingest


# ---------- normalize_repo ---------------------------------------------------


@pytest.mark.parametrize("raw", [
    "owner/vault",
    "https://github.com/owner/vault",
    "http://www.github.com/owner/vault/",
    "git@github.com:owner/vault.git",
    "https://github.com/owner/vault/tree/main/notes",
])
def test_normalize_repo_accepts_common_forms(raw):
    assert kb_git_sync.normalize_repo(raw) == "owner/vault"


@pytest.mark.parametrize("raw", ["", "just-a-name", "https://gitlab.com/x", "a b/c"])
def test_normalize_repo_rejects_garbage(raw):
    with pytest.raises(kb_git_sync.GitSyncError):
        kb_git_sync.normalize_repo(raw)


# ---------- fetch_tarball ----------------------------------------------------


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_sends_bearer_and_user_agent(monkeypatch):
    capture = {}

    def _fake(req, timeout=None):
        capture["url"] = req.full_url
        capture["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeHTTPResponse(b"tarbytes")

    monkeypatch.setattr(kb_git_sync.urllib.request, "build_opener", lambda *a: MagicMock(open=_fake))
    out = kb_git_sync.fetch_tarball("owner/vault", "main", "github_pat_x")
    assert out == b"tarbytes"
    assert capture["url"] == "https://api.github.com/repos/owner/vault/tarball/main"
    assert capture["headers"]["authorization"] == "Bearer github_pat_x"
    assert "lis-bench" in capture["headers"]["user-agent"]  # CF 1010 rule


def test_fetch_public_repo_sends_no_auth_header(monkeypatch):
    capture = {}

    def _fake(req, timeout=None):
        capture["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeHTTPResponse(b"t")

    monkeypatch.setattr(kb_git_sync.urllib.request, "build_opener", lambda *a: MagicMock(open=_fake))
    kb_git_sync.fetch_tarball("owner/vault", "", None)
    assert "authorization" not in capture["headers"]


def test_fetch_maps_http_errors_to_renderable_messages(monkeypatch):
    import urllib.error

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    monkeypatch.setattr(kb_git_sync.urllib.request, "build_opener", lambda *a: MagicMock(open=_boom))
    with pytest.raises(kb_git_sync.GitSyncError, match="404"):
        kb_git_sync.fetch_tarball("owner/vault", "", None)


def test_fetch_rejects_oversize_tarballs(monkeypatch):
    big = b"x" * (kb_git_sync.MAX_TARBALL_MB * 1024 * 1024 + 1)
    monkeypatch.setattr(
        kb_git_sync.urllib.request, "build_opener",
        lambda *a: MagicMock(open=lambda req, timeout=None: _FakeHTTPResponse(big)),
    )
    with pytest.raises(kb_git_sync.GitSyncError, match="over"):
        kb_git_sync.fetch_tarball("owner/vault", "", None)


# ---------- ingest_tarball ---------------------------------------------------


def _tarball(files: dict[str, str], root: str = "owner-vault-abc123") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_kb_repo():
    repo = MagicMock()
    repo.upsert_document.side_effect = lambda **kw: (kw["source_url"], True)
    repo.totals_for_user.return_value = (0, 0)
    repo.document_sizes_for_user.return_value = {}
    return repo


def test_ingest_tarball_strips_root_and_reuses_the_shared_loop():
    repo = _fake_kb_repo()
    blob = _tarball({
        "note.md": "hello",
        ".obsidian/app.json": "{}",
        "img.png": "bin",
    })
    result = kb_git_sync.ingest_tarball(repo, "uid-1", blob)
    assert result.docs_ingested == 1
    url = repo.upsert_document.call_args.kwargs["source_url"]
    assert url == "vault://uid-1/note.md"  # root prefix gone


def test_ingest_tarball_subdir_filter():
    repo = _fake_kb_repo()
    blob = _tarball({
        "vault/inner.md": "in scope",
        "docs/outer.md": "out of scope",
    })
    result = kb_git_sync.ingest_tarball(repo, "uid-1", blob, subdir="vault")
    assert result.docs_ingested == 1
    assert repo.upsert_document.call_args.kwargs["source_url"] == "vault://uid-1/inner.md"


def test_ingest_tarball_bad_bytes_is_a_user_error():
    with pytest.raises(kb_git_sync.GitSyncError):
        kb_git_sync.ingest_tarball(_fake_kb_repo(), "u", b"not a tarball")


# ---------- sync_user --------------------------------------------------------


def _sync_cfg(repo="owner/vault", branch="", subdir="", secret="sid"):
    cfg = MagicMock()
    cfg.repo, cfg.branch, cfg.subdir = repo, branch, subdir
    cfg.vault_secret_id = secret
    return cfg


def test_sync_user_records_summary_on_success(monkeypatch):
    kb = _fake_kb_repo()
    vs = MagicMock()
    vs.get.return_value = _sync_cfg()
    vs.token_for.return_value = "tok"
    monkeypatch.setattr(kb_git_sync, "fetch_tarball",
                        lambda r, b, t: _tarball({"a.md": "x"}))
    summary = kb_git_sync.sync_user(kb, vs, "uid-1")
    assert summary.startswith("ingested 1")
    vs.record_result.assert_called_once_with("uid-1", summary)


def test_sync_user_records_failure_and_raises(monkeypatch):
    kb = _fake_kb_repo()
    vs = MagicMock()
    vs.get.return_value = _sync_cfg()
    vs.token_for.return_value = None

    def _boom(r, b, t):
        raise kb_git_sync.GitSyncError("GitHub returned 404")

    monkeypatch.setattr(kb_git_sync, "fetch_tarball", _boom)
    with pytest.raises(kb_git_sync.GitSyncError):
        kb_git_sync.sync_user(kb, vs, "uid-1")
    assert vs.record_result.call_args.args[1].startswith("failed:")


def test_sync_user_allows_same_archive_retry_at_quota(monkeypatch):
    kb = _fake_kb_repo()
    kb.totals_for_user.return_value = (kb_ingest.MAX_DOCS, 0)
    vs = MagicMock()
    vs.get.return_value = _sync_cfg()
    monkeypatch.setattr(kb_git_sync, "fetch_tarball", lambda *a: b"archive")
    result = kb_ingest.IngestResult(1, 0, 1, 0, 0, [])
    ingest = MagicMock(return_value=result)
    monkeypatch.setattr(kb_git_sync, "ingest_tarball", ingest)
    assert "unchanged 1" in kb_git_sync.sync_user(kb, vs, "uid-1")
    ingest.assert_called_once()


# ---------- routes -----------------------------------------------------------

_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_MIRA_ADMIN_ONLY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID, email="u@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def test_connect_normalizes_saves_then_syncs_inline(monkeypatch):
    client, m = _client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.vault_sync_repo, "set_config", set_config), \
         patch.object(kb_git_sync, "sync_user", return_value="ingested 3") as sync:
        r = client.post(
            "/mira/kb/git/connect",
            data={"repo": "https://github.com/owner/vault.git",
                  "branch": "main", "subdir": "/notes/", "token": " tok "},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/mira/kb"
    kw = set_config.call_args.kwargs
    assert kw["repo"] == "owner/vault"
    assert kw["subdir"] == "notes"
    assert kw["token"] == "tok"
    sync.assert_called_once()


def test_connect_bad_repo_bounces_without_saving(monkeypatch):
    client, m = _client(monkeypatch)
    set_config = MagicMock()
    with patch.object(m.vault_sync_repo, "set_config", set_config):
        r = client.post(
            "/mira/kb/git/connect",
            data={"repo": "not a repo"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "kb_error=" in r.headers["location"]
    set_config.assert_not_called()


def test_sync_now_surfaces_errors_inline(monkeypatch):
    client, m = _client(monkeypatch)

    def _boom(kb, vs, uid):
        raise kb_git_sync.GitSyncError("GitHub rejected the token")

    with patch.object(kb_git_sync, "sync_user", _boom):
        r = client.post("/mira/kb/git/sync", follow_redirects=False)
    assert r.status_code == 303
    assert "kb_error=" in r.headers["location"]


def test_disconnect_removes_config_and_token(monkeypatch):
    client, m = _client(monkeypatch)
    delete_for = MagicMock()
    with patch.object(m.vault_sync_repo, "delete_for", delete_for):
        r = client.post("/mira/kb/git/disconnect", follow_redirects=False)
    assert r.status_code == 303
    delete_for.assert_called_once_with(_USER_UUID)
