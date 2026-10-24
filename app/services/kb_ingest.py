"""Obsidian vault ingestion (Bench v2.1 KB slice 1).

Takes a vault zip export, extracts the markdown IN MEMORY (nothing is
written to disk — no zip-slip surface), chunks each note on heading
boundaries, and upserts into the KB via content-hash so re-uploads of
an unchanged vault are near-free.

Obsidian-isms handled here, deliberately shallowly:
  - YAML frontmatter: stripped; a `title:` key wins over the filename.
  - Wikilinks `[[Note Name|alias]]`: reduced to their display text —
    retrieval wants prose, not link syntax. Link GRAPH extraction is a
    later phase; don't add it here.
  - `.obsidian/`, templates, and non-markdown files are skipped.

Archives are bounded before decompression. Quotas are checked against
the resulting vault before any writes, under a per-user import lock.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import zipfile
import zlib
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# Per-user quota knobs. Defaults sized for real vaults (a heavy
# multi-year vault is ~2-5k notes, 10-30MB of markdown).
MAX_DOCS = int(os.environ.get("LIS_KB_MAX_DOCS", "3000"))
MAX_TOTAL_MB = int(os.environ.get("LIS_KB_MAX_MB", "30"))
MAX_ZIP_MB = int(os.environ.get("LIS_KB_MAX_ZIP_MB", "60"))
MAX_EXPANDED_BYTES = MAX_TOTAL_MB * 1024 * 1024
MAX_ARCHIVE_ENTRIES = MAX_DOCS * 4


class VaultImportError(ValueError):
    """An import refusal safe to display to the user."""

# Chunking: merge sibling paragraphs up to this many characters, break
# at heading boundaries. ~1500 chars ≈ 350-400 tokens — small enough to
# cite precisely, big enough to carry an argument.
_CHUNK_TARGET_CHARS = 1500

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

_SKIP_PREFIXES = (".obsidian/", ".trash/", ".git/")


@dataclass(frozen=True)
class IngestResult:
    docs_seen: int
    docs_ingested: int
    docs_unchanged: int
    docs_skipped: int
    chunks_written: int
    errors: list[str]


def vault_source_url(user_id: str, note_path: str) -> str:
    """Synthetic per-note URL satisfying kb_documents' global UNIQUE
    constraint while namespacing by owner."""
    return f"vault://{user_id}/{note_path}"


def check_quota(kb_repo, user_id: str, incoming_bytes: int) -> str | None:
    """None = fine; else a human-readable refusal."""
    docs, total = kb_repo.totals_for_user(user_id)
    if docs >= MAX_DOCS:
        return f"Vault quota reached ({MAX_DOCS} notes). Delete some notes first."
    if total + incoming_bytes > MAX_TOTAL_MB * 1024 * 1024:
        return (
            f"Vault quota reached ({MAX_TOTAL_MB}MB of markdown). "
            "Delete some notes or upload a smaller export."
        )
    return None


def strip_frontmatter(text: str) -> tuple[str, str | None]:
    """Returns (body, frontmatter_title)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return text, None
    fm = m.group(1)
    title = None
    for line in fm.splitlines():
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("\"'") or None
            break
    return text[m.end():], title


def flatten_wikilinks(text: str) -> str:
    return _WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)


def chunk_markdown(body: str) -> list[tuple[int, str | None, str, int]]:
    """(chunk_index, section_path, content, token_count) tuples.

    Split on headings, then greedily merge consecutive blocks within a
    section up to _CHUNK_TARGET_CHARS. token_count is a chars/4
    estimate — good enough for budget math, no tokenizer dependency.
    """
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for raw_line in body.splitlines():
        m = _HEADING_RE.match(raw_line)
        if m:
            sections.append((m.group(2).strip() or None, []))
        else:
            sections[-1][1].append(raw_line)

    chunks: list[tuple[int, str | None, str, int]] = []
    ix = 0
    for section_path, lines in sections:
        text = "\n".join(lines).strip()
        if not text and not section_path:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paras and section_path:
            continue  # heading with no body — nothing to retrieve
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) + 2 > _CHUNK_TARGET_CHARS:
                chunks.append((ix, section_path, buf, max(1, len(buf) // 4)))
                ix += 1
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf:
            chunks.append((ix, section_path, buf, max(1, len(buf) // 4)))
            ix += 1
    return chunks


def strip_root_prefix(name: str) -> str:
    """Zip exports and GitHub tarballs both wrap everything in a single
    root folder; strip it so vault paths are stable across sources."""
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 and "." not in parts[0] else name


def is_note_path(rel: str) -> bool:
    return rel.lower().endswith(".md") and not any(
        rel.startswith(p) or f"/{p}" in f"/{rel}" for p in _SKIP_PREFIXES
    )


def ingest_entries(kb_repo, user_id: str, entries) -> IngestResult:
    """Validate and stage bounded entries, then atomically save each note.

    Per-note write failures are isolated and retryable; malformed input
    and quota refusals reject the entire import before persistence.
    """
    prepared = []
    paths = set()
    docs_skipped = total_bytes = 0
    for count, (rel, data) in enumerate(entries, 1):
        if count > MAX_ARCHIVE_ENTRIES:
            raise VaultImportError("Archive has too many entries.")
        total_bytes += len(data)
        if total_bytes > MAX_EXPANDED_BYTES:
            raise VaultImportError("Archive exceeds the expanded size limit.")
        if not is_note_path(rel):
            docs_skipped += int(rel.lower().endswith(".md"))
            continue
        if "\\" in rel or any(part in ("", ".", "..") for part in rel.split("/")):
            raise VaultImportError("Archive contains an invalid note path.")
        if rel in paths:
            raise VaultImportError("Archive contains duplicate note paths.")
        paths.add(rel)
        if len(paths) > MAX_DOCS:
            raise VaultImportError(f"Vault quota reached ({MAX_DOCS} notes).")
        body, fm_title = strip_frontmatter(data.decode("utf-8", errors="replace"))
        body = flatten_wikilinks(body).strip()
        prepared.append(dict(
            source_url=vault_source_url(user_id, rel),
            title=fm_title or rel.rsplit("/", 1)[-1].removesuffix(".md"),
            content_md=body,
            content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            chunks=chunk_markdown(body),
        ))

    docs_ingested = docs_unchanged = chunks_written = 0
    errors: list[str] = []
    with kb_repo.import_transaction(user_id):
        sizes = kb_repo.document_sizes_for_user(user_id)
        projected = dict(sizes)
        projected.update({note["source_url"]: len(note["content_md"].encode("utf-8")) for note in prepared})
        if len(projected) > MAX_DOCS or sum(projected.values()) > MAX_TOTAL_MB * 1024 * 1024:
            raise VaultImportError("Vault quota reached. Delete some notes or upload a smaller export.")
        total = sum(sizes.values())
        # Apply shrinking replacements first so final-size quota checks do
        # not depend on archive order. Failed shrinks still reserve old bytes.
        ordered = sorted(prepared, key=lambda note: (
            len(note["content_md"].encode("utf-8")) - sizes.get(note["source_url"], 0)
        ))
        for note in ordered:
            source_url = note["source_url"]
            size = len(note["content_md"].encode("utf-8"))
            try:
                # A failed shrinking replacement must not fund a later addition.
                next_total = total - sizes.get(source_url, 0) + size
                if next_total > MAX_TOTAL_MB * 1024 * 1024:
                    raise VaultImportError("Vault quota reached after a failed replacement.")
                _doc_id, changed = kb_repo.upsert_document(user_id=user_id, **note)
                sizes[source_url] = size
                total = next_total
                if changed:
                    docs_ingested += 1
                    chunks_written += len(note["chunks"])
                else:
                    docs_unchanged += 1
            except Exception as exc:  # noqa: BLE001 — the note transaction rolled back
                rel = source_url.removeprefix(f"vault://{user_id}/")
                errors.append(f"{rel}: {type(exc).__name__}")
                _log.warning("kb ingest failed for a note (%s)", type(exc).__name__)

    return IngestResult(
        docs_seen=len(prepared), docs_ingested=docs_ingested,
        docs_unchanged=docs_unchanged, docs_skipped=docs_skipped,
        chunks_written=chunks_written, errors=errors[:20],
    )


def ingest_zip(kb_repo, user_id: str, zip_bytes: bytes) -> IngestResult:
    """Vault zip export → the shared ingest loop (in memory only)."""
    if len(zip_bytes) > MAX_ZIP_MB * 1024 * 1024:
        raise VaultImportError(f"Archive exceeds the {MAX_ZIP_MB}MB compressed size limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise VaultImportError("Archive has too many entries.")
            if sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
                raise VaultImportError("Archive exceeds the expanded size limit.")
            files = [info for info in infos if not info.is_dir()]
            # Detect one wrapper for the whole container; stripping each file's
            # first component independently merges unrelated same-name notes.
            roots = {info.filename.split("/", 1)[0] for info in files}
            wrapped = len(roots) == 1 and all("/" in info.filename for info in files)
            entries = []
            remaining = MAX_EXPANDED_BYTES
            for info in files:
                if info.filename.startswith("/"):
                    raise VaultImportError("Archive contains an invalid note path.")
                rel = strip_root_prefix(info.filename) if wrapped else info.filename
                if not is_note_path(rel):
                    continue
                with zf.open(info) as source:
                    data = source.read(min(info.file_size, remaining) + 1)
                if len(data) > remaining or len(data) != info.file_size:
                    raise VaultImportError("Archive exceeds the expanded size limit or is damaged.")
                remaining -= len(data)
                entries.append((rel, data))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as exc:
        raise VaultImportError("Archive could not be read. Upload a valid, unencrypted ZIP.") from exc
    return ingest_entries(kb_repo, user_id, entries)
