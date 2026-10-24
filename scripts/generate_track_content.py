#!/usr/bin/env python3
"""CLI for the BEN-88 per-node content generator (substrate-only).

Currently produces a *placeholder* draft per (section, kind) tuple
because the live LLM call in ``app/services/content_generation.py`` is
deliberately stubbed pending operator review of the substrate. The
script wires the rest of the pipeline end-to-end so the review surface
at ``/tracks/<slug>/sections/<idx>/drafts`` has something to show.

Usage:

    # Generate one reading draft for ARENA Chapter 0 section 0:
    python scripts/generate_track_content.py \\
        --track arena_3 --section 0 --kind reading

    # Generate all 4 kinds for one section:
    python scripts/generate_track_content.py \\
        --track arena_3 --section 0 --all-kinds

    # Generate one kind for every section in a track:
    python scripts/generate_track_content.py \\
        --track arena_3 --all-sections --kind exercise

Drafts land under ``content/<kind>/_drafts/<slug>.md``. The slug is
``<track_slug>-s<section_idx>-<kind>-draft`` so re-runs are detected as
collisions (the script refuses to overwrite — operator discards the old
draft first, or accepts the existing one).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.config import load_config  # noqa: E402
from app.services import content_drafts, content_generation  # noqa: E402
from app.services import tracks as tracks_service  # noqa: E402


_VALID_KINDS = ("reading", "video", "podcast", "exercise")


def _load_track(slug: str, content_dir: Path) -> tracks_service.Track:
    tracks_dir = content_dir / "tracks"
    all_tracks = tracks_service.load_all_tracks(tracks_dir)
    if slug not in all_tracks:
        available = sorted(all_tracks.keys())
        raise SystemExit(
            f"unknown track {slug!r}. Available: {available}"
        )
    return all_tracks[slug]


def _generate_one(
    *,
    track: tracks_service.Track,
    section_idx: int,
    kind: str,
    content_dir: Path,
    dry_run: bool,
) -> str:
    """Generate one draft. Returns a status string."""
    draft = content_generation.generate_draft_for_node(
        track=track, section_idx=section_idx, kind=kind,
    )
    if dry_run:
        return (
            f"  [dry-run] would write {kind}/{draft.slug}.md "
            f"(placeholder={draft.is_placeholder})"
        )
    try:
        path = content_drafts.write_draft(
            content_dir,
            kind=draft.kind,
            slug=draft.slug,
            frontmatter_md=draft.frontmatter_md,
        )
        return f"  ✓ wrote {path.relative_to(REPO_ROOT)}"
    except content_drafts.DraftError as exc:
        return f"  ⚠ skip {kind}/{draft.slug}: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_track_content",
        description=(
            "Generate per-node content drafts for a track (BEN-88 substrate). "
            "Currently produces placeholders; LLM wiring is operator-deferred."
        ),
    )
    parser.add_argument("--track", required=True, help="Track slug (e.g., arena_3)")

    section_group = parser.add_mutually_exclusive_group(required=True)
    section_group.add_argument(
        "--section", type=int, help="Section index (0-based, flat across chapters)"
    )
    section_group.add_argument(
        "--all-sections", action="store_true",
        help="Generate for every section in the track"
    )

    kind_group = parser.add_mutually_exclusive_group(required=True)
    kind_group.add_argument(
        "--kind", choices=_VALID_KINDS, help="One content kind"
    )
    kind_group.add_argument(
        "--all-kinds", action="store_true",
        help="Generate one draft for each of: reading, video, podcast, exercise"
    )

    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print intended actions without writing files"
    )

    args = parser.parse_args(argv)

    config = load_config()
    content_dir = config.app.content_dir
    track = _load_track(args.track, content_dir)

    if args.all_sections:
        section_idxs = list(range(track.total_sections))
    else:
        section_idxs = [args.section]

    kinds = list(_VALID_KINDS) if args.all_kinds else [args.kind]

    print(f"# Track: {track.title} ({track.slug})", file=sys.stderr)
    for section_idx in section_idxs:
        section = tracks_service.section_at(track, section_idx)
        section_label = section.title if section else f"<idx={section_idx}>"
        print(f"## Section {section_idx}: {section_label}", file=sys.stderr)
        for kind in kinds:
            try:
                status = _generate_one(
                    track=track,
                    section_idx=section_idx,
                    kind=kind,
                    content_dir=content_dir,
                    dry_run=args.dry_run,
                )
                print(status, file=sys.stderr)
            except content_generation.GenerationError as exc:
                print(f"  ✗ error: {exc}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
