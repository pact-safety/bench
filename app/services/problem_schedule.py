"""Successive relearning for problem attempts, stored in user settings."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .recitation_schedule import interval_after


def _when(raw) -> datetime | None:
    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def due_problem_ids(state: dict | None, today: date) -> list[str]:
    """Return IDs in due order using UTC calendar days, as in daily flow."""
    due = []
    for pid, entry in (state or {}).items():
        when = _when(entry.get('due_at')) if isinstance(entry, dict) else None
        if when is not None and when.date() <= today:
            due.append((when, str(pid)))
    return [pid for _, pid in sorted(due)]


def apply_attempt(state: dict | None, attempt, *, now: datetime) -> dict:
    """Fold a completed attempt into a new schedule without mutating settings."""
    updated = dict(state or {})
    key = str(attempt.problem_id)
    prior = updated.get(key)
    prior = prior if isinstance(prior, dict) else {}
    passed = attempt.test_passed is True
    if not passed and not prior:
        return updated
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    independent = (passed and attempt.solved_without_lookup is True
                   and not attempt.looked_at_solution and not attempt.looked_at_pitfalls
                   and not attempt.hints_used)
    due_at = _when(prior.get('due_at'))
    last_passed = _when(prior.get('last_passed'))
    # Early reruns are practice, not evidence that the gap held. The daily
    # card uses calendar days, so a due-morning return counts even if the
    # previous run finished in the afternoon.
    if independent and prior and (
        (due_at is not None and due_at.date() > now.date())
        or (last_passed is not None and last_passed.date() >= now.date())
    ):
        return updated
    # Any assistance keeps the next retrieval close, without recording a
    # failure. solved_without_lookup alone currently ignores hints/pitfalls.
    current = prior.get('interval_days') if due_at is not None else None
    days = interval_after(current, missed=not independent)
    next_due = now + timedelta(days=days)
    if passed and not independent and due_at is not None and due_at.date() > now.date():
        next_due = min(next_due, due_at)
    updated[key] = {
        'interval_days': days,
        'due_at': next_due.isoformat(),
        'misses': int(prior.get('misses', 0)) + int(not passed),
        'last_passed': now.isoformat() if passed else prior.get('last_passed'),
    }
    return updated
