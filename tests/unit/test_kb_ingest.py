"""Vault ingestion (v2.1 KB slice 1) — the pure pipeline.

Pins: frontmatter stripping (+title extraction), wikilink flattening,
heading-aware chunking, hash-skip on unchanged notes, per-note error
isolation, quota refusal, and the vault:// URL namespace.
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock

from app.services import kb_ingest


def _vault_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _fake_repo(existing_hashes: dict[str, str] | None = None):
    repo = MagicMock()
    hashes = existing_hashes or {}

    def _upsert(**kw):
        changed = hashes.get(kw["source_url"]) != kw["content_hash"]
        return (f"doc-{kw['source_url']}", changed)

    repo.upsert_document.side_effect = _upsert
    repo.totals_for_user.return_value = (0, 0)
    repo.document_sizes_for_user.return_value = {}
    return repo


# ---------- pure helpers -----------------------------------------------------


def test_strip_frontmatter_extracts_title():
    body, title = kb_ingest.strip_frontmatter(
        "---\ntitle: KV caches\ntags: [ml]\n---\nActual note body."
    )
    assert title == "KV caches"
    assert body == "Actual note body."


def test_strip_frontmatter_noop_without_block():
    body, title = kb_ingest.strip_frontmatter("Just a note.")
    assert (body, title) == ("Just a note.", None)


def test_flatten_wikilinks_keeps_display_text():
    out = kb_ingest.flatten_wikilinks("See [[Attention Is All You Need|the paper]] and [[KV cache]].")
    assert out == "See the paper and KV cache."


def test_chunk_markdown_splits_on_headings_and_carries_section_path():
    body = "intro para\n\n## Setup\n\nstep one\n\nstep two\n\n## Results\n\nnumbers"
    chunks = kb_ingest.chunk_markdown(body)
    sections = [(sp, c) for _ix, sp, c, _tc in chunks]
    assert sections[0] == (None, "intro para")
    assert any(sp == "Setup" and "step one" in c for sp, c in sections)
    assert any(sp == "Results" and "numbers" in c for sp, c in sections)
    # indexes are sequential from 0
    assert [ix for ix, *_ in chunks] == list(range(len(chunks)))


def test_chunk_markdown_merges_up_to_target_and_breaks_after():
    paras = "\n\n".join(f"para {i} " + "x" * 400 for i in range(8))
    chunks = kb_ingest.chunk_markdown(paras)
    assert len(chunks) > 1
    assert all(len(c) <= kb_ingest._CHUNK_TARGET_CHARS + 500 for _ix, _sp, c, _tc in chunks)


# ---------- ingest_zip -------------------------------------------------------


def test_ingest_zip_ingests_markdown_and_skips_config():
    repo = _fake_repo()
    blob = _vault_zip({
        "MyVault/note one.md": "---\ntitle: Note One\n---\nBody with [[link|text]].",
        "MyVault/.obsidian/app.json": "{}",
        "MyVault/image.png": "binarystuff",
        "MyVault/sub/deep note.md": "## H\n\ncontent",
    })
    result = kb_ingest.ingest_zip(repo, "uid-1", blob)
    assert result.docs_ingested == 2
    assert result.docs_seen == 2  # png + .obsidian never counted as notes
    assert result.errors == []
    urls = [kw["source_url"] for _a, kw in repo.upsert_document.call_args_list]
    assert "vault://uid-1/note one.md" in urls
    assert "vault://uid-1/sub/deep note.md" in urls
    # wikilink flattened before storage
    stored = next(kw for _a, kw in repo.upsert_document.call_args_list
                  if kw["source_url"].endswith("note one.md"))
    assert "[[" not in stored["content_md"]
    assert stored["title"] == "Note One"


def test_ingest_zip_skips_unchanged_notes():
    import hashlib

    body = "stable content"
    h = hashlib.sha256(body.encode()).hexdigest()
    repo = _fake_repo({"vault://uid-1/a.md": h})
    result = kb_ingest.ingest_zip(repo, "uid-1", _vault_zip({"a.md": body}))
    assert result.docs_unchanged == 1
    assert result.docs_ingested == 0
    repo.replace_chunks.assert_not_called()


def test_ingest_zip_isolates_per_note_failures():
    repo = _fake_repo()
    calls = {"n": 0}

    def _flaky(**kw):
        calls["n"] += 1
        if kw["source_url"].endswith("bad.md"):
            raise RuntimeError("boom")
        return ("doc-x", True)

    repo.upsert_document.side_effect = _flaky
    result = kb_ingest.ingest_zip(
        repo, "uid-1", _vault_zip({"bad.md": "x", "good.md": "y"})
    )
    assert result.docs_ingested == 1
    assert len(result.errors) == 1
    assert "bad.md" in result.errors[0]


def test_check_quota_refuses_over_limits(monkeypatch):
    repo = MagicMock()
    repo.totals_for_user.return_value = (kb_ingest.MAX_DOCS, 0)
    assert "quota" in kb_ingest.check_quota(repo, "u", 10).lower()
    repo.totals_for_user.return_value = (0, kb_ingest.MAX_TOTAL_MB * 1024 * 1024)
    assert kb_ingest.check_quota(repo, "u", 1024) is not None
    repo.totals_for_user.return_value = (10, 1024)
    assert kb_ingest.check_quota(repo, "u", 1024) is None
