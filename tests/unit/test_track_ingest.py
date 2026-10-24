"""Tests for app.services.track_ingest.

BEN-87 sub-issue A. Covers:

- Manifest parsing + structural validation
- Cross-chapter prereq references rejected
- Cycle detection
- Topological sort respects prereqs + stable on ties (manifest order)
- Rendered output round-trips through the existing track loader
- Real ARENA 3.0 manifest under content/tracks/manifests/ ingests cleanly
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.services.track_ingest import (
    ManifestError,
    ingest,
    parse_manifest,
    render_track_config,
)
from app.services.tracks import _parse_track_file


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def _minimal_manifest_yaml(prereqs_b: str = "[]") -> str:
    return dedent(
        f"""
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: test_track
          title: "Test Track"
          description: "Unit test fixture"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "Node A"
                url: "https://example.com/a"
                kind: external_reading
                duration_min: 60
                domain_tags: [foo]
                axes: [algorithmic]
                prereqs: []
              - id: "b"
                title: "Node B"
                url: "https://example.com/b"
                kind: external_exercise
                duration_min: 120
                domain_tags: [bar]
                axes: [algorithmic]
                prereqs: {prereqs_b}
        """
    ).strip()


def test_minimal_manifest_parses():
    m = parse_manifest(_minimal_manifest_yaml())
    assert m.track_slug == "test_track"
    assert m.source_kind == "github_notebooks"
    assert len(m.chapters) == 1
    assert len(m.chapters[0].nodes) == 2


def test_unsupported_source_kind_rejected():
    bad = _minimal_manifest_yaml().replace("github_notebooks", "pdf_dump")
    with pytest.raises(ManifestError, match="source.kind"):
        parse_manifest(bad)


def test_missing_required_field_rejected():
    bad = _minimal_manifest_yaml().replace("slug: test_track", "")
    with pytest.raises(ManifestError, match="track.slug"):
        parse_manifest(bad)


def test_duplicate_node_id_within_chapter_rejected():
    bad = _minimal_manifest_yaml().replace('id: "b"', 'id: "a"')
    with pytest.raises(ManifestError, match="duplicate node id"):
        parse_manifest(bad)


def test_empty_chapters_rejected():
    bad = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: empty
          title: "Empty"
        chapters: []
        """
    ).strip()
    with pytest.raises(ManifestError, match="chapters must be non-empty"):
        parse_manifest(bad)


# ---------------------------------------------------------------------------
# Cross-chapter prereq rejection
# ---------------------------------------------------------------------------


def test_cross_chapter_prereq_rejected():
    bad = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: cross
          title: "Cross"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
          - title: "Chapter 1"
            nodes:
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]  # cross-chapter reference — not allowed
        """
    ).strip()
    with pytest.raises(ManifestError, match="Cross-chapter prereqs are not allowed"):
        parse_manifest(bad)


def test_unknown_prereq_reference_rejected():
    bad = _minimal_manifest_yaml(prereqs_b='["nonexistent"]')
    with pytest.raises(ManifestError, match="not declared in the same chapter"):
        parse_manifest(bad)


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def test_cycle_in_chapter_dag_rejected():
    bad = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: cyclic
          title: "Cyclic"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: ["b"]
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]
        """
    ).strip()
    with pytest.raises(ManifestError, match="cycle detected"):
        ingest(bad)  # cycles surface during render via _topo_sort


def test_self_loop_rejected():
    bad = _minimal_manifest_yaml(prereqs_b='["b"]')
    with pytest.raises(ManifestError, match="cycle detected"):
        ingest(bad)


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def test_topo_sort_respects_dependencies():
    # Declare in reverse-dependency order on purpose: B (needs A) listed
    # before A. Topo sort should put A first.
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: order
          title: "Order"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
        """
    ).strip()
    rendered, loaded = ingest(yaml_text)
    titles = [s.title for s in loaded.all_sections]
    assert titles == ["A", "B"]


def test_topo_sort_stable_on_ties_uses_declaration_order():
    # Three nodes, no prereqs between them. Declaration order should win.
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: ties
          title: "Ties"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "x"
                title: "X"
                url: "https://example.com/x"
                kind: external_reading
                prereqs: []
              - id: "y"
                title: "Y"
                url: "https://example.com/y"
                kind: external_reading
                prereqs: []
              - id: "z"
                title: "Z"
                url: "https://example.com/z"
                kind: external_reading
                prereqs: []
        """
    ).strip()
    _, loaded = ingest(yaml_text)
    assert [s.title for s in loaded.all_sections] == ["X", "Y", "Z"]


def test_diamond_topo_sort():
    # Diamond: a -> b, a -> c, b+c -> d. Valid orders: a,b,c,d or a,c,b,d.
    # With manifest declaration order b-before-c, the stable result is a,b,c,d.
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: diamond
          title: "Diamond"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]
              - id: "c"
                title: "C"
                url: "https://example.com/c"
                kind: external_reading
                prereqs: ["a"]
              - id: "d"
                title: "D"
                url: "https://example.com/d"
                kind: external_reading
                prereqs: ["b", "c"]
        """
    ).strip()
    _, loaded = ingest(yaml_text)
    assert [s.title for s in loaded.all_sections] == ["A", "B", "C", "D"]


# ---------------------------------------------------------------------------
# Round-trip through the existing loader
# ---------------------------------------------------------------------------


def test_rendered_output_round_trips_through_loader(tmp_path: Path):
    yaml_text = _minimal_manifest_yaml()
    rendered, loaded = ingest(yaml_text)
    # Write to a real file and re-load to confirm shape is loader-compatible.
    out = tmp_path / "test_track.md"
    out.write_text(rendered, encoding="utf-8")
    reloaded = _parse_track_file(out)
    assert reloaded.slug == loaded.slug
    assert reloaded.total_sections == loaded.total_sections
    assert reloaded.chapters[0].sections[0].kind == "external_reading"
    assert reloaded.chapters[0].sections[1].duration_min == 120


def test_body_md_is_appended_after_frontmatter():
    yaml_text = _minimal_manifest_yaml()
    rendered, _ = ingest(yaml_text, body_md="# Notes\n\nLong-form prose here.")
    assert "# Notes" in rendered
    assert rendered.index("# Notes") > rendered.index("---\n", rendered.index("---") + 3)


# ---------------------------------------------------------------------------
# Real ARENA 3.0 manifest dogfood
# ---------------------------------------------------------------------------


def test_topo_sort_keeps_a_branch_intact_before_opening_a_parallel_branch():
    """Regression: when an early-declared node releases its successors
    after a later-declared node has already become ready, the successors
    must leapfrog the later node — not wait their turn in a FIFO queue.

    Concretely: A -> B; X has no prereqs. Declaration order: A, B, X.
    Expected output: A, B, X (the A→B branch completes before X).
    A FIFO Kahn would emit A, X, B because X enters the ready queue
    when A is popped (at the same time B is enqueued behind it).
    """
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: branch
          title: "Branch"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]
              - id: "x"
                title: "X"
                url: "https://example.com/x"
                kind: external_reading
                prereqs: []
        """
    ).strip()
    _, loaded = ingest(yaml_text)
    assert [s.title for s in loaded.all_sections] == ["A", "B", "X"]


def test_arena_3_chapter_1_branches_stay_intact():
    """ARENA's Chapter 1 has three branches (1.3.x, 1.4.x, 1.5.x), all
    unlocked by 1.2. The operator declared them in 1.3 → 1.4 → 1.5 order;
    the ingested track must keep each branch contiguous in that order,
    not interleave them.
    """
    manifest_path = REPO_ROOT / "content" / "tracks" / "manifests" / "arena_3.yaml"
    _, loaded = ingest(manifest_path.read_text(encoding="utf-8"))
    chap1 = [s.title.split(" ", 1)[0] for s in loaded.chapters[1].sections]
    # Pin the exact expected order:
    assert chap1 == [
        "1.1",
        "1.2",
        "1.3.1",
        "1.3.2",
        "1.3.3",
        "1.3.4",
        "1.4.1",
        "1.4.2",
        "1.5.1",
        "1.5.2",
        "1.5.3",
        "1.5.4",
        "1.5.X",
    ]


def test_render_emits_depends_on_for_nodes_with_prereqs():
    """Bridge BEN-87 manifest -> BEN-89 runtime: per-chapter string
    prereq IDs become flat-index ``depends_on`` in the rendered config."""
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: bridge
          title: "Bridge"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: ["a"]
              - id: "c"
                title: "C"
                url: "https://example.com/c"
                kind: external_reading
                prereqs: ["a", "b"]
        """
    ).strip()
    rendered, loaded = ingest(yaml_text)
    # A: flat 0, no prereqs → no depends_on emitted
    # B: flat 1, prereqs=[a] → depends_on: [0]
    # C: flat 2, prereqs=[a, b] → depends_on: [0, 1] (sorted ascending)
    assert loaded.chapters[0].sections[0].depends_on is None
    assert loaded.chapters[0].sections[1].depends_on == (0,)
    assert loaded.chapters[0].sections[2].depends_on == (0, 1)
    # Section without depends_on shouldn't print the key at all
    assert "depends_on: [0]" in rendered
    assert "depends_on: [0, 1]" in rendered


def test_render_depends_on_flat_indexes_span_chapters():
    """Flat indexes are cumulative across chapters; in-chapter prereqs
    in Chapter 1 produce flat indexes that begin at len(chapter 0)."""
    yaml_text = dedent(
        """
        source:
          kind: github_notebooks
          repo_url: https://example.com/repo
        track:
          slug: spans
          title: "Spans"
        chapters:
          - title: "Chapter 0"
            nodes:
              - id: "a"
                title: "A"
                url: "https://example.com/a"
                kind: external_reading
                prereqs: []
              - id: "b"
                title: "B"
                url: "https://example.com/b"
                kind: external_reading
                prereqs: []
          - title: "Chapter 1"
            nodes:
              - id: "x"
                title: "X"
                url: "https://example.com/x"
                kind: external_reading
                prereqs: []
              - id: "y"
                title: "Y"
                url: "https://example.com/y"
                kind: external_reading
                prereqs: ["x"]
        """
    ).strip()
    _, loaded = ingest(yaml_text)
    # Chapter 0: A=0, B=1 (no depends_on)
    # Chapter 1: X=2 (no depends_on), Y=3 → depends_on=[2]
    assert loaded.chapters[1].sections[1].depends_on == (2,)


def test_arena_3_manifest_ingests_cleanly():
    """The committed ARENA 3.0 manifest must ingest without errors.

    This is the BEN-87 done-state check: a real-world manifest (the one
    paired with the existing hand-authored arena_3.md) produces a
    persisted, dependency-ordered ARENA skeleton that the loader accepts.

    Replacement of the hand-authored arena_3.md with the ingested output
    is BEN-91's job; we only verify here that the pipeline works.
    """
    manifest_path = REPO_ROOT / "content" / "tracks" / "manifests" / "arena_3.yaml"
    assert manifest_path.exists(), "ARENA 3.0 manifest must be checked in"
    rendered, loaded = ingest(manifest_path.read_text(encoding="utf-8"))

    assert loaded.slug == "arena_3"
    assert loaded.title == "ARENA 3.0"
    assert len(loaded.chapters) == 2  # Chapter 0 + Chapter 1
    # Existing hand-authored config has 6 + 13 = 19 sections.
    assert loaded.total_sections == 19

    # First section of Chapter 0 must be 0.0 (the only zero-prereq node).
    assert loaded.chapters[0].sections[0].title.startswith("0.0")
    # Last section of Chapter 0 must come after its prereqs — 0.5 needs 0.4.
    chap0_titles = [s.title for s in loaded.chapters[0].sections]
    assert chap0_titles.index("0.4 Backpropagation") < chap0_titles.index("0.5 VAEs & GANs")

    # Chapter 1: 1.4.2 needs 1.3.3 and 1.4.1, so it must come after both.
    chap1_titles = [s.title for s in loaded.chapters[1].sections]
    idx_142 = chap1_titles.index("1.4.2 SAE Circuits")
    assert chap1_titles.index("1.3.3 Interpretability with SAEs") < idx_142
    assert chap1_titles.index("1.4.1 Indirect Object Identification") < idx_142
