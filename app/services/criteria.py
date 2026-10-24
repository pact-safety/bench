"""Selection criteria — what a reviewer can actually see.

`readiness.py` answers "can I do the work": JD-weighted axis gaps in
hours. This module carries the other half, the one a fellowship
actually reads: **is there anything a stranger can look at that shows
it.**

Criteria are authored FILES under ``content/criteria/*.md`` with YAML
frontmatter, loaded at startup like tracks. They are not rows: the bar
is editorial content that should move by pull request, and a retired
criterion must never delete somebody's recorded work.

Every criterion is grounded in guidance a program has actually
published. The bench does not invent bars, and does not claim that
meeting them produces an acceptance — selection is capacity-bound and
single-digit-percent. What it claims is narrower and true: unrecorded
work is invisible work, and "strong" and "weak" versions of the same
line on a CV are not the same evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

TRACKS = ("technical", "governance", "all")
STRENGTHS = ("unrated", "weak", "partial", "strong")

# Ordering for "is this covered": partial counts as progress, weak does
# not clear the bar the criterion describes.
_COVERING = ("strong", "partial")


@dataclass(frozen=True)
class Criterion:
    slug: str
    title: str
    track: str
    weight: int
    effort_hours: int
    axes: tuple[str, ...]
    body_md: str


_by_slug: dict[str, Criterion] = {}


def set_criteria(mapping: dict[str, Criterion] | None) -> None:
    global _by_slug
    _by_slug = dict(mapping or {})


def all_criteria() -> tuple[Criterion, ...]:
    """Heaviest first, then alphabetical — the order a reader should
    spend attention in."""
    return tuple(sorted(_by_slug.values(), key=lambda c: (-c.weight, c.slug)))


def get(slug: str) -> Criterion | None:
    return _by_slug.get(slug)


def _parse(path: Path) -> Criterion:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 4:].lstrip("\n")

    slug = str(fm.get("slug") or "").strip()
    if not slug:
        raise ValueError(f"{path}: slug is required")
    if slug != path.stem:
        raise ValueError(f"{path}: slug {slug!r} must match the filename")
    track = str(fm.get("track") or "all").strip()
    if track not in TRACKS:
        raise ValueError(f"{path}: track must be one of {TRACKS}")
    return Criterion(
        slug=slug,
        title=str(fm.get("title") or slug),
        track=track,
        weight=max(1, min(5, int(fm.get("weight", 3)))),
        effort_hours=max(0, int(fm.get("effort_hours", 0))),
        axes=tuple(str(a) for a in (fm.get("axes") or [])),
        body_md=body.strip(),
    )


def load_all(criteria_dir: Path) -> dict[str, Criterion]:
    out: dict[str, Criterion] = {}
    if not criteria_dir.exists():
        return out
    for path in sorted(criteria_dir.glob("*.md")):
        c = _parse(path)
        out[c.slug] = c
    return out


# ---------------------------------------------------------------------------
# The gap read
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionStatus:
    criterion: Criterion
    artifacts: tuple  # EvidenceArtifact rows, newest first
    best_strength: str
    covered: bool


def status_for(
    criteria: tuple[Criterion, ...], artifacts_by_criterion: dict[str, list]
) -> list[CriterionStatus]:
    out: list[CriterionStatus] = []
    for c in criteria:
        rows = list(artifacts_by_criterion.get(c.slug, []))
        best = "unrated"
        for r in rows:
            s = getattr(r, "strength", "unrated")
            if STRENGTHS.index(s) > STRENGTHS.index(best):
                best = s
        out.append(
            CriterionStatus(
                criterion=c,
                artifacts=tuple(rows),
                best_strength=best,
                covered=best in _COVERING,
            )
        )
    return out


def next_actions(statuses: list[CriterionStatus], limit: int = 3) -> list[CriterionStatus]:
    """The criteria worth spending the next block of hours on.

    Ranked by published emphasis first, then by cheapness — a heavy
    criterion you can close in 20 hours beats a heavy one that needs
    200. Anything already covered drops out; a `weak` artifact stays in
    the list, because the thread's core complaint is people being told
    to do things they have already done the weak version of.
    """
    open_ = [s for s in statuses if not s.covered]
    return sorted(
        open_, key=lambda s: (-s.criterion.weight, s.criterion.effort_hours, s.criterion.slug)
    )[:limit]


def coverage(statuses: list[CriterionStatus]) -> dict:
    total = len(statuses)
    covered = sum(1 for s in statuses if s.covered)
    weak_only = sum(1 for s in statuses if not s.covered and s.best_strength == "weak")
    return {
        "total": total,
        "covered": covered,
        "weak_only": weak_only,
        "empty": total - covered - weak_only,
        "pct": round(100 * covered / total) if total else 0,
    }
