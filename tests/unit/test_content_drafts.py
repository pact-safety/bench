"""Tests for the BEN-88 content-drafts substrate.

Covers:
- list/read/promote/discard/write semantics
- safety: drafts ignored by the live content loader (non-recursive glob)
- safety: promote refuses to overwrite an existing live file
- content_generation stub returns a placeholder shaped like the schema
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import content_drafts, content_generation
from app.services import tracks as tracks_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_root(tmp_path: Path) -> Path:
    """Build a minimal content/ tree with empty live dirs for each kind."""
    root = tmp_path / "content"
    for sub in ("readings", "videos", "podcasts", "exercises"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _seed_draft(root: Path, kind_subdir: str, slug: str, *, title: str = "X") -> Path:
    drafts_dir = root / kind_subdir / "_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{slug}.md"
    path.write_text(
        f"---\nslug: {slug}\nkind: reading\ntitle: \"{title}\"\n---\n\nbody\n",
        encoding="utf-8",
    )
    return path


def _fake_track(slug: str = "arena_3") -> tracks_service.Track:
    section = tracks_service.TrackSection(
        title="0.0 Prerequisites",
        url="https://example.com/0.0",
        kind="external_reading",
        duration_min=120,
        domain_tags=("python", "pytorch"),
        axes=("algorithmic",),
    )
    chapter = tracks_service.TrackChapter(title="Chapter 0", sections=(section,))
    return tracks_service.Track(
        slug=slug,
        title="ARENA 3.0",
        description="Test",
        source_url="https://example.com/arena",
        chapters=(chapter,),
        body_md="",
    )


# ---------------------------------------------------------------------------
# list / read
# ---------------------------------------------------------------------------


def test_list_drafts_empty_when_no_drafts_dir(tmp_path: Path):
    root = _content_root(tmp_path)
    assert content_drafts.list_drafts(root, "reading") == []


def test_list_drafts_returns_seeded_drafts(tmp_path: Path):
    root = _content_root(tmp_path)
    _seed_draft(root, "readings", "x-s00-reading-draft", title="X reading")
    _seed_draft(root, "readings", "y-s01-reading-draft", title="Y reading")
    drafts = content_drafts.list_drafts(root, "reading")
    slugs = sorted(d.slug for d in drafts)
    assert slugs == ["x-s00-reading-draft", "y-s01-reading-draft"]
    # Title parsed from frontmatter
    assert any(d.title == "X reading" for d in drafts)


def test_list_all_drafts_spans_kinds(tmp_path: Path):
    root = _content_root(tmp_path)
    _seed_draft(root, "readings", "a-s00-reading-draft")
    _seed_draft(root, "exercises", "a-s00-exercise-draft")
    out = content_drafts.list_all_drafts(root)
    assert {d.kind for d in out} == {"reading", "exercise"}


def test_read_draft_returns_none_when_missing(tmp_path: Path):
    root = _content_root(tmp_path)
    assert content_drafts.read_draft(root, "reading", "nope") is None


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


def test_promote_moves_file_to_live_dir(tmp_path: Path):
    root = _content_root(tmp_path)
    _seed_draft(root, "readings", "x-s00-reading-draft")

    dst = content_drafts.promote(root, "reading", "x-s00-reading-draft")

    assert dst == root / "readings" / "x-s00-reading-draft.md"
    assert dst.exists()
    # Original draft file should be gone
    assert not (root / "readings" / "_drafts" / "x-s00-reading-draft.md").exists()


def test_promote_refuses_to_overwrite_existing_live_file(tmp_path: Path):
    root = _content_root(tmp_path)
    _seed_draft(root, "readings", "collision")
    # Pre-existing live file with same slug
    (root / "readings" / "collision.md").write_text("# live\n", encoding="utf-8")

    with pytest.raises(content_drafts.DraftError, match="already exists"):
        content_drafts.promote(root, "reading", "collision")

    # Draft is still there (no destructive partial state)
    assert (root / "readings" / "_drafts" / "collision.md").exists()


def test_promote_raises_for_missing_draft(tmp_path: Path):
    root = _content_root(tmp_path)
    with pytest.raises(content_drafts.DraftError, match="not found"):
        content_drafts.promote(root, "reading", "nope")


def test_promote_rejects_invalid_kind(tmp_path: Path):
    root = _content_root(tmp_path)
    with pytest.raises(content_drafts.DraftError, match="unknown kind"):
        content_drafts.promote(root, "garbage", "x")


# ---------------------------------------------------------------------------
# discard
# ---------------------------------------------------------------------------


def test_discard_deletes_draft(tmp_path: Path):
    root = _content_root(tmp_path)
    path = _seed_draft(root, "readings", "x-s00-reading-draft")
    assert content_drafts.discard(root, "reading", "x-s00-reading-draft") is True
    assert not path.exists()


def test_discard_returns_false_when_missing(tmp_path: Path):
    root = _content_root(tmp_path)
    assert content_drafts.discard(root, "reading", "nope") is False


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def test_write_draft_creates_drafts_dir_and_writes(tmp_path: Path):
    root = _content_root(tmp_path)
    path = content_drafts.write_draft(
        root, kind="reading", slug="new-draft", frontmatter_md="---\nslug: x\n---\n",
    )
    assert path == root / "readings" / "_drafts" / "new-draft.md"
    assert path.read_text(encoding="utf-8").startswith("---")


def test_write_draft_refuses_collision(tmp_path: Path):
    root = _content_root(tmp_path)
    content_drafts.write_draft(
        root, kind="reading", slug="dup", frontmatter_md="---\nslug: x\n---\n",
    )
    with pytest.raises(content_drafts.DraftError, match="already exists"):
        content_drafts.write_draft(
            root, kind="reading", slug="dup", frontmatter_md="---\nslug: x\n---\n",
        )


# ---------------------------------------------------------------------------
# Safety: live loader does NOT see drafts
# ---------------------------------------------------------------------------


def test_live_content_loader_ignores_drafts_dir(tmp_path: Path):
    """Drafts must NOT be picked up by load_all_content. The loader uses
    a non-recursive glob; this test pins that behavior so we'd notice if
    someone changes it to **/*.md and accidentally surfaces drafts."""
    from app.services.content import load_all_content
    from app.repositories.content_repository import ContentItem

    root = _content_root(tmp_path)

    # Seed one live reading, one draft reading
    (root / "readings" / "live.md").write_text(
        "---\nslug: live\nkind: reading\ntitle: Live\nurl: https://example.com\n"
        "duration_min: 10\ndomain_tags: []\naxes: []\nauthored_by: test\n"
        "authored_date: 2026-01-01\nversion: 1\n---\n\nbody\n",
        encoding="utf-8",
    )
    _seed_draft(root, "readings", "x-s00-reading-draft", title="DRAFT")

    # Mock the repo so we just observe what the loader tried to upsert.
    mock_repo = MagicMock()
    mock_repo.hashes_by_slug.return_value = {}

    load_all_content(root, mock_repo)

    upserted_slugs = []
    for call in mock_repo.upsert.call_args_list:
        item = call[0][0] if call[0] else call[1].get("item")
        if item is not None:
            upserted_slugs.append(item.slug)
    # Only the live one should appear; the draft must be invisible.
    assert "live" in upserted_slugs
    assert "x-s00-reading-draft" not in upserted_slugs


# ---------------------------------------------------------------------------
# content_generation stub
# ---------------------------------------------------------------------------


def test_generate_draft_returns_placeholder_with_section_metadata():
    track = _fake_track()
    draft = content_generation.generate_draft_for_node(
        track=track, section_idx=0, kind="reading",
    )
    assert draft.is_placeholder is True
    assert draft.kind == "reading"
    assert draft.slug == "arena_3-s00-reading-draft"
    # Frontmatter has the right shape
    assert draft.frontmatter_md.startswith("---\n")
    assert "kind: reading" in draft.frontmatter_md
    # PLACEHOLDER marker so operator can't miss it
    assert "[PLACEHOLDER]" in draft.frontmatter_md
    # Carries forward axes + domain_tags from the section
    assert "algorithmic" in draft.frontmatter_md
    assert "python" in draft.frontmatter_md


def test_generate_draft_rejects_invalid_kind():
    track = _fake_track()
    with pytest.raises(content_generation.GenerationError):
        content_generation.generate_draft_for_node(
            track=track, section_idx=0, kind="garbage",  # type: ignore[arg-type]
        )


def test_generate_draft_rejects_out_of_range_section():
    track = _fake_track()
    with pytest.raises(content_generation.GenerationError, match="out of range"):
        content_generation.generate_draft_for_node(
            track=track, section_idx=99, kind="reading",
        )


def test_generate_then_write_then_promote_is_roundtrippable(tmp_path: Path):
    """End-to-end: stub generates → write_draft persists → promote moves
    to live. Verifies the substrate works without any LLM call."""
    root = _content_root(tmp_path)
    track = _fake_track()
    draft = content_generation.generate_draft_for_node(
        track=track, section_idx=0, kind="reading",
    )
    content_drafts.write_draft(
        root, kind=draft.kind, slug=draft.slug, frontmatter_md=draft.frontmatter_md,
    )
    # Visible in the review list
    assert any(d.slug == draft.slug for d in content_drafts.list_drafts(root, "reading"))
    # Promote moves it to live
    dst = content_drafts.promote(root, "reading", draft.slug)
    assert dst.exists()
    assert content_drafts.list_drafts(root, "reading") == []
