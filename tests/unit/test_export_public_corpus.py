"""Tests for scripts/export_public_corpus.py."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_public_corpus.py"


def _load_export_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_public_corpus", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_export(out_dir: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--out", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        "export script failed\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _frontmatter_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"expected frontmatter in {path}"
    end = text.find("\n---", 4)
    assert end != -1, f"unterminated frontmatter in {path}"
    frontmatter = yaml.safe_load(text[4:end]) or {}
    assert isinstance(frontmatter, dict), f"frontmatter must be mapping in {path}"
    return {str(key).strip().lower() for key in frontmatter}


def test_export_public_corpus_structure_and_frontmatter_denylist(tmp_path: Path):
    export_module = _load_export_module()
    out_dir = tmp_path / "public-corpus"

    _run_export(out_dir)

    exported_content_subdirs = {
        p.name for p in (out_dir / "content").iterdir() if p.is_dir()
    }
    assert exported_content_subdirs == {
        "problems",
        "readings",
        "videos",
        "podcasts",
        "exercises",
    }

    required_files = [
        "taxonomy/axes.md",
        "taxonomy/stat-groups.md",
        "taxonomy/sub-topics.md",
        "docs/architecture/tag-vocabulary.md",
        "docs/architecture/imposter-syndrome.md",
        "docs/architecture/rest-days.md",
        "docs/architecture/tracks.md",
        "README.md",
        "LICENSE",
    ]
    for rel in required_files:
        assert (out_dir / rel).is_file(), f"missing expected export file: {rel}"

    axes_md = (out_dir / "taxonomy" / "axes.md").read_text(encoding="utf-8")
    for axis in export_module.AXES:
        assert f"`{axis}`" in axes_md

    stats_md = (out_dir / "taxonomy" / "stat-groups.md").read_text(encoding="utf-8")
    for stat in export_module.STATS:
        assert stat.label in stats_md
        assert f"`{stat.key}`" in stats_md
        for axis in stat.axes:
            assert f"`{axis}`" in stats_md

    sub_topics_md = (out_dir / "taxonomy" / "sub-topics.md").read_text(encoding="utf-8")
    assert "### Sub-topic `domain_tags`" in sub_topics_md
    assert "| Axis | Sub-topics in current corpus |" in sub_topics_md

    disallowed = export_module.DISALLOWED_FRONTMATTER_KEYS
    for exported_md in sorted((out_dir / "content").rglob("*.md")):
        keys = _frontmatter_keys(exported_md)
        assert not (keys & disallowed), (
            f"disallowed keys present in {exported_md}: "
            f"{sorted(keys & disallowed)}"
        )


def test_export_public_corpus_is_rerun_safe_and_deterministic(tmp_path: Path):
    out_dir = tmp_path / "public-corpus"

    _run_export(out_dir)
    first_digest = _tree_digest(out_dir)

    _run_export(out_dir)
    second_digest = _tree_digest(out_dir)

    assert first_digest == second_digest
