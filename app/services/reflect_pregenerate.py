"""Saturday-morning pre-generation of the weekly Reflect set (GH #229).

Pure-functional core, scheduler-agnostic. The startup hook in
``app/main.py`` arranges to call ``pregenerate_for_user`` at 7am local
time every Saturday for each active user. Single-tenant today, but the
service signature accepts a uid so the same function works once we add
multi-tenant support.

Design points:

- **Skip when current-period row already exists.** If the operator
  triggered a manual `/reflect/generate` Saturday morning before the
  cron fired, we leave that row alone — never overwrite operator work.
- **Skip inactive users.** A user with zero attempts in the last 30
  days isn't burning Anthropic credits for a reflection they won't
  read.
- **Non-fatal failures.** The cron logs and moves on. Worst case the
  operator clicks "Generate this week's reflection" Saturday morning
  and pays the 3-5s wait (down from 15-25s after #223). Pre-generation
  is a UX optimization, not a correctness requirement.
- **Always set pregenerated=True.** This is the audit-trail signal the
  UI uses to surface "your reflection is ready" rather than "click
  Generate."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from ..models import Reflection
from . import hamming as hamming_service


_HAMMING_WINDOW_DAYS = 7
_ACTIVITY_LOOKBACK_DAYS = 30

log = logging.getLogger("bench.reflect_pregenerate")


@dataclass(frozen=True)
class PregenerateOutcome:
    """One user's result from a pregeneration tick. Returned for tests
    and for the cron's structured log line."""
    user_id: str
    action: str  # "inserted" | "skipped_existing" | "skipped_inactive" | "skipped_quiet_week" | "error"
    reflection_id: int | None = None
    error_message: str = ""


def _has_recent_activity(
    *,
    attempts_repo: Any,
    user_id: str,
    now: datetime,
    lookback_days: int = _ACTIVITY_LOOKBACK_DAYS,
) -> bool:
    """True if the user has any attempt in the last N days. Cheap signal;
    we don't try to be clever about content progress / reflections too —
    the bench's primary activity is attempts."""
    since = now - timedelta(days=lookback_days)
    # Defensive: some repo paths return generators; force iteration.
    try:
        recent = attempts_repo.list_for_user_since(user_id, since)
    except AttributeError:
        # Fallback: full list, slice in Python. Slower but works on a
        # repo that hasn't grown the `_since` helper yet.
        all_attempts = attempts_repo.all_for_user(user_id)
        recent = [
            a for a in all_attempts
            if getattr(a, "started_at", None) is not None
            and a.started_at >= since
        ]
    return any(recent)


def pregenerate_for_user(
    *,
    user_id: str,
    now: datetime,
    attempts_repo: Any,
    reflection_repo: Any,
    week_summary_builder: Callable[[str, int], Any],
    generator: Callable[..., dict] = hamming_service.generate,
    window_days: int = _HAMMING_WINDOW_DAYS,
) -> PregenerateOutcome:
    """Generate (and persist) one user's weekly reflection if appropriate.

    Returns a structured outcome rather than mutating logs in-place; the
    caller (cron) can decide how to surface them.

    Parameters are injected rather than imported so unit tests can run
    without spinning up the whole `app.main` module.
    """
    period_end = now
    period_start = now - timedelta(days=window_days)

    # Skip inactive users (no activity in the last 30 days).
    if not _has_recent_activity(
        attempts_repo=attempts_repo, user_id=user_id, now=now
    ):
        return PregenerateOutcome(
            user_id=user_id,
            action="skipped_inactive",
        )

    # Skip when there's no material to reflect on THIS week. Hamming
    # framing assumes a track of recent work — generating a reflection
    # against a zero-attempt week just produces a "complete no-show"
    # finger-wag that's neither honest nor useful. Operator can still
    # manually generate from /reflect if they want the canned-fallback
    # prompts for a quiet week. (Validation feedback 2026-05-25.)
    if not _has_recent_activity(
        attempts_repo=attempts_repo,
        user_id=user_id,
        now=now,
        lookback_days=window_days,
    ):
        return PregenerateOutcome(
            user_id=user_id,
            action="skipped_quiet_week",
        )

    # Skip if a reflection covering this period already exists.
    existing = reflection_repo.latest_in_period(user_id, period_start, period_end)
    if existing is not None:
        return PregenerateOutcome(
            user_id=user_id,
            action="skipped_existing",
            reflection_id=existing.id,
        )

    # Build the week summary that hamming_service.generate consumes.
    try:
        week = week_summary_builder(user_id, window_days)
    except Exception as exc:  # noqa: BLE001 — defensive cron path
        log.warning("week_summary_builder failed for uid=%s: %s", user_id, exc)
        return PregenerateOutcome(
            user_id=user_id, action="error", error_message=f"week_summary: {exc}"
        )

    # Call hamming.generate. It already has a canned-fallback path on
    # spend-cap / API failure, so this returns *something* (just with
    # method="fallback" in the degraded case).
    try:
        result = generator(week, days=window_days, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("hamming.generate failed for uid=%s: %s", user_id, exc)
        return PregenerateOutcome(
            user_id=user_id, action="error", error_message=f"generate: {exc}"
        )

    refl = Reflection(
        id=None,
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
        generated_at=now,
        prompts=result["prompts"],
        response_md=None,
        response_updated_at=None,
        summary_md=result.get("summary"),
        method=result["method"],
        model_used=result.get("model_used"),
        pregenerated=True,
    )
    try:
        new_id = reflection_repo.insert(refl)
    except Exception as exc:  # noqa: BLE001
        log.warning("reflection_repo.insert failed for uid=%s: %s", user_id, exc)
        return PregenerateOutcome(
            user_id=user_id, action="error", error_message=f"insert: {exc}"
        )

    return PregenerateOutcome(
        user_id=user_id,
        action="inserted",
        reflection_id=new_id,
    )


def pregenerate_for_users(
    user_ids: list[str],
    *,
    now: datetime,
    attempts_repo: Any,
    reflection_repo: Any,
    week_summary_builder: Callable[[str, int], Any],
    generator: Callable[..., dict] = hamming_service.generate,
) -> list[PregenerateOutcome]:
    """Iterate per-user. Each user's failure does not affect others."""
    return [
        pregenerate_for_user(
            user_id=uid,
            now=now,
            attempts_repo=attempts_repo,
            reflection_repo=reflection_repo,
            week_summary_builder=week_summary_builder,
            generator=generator,
        )
        for uid in user_ids
    ]
