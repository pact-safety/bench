#!/usr/bin/env python3
"""Export a public corpus bundle from the repository.

This script copies a curated subset of authored content/docs, validates
markdown frontmatter against a denylist of operator/user-specific keys,
and generates taxonomy + template files in a standalone output folder.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from textwrap import dedent

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.assessment import AXES  # noqa: E402
from app.services.skill_stats import STATS  # noqa: E402


DEFAULT_OUT = Path("dist/public-corpus")
EXPORT_CONTENT_DIRS: tuple[Path, ...] = (
    Path("content/problems"),
    Path("content/readings"),
    Path("content/videos"),
    Path("content/podcasts"),
    Path("content/exercises"),
)
DOCS_TO_COPY: tuple[Path, ...] = (
    Path("docs/architecture/tag-vocabulary.md"),
    Path("docs/architecture/imposter-syndrome.md"),
    Path("docs/architecture/rest-days.md"),
    Path("docs/architecture/tracks.md"),
)

# Keys that indicate private operator metadata or direct user identity.
# The export fails fast if any exported markdown frontmatter includes
# these keys (case-insensitive).
DISALLOWED_FRONTMATTER_KEYS = frozenset(
    {
        "operator",
        "operator_id",
        "operator_email",
        "operator_notes",
        "operator_note",
        "owner_id",
        "owner_email",
        "owner_notes",
        "owner_note",
        "internal_notes",
        "internal_note",
        "private_notes",
        "private_note",
        "user_id",
        "user_email",
        "user_name",
        "user_notes",
        "submitted_by",
        "assigned_to",
        "assignee",
    }
)

README_TEMPLATE = dedent(
    """\
    # Public Interview-Prep Corpus

    > Template note: replace placeholders with your operator voice before publishing.

    ## What this corpus is
    {{OPERATOR_OVERVIEW}}

    ## Who this is for
    {{OPERATOR_AUDIENCE}}

    ## How to use these materials
    {{OPERATOR_USAGE_GUIDE}}

    ## Curation philosophy
    {{OPERATOR_CURATION_NOTES}}

    ## Contact / attribution
    {{OPERATOR_CONTACT}}
    """
).strip() + "\n"

MIT_LICENSE_TEXT = dedent(
    """\
    MIT License

    Copyright (c) [year] [copyright holder]

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
    """
).strip() + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a public corpus bundle.")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output directory (default: dist/public-corpus)",
    )
    return parser.parse_args()


def _resolve_output_dir(raw_out: str) -> Path:
    out = Path(raw_out).expanduser()
    if not out.is_absolute():
        out = Path.cwd() / out
    return out.resolve()


def _ensure_safe_output_dir(out_dir: Path) -> None:
    forbidden = {
        Path("/").resolve(),
        REPO_ROOT.resolve(),
        REPO_ROOT.parent.resolve(),
    }
    if out_dir in forbidden:
        raise ValueError(f"Refusing unsafe output path: {out_dir}")


def _parse_frontmatter(markdown: str, path: Path) -> dict[str, object]:
    if not markdown.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter fence")

    end = markdown.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter fence")

    raw_frontmatter = markdown[4:end]
    try:
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML frontmatter ({exc})") from exc

    if not isinstance(frontmatter, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")

    return frontmatter


def _validate_frontmatter(path: Path) -> None:
    frontmatter = _parse_frontmatter(path.read_text(encoding="utf-8"), path)
    normalized_keys = {str(key).strip().lower() for key in frontmatter}
    blocked = sorted(normalized_keys & DISALLOWED_FRONTMATTER_KEYS)
    if blocked:
        blocked_list = ", ".join(blocked)
        raise ValueError(
            f"{path}: disallowed frontmatter key(s) detected: {blocked_list}. "
            "Remove operator/user-specific fields before export."
        )


def _copy_file(src: Path, out_dir: Path) -> None:
    rel = src.relative_to(REPO_ROOT)
    dst = out_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_export_content(out_dir: Path) -> None:
    for rel_dir in EXPORT_CONTENT_DIRS:
        src_dir = REPO_ROOT / rel_dir
        if not src_dir.exists():
            raise FileNotFoundError(f"Missing expected content directory: {rel_dir}")

        for src in sorted(src_dir.rglob("*")):
            if src.is_dir():
                continue
            if src.suffix.lower() == ".md":
                _validate_frontmatter(src)
            _copy_file(src, out_dir)


def _copy_docs(out_dir: Path) -> None:
    for rel_path in DOCS_TO_COPY:
        src = REPO_ROOT / rel_path
        if not src.exists():
            raise FileNotFoundError(f"Missing expected docs file: {rel_path}")
        _copy_file(src, out_dir)


def _extract_domain_tags_section() -> str:
    tag_vocab_path = REPO_ROOT / "docs/architecture/tag-vocabulary.md"
    lines = tag_vocab_path.read_text(encoding="utf-8").splitlines()

    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("### Sub-topic `domain_tags`"):
            start_idx = idx
            break

    if start_idx is None:
        raise ValueError(
            "Could not find the domain-tags vocabulary section heading in "
            "docs/architecture/tag-vocabulary.md"
        )

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break

    section = "\n".join(lines[start_idx:end_idx]).strip()
    if not section:
        raise ValueError("Domain-tags vocabulary section is empty")
    return section


def _write_taxonomy_files(out_dir: Path) -> None:
    taxonomy_dir = out_dir / "taxonomy"
    taxonomy_dir.mkdir(parents=True, exist_ok=True)

    axes_lines = "\n".join(f"- `{axis}`" for axis in AXES)
    (taxonomy_dir / "axes.md").write_text(
        dedent(
            f"""\
            # Axes

            Generated from `app/services/assessment.py:AXES`.

            {axes_lines}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stats_sections = []
    for stat in STATS:
        axes = "\n".join(f"- `{axis}`" for axis in stat.axes)
        stats_sections.append(f"## {stat.label} (`{stat.key}`)\n\n{axes}")
    stats_body = "\n\n".join(stats_sections)
    (taxonomy_dir / "stat-groups.md").write_text(
        dedent(
            f"""\
            # Stat groups

            Generated from `app/services/skill_stats.py:STATS`.

            {stats_body}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    section = _extract_domain_tags_section()
    (taxonomy_dir / "sub-topics.md").write_text(
        dedent(
            f"""\
            # Sub-topics

            Generated from the domain-tags vocabulary section in
            `docs/architecture/tag-vocabulary.md`.

            {section}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_templates(out_dir: Path) -> None:
    (out_dir / "README.md").write_text(README_TEMPLATE, encoding="utf-8")
    (out_dir / "LICENSE").write_text(MIT_LICENSE_TEXT, encoding="utf-8")


def export_public_corpus(out_dir: Path) -> None:
    _ensure_safe_output_dir(out_dir)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _copy_export_content(out_dir)
    _write_taxonomy_files(out_dir)
    _copy_docs(out_dir)
    _write_templates(out_dir)


def main() -> int:
    args = _parse_args()
    out_dir = _resolve_output_dir(args.out)
    export_public_corpus(out_dir)
    print(f"Export complete: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
