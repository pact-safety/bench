"""Unit coverage for /connecting (WS6, BEN-94).

Tests the pure service layer (warmth-decay scoring, view composition,
days-since phrasing). No DB — the repo layer is exercised via the
integration tier; here we test the math + aggregation that decides
what the operator sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from app.services import connecting as svc
from app.models import Contact, ContactInteraction


def _contact(
    id: int,
    name: str = "Test Person",
    cadence_days: int = 30,
    archived: bool = False,
) -> Contact:
    return Contact(
        id=id,
        user_id="11111111-1111-1111-1111-111111111111",
        name=name,
        email=None,
        handle=None,
        context=None,
        cadence_days=cadence_days,
        archived=archived,
        created_at=datetime(2026, 5, 1, 12, 0, 0),
        updated_at=datetime(2026, 5, 1, 12, 0, 0),
    )


def _interaction(
    contact_id: int,
    occurred_at: datetime,
    direction: str | None = None,
    kind: str = "sent",
) -> ContactInteraction:
    return ContactInteraction(
        id=1,
        contact_id=contact_id,
        user_id="11111111-1111-1111-1111-111111111111",
        occurred_at=occurred_at,
        kind=kind,
        direction=direction,
        notes=None,
        created_at=occurred_at,
    )


NOW = datetime(2026, 5, 28, 12, 0, 0)


# ─── compute_warmth ─────────────────────────────────────────────

def test_warmth_full_on_just_touched():
    """Same-second touch = full warmth."""
    latest = _interaction(1, NOW)
    score, tier, days = svc.compute_warmth(latest=latest, cadence_days=30, now=NOW)
    assert score == 1.0
    assert tier == "warm"
    assert days == 0


def test_warmth_half_at_cadence_boundary():
    """At exactly cadence_days, warmth is 0.5 — half decayed.
    The formula: 1 - days / (cadence * 2) → 1 - 30/60 = 0.5."""
    latest = _interaction(1, NOW - timedelta(days=30))
    score, tier, days = svc.compute_warmth(latest=latest, cadence_days=30, now=NOW)
    assert abs(score - 0.5) < 1e-9
    # 0.5 falls in the "fading" tier (>=0.33, <0.66).
    assert tier == "fading"
    assert days == 30


def test_warmth_zero_at_double_cadence():
    """At 2x cadence, fully cold."""
    latest = _interaction(1, NOW - timedelta(days=60))
    score, tier, days = svc.compute_warmth(latest=latest, cadence_days=30, now=NOW)
    assert score == 0.0
    assert tier == "cold"
    assert days == 60


def test_warmth_clamps_below_zero_past_double_cadence():
    """Days past 2x cadence don't push warmth below 0 — it floors."""
    latest = _interaction(1, NOW - timedelta(days=180))
    score, tier, _ = svc.compute_warmth(latest=latest, cadence_days=30, now=NOW)
    assert score == 0.0
    assert tier == "cold"


def test_warmth_never_when_no_interaction():
    """No interaction yet → never tier, score 0, days_since None.
    Brand-new contacts thus surface in the operator's reach-out queue
    immediately."""
    score, tier, days = svc.compute_warmth(latest=None, cadence_days=30, now=NOW)
    assert score == 0.0
    assert tier == "never"
    assert days is None


def test_warmth_respects_custom_cadence():
    """Weekly cadence: at 7d the warmth is 0.5; at 14d it's 0."""
    latest = _interaction(1, NOW - timedelta(days=7))
    score, _, _ = svc.compute_warmth(latest=latest, cadence_days=7, now=NOW)
    assert abs(score - 0.5) < 1e-9

    latest_14 = _interaction(1, NOW - timedelta(days=14))
    score_14, tier_14, _ = svc.compute_warmth(
        latest=latest_14, cadence_days=7, now=NOW
    )
    assert score_14 == 0.0
    assert tier_14 == "cold"


def test_warmth_handles_tiny_cadence_without_division_error():
    """cadence_days=1 doesn't blow up. The min divisor clamp in the
    service keeps the formula well-defined even on absurd inputs."""
    latest = _interaction(1, NOW)
    score, _, _ = svc.compute_warmth(latest=latest, cadence_days=1, now=NOW)
    assert score == 1.0


# ─── compose_view ───────────────────────────────────────────────

def test_view_sorts_coldest_first():
    """The list view orders by warmth ascending so the most-overdue
    contact is at the top of the page."""
    warm = _contact(1, name="Warm contact")
    cold = _contact(2, name="Cold contact")
    fading = _contact(3, name="Fading contact")

    latest = {
        1: _interaction(1, NOW),                          # warmth 1.0
        2: _interaction(2, NOW - timedelta(days=90)),     # warmth 0.0
        3: _interaction(3, NOW - timedelta(days=30)),     # warmth 0.5
    }
    view = svc.compose_view(
        contacts=[warm, cold, fading],
        latest_by_contact=latest,
        now=NOW,
    )
    names = [r.contact.name for r in view.rows]
    assert names == ["Cold contact", "Fading contact", "Warm contact"]


def test_view_counts_their_move_and_cold():
    """The header micro-stats: total contacts with their_move=True
    (last interaction was inbound), and total in cold/never tiers."""
    c1 = _contact(1, name="Owes reply")
    c2 = _contact(2, name="Owes follow-up")
    c3 = _contact(3, name="Never logged")
    c4 = _contact(4, name="All good")

    latest = {
        1: _interaction(1, NOW - timedelta(days=10), direction="inbound", kind="call"),
        2: _interaction(2, NOW - timedelta(days=90), direction="outbound", kind="call"),
        # c3 has no entry — "never" tier
        4: _interaction(4, NOW, direction="outbound", kind="call"),
    }
    view = svc.compose_view(
        contacts=[c1, c2, c3, c4],
        latest_by_contact=latest,
        now=NOW,
    )
    # their_move: c1 (inbound at 10d) — c2 was outbound; c4 was outbound.
    assert view.their_move_count == 1
    # cold_count: c2 (cold) + c3 (never) = 2.
    assert view.cold_count == 2


def test_view_handles_empty_contacts_list():
    """No contacts → empty view, counts all zero."""
    view = svc.compose_view(contacts=[], latest_by_contact={}, now=NOW)
    assert view.rows == ()
    assert view.their_move_count == 0
    assert view.cold_count == 0


def test_view_treats_missing_latest_as_never():
    """A contact whose id isn't in latest_by_contact gets a 'never'
    row — same as if no interaction had been explicitly fetched."""
    c = _contact(1, name="Brand new")
    view = svc.compose_view(
        contacts=[c],
        latest_by_contact={},  # not present
        now=NOW,
    )
    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.tier == "never"
    assert row.latest is None
    assert row.days_since is None
    assert row.their_move is False


def test_view_stable_tiebreaker_on_name():
    """Two contacts with identical warmth sort alphabetically by name
    so the list is deterministic for tests and doesn't jitter for the
    operator."""
    c_z = _contact(1, name="Zara")
    c_a = _contact(2, name="Alex")
    # Both touched at the same instant.
    same_time = NOW - timedelta(days=5)
    latest = {
        1: _interaction(1, same_time),
        2: _interaction(2, same_time),
    }
    view = svc.compose_view(
        contacts=[c_z, c_a], latest_by_contact=latest, now=NOW
    )
    names = [r.contact.name for r in view.rows]
    assert names == ["Alex", "Zara"]


# ─── days_since_phrase ──────────────────────────────────────────

def test_days_since_phrase_handles_each_bucket():
    """Spot-check the bucketed phrasing — terse, no marketing-speak."""
    assert svc.days_since_phrase(None) == "never logged"
    assert svc.days_since_phrase(0) == "today"
    assert svc.days_since_phrase(1) == "yesterday"
    assert svc.days_since_phrase(3) == "3 days ago"
    assert svc.days_since_phrase(7) == "1 week ago"
    assert svc.days_since_phrase(14) == "2 weeks ago"
    assert svc.days_since_phrase(30) == "1 month ago"
    assert svc.days_since_phrase(90) == "3 months ago"
    assert svc.days_since_phrase(365) == "1 year ago"
    assert svc.days_since_phrase(730) == "2 years ago"


@pytest.mark.parametrize('kind', ['received', 'sent', 'meeting', 'call', 'message'])
@pytest.mark.parametrize('direction', [None, 'inbound', 'outbound'])
def test_reply_state_derives_unambiguous_kind_for_historical_rows(kind, direction):
    contact = _contact(1)
    latest = _interaction(1, NOW, kind=kind, direction=direction)
    view = svc.compose_view(contacts=[contact], latest_by_contact={1: latest}, now=NOW)
    expected = kind == 'received' if kind in ('received', 'sent') else direction == 'inbound'
    assert view.rows[0].their_move is expected
    assert view.their_move_count == int(expected)
    # Derivation repairs the displayed state without rewriting historical data.
    assert latest.direction == direction
