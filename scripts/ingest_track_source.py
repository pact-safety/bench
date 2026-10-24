#!/usr/bin/env python3
"""CLI wrapper for ``app.services.track_ingest``.

Reads a track-source manifest (YAML), validates it, topologically
sorts each chapter's node graph, and emits a track config file
matching the existing loader's shape.

Usage:

    python scripts/ingest_track_source.py \\
        --manifest content/tracks/manifests/arena_3.yaml \\
        --out content/tracks/arena_3_ingested.md

    python scripts/ingest_track_source.py \\
        --manifest content/tracks/manifests/arena_3.yaml \\
        --dry-run  # print to stdout, do not write

By default (no ``--out``, no ``--dry-run``), the script refuses to
proceed. This is intentional — a successful ingestion produces a track
config that the operator should review before committing. Either ask
explicitly for a target path or ask for a dry-run preview.

The CLI is intentionally thin. All logic lives in
``app.services.track_ingest`` so it stays unit-testable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make app importable when run as a top-level script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.track_ingest import ManifestError, ingest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest_track_source",
        description="Ingest a track-source manifest into a persisted track config.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the YAML manifest file.",
    )
    parser.add_argument(
        "--body",
        type=Path,
        default=None,
        help=(
            "Optional path to a markdown file whose contents are appended "
            "after the YAML frontmatter (long-form notes about the track)."
        ),
    )
    out_group = parser.add_mutually_exclusive_group(required=True)
    out_group.add_argument(
        "--out",
        type=Path,
        help="Path to write the rendered track config (e.g. content/tracks/<slug>.md).",
    )
    out_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rendered track config to stdout; do not write any file.",
    )

    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"error: manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    manifest_text = args.manifest.read_text(encoding="utf-8")

    body_md = ""
    if args.body is not None:
        if not args.body.exists():
            print(f"error: body file not found: {args.body}", file=sys.stderr)
            return 2
        body_md = args.body.read_text(encoding="utf-8")

    try:
        rendered, loaded = ingest(manifest_text, body_md=body_md)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        sys.stdout.write(rendered)
        print(
            f"\n# Dry-run: would write track {loaded.slug!r} "
            f"({loaded.total_sections} sections, "
            f"{len(loaded.chapters)} chapters)",
            file=sys.stderr,
        )
        return 0

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {out_path} — track {loaded.slug!r}, "
        f"{loaded.total_sections} sections, {len(loaded.chapters)} chapters",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
