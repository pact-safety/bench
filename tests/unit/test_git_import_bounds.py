import gzip
import io
import tarfile
from unittest.mock import MagicMock

import pytest
from app.services import kb_git_sync, kb_ingest


def archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        for name, payload in files.items():
            info = tarfile.TarInfo('owner-vault-sha/' + name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def test_expanded_attachment_limit_refuses_before_any_write(monkeypatch):
    monkeypatch.setattr(kb_ingest, 'MAX_EXPANDED_BYTES', 32, raising=False)
    repo = MagicMock()
    blob = archive({'note.md': b'hello', 'attachment.bin': b'x' * 100})
    with pytest.raises(kb_git_sync.GitSyncError, match='expanded'):
        kb_git_sync.ingest_tarball(repo, 'owner', blob)
    repo.upsert_document.assert_not_called()


def test_member_limit_counts_skipped_files_before_writes(monkeypatch):
    monkeypatch.setattr(kb_ingest, 'MAX_ARCHIVE_ENTRIES', 2, raising=False)
    repo = MagicMock()
    blob = archive({'note.md': b'hello', 'a.bin': b'x', 'b.bin': b'x'})
    with pytest.raises(kb_git_sync.GitSyncError, match='entries'):
        kb_git_sync.ingest_tarball(repo, 'owner', blob)
    repo.upsert_document.assert_not_called()


def test_gzip_expansion_is_bounded_before_tar_parser(monkeypatch):
    monkeypatch.setattr(kb_ingest, 'MAX_EXPANDED_BYTES', 32, raising=False)
    monkeypatch.setattr(kb_ingest, 'MAX_ARCHIVE_ENTRIES', 2, raising=False)
    with pytest.raises(kb_git_sync.GitSyncError, match='expanded'):
        kb_git_sync.ingest_tarball(MagicMock(), 'owner', gzip.compress(b'x' * 50000))


def test_archive_failure_recorded_with_retryable_safe_message(monkeypatch):
    error = type('VaultImportError', (ValueError,), {})
    monkeypatch.setattr(kb_ingest, 'VaultImportError', error, raising=False)
    repo, sync = MagicMock(), MagicMock()
    monkeypatch.setattr(kb_ingest, 'check_quota', lambda *a: None)
    monkeypatch.setattr(kb_git_sync, 'fetch_tarball', lambda *a: b'archive')
    monkeypatch.setattr(kb_git_sync, 'ingest_tarball', MagicMock(side_effect=error('Expanded archive is too large.')))
    with pytest.raises(kb_git_sync.GitSyncError, match='Expanded'):
        kb_git_sync.sync_user(repo, sync, 'owner')
    assert sync.record_result.call_args.args[1].startswith('failed:')


def test_github_redirect_never_forwards_token_to_download_host():
    from urllib.request import Request
    handler = kb_git_sync._GitHubRedirectHandler()
    req = Request('https://api.github.com/repos/a/b/tarball', headers={'Authorization': 'Bearer synthetic'})
    redirected = handler.redirect_request(req, None, 302, 'Found', {}, 'https://codeload.github.com/a/b/tar.gz/sha')
    assert redirected.get_header('Authorization') is None


@pytest.mark.parametrize('url', ['http://codeload.github.com/a', 'https://example.org/a', 'https://codeload.github.com@127.0.0.1/a'])
def test_github_redirect_refuses_other_destinations(url):
    from urllib.request import Request
    with pytest.raises(kb_git_sync.GitSyncError):
        kb_git_sync._GitHubRedirectHandler().redirect_request(Request('https://api.github.com/a'), None, 302, 'Found', {}, url)


def test_corrupt_deflate_is_retryable_and_recorded(monkeypatch):
    broken = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff\x07' + b'\x00' * 8
    sync = MagicMock()
    monkeypatch.setattr(kb_git_sync, 'fetch_tarball', lambda *a: broken)
    with pytest.raises(kb_git_sync.GitSyncError, match='could not be read'):
        kb_git_sync.sync_user(MagicMock(), sync, 'owner')
    assert sync.record_result.call_args.args[1].startswith('failed:')
