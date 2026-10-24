"""Tests for app.services.focus + the /focus route (BEN-80)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import focus as focus_service
from app.services import initiatives as initiatives_service


_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


def _fake_initiative(
    *,
    slug: str = "bench",
    title: str = "Bench Product Development",
    status: str = "active",
    priority: int = 0,
    bench_surface: str | None = "/",
    github_repos: tuple[str, ...] = ("LiBearden/research-engineer-interview-prep",),
    ticket_prefix: str = "BEN",
    target_date: str | None = None,
) -> initiatives_service.Initiative:
    return initiatives_service.Initiative(
        slug=slug,
        title=title,
        status=status,
        priority=priority,
        linear=initiatives_service.InitiativeLinear(
            team="Li's Bench",
            ticket_prefix=ticket_prefix,
            label=None,
        ),
        github=initiatives_service.InitiativeGitHub(repos=github_repos),
        bench=initiatives_service.InitiativeBench(surface=bench_surface),
        target_date=target_date,
        notes="Test initiative notes.",
    )


def _attempt(started_at: datetime, *, initiative_slug: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        user_id="u",
        started_at=started_at,
        initiative_slug=initiative_slug,
    )


def _reflection(generated_at: datetime, *, initiative_slug: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        user_id="u",
        generated_at=generated_at,
        initiative_slug=initiative_slug,
    )


def _content_progress(
    checked_at: datetime,
    status: str = "completed",
    *,
    initiative_slug: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content_id="c1",
        status=status,
        checked_at=checked_at,
        initiative_slug=initiative_slug,
    )


# ---------------------------------------------------------------------------
# Activity rollup
# ---------------------------------------------------------------------------


def test_compute_activity_counts_only_last_7_days():
    """Rows without an initiative_slug fall into the unassigned bucket
    (slug=None). The 7-day window + completed-only filtering applies
    the same way regardless of which slug we ask for."""
    attempts = [
        _attempt(_NOW - timedelta(days=1)),
        _attempt(_NOW - timedelta(days=6)),
        _attempt(_NOW - timedelta(days=10)),  # outside window
    ]
    reflections = [_reflection(_NOW - timedelta(days=2))]
    content = {
        "c1": _content_progress(_NOW - timedelta(days=3)),
        "c2": _content_progress(_NOW - timedelta(days=20)),  # outside window
        "c3": _content_progress(_NOW - timedelta(days=1), status="in_progress"),  # not completed
    }

    # No tagged rows + no active slugs → everything counts as unassigned.
    activity = focus_service._compute_activity_for_slug(
        None,
        attempts=attempts,
        reflections=reflections,
        content_progress=content,
        now=_NOW,
        active_slugs=set(),
    )

    assert activity.attempts_last_7d == 2
    assert activity.reflections_last_7d == 1
    assert activity.content_completed_last_7d == 1


def test_compute_activity_handles_naive_datetimes():
    """Repos sometimes return naive datetimes; we coerce to UTC rather than crash."""
    naive_recent = (_NOW - timedelta(days=1)).replace(tzinfo=None)
    activity = focus_service._compute_activity_for_slug(
        None,
        attempts=[_attempt(naive_recent)],
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=set(),
    )
    assert activity.attempts_last_7d == 1


def test_compute_activity_handles_empty_inputs():
    activity = focus_service._compute_activity_for_slug(
        None,
        attempts=[],
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=set(),
    )
    assert activity.attempts_last_7d == 0
    assert activity.reflections_last_7d == 0
    assert activity.content_completed_last_7d == 0
    assert activity.last_attempt_at is None


# ---------------------------------------------------------------------------
# Per-attempt initiative tagging (migration 011 / PR #3 read path)
# ---------------------------------------------------------------------------


def test_compute_activity_filters_by_exact_slug_match():
    """The defining new behavior: attempts tagged 'capstone' show ONLY
    under Capstone, not under every bench-surface initiative.
    Validates the proposal's core promise."""
    attempts = [
        _attempt(_NOW - timedelta(days=1), initiative_slug="capstone"),
        _attempt(_NOW - timedelta(days=2), initiative_slug="capstone"),
        _attempt(_NOW - timedelta(days=1), initiative_slug="bench"),
        _attempt(_NOW - timedelta(days=3), initiative_slug=None),
    ]
    active = {"capstone", "bench"}

    capstone_activity = focus_service._compute_activity_for_slug(
        "capstone",
        attempts=attempts,
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=active,
    )
    bench_activity = focus_service._compute_activity_for_slug(
        "bench",
        attempts=attempts,
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=active,
    )

    # No double-counting: capstone sees 2, bench sees 1, total 3 +
    # 1 unassigned = matches input.
    assert capstone_activity.attempts_last_7d == 2
    assert bench_activity.attempts_last_7d == 1


def test_unassigned_bucket_includes_null_slug_rows():
    """Rows with NULL initiative_slug fall into the slug=None bucket."""
    attempts = [
        _attempt(_NOW - timedelta(days=1), initiative_slug=None),
        _attempt(_NOW - timedelta(days=2), initiative_slug="bench"),
    ]

    unassigned = focus_service._compute_activity_for_slug(
        None,
        attempts=attempts,
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs={"bench"},
    )

    assert unassigned.attempts_last_7d == 1


def test_unassigned_bucket_includes_rows_tagged_to_closed_initiative():
    """Rows tagged with a slug that's since been closed (e.g.,
    anthropic-fellows after rejection) fall into Unassigned — there's
    no card for that initiative on /focus anymore, so attribution
    has to go somewhere and Unassigned is the right somewhere."""
    attempts = [
        _attempt(_NOW - timedelta(days=1), initiative_slug="anthropic-fellows"),
        _attempt(_NOW - timedelta(days=2), initiative_slug="bench"),
    ]
    # active set excludes anthropic-fellows (it's closed)
    active = {"bench"}

    unassigned = focus_service._compute_activity_for_slug(
        None,
        attempts=attempts,
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=active,
    )
    bench_activity = focus_service._compute_activity_for_slug(
        "bench",
        attempts=attempts,
        reflections=[],
        content_progress={},
        now=_NOW,
        active_slugs=active,
    )

    assert unassigned.attempts_last_7d == 1
    assert bench_activity.attempts_last_7d == 1


def test_view_per_initiative_activity_uses_slug_match():
    """End-to-end via compute_focus_view: attempts tagged different
    slugs are correctly attributed to the right cards."""
    inits = [
        _fake_initiative(slug="bench", status="active"),
        _fake_initiative(slug="capstone", status="active", bench_surface=None),
    ]
    attempts = [
        _attempt(_NOW - timedelta(days=1), initiative_slug="capstone"),
        _attempt(_NOW - timedelta(days=1), initiative_slug="capstone"),
        _attempt(_NOW - timedelta(days=2), initiative_slug="bench"),
    ]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=attempts,
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    by_slug = {r.initiative.slug: r for r in view.rows}
    assert by_slug["bench"].activity.attempts_last_7d == 1
    assert by_slug["capstone"].activity.attempts_last_7d == 2


def test_view_initiative_without_bench_surface_can_now_accrue_activity():
    """Pre-tagging, initiatives whose bench.surface was null got zero
    activity (bench.surface heuristic). Now, with explicit tagging,
    they can accrue activity — useful for writings tagged to non-bench
    initiatives like content / legal / etc."""
    inits = [_fake_initiative(slug="legal", status="active", bench_surface=None)]
    attempts = [_attempt(_NOW - timedelta(days=1), initiative_slug="legal")]

    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=attempts,
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )

    assert view.rows[0].activity.attempts_last_7d == 1


def test_view_carries_unassigned_activity():
    """compute_focus_view exposes the unassigned bucket on the view so
    the template can render the toggle hint without re-computing."""
    inits = [_fake_initiative(slug="bench", status="active")]
    attempts = [
        _attempt(_NOW - timedelta(days=1), initiative_slug=None),
        _attempt(_NOW - timedelta(days=2), initiative_slug=None),
    ]

    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=attempts,
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )

    assert view.unassigned_activity.attempts_last_7d == 2
    # show_unassigned defaults False
    assert view.show_unassigned is False


def test_view_show_unassigned_flag_propagates():
    inits = [_fake_initiative(slug="bench", status="active")]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
            show_unassigned=True,
        )
    assert view.show_unassigned is True


# ---------------------------------------------------------------------------
# View composition
# ---------------------------------------------------------------------------


def test_view_orders_active_before_dormant_then_by_priority():
    inits = [
        _fake_initiative(slug="z-dormant", status="dormant", priority=0),
        _fake_initiative(slug="b-low", status="active", priority=2),
        _fake_initiative(slug="a-high", status="active", priority=0),
    ]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    slugs = [row.initiative.slug for row in view.rows]
    assert slugs == ["a-high", "b-low", "z-dormant"]


def test_view_orders_by_target_date_within_priority_bucket():
    """Same priority → earliest target_date first; undated last.
    Validation feedback 2026-05-25.
    """
    inits = [
        _fake_initiative(slug="undated", priority=1, target_date=None),
        _fake_initiative(slug="far", priority=1, target_date="2027-01-01"),
        _fake_initiative(slug="soon", priority=1, target_date="2026-06-01"),
        _fake_initiative(slug="higher-prio", priority=0, target_date="2027-12-01"),
    ]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    slugs = [row.initiative.slug for row in view.rows]
    # Higher priority (0) wins over all priority-1 rows regardless of date.
    # Within priority=1, soon < far < undated.
    assert slugs == ["higher-prio", "soon", "far", "undated"]


def test_target_date_relative_phrases_render_per_urgency():
    """The row carries (target_relative, target_urgency) so the template
    can paint overdue/soon/future tiers without duplicating math.
    """
    inits = [
        _fake_initiative(slug="overdue", target_date="2026-05-20"),  # 4d ago
        _fake_initiative(slug="today", target_date="2026-05-24"),     # today
        _fake_initiative(slug="soon", target_date="2026-06-01"),      # 8 days
        _fake_initiative(slug="future", target_date="2026-12-01"),    # ~6 months
        _fake_initiative(slug="undated", target_date=None),
    ]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    by_slug = {r.initiative.slug: r for r in view.rows}
    assert by_slug["overdue"].target_urgency == "overdue"
    assert "overdue 4 days" == by_slug["overdue"].target_relative
    assert by_slug["today"].target_urgency == "overdue"
    assert by_slug["today"].target_relative == "today"
    assert by_slug["soon"].target_urgency == "soon"
    assert by_slug["soon"].target_relative == "in 8 days"
    assert by_slug["future"].target_urgency == "future"
    # Either "in N weeks" (delta/7 ≤ 12) or "in N months" — both are
    # legal "future" phrases; assert the prefix.
    assert by_slug["future"].target_relative.startswith("in ")
    assert by_slug["undated"].target_urgency is None
    assert by_slug["undated"].target_relative is None


def test_format_target_date_handles_invalid_strings_gracefully():
    """Loader validates shape on load, but degrade-not-crash if a bad
    value sneaks through (e.g. via a partial migration)."""
    out_relative, out_urgency = focus_service._format_target_date(
        "not-a-date", now=_NOW
    )
    assert out_relative is None
    assert out_urgency is None


def test_view_hides_done_and_archived():
    inits = [
        _fake_initiative(slug="active1", status="active"),
        _fake_initiative(slug="finished", status="done"),
        _fake_initiative(slug="historical", status="archived"),
    ]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    assert [r.initiative.slug for r in view.rows] == ["active1"]


def test_view_marks_active_initiative_from_settings():
    inits = [_fake_initiative(slug="bench")]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={"active_initiative": "bench"},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    assert view.active_initiative_slug == "bench"


def test_view_with_gh_disabled_emits_integration_note():
    with patch.object(initiatives_service, "load_initiatives", return_value=[]):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    assert any("gh` CLI" in note for note in view.integration_notes)
    assert any("Linear" in note for note in view.integration_notes)


def test_view_initiative_without_bench_surface_has_zero_activity():
    inits = [_fake_initiative(slug="capstone", bench_surface=None)]
    attempts = [_attempt(_NOW - timedelta(days=1))]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=attempts,
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    # Initiative shown but with zero attribution since it has no bench surface.
    assert len(view.rows) == 1
    assert view.rows[0].activity.attempts_last_7d == 0


def test_view_row_pr_state_skipped_when_gh_unavailable():
    inits = [_fake_initiative()]
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
        )
    row = view.rows[0]
    assert row.pr_fetch_state == "skipped_no_gh"
    assert row.open_prs == ()


# ---------------------------------------------------------------------------
# /focus route
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Last-decided cross-surface lookup (BEN-82 follow-up)
# ---------------------------------------------------------------------------


def _outcome(*, eid: str, slug: str, decisions: str = "", next_actions: str = "",
             created_at: str = "2026-05-25T10:00:00+00:00"):
    return {
        "id": eid,
        "initiative": slug,
        "decisions": decisions,
        "next_actions": next_actions,
        "chat_url": None,
        "created_at": created_at,
    }


def _chat_outcome(
    *, eid, slug="bench", decisions="d", next_actions="",
    created_iso="2026-05-25T10:00:00+00:00",
):
    """Build a ChatOutcome instance for repo mocks. Post-PR-B the focus
    service consumes ChatOutcome dataclasses directly via the repo —
    no JSON parsing path remains, so tests use the dataclass shape."""
    from app.models import ChatOutcome
    from datetime import datetime as _dt
    created_at = _dt.fromisoformat(created_iso.replace("Z", "+00:00"))
    return ChatOutcome(
        id=eid,
        user_id="u",
        initiative_slug=slug,
        decisions=decisions,
        next_actions=next_actions,
        chat_url=None,
        created_at=created_at,
        source="mcp",
    )


def _repo_with_latest(latest_by_slug: dict):
    """Build a mock chat_outcomes_repo whose latest_per_initiative
    returns the provided {slug: ChatOutcome} dict."""
    from unittest.mock import MagicMock
    repo = MagicMock()
    repo.latest_per_initiative.return_value = latest_by_slug
    return repo


def test_latest_decision_picks_newest_per_initiative():
    """The repo's latest_per_initiative already returns just the newest
    per slug. The service just renders the FocusLastDecision shape."""
    repo = _repo_with_latest({
        "bench": _chat_outcome(eid="new", slug="bench", decisions="New"),
        "capstone": _chat_outcome(eid="capstone1", slug="capstone", decisions="Cap"),
    })
    out = focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    )
    assert set(out.keys()) == {"bench", "capstone"}
    assert out["bench"].entry_id == "new"
    assert out["bench"].decisions_excerpt == "New"
    assert out["capstone"].entry_id == "capstone1"


def test_latest_decision_returns_empty_when_repo_empty():
    repo = _repo_with_latest({})
    assert focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    ) == {}


def test_latest_decision_returns_empty_when_no_repo_wired():
    """Without a repo (e.g., test paths that don't inject one), the
    service short-circuits to empty rather than 500-ing /focus."""
    assert focus_service._latest_decision_by_initiative({}) == {}
    assert focus_service._latest_decision_by_initiative({}, user_id="u") == {}


def test_latest_decision_handles_repo_failure_gracefully():
    """A repo exception (e.g., connection blip) returns empty rather
    than propagating — /focus continues rendering."""
    from unittest.mock import MagicMock
    repo = MagicMock()
    repo.latest_per_initiative.side_effect = RuntimeError("DB hiccup")
    assert focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    ) == {}


def test_latest_decision_falls_back_to_next_actions_when_decisions_empty():
    repo = _repo_with_latest({
        "bench": _chat_outcome(eid="x", decisions="", next_actions="Ship Y"),
    })
    out = focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    )
    assert out["bench"].decisions_excerpt == "Ship Y"


def test_latest_decision_skips_entries_with_no_content():
    repo = _repo_with_latest({
        "bench": _chat_outcome(eid="empty", decisions="", next_actions=""),
    })
    assert focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    ) == {}


def test_latest_decision_excerpt_trimmed_with_ellipsis():
    long_text = "x" * 200
    repo = _repo_with_latest({
        "bench": _chat_outcome(eid="long", decisions=long_text),
    })
    out = focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    )
    excerpt = out["bench"].decisions_excerpt
    assert len(excerpt) <= 120
    assert excerpt.endswith("…")


def test_latest_decision_collapses_whitespace():
    """Multi-line entries should fit in one row on the dashboard."""
    repo = _repo_with_latest({
        "bench": _chat_outcome(
            eid="multi", decisions="Line 1\n\nLine 2\n  Line 3",
        ),
    })
    out = focus_service._latest_decision_by_initiative(
        {}, chat_outcomes_repo=repo, user_id="u",
    )
    assert "\n" not in out["bench"].decisions_excerpt
    assert "Line 1 Line 2 Line 3" == out["bench"].decisions_excerpt


def test_compute_focus_view_populates_last_decision_on_rows():
    """End-to-end: a row whose initiative slug appears in the repo's
    latest_per_initiative map gets a populated last_decision; others
    stay None."""
    inits = [
        _fake_initiative(slug="bench"),
        _fake_initiative(slug="capstone", bench_surface=None),
    ]
    repo = _repo_with_latest({
        "bench": _chat_outcome(eid="b1", slug="bench", decisions="Recent bench decision"),
    })
    with patch.object(initiatives_service, "load_initiatives", return_value=inits):
        view = focus_service.compute_focus_view(
            user_id="u",
            settings={},
            attempts=[],
            reflections=[],
            content_progress={},
            now=_NOW,
            gh_available=False,
            chat_outcomes_repo=repo,
        )
    by_slug = {r.initiative.slug: r for r in view.rows}
    assert by_slug["bench"].last_decision is not None
    assert by_slug["bench"].last_decision.entry_id == "b1"
    assert by_slug["capstone"].last_decision is None
    assert by_slug["capstone"].last_decision is None


def test_focus_route_renders_for_authenticated_user(monkeypatch):
    """End-to-end: GET /focus returns 200 with the dashboard markup."""
    import app.main as m
    from starlette.requests import Request

    monkeypatch.setattr(m.attempt_repo, "all_for_user", lambda _uid: [])
    monkeypatch.setattr(m.reflection_repo, "list_for_user", lambda _uid, limit=200: [])
    monkeypatch.setattr(m.content_repo, "progress_for_user", lambda _uid: {})
    monkeypatch.setattr(
        initiatives_service,
        "load_initiatives",
        lambda: [_fake_initiative()],
    )
    # Skip the gh CLI entirely in unit tests.
    monkeypatch.setattr(focus_service, "_gh_cli_available", lambda: False)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/focus",
            "headers": [],
            "query_string": b"",
        }
    )
    request.state.user_session = SimpleNamespace(
        user_id="00000000-0000-0000-0000-000000000001",
        email="op@example.com",
    )
    request.state.user_settings = {"active_initiative": "bench"}

    response = m.focus_page(request)
    assert response.status_code == 200
    body = response.body.decode()
    assert "Focus" in body
    assert "Bench Product Development" in body
    assert "gh` CLI" in body  # integration note rendered
