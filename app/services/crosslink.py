"""Cross-references between attempts and content.

Two questions the UI wants to answer:

1. Per-content page: "what did I attempt after I read/watched this?"
   Surfaces the practical impact of the reading on the day's coding.

2. Per-attempt page: "what content did I engage with in the days
   leading up to this attempt?" Helps the user (and Sonnet, when
   reviewing) understand the context the attempt landed in.

There is no explicit citation link in the DB — we infer the
relationship by time-window + axis-overlap. False positives are
acceptable because the section header phrases this honestly: "within
the previous {days} days" rather than "you cited this."
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from ..models import Attempt, ContentItem, ContentProgress, Problem
from ..services.scheduler import problem_axes


def _axes_overlap(content_axes: Iterable[str], problem: Problem) -> bool:
    p_axes = problem_axes(problem)
    return bool(set(content_axes or []) & p_axes)


def attempts_following_content(
    *,
    content: ContentItem,
    progress: ContentProgress | None,
    attempts: list[Attempt],
    problem_by_id: dict[int, Problem],
    days: int = 7,
    limit: int = 6,
) -> list[dict]:
    """Return attempts that started within `days` after the user marked
    this content complete AND share at least one skill axis with it.

    Returns oldest → newest (chronological) so the user can see the
    arc; capped at `limit` to keep the footer compact.
    """
    if progress is None or progress.checked_at is None or progress.status != "completed":
        return []
    start = progress.checked_at
    end = start + timedelta(days=days)
    out: list[dict] = []
    for a in attempts:
        if a.started_at is None or a.started_at < start or a.started_at > end:
            continue
        p = problem_by_id.get(a.problem_id)
        if p is None or not _axes_overlap(content.axes, p):
            continue
        out.append({
            "attempt": a,
            "problem": p,
            "delta_hours": int((a.started_at - start).total_seconds() / 3600),
            "passed": bool(a.test_passed),
        })
    out.sort(key=lambda d: d["attempt"].started_at)
    return out[:limit]


def content_before_attempt(
    *,
    attempt: Attempt,
    problem: Problem,
    progress_by_id: dict[int, ContentProgress],
    content_by_id: dict[int, ContentItem],
    days: int = 7,
    limit: int = 6,
) -> list[dict]:
    """Return content items the user finished in the `days` window
    before this attempt started, intersected on skill axes.

    Sorted by recency (most recent first), capped at `limit`.
    """
    if attempt.started_at is None:
        return []
    start = attempt.started_at - timedelta(days=days)
    end = attempt.started_at
    out: list[dict] = []
    for cid, pr in progress_by_id.items():
        if pr.status != "completed" or pr.checked_at is None:
            continue
        if pr.checked_at < start or pr.checked_at > end:
            continue
        ci = content_by_id.get(cid)
        if ci is None or not _axes_overlap(ci.axes, problem):
            continue
        out.append({
            "content": ci,
            "progress": pr,
            "delta_hours": int((end - pr.checked_at).total_seconds() / 3600),
            "rating_1_to_5": pr.rating_1_to_5,
        })
    out.sort(key=lambda d: d["progress"].checked_at, reverse=True)
    return out[:limit]
