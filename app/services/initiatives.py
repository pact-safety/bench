"""Initiative loader for cross-surface strategic workstreams.

Initiatives are authored as markdown files under ``content/initiatives/*.md``
using YAML frontmatter for structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


_ALLOWED_STATUSES = {"active", "dormant", "done", "archived"}
_INITIATIVES_DIR = Path(__file__).resolve().parents[2] / "content" / "initiatives"


@dataclass(frozen=True)
class InitiativeLinear:
    team: str
    ticket_prefix: str
    label: str | None


@dataclass(frozen=True)
class InitiativeGitHub:
    repos: tuple[str, ...]


@dataclass(frozen=True)
class InitiativeBench:
    surface: str | None


@dataclass(frozen=True)
class Initiative:
    slug: str
    title: str
    status: str
    priority: int
    linear: InitiativeLinear
    github: InitiativeGitHub
    bench: InitiativeBench
    target_date: str | None
    notes: str


_initiatives_by_slug: dict[str, Initiative] = {}


def _parse_frontmatter(text: str, path: Path) -> dict:
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")

    fm_raw = text[4:end]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML frontmatter") from exc
    if not isinstance(fm, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    return fm


def _require_non_empty_str(raw: dict, key: str, path: Path, *, field_name: str | None = None) -> str:
    val = raw.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{path}: missing required field '{field_name or key}'")
    return val.strip()


def _optional_str(raw: dict, key: str, path: Path, *, field_name: str | None = None) -> str | None:
    val = raw.get(key)
    if val in (None, ""):
        return None
    if not isinstance(val, str):
        raise ValueError(f"{path}: {(field_name or key)} must be a string")
    cleaned = val.strip()
    return cleaned or None


def _require_mapping(raw: dict, key: str, path: Path) -> dict:
    val = raw.get(key)
    if val is None:
        raise ValueError(f"{path}: missing required field '{key}'")
    if not isinstance(val, dict):
        raise ValueError(f"{path}: {key} must be a mapping")
    return val


def _require_priority(raw: dict, path: Path) -> int:
    val = raw.get("priority")
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{path}: missing required field 'priority'")
    if not 0 <= val <= 4:
        raise ValueError(f"{path}: priority must be between 0 and 4")
    return val


def _parse_target_date(raw: object, path: Path) -> str | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw.isoformat()
    if isinstance(raw, str):
        cleaned = raw.strip()
        return cleaned or None
    raise ValueError(f"{path}: target_date must be a YYYY-MM-DD string or null")


def _parse_status(raw: dict, path: Path) -> str:
    status = _require_non_empty_str(raw, "status", path)
    if status not in _ALLOWED_STATUSES:
        raise ValueError(
            f"{path}: status must be one of {', '.join(sorted(_ALLOWED_STATUSES))}"
        )
    return status


def _parse_repos(github_raw: dict, path: Path) -> tuple[str, ...]:
    repos_raw = github_raw.get("repos")
    if repos_raw is None:
        raise ValueError(f"{path}: missing required field 'github.repos'")
    if not isinstance(repos_raw, list):
        raise ValueError(f"{path}: github.repos must be a list")

    repos: list[str] = []
    for idx, repo in enumerate(repos_raw):
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError(f"{path}: github.repos[{idx}] must be a non-empty string")
        cleaned = repo.strip()
        if cleaned.count("/") != 1:
            raise ValueError(f"{path}: github.repos[{idx}] must be in owner/repo format")
        repos.append(cleaned)
    return tuple(repos)


def _parse_initiative_file(path: Path) -> Initiative:
    fm = _parse_frontmatter(path.read_text(), path)

    linear_raw = _require_mapping(fm, "linear", path)
    github_raw = _require_mapping(fm, "github", path)
    bench_raw = _require_mapping(fm, "bench", path)

    return Initiative(
        slug=_require_non_empty_str(fm, "slug", path),
        title=_require_non_empty_str(fm, "title", path),
        status=_parse_status(fm, path),
        priority=_require_priority(fm, path),
        linear=InitiativeLinear(
            team=_require_non_empty_str(linear_raw, "team", path, field_name="linear.team"),
            ticket_prefix=_require_non_empty_str(
                linear_raw,
                "ticket_prefix",
                path,
                field_name="linear.ticket_prefix",
            ),
            label=_optional_str(linear_raw, "label", path, field_name="linear.label"),
        ),
        github=InitiativeGitHub(repos=_parse_repos(github_raw, path)),
        bench=InitiativeBench(
            surface=_optional_str(bench_raw, "surface", path, field_name="bench.surface")
        ),
        target_date=_parse_target_date(fm.get("target_date"), path),
        notes=_require_non_empty_str(fm, "notes", path),
    )


def load_initiatives() -> list[Initiative]:
    """Parse every ``content/initiatives/*.md`` into Initiative objects."""
    global _initiatives_by_slug

    if not _INITIATIVES_DIR.exists():
        _initiatives_by_slug = {}
        return []

    initiatives: list[Initiative] = []
    initiatives_by_slug: dict[str, Initiative] = {}
    for path in sorted(_INITIATIVES_DIR.glob("*.md")):
        initiative = _parse_initiative_file(path)
        if initiative.slug in initiatives_by_slug:
            raise ValueError(f"{path}: duplicate initiative slug '{initiative.slug}'")
        initiatives.append(initiative)
        initiatives_by_slug[initiative.slug] = initiative

    _initiatives_by_slug = initiatives_by_slug
    return initiatives


def get_initiative(slug: str) -> Initiative | None:
    """Return a loaded initiative by slug, if present."""
    if not _initiatives_by_slug:
        load_initiatives()
    return _initiatives_by_slug.get(slug)
