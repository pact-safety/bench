"""BEN-135: due recitations surface through daily_flow as a next-action,
framed as what's returning (never what was missed)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.models import ContentProgress
from app.services import daily_flow
from app.services import recitation_schedule as rs

_TODAY = date(2026, 7, 23)


def _progress(state):
    return ContentProgress(
        user_id="u", content_id=5, status="in_progress",
        checked_at=None, notes_md=None, recitation_state=state,
    )


def test_due_recitation_surfaces_as_next_action():
    past = datetime(2026, 7, 20, tzinfo=timezone.utc)
    state = {"attention mask": {"interval_days": 1, "due_at": rs._iso(past), "misses": 1}}
    item = SimpleNamespace(title="Attention paper", slug="attn", kind="reading")
    action = daily_flow.compute_next(
        today=_TODAY,
        progress_by_content_id={5: _progress(state)},
        content_by_id={5: item},
    )
    assert action.kind == "recite"
    assert action.url == "/content/attn#recite"
    assert "come back" in action.why      # scheduling framing, not "missed"


def test_future_recitation_does_not_surface():
    future = datetime(2026, 7, 30, tzinfo=timezone.utc)
    state = {"softmax": {"interval_days": 7, "due_at": rs._iso(future), "misses": 0}}
    item = SimpleNamespace(title="x", slug="x", kind="reading")
    action = daily_flow.compute_next(
        today=_TODAY,
        progress_by_content_id={5: _progress(state)},
        content_by_id={5: item},
    )
    assert action.kind != "recite"   # nothing due → normal flow (caught_up here)
