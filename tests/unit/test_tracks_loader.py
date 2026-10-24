"""Tests for app.services.tracks markdown loader."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.services.tracks import TrackResource, dependencies_for, load_all_tracks, section_at


def _write_track(tracks_dir: Path, filename: str, frontmatter: str, body: str = "# Track notes") -> None:
    (tracks_dir / filename).write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}\n")


def test_empty_dir_returns_empty_dict(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()

    assert load_all_tracks(tracks_dir) == {}


def test_mixed_supplement_types_survive_loading(tmp_path: Path):
    _write_track(tmp_path, "mixed.md", dedent("""
        slug: mixed
        title: Mixed resources
        chapters:
          - title: Tensor practice
            sections:
              - title: Tensor operations
                kind: external_exercise
                url: https://example.com/notebook
                resources:
                  - title: Documentation
                    url: https://example.com/docs
                  - title: Demonstration
                    url: https://example.com/video
                    kind: video
                  - title: Discussion
                    url: https://example.com/podcast
                    kind: podcast
                  - title: Practice
                    url: https://example.com/practice
                    kind: exercise
        """))

    resources = load_all_tracks(tmp_path)["mixed"].all_sections[0].resources

    assert [resource.kind for resource in resources] == ["reading", "video", "podcast", "exercise"]
    assert TrackResource(title="Legacy reference", url="https://example.com").kind == "reading"


@pytest.mark.parametrize("kind", ["external_video", "unknown", "null", "[]"])
def test_invalid_supplement_type_is_rejected(tmp_path: Path, kind: str):
    _write_track(tmp_path, "invalid.md", dedent(f"""
        slug: invalid
        title: Invalid resource
        chapters:
          - title: Chapter
            sections:
              - title: Section
                kind: external_reading
                url: https://example.com
                resources:
                  - title: Reference
                    url: https://example.com/reference
                    kind: {kind}
        """))

    with pytest.raises(ValueError, match=r"resources\[0\].kind must be"):
        load_all_tracks(tmp_path)


def test_ml4good_supplements_keep_their_source_media_type():
    tracks_dir = Path(__file__).resolve().parents[2] / "content" / "tracks"
    track = load_all_tracks(tracks_dir)["ml4good-prework-fall-2026"]
    resources = [resource for section in track.all_sections for resource in section.resources]

    assert len(resources) == 21
    assert sum(resource.kind == "video" for resource in resources) == 7
    assert sum(resource.kind == "reading" for resource in resources) == 14
    assert [resource.kind for resource in track.all_sections[4].resources] == ["reading", "video"]
    assert [resource.kind for resource in track.all_sections[11].resources] == [
        "video", "reading", "video", "video", "video",
    ]


def test_single_track_loads_and_flattens_sections(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            description: "Alignment curriculum"
            source_url: "https://example.com/arena"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1 Prerequisites"
                    url: "https://example.com/0.1"
                    kind: external_reading
                    duration_min: 60
                    domain_tags: [python]
                    axes: [algorithmic]
                  - title: "0.2 CNNs"
                    url: "https://example.com/0.2"
                    kind: external_reading
                    duration_min: 120
                    domain_tags: [cnn]
                    axes: [transformer_internals]
            """
        ),
    )

    loaded = load_all_tracks(tracks_dir)

    assert set(loaded.keys()) == {"arena_3"}
    track = loaded["arena_3"]
    assert track.title == "ARENA 3.0"
    assert [section.title for section in track.all_sections] == [
        "0.1 Prerequisites",
        "0.2 CNNs",
    ]


def test_multiple_chapters_preserve_chapter_and_section_order(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
              - title: "Chapter 1"
                sections:
                  - title: "1.1"
                    kind: external_reading
                    url: "https://example.com/1.1"
                  - title: "1.2"
                    kind: external_exercise
                    url: "https://example.com/1.2"
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert [chapter.title for chapter in track.chapters] == ["Chapter 0", "Chapter 1"]
    assert [section.title for section in track.all_sections] == ["0.1", "1.1", "1.2"]


def test_missing_slug_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "missing_slug.md",
        dedent(
            """
            title: "ARENA 3.0"
            chapters: []
            """
        ),
    )

    with pytest.raises(ValueError, match="missing required field 'slug'"):
        load_all_tracks(tracks_dir)


def test_missing_title_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "missing_title.md",
        dedent(
            """
            slug: arena_3
            chapters: []
            """
        ),
    )

    with pytest.raises(ValueError, match="missing required field 'title'"):
        load_all_tracks(tracks_dir)


def test_invalid_yaml_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "invalid_yaml.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters: [
            """
        ),
    )

    with pytest.raises(ValueError, match="invalid YAML frontmatter"):
        load_all_tracks(tracks_dir)


def test_section_at_out_of_range_returns_none(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert section_at(track, -1) is None
    assert section_at(track, 1) is None


def test_total_sections_matches_actual_count(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                  - title: "0.2"
                    kind: external_reading
                    url: "https://example.com/0.2"
              - title: "Chapter 1"
                sections:
                  - title: "1.1"
                    kind: external_exercise
                    url: "https://example.com/1.1"
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert track.total_sections == 3
    assert track.total_sections == len(track.all_sections)


def test_duplicate_slug_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "track_a.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters: []
            """
        ),
    )
    _write_track(
        tracks_dir,
        "track_b.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0 copy"
            chapters: []
            """
        ),
    )

    with pytest.raises(ValueError, match="duplicate track slug 'arena_3'"):
        load_all_tracks(tracks_dir)


def test_non_integer_duration_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                    duration_min: "sixty"
            """
        ),
    )

    with pytest.raises(ValueError, match="duration_min must be an integer"):
        load_all_tracks(tracks_dir)


def test_track_section_parses_checkpoint_and_explicit_dependencies(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                    checkpoint: "Explain tensor shape discipline from memory"
                  - title: "0.2"
                    kind: external_reading
                    url: "https://example.com/0.2"
                    depends_on: [0]
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert track.all_sections[0].checkpoint == "Explain tensor shape discipline from memory"
    assert track.all_sections[1].depends_on == (0,)


def test_dependencies_default_to_sequential_when_not_authored(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                  - title: "0.2"
                    kind: external_reading
                    url: "https://example.com/0.2"
                  - title: "0.3"
                    kind: external_reading
                    url: "https://example.com/0.3"
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert dependencies_for(track, 0) == ()
    assert dependencies_for(track, 1) == (0,)
    assert dependencies_for(track, 2) == (1,)


def test_explicit_empty_dependencies_override_sequential_fallback(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                  - title: "0.2"
                    kind: external_reading
                    url: "https://example.com/0.2"
                    depends_on: []
            """
        ),
    )

    track = load_all_tracks(tracks_dir)["arena_3"]

    assert dependencies_for(track, 1) == ()


def test_invalid_dependency_index_raises_clear_error(tmp_path: Path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    _write_track(
        tracks_dir,
        "arena_3.md",
        dedent(
            """
            slug: arena_3
            title: "ARENA 3.0"
            chapters:
              - title: "Chapter 0"
                sections:
                  - title: "0.1"
                    kind: external_reading
                    url: "https://example.com/0.1"
                  - title: "0.2"
                    kind: external_reading
                    url: "https://example.com/0.2"
                    depends_on: [99]
            """
        ),
    )

    with pytest.raises(ValueError, match="depends on missing section index 99"):
        load_all_tracks(tracks_dir)
