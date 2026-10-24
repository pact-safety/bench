"""Service layer for /connecting (WS6, BEN-94).

Composes the list view by joining contacts with their latest
interaction and computing warmth-decay scores. Pure functions over
data — no I/O. Repo handles the DB round-trips; the route handler
calls into here to assemble the view.

Warmth decay model:

    warmth = max(0, 1 - days_since_last_interaction / (cadence_days * 2))

The intuition: a contact at exactly `cadence_days` since last touch
is half-decayed (warmth = 0.5). Past 2x the cadence they're fully
cold (warmth = 0). New contact with no interactions yet is also
treated as cold so they surface in the operator's "reach out" queue
right after creation.

Tiers derived from the score:

  warm    >= 0.66    just touched, no urgency
  fading  0.33-0.66  cadence approaching
  cold    <  0.33    overdue
  never   no log     no interaction yet (special)

The list view orders by warmth ascending — coldest first — so the
operator sees who's most overdue at the top.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import Contact, ContactInteraction


@dataclass(frozen=True)
class ContactRow:
    """One row in the /connecting list view. Wraps the persisted
    Contact with computed warmth + display helpers."""
    contact: Contact
    latest: ContactInteraction | None
    warmth: float            # 0.0 (cold) → 1.0 (warm)
    tier: str                # "warm" | "fading" | "cold" | "never"
    days_since: int | None   # None when no interaction yet
    their_move: bool         # operator owes a reply after an inbound touch


@dataclass(frozen=True)
class ConnectingView:
    """Top-level rollup for /connecting. The list is pre-sorted by
    warmth ascending; the template iterates it directly."""
    rows: tuple[ContactRow, ...]
    their_move_count: int    # how many rows have their_move=True
    cold_count: int          # tier == 'cold' or 'never'


# Tier thresholds. Same dial moves both visual treatment and the
# top-of-page "X overdue" headline. Centralized here so the template
# doesn't redefine them.
_WARM_FLOOR = 0.66
_FADING_FLOOR = 0.33


def compute_warmth(
    *,
    latest: ContactInteraction | None,
    cadence_days: int,
    now: datetime,
) -> tuple[float, str, int | None]:
    """Pure warmth computation. Returns (score, tier, days_since)
    where score is in [0.0, 1.0] and tier is one of the four labels.

    Pure function; no DB, no I/O. Called once per contact during
    view composition; also re-exported for unit tests.
    """
    if latest is None or latest.occurred_at is None:
        # Never logged. Cold by convention so brand-new contacts
        # surface for "reach out" prompts.
        return 0.0, "never", None

    delta = now - latest.occurred_at
    days = max(0, int(delta.total_seconds() // 86400))
    # Guard the divisor against the schema's CHECK lower bound and any
    # future drift. cadence_days * 2 forms the "fully cold" boundary.
    span = max(1, int(cadence_days) * 2)
    score = max(0.0, 1.0 - days / span)

    if score >= _WARM_FLOOR:
        tier = "warm"
    elif score >= _FADING_FLOOR:
        tier = "fading"
    else:
        tier = "cold"
    return score, tier, days


def compose_view(
    *,
    contacts: list[Contact],
    latest_by_contact: dict[int, ContactInteraction],
    now: datetime,
) -> ConnectingView:
    """Build a ConnectingView from raw repo output.

    `contacts` is the user's contact list (already archive-filtered
    by the repo). `latest_by_contact` is the per-contact most-recent
    interaction (fetched in a single round trip by
    repo.latest_interaction_by_contact). Both feed into a single
    in-memory aggregation; no I/O happens here.
    """
    rows: list[ContactRow] = []
    for c in contacts:
        latest = latest_by_contact.get(c.id) if c.id is not None else None
        score, tier, days = compute_warmth(
            latest=latest,
            cadence_days=c.cadence_days,
            now=now,
        )
        # Older received/sent rows may have blank or contradictory direction;
        # derive their meaning without rewriting the saved interaction history.
        direction = ({"received": "inbound", "sent": "outbound"}.get(latest.kind, latest.direction)
                     if latest else None)
        their_move = direction == "inbound"
        rows.append(
            ContactRow(
                contact=c,
                latest=latest,
                warmth=score,
                tier=tier,
                days_since=days,
                their_move=their_move,
            )
        )

    # Coldest first. Stable tiebreaker on name keeps the list
    # deterministic for tests + spares the operator from jitter when
    # two contacts have identical warmth.
    rows.sort(key=lambda r: (r.warmth, r.contact.name.lower()))

    their_move_count = sum(1 for r in rows if r.their_move)
    cold_count = sum(1 for r in rows if r.tier in ("cold", "never"))

    return ConnectingView(
        rows=tuple(rows),
        their_move_count=their_move_count,
        cold_count=cold_count,
    )


# Microcopy helpers — return human strings the template can render
# without inline conditionals. Centralized so the wording stays
# consistent across surfaces if /connecting later surfaces summaries
# elsewhere (e.g., a "you have 3 overdue contacts" rail card on /).

def days_since_phrase(days: int | None) -> str:
    """Human relative phrase for the row meta line. Mirrors the
    /focus target-date helper's tone (terse, no marketing-speak)."""
    if days is None:
        return "never logged"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"
