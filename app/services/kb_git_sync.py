"""Git-repo vault sync (v2.1 slice 5).

Most Obsidian vaults are git repos. This fetches the GitHub tarball —
no git binary, nothing user-supplied touches disk — and feeds the same
ingest pipeline as the zip upload. GitHub only in v1; the repository
field is normalized `owner/name`, so another host later is a second
fetcher, not a schema change.

Custody: the read token comes from Vault at call time and goes into
one request header. It is never logged, and error strings surfaced to
the UI carry no request details beyond the HTTP status.

Cloudflare note: GitHub fronts with CF, so requests carry an explicit
User-Agent (the bench's outbound rule — error 1010 otherwise; see
app/services/notifications.py).
"""

from __future__ import annotations

import io
import gzip
import logging
import re
import tarfile
import zlib
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from . import kb_ingest

_log = logging.getLogger(__name__)

_UA = "lis-bench/1.0 (+https://bench.libearden.dev)"
_TIMEOUT_S = 30
# Compressed-tarball ceiling. Text vaults compress hard; anything past
# this is not a notes repo (or not only one).
MAX_TARBALL_MB = int(kb_ingest.MAX_ZIP_MB)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitSyncError(RuntimeError):
    """Message is safe to render to the user."""


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme != "https" or target.hostname not in {"api.github.com", "codeload.github.com"}
                or target.username is not None or target.password is not None
                or target.port not in {None, 443}):
            raise GitSyncError("GitHub returned an unsupported download redirect. Try again.")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and target.hostname != urlsplit(req.full_url).hostname:
            # GitHub's download redirect is signed; the repository token belongs
            # only to the API request, never to the redirected download host.
            redirected.remove_header("Authorization")
        return redirected


def normalize_repo(raw: str) -> str:
    """Accept `owner/name`, a github.com URL, or a clone URL; return
    `owner/name` or raise."""
    s = (raw or "").strip()
    s = re.sub(r"^(https?://)?(www\.)?github\.com[:/]", "", s)
    s = re.sub(r"^git@github\.com:", "", s)
    s = s.removesuffix(".git").strip("/")
    # Drop anything past owner/name (tree/branch paths pasted from the UI).
    parts = s.split("/")
    if len(parts) >= 2:
        s = f"{parts[0]}/{parts[1]}"
    if not _REPO_RE.match(s):
        raise GitSyncError(
            "Repository must look like owner/name or a github.com URL."
        )
    return s


def fetch_tarball(repo: str, branch: str, token: str | None) -> bytes:
    """The compressed tarball for `repo` at `branch` (empty = default
    branch). Public repos work with no token."""
    ref = f"/{quote(branch, safe='')}" if branch else ""
    url = f"https://api.github.com/repos/{repo}/tarball{ref}"
    headers = {
        "User-Agent": _UA,
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _GitHubRedirectHandler()).open(req, timeout=_TIMEOUT_S) as resp:
            blob = resp.read(MAX_TARBALL_MB * 1024 * 1024 + 1)
    except GitSyncError:
        raise
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise GitSyncError(
                "GitHub returned 404 — private repo without a valid token, "
                "wrong repo name, or wrong branch."
            ) from e
        if e.code in (401, 403):
            raise GitSyncError(
                "GitHub rejected the token. Re-check it (and its repo scope)."
            ) from e
        raise GitSyncError(f"GitHub error (HTTP {e.code}). Try again.") from e
    except Exception as e:  # noqa: BLE001 — network/timeout/DNS
        raise GitSyncError("Could not reach GitHub. Try again.") from e
    if len(blob) > MAX_TARBALL_MB * 1024 * 1024:
        raise GitSyncError(
            f"Repo tarball is over {MAX_TARBALL_MB}MB compressed — that's "
            "not a notes vault. Point the sync at a subfolder repo instead."
        )
    return blob


def ingest_tarball(
    kb_repo, user_id: str, tar_bytes: bytes, subdir: str = ""
) -> kb_ingest.IngestResult:
    """GitHub tarball → the shared ingest loop. The tarball wraps
    everything in `owner-repo-sha/`; strip it, then apply the optional
    subdir filter (vault-in-a-monorepo)."""
    prefix = (subdir or "").strip().strip("/")
    if len(tar_bytes) > MAX_TARBALL_MB * 1024 * 1024:
        raise GitSyncError("Repo tarball is over the compressed import limit.")
    # Bound gzip output before tarfile can allocate a large PAX/long-name header.
    # Allow record padding separately from the accepted file-content budget.
    wire_limit = kb_ingest.MAX_EXPANDED_BYTES + kb_ingest.MAX_ARCHIVE_ENTRIES * 1024 + 10240
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(tar_bytes)) as stream:
            expanded = stream.read(wire_limit + 1)
        if len(expanded) > wire_limit:
            raise GitSyncError("Repo tarball is over the expanded import limit.")
        entries = []
        expanded_size = 0
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as tf:
            for count, member in enumerate(tf, start=1):
                if count > kb_ingest.MAX_ARCHIVE_ENTRIES:
                    raise GitSyncError("Repo tarball has too many entries. Split the vault and retry.")
                expanded_size += member.size
                if member.size < 0 or expanded_size > kb_ingest.MAX_EXPANDED_BYTES:
                    raise GitSyncError("Repo tarball is over the expanded import limit.")
                if not member.isfile():
                    continue
                rel = kb_ingest.strip_root_prefix(member.name)
                if prefix:
                    if not rel.startswith(prefix + "/"):
                        continue
                    rel = rel[len(prefix) + 1:]
                if not kb_ingest.is_note_path(rel):
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                with fh:
                    data = fh.read(member.size + 1)
                if len(data) != member.size:
                    raise GitSyncError("Repo tarball contains an incomplete note. Retry the sync.")
                entries.append((rel, data))
        # Staging first means archive/quota rejection cannot leave a partial import.
        return kb_ingest.ingest_entries(kb_repo, user_id, entries)
    except kb_ingest.VaultImportError as exc:
        raise GitSyncError(str(exc)) from exc
    except (tarfile.TarError, OSError, EOFError, ValueError, zlib.error) as exc:
        raise GitSyncError("GitHub's tarball could not be read. Try again.") from exc


def sync_user(kb_repo, vault_sync_repo, user_id: str) -> str:
    """One user's full sync. Returns the short result string that
    lands in `last_result` (also recorded here). Raises GitSyncError
    for user-visible failures — callers decide whether that surfaces
    inline (manual sync) or is swallowed into last_result (cron)."""
    cfg = vault_sync_repo.get(user_id)
    if cfg is None:
        raise GitSyncError("No git vault is connected.")
    token = vault_sync_repo.token_for(user_id)
    try:
        blob = fetch_tarball(cfg.repo, cfg.branch, token)
        result = ingest_tarball(kb_repo, user_id, blob, cfg.subdir)
    except kb_ingest.VaultImportError as exc:
        vault_sync_repo.record_result(user_id, f"failed: {exc}")
        raise GitSyncError(str(exc)) from exc
    except GitSyncError as e:
        vault_sync_repo.record_result(user_id, f"failed: {e}")
        raise
    summary = (
        f"ingested {result.docs_ingested}, unchanged {result.docs_unchanged}"
        + (f", {len(result.errors)} errors" if result.errors else "")
    )
    vault_sync_repo.record_result(user_id, summary)
    return summary
