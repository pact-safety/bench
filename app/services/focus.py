"""Focus dashboard service.

BEN-80: cross-surface priority dashboard. The surface the operator
opens when they don't know what they were working on yesterday or
which thread to pick up today.

This module composes data from:

* The bench's own state (attempts, reflections, content progress,
  active track + JD + writing) — always available.
* GitHub open PRs across the LiBearden repos linked from each
  initiative — best-effort via ``gh`` CLI; falls back to "configure
  the `gh` CLI to see PRs" when the CLI is absent or unauthenticated.
* Linear open + in-progress tickets matching each initiative's
  team/prefix — deferred until BEN-81's MCP server exposes a reliable
  per-initiative query; for MVP we render a "Linear integration
  pending" placeholder rather than block the surface.

The whole computation is wrapped so any single source failure
degrades gracefully rather than 500-ing /focus. The operator must
always be able to open this page and see *something*, even on an
airplane with no network and no GitHub CLI.

The service is intentionally pure-functional: callers pass the
operator's settings + per-source fetchers; the service does the
join + ordering. This shape lets BEN-81's MCP server later expose
the same view to claude.ai via ``get_current_focus()`` without
duplicating the join logic.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import initiatives as initiatives_service


_GH_TIMEOUT_SECONDS = 8
_RECENT_ACTIVITY_DAYS = 14


@dataclass(frozen=True)
class FocusActivity:
    """One bench-side activity bucket for an initiative."""
    attempts_last_7d: int = 0
    reflections_last_7d: int = 0
    content_completed_last_7d: int = 0
    last_attempt_at: datetime | None = None
    last_reflection_at: datetime | None = None


@dataclass(frozen=True)
class FocusPR:
    """One open PR pulled from GitHub for an initiative's linked repos."""
    repo: str  # "owner/repo"
    number: int
    title: str
    url: str
    is_draft: bool
    updated_at: str  # ISO string from gh; we don't bother parsing


@dataclass(frozen=True)
class FocusLastDecision:
    """Latest journal entry (/decisions) for one initiative.

    Surfaced on the focus row so the operator can see "I decided X
    yesterday on capstone" at a glance, with click-through to the
    permalink. Populated by joining initiatives with the MCP-written
    chat_outcomes log; absent when no entries exist for that slug.
    """
    entry_id: str
    decisions_excerpt: str  # first 120 chars, ellipsis-trimmed
    created_at: datetime


@dataclass(frozen=True)
class FocusInitiativeRow:
    """Per-initiative row in the focus dashboard."""
    initiative: initiatives_service.Initiative
    activity: FocusActivity
    open_prs: tuple[FocusPR, ...] = ()
    pr_fetch_state: str = "ok"  # "ok" | "skipped_no_gh" | "skipped_unauth" | "error"
    pr_fetch_error: str = ""
    # Linear: deferred. Stub for shape stability.
    linear_state: str = "deferred"
    linear_open_count: int | None = None
    # /decisions cross-surface link (closes BEN-82's "/focus shows last
    # decided per initiative" follow-up). None when no chat outcome has
    # been logged for this initiative.
    last_decision: FocusLastDecision | None = None
    # Pre-computed target-date display (validation feedback 2026-05-25:
    # "wonky ordering — make this better, maybe with priorities + due dates").
    # `target_relative` is a human phrase ("in 12 days", "overdue 4 days").
    # `target_urgency` drives the CSS class — "overdue" | "soon" | "future".
    # Both None when initiative has no target_date.
    target_relative: str | None = None
    target_urgency: str | None = None

    @property
    def bucket(self) -> str:
        """Status-based bucket label for the collapsible /focus layout.
        Mirrors initiative.status but exposed on the row so the template
        doesn't have to reach through ``row.initiative.status``."""
        return self.initiative.status

    @property
    def recent_activity_total(self) -> int:
        """Single-number summary surfaced on each compact row in the
        collapsible layout — sum of attempts + reflections + content
        completed in the last 7 days. The detail card (attempts /
        reflections / content separately) still lives behind the
        expand-on-click row interaction."""
        return (
            self.activity.attempts_last_7d
            + self.activity.reflections_last_7d
            + self.activity.content_completed_last_7d
        )


@dataclass(frozen=True)
class FocusView:
    """Top-level rollup for /focus."""
    generated_at: datetime
    active_initiative_slug: str | None
    rows: tuple[FocusInitiativeRow, ...] = field(default_factory=tuple)
    integration_notes: tuple[str, ...] = field(default_factory=tuple)
    # Unassigned bucket: activity whose initiative_slug is NULL OR
    # points at a non-active initiative. Always computed; the template
    # only renders the dedicated card when ``show_unassigned`` is true.
    # A small "(N items unassigned — show)" hint appears even when
    # hidden, so the operator knows the bucket has content without
    # being subjected to it.
    unassigned_activity: FocusActivity = field(default_factory=lambda: FocusActivity())
    # The route handler propagates ``?show_unassigned=1`` as this flag.
    show_unassigned: bool = False

    @property
    def active_rows(self) -> tuple[FocusInitiativeRow, ...]:
        """Rows whose initiative.status == 'active'. The /focus template
        renders these inside the first <details open> section."""
        return tuple(r for r in self.rows if r.bucket == "active")

    @property
    def dormant_rows(self) -> tuple[FocusInitiativeRow, ...]:
        """Rows whose initiative.status == 'dormant' — work that's
        paused but not done. Collapsed by default in the template."""
        return tuple(r for r in self.rows if r.bucket == "dormant")

    @property
    def closed_rows(self) -> tuple[FocusInitiativeRow, ...]:
        """Rows whose initiative.status is 'done' or 'archived' —
        the dashboard's audit trail. Only populated when the route
        passes include_closed=True. Collapsed by default."""
        return tuple(r for r in self.rows if r.bucket in ("done", "archived"))

    @property
    def unassigned_total(self) -> int:
        """Single-number summary for the Unassigned bucket header — the
        sum that the template uses to decide whether to render the
        section at all."""
        u = self.unassigned_activity
        return (
            u.attempts_last_7d
            + u.reflections_last_7d
            + u.content_completed_last_7d
        )


# ---------------------------------------------------------------------------
# Target-date formatting (validation feedback 2026-05-25)
# ---------------------------------------------------------------------------


def _format_target_date(
    target_date: str | None, *, now: datetime
) -> tuple[str | None, str | None]:
    """Render an initiative's target_date as (phrase, urgency-tier).

    Returns (None, None) when there's no target_date. Otherwise:

    * "overdue 12 days" / urgency="overdue" — target in the past
    * "today" / urgency="overdue" — target is today (treated as urgent)
    * "in 5 days" / urgency="soon" — target ≤ 30 days out
    * "in 12 weeks" / urgency="future" — target > 30 days out

    Parses date strings as plain YYYY-MM-DD (no timezone math); the
    initiatives loader already validates this shape on load. `now` is
    truncated to its date portion for the comparison so a target of
    today never flips between "today" and "in 1 day" depending on
    wall-clock hour.
    """
    if not target_date:
        return None, None
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        # Loader should have rejected this, but degrade gracefully.
        return None, None

    today = now.date()
    delta = (target - today).days

    if delta < 0:
        n = -delta
        return f"overdue {n} day{'s' if n != 1 else ''}", "overdue"
    if delta == 0:
        return "today", "overdue"
    if delta <= 30:
        return f"in {delta} day{'s' if delta != 1 else ''}", "soon"
    weeks = delta // 7
    if weeks <= 12:
        return f"in {weeks} week{'s' if weeks != 1 else ''}", "future"
    months = delta // 30
    return f"in {months} month{'s' if months != 1 else ''}", "future"


# ---------------------------------------------------------------------------
# Bench-side activity (per-attempt initiative tagging — migration 011)
# ---------------------------------------------------------------------------


def _row_initiative_slug(row: Any) -> str | None:
    """Read the row's tagged initiative_slug. Returns None if absent
    (pre-PR-#275 rows) or if explicitly None ('unassigned')."""
    return getattr(row, "initiative_slug", None)


def _row_matches_active_slugs(row: Any, active_slugs: set[str]) -> bool:
    """True if this row's initiative_slug points at a currently-active
    initiative. Rows tagged with a slug that's since been closed
    (e.g., anthropic-fellows after rejection) fall into the unassigned
    bucket rather than being silently dropped — that initiative's card
    isn't on /focus anymore, so showing the activity there would be
    impossible anyway."""
    slug = _row_initiative_slug(row)
    return slug is not None and slug in active_slugs


def _compute_activity_for_slug(
    slug: str | None,
    *,
    attempts: list[Any],
    reflections: list[Any],
    content_progress: dict[str, Any],
    now: datetime,
    active_slugs: set[str],
) -> FocusActivity:
    """Aggregate the last 7 days of bench activity matching this slug.

    Pass ``slug=None`` to compute the "unassigned" bucket: rows whose
    initiative_slug is NULL (pre-tagging legacy or operator-explicit
    unassigned) PLUS rows tagged with a now-closed initiative.

    Pass a specific slug to compute that initiative's activity.

    Args:
        slug: The initiative slug to filter on, or None for unassigned.
        active_slugs: Set of currently-active initiative slugs. Used
            only when ``slug is None`` to determine which non-NULL
            rows are "effectively unassigned" (i.e., tagged but the
            target initiative is no longer active).
    """
    seven_days_ago = now - timedelta(days=7)

    def _to_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def _row_in_bucket(row: Any) -> bool:
        if slug is None:
            # Unassigned bucket: NULL slug OR pointing at non-active
            # initiative (closed/archived/removed).
            return not _row_matches_active_slugs(row, active_slugs)
        return _row_initiative_slug(row) == slug

    last_attempt_at: datetime | None = None
    attempts_in_window = 0
    for attempt in attempts:
        if not _row_in_bucket(attempt):
            continue
        started = _to_aware(getattr(attempt, "started_at", None))
        if started is None:
            continue
        if last_attempt_at is None or started > last_attempt_at:
            last_attempt_at = started
        if started >= seven_days_ago:
            attempts_in_window += 1

    last_reflection_at: datetime | None = None
    reflections_in_window = 0
    for refl in reflections:
        if not _row_in_bucket(refl):
            continue
        generated = _to_aware(getattr(refl, "generated_at", None))
        if generated is None:
            continue
        if last_reflection_at is None or generated > last_reflection_at:
            last_reflection_at = generated
        if generated >= seven_days_ago:
            reflections_in_window += 1

    content_in_window = 0
    for prog in content_progress.values():
        if not _row_in_bucket(prog):
            continue
        if getattr(prog, "status", None) != "completed":
            continue
        checked = _to_aware(getattr(prog, "checked_at", None))
        if checked is None:
            continue
        if checked >= seven_days_ago:
            content_in_window += 1

    return FocusActivity(
        attempts_last_7d=attempts_in_window,
        reflections_last_7d=reflections_in_window,
        content_completed_last_7d=content_in_window,
        last_attempt_at=last_attempt_at,
        last_reflection_at=last_reflection_at,
    )


# ---------------------------------------------------------------------------
# GitHub PRs (via gh CLI)
# ---------------------------------------------------------------------------


def _gh_cli_available() -> bool:
    """True when the `gh` CLI is on PATH and not explicitly disabled."""
    if os.environ.get("FOCUS_DISABLE_GH") == "1":
        return False
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _fetch_open_prs_for_repo(repo: str) -> tuple[list[FocusPR], str, str]:
    """Fetch open PRs for one repo via gh CLI.

    Returns (prs, state, error_message). `state` is "ok" | "skipped_unauth"
    | "error" so the caller can distinguish "we tried but got nothing" from
    "the auth needs setup."
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--repo", repo,
                "--state", "open",
                "--limit", "10",
                "--json", "number,title,url,isDraft,updatedAt",
            ],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], "error", f"gh CLI timed out after {_GH_TIMEOUT_SECONDS}s"
    except FileNotFoundError:
        return [], "skipped_no_gh", "gh CLI not on PATH"

    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if "authentication" in stderr or "gh auth login" in stderr:
            return [], "skipped_unauth", "gh CLI not authenticated (run `gh auth login`)"
        return [], "error", (result.stderr or "unknown gh error").strip()[:200]

    try:
        import json
        raw = json.loads(result.stdout or "[]")
    except (ValueError, TypeError) as exc:
        return [], "error", f"could not parse gh output: {exc}"

    prs: list[FocusPR] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            prs.append(
                FocusPR(
                    repo=repo,
                    number=int(entry["number"]),
                    title=str(entry.get("title", "")),
                    url=str(entry.get("url", "")),
                    is_draft=bool(entry.get("isDraft", False)),
                    updated_at=str(entry.get("updatedAt", "")),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return prs, "ok", ""


def _fetch_open_prs_for_initiative(
    initiative: initiatives_service.Initiative,
    *,
    gh_available: bool,
) -> tuple[tuple[FocusPR, ...], str, str]:
    """Aggregate open PRs across an initiative's linked repos."""
    if not gh_available:
        return (), "skipped_no_gh", "gh CLI not on PATH (set FOCUS_DISABLE_GH=1 to silence)"
    if not initiative.github.repos:
        return (), "ok", ""

    all_prs: list[FocusPR] = []
    error_state = "ok"
    error_message = ""

    for repo in initiative.github.repos:
        prs, state, err = _fetch_open_prs_for_repo(repo)
        all_prs.extend(prs)
        # Surface the first non-ok state so the operator sees a real error
        # instead of "0 PRs."
        if state != "ok" and error_state == "ok":
            error_state = state
            error_message = err

    # Sort most-recently-updated first.
    all_prs.sort(key=lambda pr: pr.updated_at, reverse=True)
    return tuple(all_prs), error_state, error_message


# ---------------------------------------------------------------------------
# Latest-decision lookup (joins /focus with /decisions / BEN-82)
# ---------------------------------------------------------------------------


_DECISIONS_EXCERPT_MAX = 120


def _decision_excerpt(decisions: str, next_actions: str) -> str:
    """Build a short label for the focus row.

    Prefer decisions prose; fall back to next_actions when the entry
    only has next-action text. Trim with ellipsis at ``_DECISIONS_EXCERPT_MAX``.
    """
    text = (decisions or "").strip() or (next_actions or "").strip()
    if not text:
        return ""
    # Collapse internal whitespace so multi-line entries fit in one row.
    flat = " ".join(text.split())
    if len(flat) <= _DECISIONS_EXCERPT_MAX:
        return flat
    return flat[: _DECISIONS_EXCERPT_MAX - 1].rstrip() + "…"


def _latest_decision_by_initiative(
    settings: dict,
    chat_outcomes_repo: Any = None,
    user_id: str | None = None,
) -> dict[str, FocusLastDecision]:
    """Return ``{initiative_slug: FocusLastDecision}`` from chat_outcomes.

    Post-PR-B: repo-only. The legacy ``user_settings.chat_outcomes``
    JSON parachute is gone. When the repo isn't wired (unit tests
    without a chat_outcomes_repo mock), returns an empty dict — /focus
    just renders without "last decided" rows in that case.

    The ``settings`` arg is kept in the signature for backward-compat
    with callers passing it; it's no longer read here.
    """
    del settings  # explicitly unused now

    if chat_outcomes_repo is None or not user_id:
        return {}

    try:
        repo_rows = chat_outcomes_repo.latest_per_initiative(user_id)
    except Exception:  # noqa: BLE001 — read path must never 500 the page
        return {}

    out: dict[str, FocusLastDecision] = {}
    for slug, co in repo_rows.items():
        excerpt = _decision_excerpt(co.decisions, co.next_actions)
        if not excerpt:
            continue
        created_at = co.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        out[slug] = FocusLastDecision(
            entry_id=co.id,
            decisions_excerpt=excerpt,
            created_at=created_at,
        )
    return out


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def compute_focus_view(
    *,
    user_id: str,
    settings: dict,
    attempts: list[Any],
    reflections: list[Any],
    content_progress: dict[str, Any],
    now: datetime | None = None,
    gh_available: bool | None = None,
    chat_outcomes_repo: Any = None,
    show_unassigned: bool = False,
    include_closed: bool = False,
) -> FocusView:
    """Compose the /focus dashboard view from current bench state.

    `gh_available` is a dependency-injection knob for tests; pass `False`
    to skip CLI calls entirely. `chat_outcomes_repo` switches the
    "last decided" lookup to use the migration-009 table; when None,
    falls back to the legacy JSON storage.

    `include_closed` controls whether done/archived initiatives appear
    in `rows` for the closed bucket (WS2 collapsible-by-status layout,
    2026-05-28). The /focus route opts in so the operator gets the
    audit-trail bucket; non-UI callers (MCP, legacy chat-outcome
    lookups) stay opted out so behavior is unchanged for them.
    """
    now = now or datetime.now(timezone.utc)
    if gh_available is None:
        gh_available = _gh_cli_available()

    integration_notes: list[str] = []
    if not gh_available:
        integration_notes.append(
            "GitHub: `gh` CLI not detected. PR counts hidden. "
            "Install + authenticate the GitHub CLI to enable."
        )
    integration_notes.append(
        "Linear: per-initiative ticket counts deferred until BEN-81 "
        "(MCP server). Use the Linear app for now."
    )

    all_initiatives = initiatives_service.load_initiatives()
    # Order: active first (by priority asc — 0=highest), then dormant,
    # then done/archived (only when ``include_closed`` is set). Within
    # each tier: by target_date (earliest first; undated sorts after
    # dated), then alphabetical for a stable tiebreaker. Validation
    # feedback 2026-05-25 wanted priorities + due-date ordering so the
    # next deadline is obvious.
    visible_statuses = {"active", "dormant"}
    if include_closed:
        visible_statuses |= {"done", "archived"}
    status_order = {"active": 0, "dormant": 1, "done": 2, "archived": 3}
    visible = [i for i in all_initiatives if i.status in visible_statuses]
    visible.sort(
        key=lambda i: (
            status_order.get(i.status, 99),
            i.priority,
            i.target_date or "9999-12-31",
            i.title.lower(),
        )
    )

    # Pre-compute the per-initiative "last decided" entry. Prefers the
    # DB-backed repo (PR A of the chat_outcomes cutover) when wired;
    # falls back to the legacy JSON storage in settings.
    last_decision_by_slug = _latest_decision_by_initiative(
        settings,
        chat_outcomes_repo=chat_outcomes_repo,
        user_id=user_id,
    )

    # Per-attempt tagging (migration 011 / PR #275): attribute activity
    # by exact ``initiative_slug`` match rather than the old
    # ``bench.surface == "/"`` heuristic. An attempt tagged ``capstone``
    # shows under Capstone; the same attempt no longer double-counts
    # under "Bench Product Development." Untagged rows fall into an
    # Unassigned bucket below.
    active_slugs = {i.slug for i in visible if i.status == "active"}

    rows: list[FocusInitiativeRow] = []
    for initiative in visible:
        activity = _compute_activity_for_slug(
            initiative.slug,
            attempts=attempts,
            reflections=reflections,
            content_progress=content_progress,
            now=now,
            active_slugs=active_slugs,
        )

        open_prs, pr_state, pr_err = _fetch_open_prs_for_initiative(
            initiative, gh_available=gh_available
        )

        target_relative, target_urgency = _format_target_date(
            initiative.target_date, now=now
        )

        rows.append(
            FocusInitiativeRow(
                initiative=initiative,
                activity=activity,
                open_prs=open_prs,
                pr_fetch_state=pr_state,
                pr_fetch_error=pr_err,
                last_decision=last_decision_by_slug.get(initiative.slug),
                target_relative=target_relative,
                target_urgency=target_urgency,
            )
        )

    active_slug = None
    settings_active = settings.get("active_initiative") if isinstance(settings, dict) else None
    if isinstance(settings_active, str) and settings_active.strip():
        active_slug = settings_active.strip()

    # Unassigned bucket: rows with NULL initiative_slug OR pointing at
    # a non-active initiative. Computed unconditionally so the template
    # can render a "(N items unassigned)" hint even when the bucket
    # card itself is hidden. Cheap — same single pass over the same
    # in-memory lists.
    unassigned_activity = _compute_activity_for_slug(
        None,
        attempts=attempts,
        reflections=reflections,
        content_progress=content_progress,
        now=now,
        active_slugs=active_slugs,
    )

    return FocusView(
        generated_at=now,
        active_initiative_slug=active_slug,
        rows=tuple(rows),
        integration_notes=tuple(integration_notes),
        unassigned_activity=unassigned_activity,
        show_unassigned=show_unassigned,
    )
