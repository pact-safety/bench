"""Content authoring loader + daily picker.

Reads markdown files under content/{readings,videos,podcasts,exercises}/
and upserts them into content_items on startup. Same shape as the
problem loader: YAML frontmatter + a markdown body that serves as the
in-app summary (excerpt + key points + what-to-take-away).

The daily picker chooses one item per kind that aligns with the user's
weakest stat, prefers items the user hasn't completed, and falls back
to least-recently-checked when there's no obvious weak-axis pick.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..models import ContentItem
from ..repositories import ContentRepository
from ..services import assessment as assess_svc


_KIND_DIRS = {
    "reading":  "readings",
    "video":    "videos",
    "podcast":  "podcasts",
    "exercise": "exercises",
}

# Startup loader parses authored exercise markdown files and records
# GPU/Colab flags by slug. We keep this in memory because `content_items`
# has no dedicated columns for these optional exercise-only fields.
_EXERCISE_FRONTMATTER_BY_SLUG: dict[str, dict[str, object]] = {}


def _coerce_optional_bool(value: object, *, field: str, path: Path, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{path}: {field} must be a boolean")


def _coerce_optional_str(value: object, *, field: str, path: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path}: {field} must be a string")
    cleaned = value.strip()
    return cleaned or None


def exercise_frontmatter(slug: str) -> tuple[bool, str | None]:
    """Return (`gpu_required`, `colab_url`) for an authored exercise.

    Values come from markdown frontmatter parsed at startup load.
    Missing slugs default to (False, None).
    """
    raw = _EXERCISE_FRONTMATTER_BY_SLUG.get(slug)
    if raw is None:
        return False, None
    gpu_required = bool(raw.get("gpu_required", False))
    colab_url = raw.get("colab_url")
    return gpu_required, (colab_url if isinstance(colab_url, str) else None)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("missing frontmatter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    fm_raw = text[4:end]
    body = text[end + 4:].lstrip("\n")
    return yaml.safe_load(fm_raw) or {}, body


def parse_content_file(path: Path) -> ContentItem:
    fm, body = _parse_frontmatter(path.read_text())
    kind = fm["kind"]
    gpu_required = False
    colab_url = None
    if kind == "exercise":
        gpu_required = _coerce_optional_bool(
            fm.get("gpu_required", False),
            field="gpu_required",
            path=path,
            default=False,
        )
        colab_url = _coerce_optional_str(
            fm.get("colab_url"),
            field="colab_url",
            path=path,
        )

    return ContentItem(
        id=0,
        slug=fm["slug"],
        kind=kind,
        title=fm["title"],
        source=fm.get("source"),
        url=fm.get("url"),
        duration_min=int(fm["duration_min"]) if fm.get("duration_min") is not None else None,
        axes=list(fm.get("axes", [])),
        domain_tags=list(fm.get("domain_tags", [])),
        prerequisites=list(fm.get("prerequisites", [])),
        content_md=body.strip() or None,
        authored_by=fm.get("authored_by"),
        authored_date=fm.get("authored_date"),
        version=int(fm.get("version", 1)),
        gpu_required=gpu_required,
        colab_url=colab_url,
    )


def load_all_content(
    content_dir: Path,
    repo: ContentRepository,
    progress_cb=None,
) -> int:
    """Upsert authored content (readings, videos, podcasts, exercises).

    Hash-skip optimization (same pattern as load_all_problems): one
    SELECT to learn what's in the DB, only round-trip on actual
    changes."""
    import hashlib

    files: list[Path] = []
    for sub in _KIND_DIRS.values():
        d = content_dir / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            files.append(f)
    total = len(files)
    db_hashes = repo.hashes_by_slug()
    _EXERCISE_FRONTMATTER_BY_SLUG.clear()
    n = 0
    skipped = 0
    for f in files:
        raw = f.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        item = parse_content_file(f)
        if item.kind == "exercise":
            _EXERCISE_FRONTMATTER_BY_SLUG[item.slug] = {
                "gpu_required": item.gpu_required,
                "colab_url": item.colab_url,
            }
        if db_hashes.get(item.slug) == digest:
            skipped += 1
            n += 1
            if progress_cb:
                progress_cb(n, total, f"{f.stem} (skipped)")
            continue
        repo.upsert(item, content_hash=digest)
        n += 1
        if progress_cb:
            progress_cb(n, total, f.stem)
    if skipped:
        import sys
        sys.stdout.write(f"\n[startup]   ({skipped} unchanged, skipped)\n")
        sys.stdout.flush()
    return n


def pick_daily(
    items: list[ContentItem],
    progress_by_content_id: dict,
    skill_scores: dict[str, float],
    axis_ratings: dict[str, float] | None = None,
) -> ContentItem | None:
    """Pick one item from `items` aligned with the user's weakest stat,
    biased by their historical ratings.

    Signals (higher = more attractive):
    - Weak-axis overlap: +1 per matching weak axis (the user wants to grow).
    - Average historical rating across the item's axes, centered at 3:
      a 5★ axis adds +0.4 to attractiveness; a 1★ adds -0.4.
    - Favorited-similar bonus is implicit via ratings (favorited items
      tend to be highly rated).
    - Duration: a small (~milli) tiebreak preferring shorter items.

    Items rated 4-5★ on axes the user has loved → climb. Items in 1-2★
    territory → sink, even if they cover a "weak" axis the user
    nominally should drill (don't burn engagement on content the user
    already rejected).
    """
    # Curriculum resources are selected by the active track's dependency
    # gates; the axis-fit fallback must not surface locked or unrelated work.
    items = [item for item in items
             if not (item.source_kind == "authored" and item.slug.startswith("track-"))]
    if not items:
        return None

    unread = [it for it in items if progress_by_content_id.get(it.id, None) is None or progress_by_content_id[it.id].status != "completed"]
    pool = unread or items

    weak_axes = {a for a in assess_svc.AXES if skill_scores.get(a, 0.0) < 0.5}
    axis_ratings = axis_ratings or {}

    def score(it: ContentItem) -> float:
        overlap = sum(1 for a in it.axes if a in weak_axes)
        # Mean rating across the item's axes, centered on 3 (neutral).
        ratings = [axis_ratings[a] for a in it.axes if a in axis_ratings]
        rating_signal = (sum(ratings) / len(ratings) - 3.0) if ratings else 0.0
        # Higher is better. Negate at sort time.
        attractiveness = overlap + 0.4 * rating_signal
        # Duration is a tiny tiebreak (1000-divisor keeps it small).
        return -attractiveness + (it.duration_min or 999) / 1000.0

    pool.sort(key=lambda it: (score(it), it.slug))
    return pool[0]
