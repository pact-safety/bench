"""Track-source ingestion service.

Phase 2 / sub-issue A of the dynamic curriculum engine ([BEN-87]).

Reads a YAML manifest describing a curriculum source (MVP: a GitHub
notebook repo) and emits a track config file matching the existing
``app/services/tracks.py`` loader's expected shape.

The manifest declares a node graph per chapter: every node has an ``id``
and an optional ``prereqs`` list referencing other node IDs in the same
chapter. The ingestion pipeline:

1. Validates the manifest's top-level structure.
2. Validates per-chapter that every prereq reference resolves.
3. Cycle-detects each chapter's DAG.
4. Topologically sorts each chapter (stable; ties broken by declaration order).
5. Emits a track config in the existing loader's shape (chapter -> sections).
6. Round-trips the emitted output through the loader to validate shape.

The output is a flat ``chapters[] -> sections[]`` list per the Phase 1
schema. The DAG is consumed at ingest time; the runtime sees only the
linear cursor that already powers the picker yield.

See ``docs/architecture/tracks.md`` Phase 2 section for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import tracks


_ALLOWED_SOURCE_KINDS = frozenset({"github_notebooks"})


class ManifestError(ValueError):
    """Raised when a manifest fails validation."""


@dataclass(frozen=True)
class _ManifestNode:
    id: str
    title: str
    url: str
    kind: str
    duration_min: int | None
    domain_tags: tuple[str, ...]
    axes: tuple[str, ...]
    prereqs: tuple[str, ...]
    declaration_order: int  # used for stable tie-breaking inside topo sort


@dataclass(frozen=True)
class _ManifestChapter:
    title: str
    nodes: tuple[_ManifestNode, ...]


@dataclass(frozen=True)
class Manifest:
    source_kind: str
    source_repo_url: str
    track_slug: str
    track_title: str
    track_description: str
    chapters: tuple[_ManifestChapter, ...]


# ---------------------------------------------------------------------------
# Parse + validate
# ---------------------------------------------------------------------------


def _require_str(raw: Any, *, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"missing or empty required string field: {field}")
    return raw.strip()


def _require_mapping(raw: Any, *, field: str) -> dict:
    if not isinstance(raw, dict):
        raise ManifestError(f"{field} must be a mapping")
    return raw


def _require_list(raw: Any, *, field: str) -> list:
    if not isinstance(raw, list):
        raise ManifestError(f"{field} must be a list")
    return raw


def _as_string_tuple(raw: Any, *, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    items = _require_list(raw, field=field)
    out: list[str] = []
    for idx, item in enumerate(items):
        if not isinstance(item, str):
            raise ManifestError(f"{field}[{idx}] must be a string")
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def _parse_node(raw: Any, *, chapter_idx: int, node_idx: int) -> _ManifestNode:
    field = f"chapters[{chapter_idx}].nodes[{node_idx}]"
    raw_dict = _require_mapping(raw, field=field)

    node_id = _require_str(raw_dict.get("id"), field=f"{field}.id")
    title = _require_str(raw_dict.get("title"), field=f"{field}.title")
    url = _require_str(raw_dict.get("url"), field=f"{field}.url")
    kind = _require_str(raw_dict.get("kind"), field=f"{field}.kind")

    duration_raw = raw_dict.get("duration_min")
    if duration_raw in (None, ""):
        duration_min: int | None = None
    else:
        try:
            duration_min = int(duration_raw)
        except (TypeError, ValueError) as exc:
            raise ManifestError(
                f"{field}.duration_min must be an integer (got {duration_raw!r})"
            ) from exc

    return _ManifestNode(
        id=node_id,
        title=title,
        url=url,
        kind=kind,
        duration_min=duration_min,
        domain_tags=_as_string_tuple(raw_dict.get("domain_tags"), field=f"{field}.domain_tags"),
        axes=_as_string_tuple(raw_dict.get("axes"), field=f"{field}.axes"),
        prereqs=_as_string_tuple(raw_dict.get("prereqs"), field=f"{field}.prereqs"),
        declaration_order=node_idx,
    )


def _parse_chapter(raw: Any, *, chapter_idx: int) -> _ManifestChapter:
    field = f"chapters[{chapter_idx}]"
    raw_dict = _require_mapping(raw, field=field)
    title = _require_str(raw_dict.get("title"), field=f"{field}.title")

    raw_nodes = _require_list(raw_dict.get("nodes", []), field=f"{field}.nodes")
    nodes = tuple(
        _parse_node(raw_node, chapter_idx=chapter_idx, node_idx=idx)
        for idx, raw_node in enumerate(raw_nodes)
    )

    if not nodes:
        raise ManifestError(f"{field}.nodes must be non-empty")

    # Per-chapter uniqueness of IDs
    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            raise ManifestError(f"{field}: duplicate node id {node.id!r}")
        seen.add(node.id)

    return _ManifestChapter(title=title, nodes=nodes)


def parse_manifest(text: str) -> Manifest:
    """Parse and validate a manifest YAML string.

    Raises ``ManifestError`` on any structural or referential failure.
    Does not write anything; safe to call on untrusted input.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("top-level manifest must be a mapping")

    source = _require_mapping(raw.get("source"), field="source")
    source_kind = _require_str(source.get("kind"), field="source.kind")
    if source_kind not in _ALLOWED_SOURCE_KINDS:
        raise ManifestError(
            f"source.kind={source_kind!r} not supported; MVP allows {sorted(_ALLOWED_SOURCE_KINDS)}"
        )
    source_repo_url = _require_str(source.get("repo_url"), field="source.repo_url")

    track = _require_mapping(raw.get("track"), field="track")
    track_slug = _require_str(track.get("slug"), field="track.slug")
    track_title = _require_str(track.get("title"), field="track.title")
    track_description = str(track.get("description", "")).strip()

    raw_chapters = _require_list(raw.get("chapters", []), field="chapters")
    if not raw_chapters:
        raise ManifestError("chapters must be non-empty")

    chapters = tuple(
        _parse_chapter(raw_chapter, chapter_idx=idx)
        for idx, raw_chapter in enumerate(raw_chapters)
    )

    # Cross-chapter validation: prereqs may not reference IDs outside the
    # same chapter. The design doc explains why (chapter boundaries are
    # honored; cross-chapter ordering is implicit by chapter order).
    for chapter_idx, chapter in enumerate(chapters):
        ids_in_chapter = {n.id for n in chapter.nodes}
        for node in chapter.nodes:
            for prereq in node.prereqs:
                if prereq not in ids_in_chapter:
                    raise ManifestError(
                        f"chapters[{chapter_idx}].nodes[id={node.id!r}].prereqs references "
                        f"{prereq!r}, which is not declared in the same chapter. "
                        "Cross-chapter prereqs are not allowed (see docs/architecture/tracks.md)."
                    )

    return Manifest(
        source_kind=source_kind,
        source_repo_url=source_repo_url,
        track_slug=track_slug,
        track_title=track_title,
        track_description=track_description,
        chapters=chapters,
    )


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def _topo_sort(nodes: tuple[_ManifestNode, ...]) -> tuple[_ManifestNode, ...]:
    """Lexicographic topological sort: at each step, pick the
    earliest-declared not-yet-placed node whose prereqs are all placed.

    This matters when an earlier-declared node becomes ready later than
    a later-declared node. A plain FIFO Kahn would let the later
    declaration win (it entered the ready queue first). For curriculum
    authoring, the operator's declaration order is the intent: if 1.3.x
    is declared before 1.5.x, the 1.3.x branch should complete before
    1.5.x opens, even though both unlock at the same point in the DAG.

    Implementation: O(n^2) scan-then-place. Curriculum chapters are
    small (ARENA's largest is 13 nodes); the constant-factor win of a
    heap doesn't justify the readability cost.

    Raises ``ManifestError`` on any cycle.
    """
    by_id = {n.id: n for n in nodes}
    ordered_by_decl = sorted(nodes, key=lambda n: n.declaration_order)

    placed: set[str] = set()
    result: list[_ManifestNode] = []

    while len(placed) < len(nodes):
        # Scan in declaration order; pick the first node whose prereqs are
        # all already placed.
        for node in ordered_by_decl:
            if node.id in placed:
                continue
            if all(prereq in placed for prereq in node.prereqs):
                placed.add(node.id)
                result.append(node)
                break
        else:
            # No node could be placed this pass → cycle.
            remaining = [n.id for n in ordered_by_decl if n.id not in placed]
            raise ManifestError(
                "cycle detected in chapter prereqs involving nodes: "
                + ", ".join(sorted(remaining))
            )

    # Defensive: also catch self-loops, which the prereq scan above
    # would handle (a self-loop means prereq not yet placed → blocked
    # forever → cycle), but make the error message explicit.
    for node in nodes:
        if node.id in node.prereqs:
            raise ManifestError(
                f"cycle detected: node {node.id!r} lists itself as a prereq"
            )

    return tuple(result)


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def _yaml_string(value: str) -> str:
    """Render a string with double-quotes for the YAML scalar form
    used in existing track configs."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _emit_section_yaml(
    node: _ManifestNode,
    *,
    depends_on_flat_idxs: tuple[int, ...] = (),
) -> list[str]:
    """Emit a single section block as a list of YAML lines (no trailing newline).

    ``depends_on_flat_idxs`` bridges BEN-87's per-chapter string node IDs
    into BEN-89's runtime schema (``TrackSection.depends_on`` as flat
    integer indexes across all chapters). Empty tuple = no explicit
    dependency; BEN-89's loader falls back to sequential (previous-section).
    """
    lines = [
        f"      - title: {_yaml_string(node.title)}",
        f"        url: {_yaml_string(node.url)}",
        f"        kind: {node.kind}",
    ]
    if node.duration_min is not None:
        lines.append(f"        duration_min: {node.duration_min}")
    if node.domain_tags:
        lines.append(
            "        domain_tags: [" + ", ".join(t for t in node.domain_tags) + "]"
        )
    if node.axes:
        lines.append("        axes: [" + ", ".join(a for a in node.axes) + "]")
    if depends_on_flat_idxs:
        lines.append(
            "        depends_on: [" + ", ".join(str(i) for i in depends_on_flat_idxs) + "]"
        )
    return lines


def render_track_config(manifest: Manifest, *, body_md: str = "") -> str:
    """Render an ordered manifest into a track config string.

    Output matches the existing loader's expected shape — same YAML
    frontmatter fields as the hand-authored ``content/tracks/arena_3.md``.
    The optional ``body_md`` is appended after the frontmatter fence so
    the operator can carry over long-form notes from the manifest.

    Bridges BEN-87 (per-chapter string node IDs in the manifest) into
    BEN-89 (flat-integer ``depends_on`` indexes in the runtime schema).
    For every node with declared prereqs, the rendered section gains a
    ``depends_on: [flat_idx, ...]`` entry so BEN-89's checkpoint gating
    respects the real DAG instead of falling back to sequential.
    """
    # First pass: topo-sort each chapter and compute (chapter_idx, sorted
    # node list, flat index per node id). Sorted node list comes from
    # topo_sort; the flat index for the j-th node in chapter i is
    # (sum of len(prev chapters)) + j.
    sorted_chapters: list[tuple[str, tuple[_ManifestNode, ...]]] = []
    flat_idx_by_chapter_and_id: dict[int, dict[str, int]] = {}
    cumulative = 0
    for chapter_idx, chapter in enumerate(manifest.chapters):
        ordered = _topo_sort(chapter.nodes)
        sorted_chapters.append((chapter.title, ordered))
        id_to_flat: dict[str, int] = {}
        for offset, node in enumerate(ordered):
            id_to_flat[node.id] = cumulative + offset
        flat_idx_by_chapter_and_id[chapter_idx] = id_to_flat
        cumulative += len(ordered)

    lines: list[str] = ["---"]
    lines.append(f"slug: {manifest.track_slug}")
    lines.append(f"title: {_yaml_string(manifest.track_title)}")
    if manifest.track_description:
        lines.append(f"description: {_yaml_string(manifest.track_description)}")
    lines.append(f"source_url: {_yaml_string(manifest.source_repo_url)}")
    lines.append("chapters:")
    for chapter_idx, (chapter_title, ordered_nodes) in enumerate(sorted_chapters):
        id_to_flat = flat_idx_by_chapter_and_id[chapter_idx]
        lines.append(f"  - title: {_yaml_string(chapter_title)}")
        lines.append("    sections:")
        for node in ordered_nodes:
            # Map prereqs (string IDs, validated at parse time to be
            # in-chapter) to flat indexes. Sort ascending so the emitted
            # output is deterministic regardless of manifest declaration
            # order of prereqs.
            depends_on = tuple(
                sorted(id_to_flat[prereq] for prereq in node.prereqs)
            )
            lines.extend(_emit_section_yaml(node, depends_on_flat_idxs=depends_on))
        lines.append("")  # blank line between chapters for readability
    if lines[-1] == "":
        lines.pop()
    lines.append("---")
    if body_md.strip():
        lines.append("")
        lines.append(body_md.rstrip())
    lines.append("")  # final newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Round-trip validation
# ---------------------------------------------------------------------------


def _validate_roundtrip(rendered: str, *, manifest: Manifest) -> tracks.Track:
    """Round-trip the rendered output through the existing loader.

    Raises ``ManifestError`` if the loader rejects the output, or if the
    re-loaded track's slug/section count diverges from the manifest.
    """
    # Use a tmp path that mimics the loader's expectations (it just needs
    # to read .read_text(); the path itself only shows up in errors).
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    try:
        try:
            loaded = tracks._parse_track_file(tmp_path)
        except ValueError as exc:
            raise ManifestError(
                f"rendered track config failed loader round-trip: {exc}"
            ) from exc

        if loaded.slug != manifest.track_slug:
            raise ManifestError(
                f"rendered slug={loaded.slug!r} diverges from manifest "
                f"slug={manifest.track_slug!r}"
            )
        expected_section_count = sum(len(c.nodes) for c in manifest.chapters)
        actual_section_count = loaded.total_sections
        if expected_section_count != actual_section_count:
            raise ManifestError(
                f"rendered section count={actual_section_count} diverges from "
                f"manifest count={expected_section_count}"
            )
        return loaded
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public pipeline entry
# ---------------------------------------------------------------------------


def ingest(manifest_text: str, *, body_md: str = "") -> tuple[str, tracks.Track]:
    """Full pipeline: parse manifest, sort, render, round-trip-validate.

    Returns ``(rendered_text, loaded_track)``. Caller decides whether to
    write the rendered text to disk; the loaded track is provided so the
    caller can introspect (e.g., for CLI confirmation output).

    Raises ``ManifestError`` on any failure along the pipeline.
    """
    manifest = parse_manifest(manifest_text)
    rendered = render_track_config(manifest, body_md=body_md)
    loaded = _validate_roundtrip(rendered, manifest=manifest)
    return rendered, loaded
