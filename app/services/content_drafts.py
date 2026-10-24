"""Content draft management for BEN-88 (Tracks B).

The dynamic curriculum engine generates per-node multi-modal content
(readings, videos, exercises, debugging problems). The hard constraint
from the operator: **never auto-publish.** Generated content lands in
``content/<kind>/_drafts/<slug>.md`` first, where it is NOT picked up
by ``load_all_content`` (the loader uses non-recursive ``glob('*.md')``,
so subdirectories are excluded by construction).

This module owns the post-generation lifecycle:

- ``list_drafts(kind)``           — enumerate pending drafts for a kind
- ``list_all_drafts()``           — across all kinds
- ``read_draft(kind, slug)``      — load a single draft file
- ``promote(kind, slug)``         — move from ``_drafts/`` to live
- ``discard(kind, slug)``         — delete a draft permanently

Drafts carry the same frontmatter as live content; the only difference
is location on disk. This keeps the schema flat and lets the operator
preview a draft via the existing renderer just by moving it.

Promote is an `os.replace` of the file path. It's atomic on POSIX, so a
crash mid-promote can't leave the system in a half-state.

This module does NOT call any LLM. ``content_generation.py`` produces
drafts; this module manages them after.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_VALID_KINDS = frozenset({"reading", "video", "podcast", "exercise"})
_KIND_TO_SUBDIR = {
    "reading": "readings",
    "video": "videos",
    "podcast": "podcasts",
    "exercise": "exercises",
}
_DRAFTS_SUBDIR = "_drafts"


class DraftError(ValueError):
    """Raised when a draft operation can't be performed."""


@dataclass(frozen=True)
class Draft:
    kind: str
    slug: str
    path: Path
    title: str  # parsed from frontmatter; empty string if absent

    @property
    def filename(self) -> str:
        return self.path.name


def _require_valid_kind(kind: str) -> None:
    if kind not in _VALID_KINDS:
        raise DraftError(
            f"unknown kind {kind!r}; valid: {sorted(_VALID_KINDS)}"
        )


def _drafts_dir_for(content_dir: Path, kind: str) -> Path:
    _require_valid_kind(kind)
    return content_dir / _KIND_TO_SUBDIR[kind] / _DRAFTS_SUBDIR


def _live_dir_for(content_dir: Path, kind: str) -> Path:
    _require_valid_kind(kind)
    return content_dir / _KIND_TO_SUBDIR[kind]


def _extract_title(text: str) -> str:
    """Cheap frontmatter title extraction — operator-facing only; we
    just want a label for the review list, not a parsed model."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    for line in text[4:end].splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            val = stripped[len("title:"):].strip()
            # Strip wrapping quotes if present.
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            return val
    return ""


def _read_draft(path: Path, *, kind: str) -> Draft:
    text = path.read_text(encoding="utf-8")
    return Draft(
        kind=kind,
        slug=path.stem,
        path=path,
        title=_extract_title(text),
    )


def list_drafts(content_dir: Path, kind: str) -> list[Draft]:
    """All pending drafts for one kind. Empty list when the _drafts/
    directory doesn't exist (the common case at startup)."""
    drafts_dir = _drafts_dir_for(content_dir, kind)
    if not drafts_dir.exists():
        return []
    return [
        _read_draft(p, kind=kind)
        for p in sorted(drafts_dir.glob("*.md"))
    ]


def list_all_drafts(content_dir: Path) -> list[Draft]:
    """All pending drafts across every kind, sorted (kind, slug)."""
    out: list[Draft] = []
    for kind in sorted(_VALID_KINDS):
        out.extend(list_drafts(content_dir, kind))
    return out


def read_draft(content_dir: Path, kind: str, slug: str) -> Draft | None:
    drafts_dir = _drafts_dir_for(content_dir, kind)
    path = drafts_dir / f"{slug}.md"
    if not path.exists():
        return None
    return _read_draft(path, kind=kind)


def promote(content_dir: Path, kind: str, slug: str) -> Path:
    """Move a draft from ``_drafts/`` to the live kind directory.

    Returns the destination path. Raises ``DraftError`` if:
    - the kind isn't valid
    - the draft doesn't exist
    - a live file with the same slug already exists (no auto-overwrite)

    Atomic via ``os.replace``. If the destination disk is on a different
    filesystem (typically not the case — both paths share a content
    root), ``os.replace`` will still atomically rename within one volume.
    """
    _require_valid_kind(kind)
    drafts_dir = _drafts_dir_for(content_dir, kind)
    live_dir = _live_dir_for(content_dir, kind)
    src = drafts_dir / f"{slug}.md"
    dst = live_dir / f"{slug}.md"
    if not src.exists():
        raise DraftError(f"draft not found: {kind}/{slug}")
    if dst.exists():
        raise DraftError(
            f"a live {kind} with slug {slug!r} already exists at {dst}; "
            "promote refuses to overwrite. Rename the draft or remove the "
            "live file first."
        )
    live_dir.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return dst


def discard(content_dir: Path, kind: str, slug: str) -> bool:
    """Permanently delete a draft. Returns True on success, False when
    the draft doesn't exist (operator probably double-clicked Discard;
    don't surface that as an error)."""
    _require_valid_kind(kind)
    drafts_dir = _drafts_dir_for(content_dir, kind)
    path = drafts_dir / f"{slug}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def write_draft(
    content_dir: Path,
    *,
    kind: str,
    slug: str,
    frontmatter_md: str,
) -> Path:
    """Write a new draft. Raises ``DraftError`` if a draft with this
    slug already exists for this kind (no auto-overwrite — the generator
    should pick a unique slug per node, and a collision means a bug).

    ``frontmatter_md`` is the full markdown file content, including the
    leading ``---`` frontmatter fence. Callers (the generator) are
    responsible for producing valid content.
    """
    _require_valid_kind(kind)
    drafts_dir = _drafts_dir_for(content_dir, kind)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{slug}.md"
    if path.exists():
        raise DraftError(
            f"draft already exists for {kind}/{slug}; "
            "regenerate to a different slug or discard first"
        )
    path.write_text(frontmatter_md, encoding="utf-8")
    return path
