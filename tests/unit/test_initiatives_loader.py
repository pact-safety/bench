"""Tests for app.services.initiatives markdown loader."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.services import initiatives as initiatives_svc


def _write_initiative(initiatives_dir: Path, filename: str, frontmatter: str) -> None:
    (initiatives_dir / filename).write_text(f"---\n{frontmatter.strip()}\n---\n")


def _set_initiatives_dir(monkeypatch: pytest.MonkeyPatch, initiatives_dir: Path) -> None:
    monkeypatch.setattr(initiatives_svc, "_INITIATIVES_DIR", initiatives_dir)
    monkeypatch.setattr(initiatives_svc, "_initiatives_by_slug", {})


def test_single_initiative_loads_and_getter_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    initiatives_dir = tmp_path / "initiatives"
    initiatives_dir.mkdir()
    _set_initiatives_dir(monkeypatch, initiatives_dir)
    _write_initiative(
        initiatives_dir,
        "capstone.md",
        dedent(
            """
            slug: capstone
            title: "MSCS Sycophancy Capstone"
            status: active
            priority: 1
            linear:
              team: "Test Team"
              ticket_prefix: LIS
              label: capstone
            github:
              repos:
                - LiBearden/sycophancy-eval
            bench:
              surface: null
            target_date: 2026-07-01
            notes: "Load-bearing initiative"
            """
        ),
    )

    loaded = initiatives_svc.load_initiatives()

    assert len(loaded) == 1
    assert loaded[0].slug == "capstone"
    assert loaded[0].linear.ticket_prefix == "LIS"
    assert loaded[0].github.repos == ("LiBearden/sycophancy-eval",)
    assert initiatives_svc.get_initiative("capstone") == loaded[0]
    assert initiatives_svc.get_initiative("missing") is None


def test_example_initiative_ships_and_parses():
    """A fresh clone ships the example template as its only initiative.

    Personal initiatives are gitignored per-user data, so the repo must
    not depend on them. This guards the template staying valid — a
    malformed example breaks every new self-hoster's first boot."""
    loaded = initiatives_svc.load_initiatives()

    assert "example-getting-started" in [i.slug for i in loaded]

def test_invalid_yaml_raises_clean_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    initiatives_dir = tmp_path / "initiatives"
    initiatives_dir.mkdir()
    _set_initiatives_dir(monkeypatch, initiatives_dir)
    _write_initiative(
        initiatives_dir,
        "invalid.md",
        dedent(
            """
            slug: capstone
            title: "MSCS Sycophancy Capstone"
            linear: [
            """
        ),
    )

    with pytest.raises(ValueError, match="invalid YAML frontmatter"):
        initiatives_svc.load_initiatives()


def test_missing_required_field_raises_clean_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    initiatives_dir = tmp_path / "initiatives"
    initiatives_dir.mkdir()
    _set_initiatives_dir(monkeypatch, initiatives_dir)
    _write_initiative(
        initiatives_dir,
        "missing_title.md",
        dedent(
            """
            slug: capstone
            status: active
            priority: 1
            linear:
              team: "Test Team"
              ticket_prefix: LIS
            github:
              repos: []
            bench:
              surface: null
            notes: "missing title"
            """
        ),
    )

    with pytest.raises(ValueError, match="missing required field 'title'"):
        initiatives_svc.load_initiatives()


def test_example_initiative_output_shape():
    """Field/type contract for a parsed initiative, pinned on the one
    initiative the repo actually ships. Contains no personal data."""
    initiatives_svc.load_initiatives()
    example = initiatives_svc.get_initiative("example-getting-started")

    assert example is not None
    assert example.slug == "example-getting-started"
    assert example.title == "Getting Started"
    assert example.status == "active"
    assert example.priority == 0
    assert example.linear.team == "Your Team"
    assert example.linear.ticket_prefix == "EXA"
    assert example.linear.label == "example"
    assert example.github.repos == ("your-org/your-repo",)
    assert example.bench.surface == "/"
    assert example.target_date is None
    assert example.notes.startswith("Template initiative")
