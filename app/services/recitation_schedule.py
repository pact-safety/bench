"""Successive-relearning schedule for the recitation loop (BEN-135).

Pure schedule math — no DB, no LLM — so it's cheap to test and the grading
service (recitation.py) and the daily flow both call the same source of truth.

The ladder is the one the operator's university loop used and that
``recall.py`` describes: **+1 / +7 / +30 days**, and **a miss resets to +1**.
A concept he explained ("covered") advances up the ladder; a concept he left
out ("missed") drops back to +1 so it returns sooner. That "returns sooner"
is the *only* user-visible consequence of a miss — there is no score, no
penalty, no streak (BEN-135 grading constraint). ``misses`` is kept purely as
internal telemetry for the ladder; it never surfaces as a count of failures.

State shape, per concept, stored under content_progress.recitation_state:

    {"interval_days": int, "due_at": iso8601, "misses": int, "last_recited": iso8601}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# The successive-relearning ladder. Ascending; a hold advances to the next
# rung, a miss drops to the first.
LADDER: tuple[int, ...] = (1, 7, 30)

_UTC = timezone.utc


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC).isoformat()


def advance_interval(current_days: int | None) -> int:
    """Next rung up the ladder from ``current_days`` (caps at the top rung).
    Unknown/None starts the ladder at its first rung."""
    if current_days is None:
        return LADDER[0]
    for rung in LADDER:
        if rung > current_days:
            return rung
    return LADDER[-1]


def interval_after(current_days: int | None, *, missed: bool) -> int:
    """A miss always resets to the first rung (+1); a hold advances."""
    return LADDER[0] if missed else advance_interval(current_days)


def _entry(interval_days: int, now: datetime, prior: dict | None, *, missed: bool) -> dict:
    prior = prior or {}
    return {
        "interval_days": interval_days,
        "due_at": _iso(now + timedelta(days=interval_days)),
        # Internal only — drives nothing user-visible. Never rendered as a count.
        "misses": int(prior.get("misses", 0)) + (1 if missed else 0),
        "last_recited": _iso(now),
    }


def apply_grade(
    state: dict[str, Any] | None,
    *,
    covered: list[str],
    missing: list[str],
    now: datetime,
    pretest: bool = False,
) -> dict[str, Any]:
    """Fold one graded recitation into the per-concept schedule.

    - ``covered`` concepts advance up the ladder (retention → later).
    - ``missing`` concepts reset to +1 (return sooner) — the sole consequence.
    - ``pretest`` mode schedules everything at the +1 baseline and records NO
      misses: blanking a pretest is the expected result, so it must never leave
      penalty state (BEN-135 Part 4). It still schedules — pretesting genuinely
      improves later retention.

    Returns a NEW dict (caller persists it); the input is not mutated.
    """
    new_state: dict[str, Any] = dict(state or {})

    if pretest:
        # Baseline every touched concept at +1, no miss recorded.
        for concept in list(covered) + list(missing):
            prior = new_state.get(concept)
            new_state[concept] = _entry(LADDER[0], now, prior, missed=False)
        return new_state

    for concept in covered:
        prior = new_state.get(concept)
        cur = prior.get("interval_days") if prior else None
        new_state[concept] = _entry(interval_after(cur, missed=False), now, prior, missed=False)

    for concept in missing:
        prior = new_state.get(concept)
        new_state[concept] = _entry(interval_after(None, missed=True), now, prior, missed=True)

    return new_state


def due_concepts(state: dict[str, Any] | None, now: datetime) -> list[str]:
    """Concepts whose next encounter is due (due_at <= now), soonest first."""
    if not state:
        return []
    now_utc = now if now.tzinfo else now.replace(tzinfo=_UTC)
    due: list[tuple[str, str]] = []
    for concept, entry in state.items():
        raw = (entry or {}).get("due_at")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=_UTC)
        if when <= now_utc:
            due.append((concept, raw))
    due.sort(key=lambda t: t[1])
    return [c for c, _ in due]


def next_due_at(state: dict[str, Any] | None) -> datetime | None:
    """The earliest due_at across all concepts, or None if the map is empty —
    used by daily_flow to decide whether a recitation is a next-action."""
    if not state:
        return None
    times: list[datetime] = []
    for entry in state.values():
        raw = (entry or {}).get("due_at")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        times.append(when if when.tzinfo else when.replace(tzinfo=_UTC))
    return min(times) if times else None
