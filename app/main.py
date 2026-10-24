from __future__ import annotations

import os
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

# Load .env before any service module reads os.environ at import time
# (review.py, jds.py, credentials.py all read ANTHROPIC_MODEL at module
# scope, so this has to win the race against those imports below).
from .env import load_dotenv as _load_dotenv

_load_dotenv()

# Sentry has to init BEFORE the FastAPI() instantiation so the SDK can
# wrap the app's middleware stack. Soft-fails if SENTRY_DSN isn't set.
from .observability import init_sentry as _init_sentry, crash_for_test as _crash_for_test

_sentry_enabled = _init_sentry()
if _sentry_enabled:
    print("[startup] Sentry initialized")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Scope

from .services.markdown import render_code, render_markdown

from .config import load_config, REPO_ROOT
from .content_loader import load_all_problems
from .db import (
    LOCK_NEWS_POLLER,
    LOCK_REFLECT_PREGENERATE,
    LOCK_VAULT_GIT_SYNC,
    apply_migrations,
    connect,
    single_flight,
)
from .models import Attempt, Problem, Reflection, Session
from .repositories import (
    AssessmentRepository,
    AttemptRepository,
    AttemptReviewRepository,
    ContentRepository,
    CredentialsRepository,
    FeedbackRepository,
    JdRepository,
    ReflectionRepository,
    NoteRepository,
    ProblemRepository,
    ReviewStateRepository,
    SessionRepository,
    SourceRepository,
    WritingRepository,
)
from .runners import run_python_tests, run_rust_tests
from .services import assessment as assess_service
from .services import readiness as readiness_service
from .services import content as content_service
from .services import tracks as tracks_service
from .services import track_content
from .services import paper_reading as paper_reading_service
from .services import criteria as criteria_service
from .services import credentials as credentials_service
from .services import feedback_inbox as feedback_inbox_service
from .services import connecting as connecting_service
from .services import crosslink as crosslink_service
from .services import daily_flow as daily_flow_service
from .services import diag_log as diag_log_service
from .services import focus as focus_service
from .services import hamming as hamming_service
from .services import initiative_picker
from .services import initiatives as initiatives_service
from .services import hints as hint_service
from .services import imposter as imposter_service
from .services import jds as jd_service
from .services import review as review_service
from .services import skill_stats
from .services.em import resolve_mode, resolve_prompts, visible_phases
from .services.references import group_by_phase as group_refs_by_phase
from .services.scheduler import ReviewStrategy, pick_warmup, problem_axes
from .services.skill_stats import pentagon_geometry


_log = logging.getLogger(__name__)


config = load_config()
conn = connect()
apply_migrations(conn, REPO_ROOT / "migrations_pg")

problem_repo = ProblemRepository(conn)
attempt_repo = AttemptRepository(conn)
review_repo = ReviewStateRepository(conn)
session_repo = SessionRepository(conn)
assessment_repo = AssessmentRepository(conn)
content_repo = ContentRepository(conn)
credentials_repo = CredentialsRepository(conn)
attempt_review_repo = AttemptReviewRepository(conn)
jd_repo = JdRepository(conn)
feedback_repo = FeedbackRepository(conn)
from .repositories.track_assessment_repository import TrackAssessmentRepository
track_assessment_repo = TrackAssessmentRepository(conn)
from .repositories.access_request_repository import AccessRequestRepository
access_request_repo = AccessRequestRepository(conn)
from .repositories.allowlist_repository import AllowlistRepository
allowlist_repo = AllowlistRepository(conn)

# DB-backed allowlist → access service, behind a short TTL so the
# per-request middleware check stays a memory read, not a DB
# round-trip. The TTL is also the cross-machine convergence bound: a
# grant made on the other Fly machine is honored here within 30s with
# no invalidation traffic. Admin mutation routes call
# _db_allowlist_cache_clear() so the machine that took the write
# reflects it immediately.
_DB_ALLOWLIST_TTL_S = 30.0
_db_allowlist_cache: tuple[float, set[str]] | None = None
_db_allowlist_lock = threading.Lock()


def _db_allowlist_cache_clear() -> None:
    global _db_allowlist_cache
    with _db_allowlist_lock:
        _db_allowlist_cache = None


def _db_allowed_emails_cached() -> set[str]:
    # Raises under LIS_NO_DB / DB outage — access.db_allowed_emails
    # catches and fails closed, and the env-var back-door still admits
    # the operator.
    global _db_allowlist_cache
    with _db_allowlist_lock:
        now = time.monotonic()
        if (
            _db_allowlist_cache is not None
            and now - _db_allowlist_cache[0] < _DB_ALLOWLIST_TTL_S
        ):
            return _db_allowlist_cache[1]
        emails = allowlist_repo.active_emails()
        _db_allowlist_cache = (now, emails)
        return emails


from .services import access as _access_wiring
_access_wiring.set_db_email_source(_db_allowed_emails_cached)
writing_repo = WritingRepository(conn)
reflection_repo = ReflectionRepository(conn)
from .repositories.chat_outcomes_repository import ChatOutcomesRepository
chat_outcomes_repo = ChatOutcomesRepository(conn)
from .repositories.news_repository import NewsRepository
news_repo = NewsRepository(conn)
from .repositories.contacts_repository import ContactsRepository
contacts_repo = ContactsRepository(conn)
from .repositories.mira_repository import MiraRepository
mira_repo = MiraRepository(conn)
from .repositories.llm_config_repository import LlmConfigRepository
llm_config_repo = LlmConfigRepository(conn)
from .repositories.kb_repository import KbRepository
kb_repo = KbRepository(conn)
from .repositories.linear_config_repository import LinearConfigRepository
linear_config_repo = LinearConfigRepository(conn)
from .repositories.vault_sync_repository import VaultSyncRepository
vault_sync_repo = VaultSyncRepository(conn)
from .repositories.signal_repository import EvidenceRepository, OpportunityRepository
evidence_repo = EvidenceRepository(conn)
opportunity_repo = OpportunityRepository(conn)
# Retrieval (rag.hybrid_search) reads the KB through the same repo;
# injected so the async rag module stays import-clean for unit tests.
from .services import rag as _rag_wiring
_rag_wiring.set_kb_repo(kb_repo)
# BYO-key routing: services construct their client via
# llm_keys.client_for(user_id); the repo is injected here so the
# service module stays import-clean for unit tests.
from .services import llm_keys as _llm_keys_wiring
_llm_keys_wiring.set_repo(llm_config_repo)
# Instantiated but not used in v1; presence is the contract for v1.5.
_source_repo = SourceRepository(conn)
_note_repo = NoteRepository(conn)

def _startup_progress(label: str):
    """Return a progress_cb that prints a single-line counter to stdout.

    Each round-trip to Supabase is ~100-200ms, so the visible motion
    is what tells the user the loader is making progress vs hung. We
    use carriage-return + flush so the line stays compact, then print
    a final newline when the loader finishes so subsequent startup
    lines land cleanly."""
    import sys, time
    state = {"t0": time.monotonic()}

    def _cb(n: int, total: int, item_label: str) -> None:
        elapsed = time.monotonic() - state["t0"]
        slug = (item_label or "")[:48]
        sys.stdout.write(
            f"\r[startup] {label}: {n:>3}/{total:<3} · {elapsed:5.1f}s · {slug:<48}"
        )
        sys.stdout.flush()
        if n == total:
            sys.stdout.write("\n")
            sys.stdout.flush()
    return _cb


_tracks_by_slug: dict[str, tracks_service.Track] = {}


# Skip the content-loader in test environments. Tests that need real
# content stand up their own fixtures or mark themselves @integration.
# Without this gate, importing `app.main` for a unit test would burn
# ~70 seconds on Supabase round-trips for content the test never reads.
if os.environ.get("LIS_SKIP_STARTUP_LOAD") == "1":
    print("[startup] LIS_SKIP_STARTUP_LOAD=1 set; skipping problem + content + tracks load")
    tracks_service.set_tracks({})
    criteria_service.set_criteria({})
else:
    loaded = load_all_problems(
        config.app.content_dir, problem_repo,
        progress_cb=_startup_progress("loading problems"),
    )
    print(f"[startup] loaded {loaded} problem files")
    loaded_content = content_service.load_all_content(
        config.app.content_dir, content_repo,
        progress_cb=_startup_progress("loading content"),
    )
    print(f"[startup] loaded {loaded_content} content items")
    criteria_service.set_criteria(
        criteria_service.load_all(config.app.content_dir / "criteria")
    )
    _tracks_by_slug = tracks_service.load_all_tracks(config.app.content_dir / "tracks")
    tracks_service.set_tracks(_tracks_by_slug)
    track_content.sync_track_content(_tracks_by_slug, content_repo)
    print(f"[startup] loaded {len(_tracks_by_slug)} tracks")

    # 6d seed: the canonical Mira-proposed eval, so /mira/evals demonstrates
    # its condition table before the agent's tool-use write path lands. Seeded
    # per admin user, and only when they have zero evals (so it never fights a
    # curated list). Best-effort: a demo seed must never brick boot.
    try:
        from .services import access as _access_service

        _seed_eval = {
            "hypothesis": "Capability drops when the model infers it is being evaluated.",
            "falsifier": "The gap disappears under a capability-matched control.",
            "conditions": [
                {"label": "A · overt", "framing": '"This is a capability evaluation."'},
                {"label": "B · casual", "framing": "Same items, conversational wrapper."},
                {"label": "C · control", "framing": "Capability-matched, framing held out."},
            ],
            "meta": {
                "title": "Sandbagging under eval-framing",
                "inspect_path": "evals/mira/sandbagging_framing.py",
            },
        }
        for _uid in _access_service.admin_user_ids():
            if not mira_repo.list_proposed_evals(_uid, limit=1):
                mira_repo.add_proposed_eval(user_id=_uid, **_seed_eval)
                print(f"[startup] seeded canonical proposed eval for {_uid}")
    except Exception as _seed_err:  # noqa: BLE001 — never brick boot on a demo seed
        print(f"[startup] proposed-eval seed skipped: {_seed_err}")


# Reflect pre-generation scheduler (GH #229). Single in-process job,
# fires every Saturday at 7am operator-local-time. Disabled by env var
# for local dev (no need to fire while iterating). Disabled too when
# LIS_SKIP_STARTUP_LOAD=1 — unit-test imports must not start a real
# scheduler with a real DB hookup.
_pregenerate_scheduler = None


def _start_reflect_pregenerator() -> None:
    """Wire the Saturday 7am Reflect pre-generation cron.

    Failure is non-fatal: if APScheduler isn't installed (e.g., minimal
    image), or if the scheduler errors at start, /reflect/generate still
    works on-demand. Log loudly so the operator notices.
    """
    global _pregenerate_scheduler
    if os.environ.get("LIS_SKIP_STARTUP_LOAD") == "1":
        return
    if os.environ.get("REFLECT_PREGENERATE", "1") == "0":
        print("[startup] REFLECT_PREGENERATE=0; skipping Saturday pre-generation cron")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        print(f"[startup] apscheduler not available, Reflect pre-generation disabled: {exc}")
        return

    tz_name = os.environ.get("REFLECT_PREGENERATE_TZ", "UTC")
    cron_hour = int(os.environ.get("REFLECT_PREGENERATE_HOUR", "7"))

    try:
        sched = BackgroundScheduler(timezone=tz_name)
        sched.add_job(
            _run_reflect_pregeneration_tick,
            trigger=CronTrigger(day_of_week="sat", hour=cron_hour, minute=0),
            id="reflect_pregenerate_saturday",
            replace_existing=True,
        )
        sched.start()
        _pregenerate_scheduler = sched
        print(
            f"[startup] Reflect pre-generation cron armed: Sat {cron_hour}:00 {tz_name}"
        )
    except Exception as exc:  # noqa: BLE001 — startup must never crash
        print(f"[startup] Reflect pre-generation cron failed to start: {exc}")


def _run_reflect_pregeneration_tick() -> None:
    """Single-flight wrapper. Every instance arms this cron, so the
    advisory lock is what stops N machines doing the work N times.
    The lock is held for the whole of _run_reflect_pregeneration_tick_locked()."""
    with single_flight(conn, LOCK_REFLECT_PREGENERATE) as mine:
        if not mine:
            print("[reflect_pregenerate] another instance holds the lock; skipping tick")
            return
        _run_reflect_pregeneration_tick_locked()


def _run_reflect_pregeneration_tick_locked() -> None:
    """Saturday 7am job body. Single-tenant today: walks the access-
    allowlist for active uids."""
    from .services import access as access_service
    from .services import reflect_pregenerate as pregen_service

    try:
        user_ids = list(access_service.allowed_user_ids())
    except Exception as exc:  # noqa: BLE001
        print(f"[reflect_pregenerate] couldn't load allowlist: {exc}")
        return

    if not user_ids:
        print("[reflect_pregenerate] no allowlisted users; nothing to do")
        return

    now = datetime.utcnow()
    outcomes = pregen_service.pregenerate_for_users(
        user_ids,
        now=now,
        attempts_repo=attempt_repo,
        reflection_repo=reflection_repo,
        week_summary_builder=lambda uid, days: _build_week_summary(uid, days=days),
    )
    summary = ", ".join(f"{o.user_id[:8]}={o.action}" for o in outcomes)
    print(f"[reflect_pregenerate] tick ran; {len(outcomes)} users: {summary}")


# _start_reflect_pregenerator() is INTENTIONALLY NOT called here at
# module-load time. The lifespan handler `_bench_lifespan` (defined
# below) calls it during FastAPI startup so test imports never spin up
# a real scheduler.


_vault_git_sync_scheduler = None


def _start_vault_git_sync() -> None:
    """Nightly git-vault pull (v2.1 slice 5). Interval-based like the
    news poller; the advisory lock stops the two machines double-
    pulling. Set VAULT_GIT_SYNC=0 to disable; override the cadence via
    VAULT_GIT_SYNC_INTERVAL_MINUTES (default 24h)."""
    global _vault_git_sync_scheduler
    if os.environ.get("LIS_SKIP_STARTUP_LOAD") == "1":
        return
    if os.environ.get("VAULT_GIT_SYNC", "1") == "0":
        print("[startup] VAULT_GIT_SYNC=0; skipping git vault sync cron")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:
        print(f"[startup] apscheduler not available, git vault sync disabled: {exc}")
        return
    try:
        interval_min = int(os.environ.get("VAULT_GIT_SYNC_INTERVAL_MINUTES", "1440"))
    except ValueError:
        interval_min = 1440
    try:
        sched = BackgroundScheduler(timezone="UTC")
        sched.add_job(
            _run_vault_git_sync_tick,
            trigger=IntervalTrigger(minutes=interval_min),
            id="vault_git_sync_nightly",
            replace_existing=True,
        )
        sched.start()
        _vault_git_sync_scheduler = sched
        print(f"[startup] Git vault sync cron armed: every {interval_min}m")
    except Exception as exc:  # noqa: BLE001 — startup must never crash
        print(f"[startup] Git vault sync cron failed to start: {exc}")


def _run_vault_git_sync_tick() -> None:
    """Single-flight wrapper — every machine arms the cron; the lock
    picks the worker. Per-user failures land in that user's
    last_result and never stop the walk."""
    from .services import kb_git_sync

    with single_flight(conn, LOCK_VAULT_GIT_SYNC) as mine:
        if not mine:
            print("[vault_git_sync] another instance holds the lock; skipping tick")
            return
        configs = vault_sync_repo.list_all()
        ok = failed = 0
        for cfg in configs:
            try:
                kb_git_sync.sync_user(kb_repo, vault_sync_repo, cfg.user_id)
                ok += 1
            except Exception:  # noqa: BLE001 — recorded in last_result
                failed += 1
        print(f"[vault_git_sync] tick ran; {ok} synced, {failed} failed of {len(configs)}")


_news_poller_scheduler = None


def _start_news_poller() -> None:
    """Wire the hourly RSS poller cron (rss-news-feed Phase 1).

    Reads feed registry from ``content/news_feeds.toml``; ingests into
    ``news_items`` via NewsRepository. Failure is non-fatal: missing
    APScheduler / missing TOML / network errors are logged, not raised.

    Set ``NEWS_POLLER=0`` to disable. Defaults to 60-minute interval;
    override via ``NEWS_POLLER_INTERVAL_MINUTES``.
    """
    global _news_poller_scheduler
    if os.environ.get("LIS_SKIP_STARTUP_LOAD") == "1":
        return
    if os.environ.get("NEWS_POLLER", "1") == "0":
        print("[startup] NEWS_POLLER=0; skipping RSS poller cron")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:
        print(f"[startup] apscheduler not available, news poller disabled: {exc}")
        return

    try:
        interval_min = int(os.environ.get("NEWS_POLLER_INTERVAL_MINUTES", "60"))
    except ValueError:
        interval_min = 60

    try:
        sched = BackgroundScheduler(timezone="UTC")
        sched.add_job(
            _run_news_poller_tick,
            trigger=IntervalTrigger(minutes=interval_min),
            id="news_poller_hourly",
            replace_existing=True,
        )
        sched.start()
        _news_poller_scheduler = sched
        print(f"[startup] News poller cron armed: every {interval_min}m")
    except Exception as exc:  # noqa: BLE001 — startup must never crash
        print(f"[startup] News poller cron failed to start: {exc}")


def _run_news_poller_tick() -> None:
    """Single-flight wrapper. Every instance arms this cron, so the
    advisory lock is what stops N machines doing the work N times.
    The lock is held for the whole of _run_news_poller_tick_locked()."""
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        if not mine:
            print("[news_poller] another instance holds the lock; skipping tick")
            return
        _run_news_poller_tick_locked()


def _run_news_poller_tick_locked() -> None:
    """One poll tick. Loads feeds.toml, walks every feed, logs a summary."""
    from .services import news_poller as news_poller_service

    feeds_path = REPO_ROOT / "content" / "news_feeds.toml"
    feeds = news_poller_service.load_feeds_from_toml(feeds_path)
    if not feeds:
        print(f"[news_poller] no feeds in {feeds_path}; nothing to do")
        return

    outcomes = news_poller_service.poll_feeds(feeds, repo=news_repo)
    inserted = sum(o.items_inserted for o in outcomes if o.status == "ok")
    errors = [o for o in outcomes if o.status != "ok"]
    print(
        f"[news_poller] tick: {len(outcomes)} feeds, {inserted} new items"
        + (f"; {len(errors)} errors" if errors else "")
    )


# MCP server mount (BEN-81). Behind a feature flag so the scaffold can
# ship without committing to an auth posture for production. When
# BENCH_MCP_ENABLED=1, mount the streamable-HTTP MCP server at /mcp,
# gated by BENCH_MCP_TOKEN and bound to one explicit operator identity.
def _build_mcp_server_or_none():
    """Construct the MCP server object (sync). Returns None when the
    feature flag is off, the allowlist is empty, or anything fails.

    The actual `app.mount(...)` + `session_manager.run()` context are
    handled inside the lifespan handler below — FastMCP requires its
    async task group entered via a lifespan context, not at import.
    """
    if os.environ.get("LIS_SKIP_STARTUP_LOAD") == "1":
        return None, None
    if os.environ.get("BENCH_MCP_ENABLED", "0") != "1":
        return None, None
    try:
        from . import mcp_server as bench_mcp
        from .services import focus as focus_service
        from .services import initiatives as initiatives_service
        from .services import access as access_service

        if not bench_mcp.auth_token_from_env():
            print("[startup] BENCH_MCP_ENABLED=1 requires BENCH_MCP_TOKEN; MCP not mounted")
            return None, None
        allowed = access_service.allowed_user_ids()
        configured_uid = os.environ.get("BENCH_MCP_USER_ID", "").strip()
        # A bearer token represents one operator, never whichever member
        # happens to be first in a hash-randomized multi-user allowlist.
        if configured_uid:
            if configured_uid not in allowed:
                print("[startup] BENCH_MCP_USER_ID is not allowlisted; MCP not mounted")
                return None, None
            operator_uid = configured_uid
        elif len(allowed) == 1:
            operator_uid = next(iter(allowed))
        else:
            print("[startup] Set BENCH_MCP_USER_ID to an allowlisted operator; MCP not mounted")
            return None, None

        server = bench_mcp.build_mcp_server(
            user_id=operator_uid,
            focus_service=focus_service,
            initiatives_service=initiatives_service,
            attempt_repo=attempt_repo,
            reflection_repo=reflection_repo,
            content_repo=content_repo,
            user_settings_loader=lambda uid: _user_settings(uid),
            user_settings_saver=lambda uid, settings: _save_user_settings(uid, settings),
            chat_outcomes_repo=chat_outcomes_repo,
        )
        return server, bench_mcp
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] MCP build failed: {exc}")
        return None, None


# Lifespan handler that drives the MCP session manager. FastMCP's
# streamable HTTP transport requires the session manager's task group
# to be entered as an async context — that's the only place `app.mount`
# can be paired with `session_manager.run()` correctly. See PR #246/#247
# history for the prior NameError + 500 round-trip that landed us here.
from contextlib import asynccontextmanager  # noqa: E402  — kept local to bench startup


@asynccontextmanager
async def _bench_lifespan(_app):
    """FastAPI lifespan: arm the Reflect cron, then enter the MCP
    server's session manager (if enabled) so /mcp can actually serve.

    Failure modes are non-fatal; the bench keeps running even if MCP
    setup explodes."""
    # Reflect pre-generation (sync). Hoisted into lifespan from module-
    # load so test imports don't accidentally start a real scheduler.
    _start_reflect_pregenerator()

    # RSS news poller (rss-news-feed Phase 1). Same rationale: arm at
    # lifespan start, never at module load.
    _start_news_poller()
    _start_vault_git_sync()

    server, bench_mcp = _build_mcp_server_or_none()
    if server is None:
        yield
        return

    token = bench_mcp.auth_token_from_env()
    if not token:
        print("[startup] MCP token unavailable; MCP not mounted")
        yield
        return
    mcp_app = bench_mcp._BearerTokenMiddleware(server.streamable_http_app(), token=token)

    try:
        # Enter the FastMCP session manager's task group. Without this,
        # every /mcp request raises "Task group is not initialized" at
        # the SDK layer.
        async with server.session_manager.run():
            _app.mount("/mcp", mcp_app)
            print("[startup] MCP server mounted at /mcp (bearer-token gated)")
            yield
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] MCP lifespan failed: {exc}")
        yield


# NOTE: previous module-load-time mount calls are GONE. The lifespan
# handler above owns both the MCP session manager and the mount. See
# `app = FastAPI(lifespan=_bench_lifespan)` below.


def get_track(slug: str) -> tracks_service.Track | None:
    return tracks_service.get_track(slug)


def _utc_iso_now() -> str:
    return datetime.utcnow().isoformat()


def _normalized_section_indexes(raw: object, *, total_sections: int | None) -> list[int]:
    out: list[int] = []
    if not isinstance(raw, list):
        return out
    for value in raw:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx in out:
            continue
        if total_sections is not None and idx >= total_sections:
            continue
        out.append(idx)
    return out


def _normalized_section_stamp_map(raw: object, *, total_sections: int | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for raw_idx, stamp in raw.items():
        if not isinstance(stamp, str):
            continue
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if idx < 0:
            continue
        if total_sections is not None and idx >= total_sections:
            continue
        out[str(idx)] = stamp
    return out


def _track_gate_status(section: tracks_service.TrackSection, user_id: str) -> dict | None:
    """A missing or unreadable practical assessment cannot grant a pass."""
    slugs = [s.strip() for s in (section.cold_checkpoint or ()) if s and s.strip()]
    if not slugs:
        return None
    items = []
    for slug in slugs:
        item = {"slug": slug, "title": slug, "passed": False, "unavailable": False}
        try:
            problem = problem_repo.get_by_slug(slug)
            if problem is None or problem.id is None:
                item["unavailable"] = True
            else:
                item.update(title=problem.title, passed=attempt_repo.has_passing_attempt(user_id, problem.id))
        except Exception:
            item["unavailable"] = True
        items.append(item)
    remaining = [item for item in items if not item["passed"]]
    return {"items": items, "remaining": remaining, "passed": not remaining,
            "passed_count": len(items) - len(remaining), "total": len(items),
            "unavailable": any(item["unavailable"] for item in items)}


def _track_prep_items(section: tracks_service.TrackSection) -> list[dict]:
    """Bench content to work BEFORE the external notebook. Missing slugs
    are dropped rather than rendered as dead links."""
    out: list[dict] = []
    for slug in section.prep:
        try:
            item = content_repo.get_by_slug(slug)
        except Exception:  # noqa: BLE001
            item = None
        if item is None:
            continue
        out.append({
            "slug": slug,
            "title": item.title,
            "kind": item.kind,
            "duration_min": item.duration_min,
        })
    return out


def _default_track_checkpoint_text(section: tracks_service.TrackSection) -> str:
    domain_bits = [tag for tag in section.domain_tags if tag]
    axis_bits = [axis.replace("_", " ") for axis in section.axes if axis]
    focus_bits = domain_bits[:2] + axis_bits[:1]
    focus_text = f" and {', '.join(focus_bits)}" if focus_bits else ""
    return (
        f"Explain {section.title} in your own words{focus_text}, then walk through one concrete"
        " application from memory."
    )


def _track_socratic_questions_for_section(
    *,
    track: tracks_service.Track,
    idx: int,
    user_id: str,
) -> list[str]:
    # Track checks rehearse the curriculum; exercise review requires a real attempt.
    from .services.track_checks import questions_for_section
    return questions_for_section(track, idx)


def _track_exemptions(track, settings, user_id=None) -> set[int]:
    from .services.track_exams import valid_exemptions
    if not hasattr(track, "all_sections"):
        return set()
    return valid_exemptions(track, (settings or {}).get("track_assessments", []), user_id=user_id)


def _track_checkpoint_passed_sections(
    *,
    state: dict,
    track: tracks_service.Track,
) -> set[int]:
    passed: set[int] = set()
    for value in state.get("checkpoint_passed_sections", []):
        if isinstance(value, int) and 0 <= value < track.total_sections:
            passed.add(value)
    return passed


def _track_artifact_url(value: str) -> str:
    from urllib.parse import urlsplit

    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        valid = (len(value) <= 2048 and parsed.scheme in {"https", "http"}
                 and parsed.hostname and not parsed.username and not parsed.password
                 and not any(char.isspace() or ord(char) < 32 for char in value))
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Artifact link must be an HTTP or HTTPS URL, up to 2048 characters.")
    return value


def _track_section_records(raw: object, *, total_sections: int | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    records = {}
    for key, value in raw.items():
        try:
            idx = int(key)
        except (ValueError, TypeError):
            continue
        if idx < 0 or (total_sections is not None and idx >= total_sections) or not isinstance(value, dict):
            continue
        record = dict(value)
        try:
            record["artifact_url"] = _track_artifact_url(str(record.get("artifact_url") or ""))
        except ValueError:
            record["artifact_url"] = ""
        records[str(idx)] = record
    return records


def _normalized_track_state(raw: object, *, slug: str, settings: dict | None = None, user_id: str | None = None) -> dict:
    """Normalize persisted track progress payloads from user settings.

    The settings blob is user-editable/migrated over time, so route
    code reads through this normalizer before mutating progress.
    """
    state = dict(raw) if isinstance(raw, dict) else {}
    state["slug"] = slug

    track = get_track(slug)
    track_supports_graph = bool(track is not None and hasattr(track, "all_sections"))
    if track is not None and hasattr(track, "total_sections"):
        total_sections = int(getattr(track, "total_sections"))
    else:
        total_sections = None

    try:
        legacy_cursor = int(state.get("cursor", 0))
    except (TypeError, ValueError):
        legacy_cursor = 0
    legacy_cursor = max(0, legacy_cursor)

    raw_checkpoint_passed = state.get("checkpoint_passed_sections")
    if not isinstance(raw_checkpoint_passed, list):
        raw_checkpoint_passed = state.get("completed_sections")
    checkpoint_passed_sections = _normalized_section_indexes(
        raw_checkpoint_passed,
        total_sections=total_sections,
    )
    if not isinstance(raw_checkpoint_passed, list) and legacy_cursor > 0:
        upper = legacy_cursor if total_sections is None else min(legacy_cursor, total_sections)
        checkpoint_passed_sections = list(range(upper))

    state["checkpoint_passed_sections"] = checkpoint_passed_sections
    # Back-compat mirror: older routes/templates still read this key.
    state["completed_sections"] = list(checkpoint_passed_sections)

    raw_checkpoint_passed_at = state.get("checkpoint_passed_at_per_section")
    if not isinstance(raw_checkpoint_passed_at, dict):
        raw_checkpoint_passed_at = state.get("completed_at_per_section")
    checkpoint_passed_at_per_section = _normalized_section_stamp_map(
        raw_checkpoint_passed_at,
        total_sections=total_sections,
    )
    state["checkpoint_passed_at_per_section"] = checkpoint_passed_at_per_section
    # Back-compat mirror.
    state["completed_at_per_section"] = dict(checkpoint_passed_at_per_section)

    checkpoint_questions_per_section: dict[str, list[str]] = {}
    raw_checkpoint_questions = state.get("checkpoint_questions_per_section")
    if isinstance(raw_checkpoint_questions, dict):
        passed_set = set(checkpoint_passed_sections)
        for raw_idx, raw_questions in raw_checkpoint_questions.items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx in passed_set:
                continue
            if total_sections is not None and idx >= total_sections:
                continue
            if not isinstance(raw_questions, list):
                continue
            cleaned = [
                question.strip()
                for question in raw_questions
                if isinstance(question, str) and question.strip()
            ]
            if cleaned:
                checkpoint_questions_per_section[str(idx)] = cleaned[:6]
    state["checkpoint_questions_per_section"] = checkpoint_questions_per_section

    for field in ("session_per_section", "checkpoint_response_per_section"):
        state[field] = _track_section_records(state.get(field), total_sections=total_sections)

    if track_supports_graph:
        passed_set = set(checkpoint_passed_sections)
        preferred = state.get("preferred_section")
        next_idx = tracks_service.next_section_index(track, passed_set | _track_exemptions(track, settings, user_id=user_id), preferred)
        if preferred is not None and str(preferred) != str(next_idx):
            state.pop("preferred_section", None)
        state["cursor"] = total_sections if next_idx is None else next_idx
    else:
        cursor_hint = max(legacy_cursor, len(checkpoint_passed_sections))
        if total_sections is not None:
            cursor_hint = min(cursor_hint, total_sections)
        state["cursor"] = cursor_hint

    started_at = state.get("started_at")
    if not isinstance(started_at, str) or not started_at.strip():
        state["started_at"] = _utc_iso_now()

    return state


def _paused_tracks(settings: dict) -> dict[str, dict]:
    raw = settings.get("paused_tracks")
    if not isinstance(raw, dict):
        return {}
    paused: dict[str, dict] = {}
    for slug, progress in raw.items():
        if isinstance(progress, dict):
            paused[str(slug)] = dict(progress)
    return paused


def _track_status_and_state(settings: dict, slug: str, user_id=None) -> tuple[str, dict]:
    active_raw = settings.get("active_track")
    if isinstance(active_raw, dict) and str(active_raw.get("slug") or "").strip() == slug:
        return "active", _normalized_track_state(active_raw, slug=slug, settings=settings, user_id=user_id)

    paused = _paused_tracks(settings).get(slug)
    if isinstance(paused, dict):
        return "paused", _normalized_track_state(paused, slug=slug, settings=settings, user_id=user_id)

    return "not_started", _normalized_track_state({}, slug=slug, settings=settings, user_id=user_id)


class BenchStaticFiles(StaticFiles):
    """Static asset server with explicit media type for the web manifest."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and path == "manifest.json":
            response.headers["content-type"] = "application/manifest+json"
        return response

app = FastAPI(title="Li's Bench", lifespan=_bench_lifespan)
diag_log_service.install()

# Rate-limit setup (LIS-280). The slowapi Limiter instance is keyed by
# user_id when signed in, else client IP. Per-endpoint caps live in
# rate_limit.LIMITS. RateLimitExceeded → 429 with a friendly body.
from .services.rate_limit import limiter as _rate_limiter, LIMITS as RATE_LIMITS
from slowapi.errors import RateLimitExceeded as _RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler  # type: ignore[attr-defined]
app.state.limiter = _rate_limiter
app.add_exception_handler(_RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", BenchStaticFiles(directory=str(REPO_ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))
templates.env.filters["markdown"] = render_markdown
templates.env.filters["code"] = render_code
templates.env.filters["pentagon_geometry"] = pentagon_geometry


@lru_cache(maxsize=64)
def static_hash(rel_path: str) -> str:
    """Return a short content hash for static assets used in templates."""
    static_root = (REPO_ROOT / "static").resolve()
    target = (static_root / rel_path).resolve()

    # Keep template input constrained to files inside /static.
    if static_root != target and static_root not in target.parents:
        return "0"

    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()[:10]
    except FileNotFoundError:
        return "0"
    except OSError:
        return "0"


templates.env.globals["static_hash"] = static_hash

from .services.resource_reader import resource_reader_url
templates.env.globals["resource_reader_url"] = resource_reader_url


def _vite_manifest() -> dict:
    """Parse static/dist/.vite/manifest.json, or {} when no build has
    run. NOT cached: the file is tiny, reads are page-render-rate, and
    an uncached read means a fresh `npm run build` is picked up without
    restarting the server in local dev. Prod bakes the file into the
    image, so the read is always warm page cache there."""
    manifest_path = REPO_ROOT / "static" / "dist" / ".vite" / "manifest.json"
    try:
        import json as _json
        return _json.loads(manifest_path.read_text())
    except (FileNotFoundError, OSError, ValueError):
        return {}


def asset(entry: str) -> str | None:
    """FRONTEND-1a: resolve a Vite entry to its served URL.

    - `LIS_VITE_DEV=1` → the Vite dev server (HMR) at :5173.
    - Otherwise → the hashed filename from the build manifest
      (cache-busting for free).
    - No manifest (Node never ran — e.g. a Python-only checkout) →
      None; base.html skips the script tag and every island mount
      renders its server fallback. The page is always the floor.
    """
    if os.environ.get("LIS_VITE_DEV", "").strip() == "1":
        return f"http://127.0.0.1:5173/{entry}"
    row = _vite_manifest().get(entry)
    if not row or "file" not in row:
        return None
    return f"/static/dist/{row['file']}"


templates.env.globals["asset"] = asset


def _jd_display_title(title: str | None) -> str:
    """Template filter for rendering a JD title. If the stored title
    looks like a raw URL (legacy data from before the slug-fallback
    landed), derive a clean title from the URL's slug at render time.
    This is defense-in-depth — newly-created JDs already get a clean
    title via title_from_url() in jds_create. Existing rows are healed
    on first view."""
    from .services import jds as _jds
    t = (title or "").strip()
    if _jds.is_url_title(t):
        return _jds.title_from_url(t)
    return t


templates.env.filters["jd_title"] = _jd_display_title


# Public health endpoint for the load balancer (Fly.io, Cloudflare).
# Returns 200 immediately when the process is up. Deliberately answers
# without touching the DB so a Postgres outage doesn't take the whole
# app offline at the LB level. Add deeper readiness checks (DB,
# Anthropic) on separate auth-gated endpoints if needed.
@app.get("/__health", response_class=HTMLResponse)
def _health():
    return HTMLResponse("ok", status_code=200)


# Sentry self-test endpoints. Only registered when the SDK initialized.
#
#   GET /__sentry/ping  — sends a `capture_message` event explicitly +
#       flushes synchronously. Tests "can we reach Sentry at all" in
#       isolation from middleware behavior. Returns a confirmation
#       page; no exception path.
#
#   GET /__sentry/test  — captures an exception explicitly + flushes,
#       THEN raises. This double-path (explicit capture + raise)
#       guarantees we don't depend on the FastAPI/Starlette exception
#       middleware actually forwarding the unhandled raise to Sentry.
#
# Both flush with a 5-second timeout so the event is over the wire
# before the request returns. Without explicit flush the SDK buffers
# events and a fast restart could drop them.
from .services import security as security_service


# Diagnostic routes (/__sentry/*, /__claude/*) are gated behind
# `LIS_DIAGNOSTICS_ENABLED`. Default ON in local dev, OFF in production.
# See app/services/security.py:diagnostics_enabled.
_diag_enabled = security_service.diagnostics_enabled()


def _diag_off() -> HTMLResponse:
    return HTMLResponse(
        "Diagnostics disabled. Set LIS_DIAGNOSTICS_ENABLED=1 to enable.",
        status_code=404,
    )


if _sentry_enabled and _diag_enabled:
    import sentry_sdk as _sentry_sdk

    @app.get("/__sentry/ping")
    def _sentry_ping():
        event_id = _sentry_sdk.capture_message(
            "Li's Bench Sentry ping — explicit capture_message test",
            level="info",
        )
        _sentry_sdk.flush(timeout=5.0)
        return HTMLResponse(
            f"<!doctype html><body style='font-family: system-ui; padding: 2rem;'>"
            f"<h1>Sentry ping sent</h1>"
            f"<p>Event id: <code>{event_id}</code></p>"
            f"<p>Check sentry.io → Issues. Should arrive within ~5s.</p>"
            f"<p><a href='/__sentry/test'>Now try the exception path →</a></p>"
            f"</body>"
        )

    @app.get("/__sentry/test")
    def _sentry_test():
        try:
            _crash_for_test()
        except Exception as e:
            # Capture explicitly so we don't depend on the FastAPI
            # exception middleware forwarding the unhandled raise.
            _sentry_sdk.capture_exception(e)
            _sentry_sdk.flush(timeout=5.0)
            # Re-raise so the user still sees a 500 (and so middleware-
            # based capture can also fire if it's working).
            raise



# Paths that don't require authentication. Static assets, the OAuth
# round-trip endpoints, the login page itself, and the diagnostic
# endpoints all bypass the auth gate. Anything else with a None user
# session bounces to /login.
# Exact-match public paths. Kept separate from _PUBLIC_PATH_PREFIXES on
# purpose: entries there that end in "/" are prefix-matched, so putting "/"
# in that tuple would match every path in the app and silently unauthenticate
# everything. Anything added here is matched by full equality only.
_PUBLIC_EXACT_PATHS = frozenset({
    # The logged-out landing page. `home()` serves templates/landing.html
    # when there is no session and the Today view when there is.
    "/",
})

_PUBLIC_PATH_PREFIXES = (
    "/static/",
    "/auth/",
    "/login",
    "/public/",
    "/about",
    "/__sentry/",
    "/__claude/",
    # Load-balancer health check (Fly.io). Cannot be auth-gated; the
    # LB has no session.
    "/__health",
    # Public request-access form (GET form + POST submit). Anyone
    # landing on the URL via a talk or write-up needs to reach this
    # without an existing session.
    "/request-access",
    # Public technical-writing index (external docs links).
    "/writing",
    # MCP server (BEN-81) lives at /mcp and has its OWN bearer-token
    # middleware in app/mcp_server.py. The session middleware must NOT
    # intercept these requests — otherwise unauthenticated MCP probes
    # get bounced to /login (303) before the bearer-token check fires,
    # which makes the connector impossible to use from claude.ai /
    # Claude Code / curl. Auth is enforced at the MCP layer instead.
    "/mcp",
)


def _is_public_path(path: str) -> bool:
    """Return True when a request path is auth-exempt.

    Prefixes ending with "/" stay prefix-matched (`/static/...`,
    `/auth/...`). Exact-ish entries (`/writing`, `/login`, etc.) also
    allow their nested forms (`/writing/...`) while avoiding sibling
    collisions (`/writings`).
    """
    if path in _PUBLIC_EXACT_PATHS:
        return True

    for public_prefix in _PUBLIC_PATH_PREFIXES:
        if public_prefix.endswith("/"):
            if path.startswith(public_prefix):
                return True
            continue

        if path == public_prefix or path.startswith(f"{public_prefix}/"):
            return True

    return False


def _local_mode_enabled(env) -> bool:
    """Single-user self-host mode: `LIS_LOCAL_MODE=1` bypasses auth so a
    self-hoster can use the app without provisioning Supabase/OAuth.

    Security interlock: it will NOT engage when real auth is configured
    (`SUPABASE_JWT_SECRET` present), so setting the flag can never
    silently disable auth on a hosted deployment (prod keeps the secret
    set)."""
    return env.get("LIS_LOCAL_MODE") == "1" and not env.get("SUPABASE_JWT_SECRET")


_LOCAL_MODE = _local_mode_enabled(os.environ)
if os.environ.get("LIS_LOCAL_MODE") == "1" and not _LOCAL_MODE:
    print("[startup] WARN: LIS_LOCAL_MODE=1 ignored — SUPABASE_JWT_SECRET is set "
          "(refusing to disable auth on a deployment with real auth configured)")
elif _LOCAL_MODE:
    print("[startup] LIS_LOCAL_MODE active — single-user local mode, auth bypassed")
    # Ensure the fixed local user has a public.users row so settings
    # writes persist (they're an UPDATE keyed on id — no row, no save).
    # auth.users must already carry the id: Supabase setups have the
    # signup trigger; plain-Postgres setups get it from
    # scripts/e2e_bootstrap.sql. Soft-fail so a missing auth stub
    # degrades to read-only settings instead of blocking boot.
    try:
        with conn.cursor() as _cur:
            _cur.execute(
                """
                INSERT INTO public.users (id, email)
                VALUES ('00000000-0000-4000-8000-000000000001', 'local@localhost')
                ON CONFLICT (id) DO NOTHING
                """
            )
        conn.commit()
    except Exception as _exc:  # noqa: BLE001
        print(f"[startup] WARN: could not ensure local user row ({_exc}); "
              "settings will not persist — see scripts/e2e_bootstrap.sql")


def _session_request_state(
    uid: str, email: str | None, run_allowlist_check: bool
) -> tuple[bool, bool, dict, int]:
    """Per-request DB reads for the session middleware, extracted so
    they run in the threadpool (BEN-153): the middleware is async, and
    every one of these can block on a pool checkout — on the event
    loop that would stall EVERY in-flight request, not just this one.

    Returns (allowed, is_admin, settings, fb_open_count). When
    `allowed` is False the rest are defaults — the caller 403s and
    never reads them."""
    from .services import access as access_service

    if (
        run_allowlist_check
        and access_service.allowlist_enabled()
        and not access_service.is_allowed(uid, email)
    ):
        return False, False, {}, 0

    if _LOCAL_MODE:
        # Single-user self-host: the one user IS the operator —
        # admin surfaces (feedback inbox, Mira) are theirs. Guarded
        # by the same SUPABASE_JWT_SECRET interlock as local mode,
        # so this can never widen access on a real deploy.
        is_admin = True
    else:
        try:
            is_admin = access_service.is_admin(uid)
        except Exception:  # noqa: BLE001
            is_admin = False
    try:
        settings = _user_settings(uid)
    except Exception:  # noqa: BLE001
        settings = {}
    # Feedback-inbox notification badge (operator-requested 2026-05-28).
    # Single COUNT() query per admin page render — cheap and avoids
    # loading the full inbox just to render a badge.
    fb_open = 0
    if is_admin:
        try:
            fb_open = feedback_repo.counts_all().get("open", 0)
        except Exception:  # noqa: BLE001
            # Don't fail page render over a badge.
            fb_open = 0
    return True, is_admin, settings, fb_open


@app.middleware("http")
async def _inject_session(request: Request, call_next):
    """Three passes per request:

    1. Auth: read the Supabase access-token cookie (if any), decode
       to populate `request.state.user_session`. None when not signed
       in. Routes outside the public-prefix allowlist redirect to
       /login when there's no session.

    2. Access allowlist (LIS-280): if a session is present but the
       authenticated identity is NOT in the env-driven allowlist,
       sign them out and render a 403. Keeps bench.libearden.dev
       single-tenant even though Supabase OAuth itself lets anyone
       with a GitHub account complete the flow. Empty allowlist =
       no restriction (local dev default).

    3. User settings: stash a11y prefs + display name for the base
       template. Only meaningful when the user is signed in; otherwise
       leave it empty."""
    from .auth import current_user, ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
    from .services import access as access_service

    request.state.user_session = current_user(request)

    # BEN-145 — scope Sentry to whoever this actually is. Without it every
    # event carries the operator's identity and "is this breaking for anyone
    # but me?" has no answer. Opaque id only; email is never forwarded.
    try:
        from .observability import set_request_user

        _sess = request.state.user_session
        set_request_user(getattr(_sess, "user_id", None) if _sess else None)
    except Exception:  # noqa: BLE001 — observability never breaks a request
        pass

    if request.state.user_session is None and _LOCAL_MODE:
        # Inject a fixed single-user session so the app is usable without
        # any auth provider. Guarded by the interlock in _local_mode_enabled.
        # The id must be a VALID UUID — user_id hits `uuid` columns in
        # every repo query, and the literal "local" made Postgres throw
        # InvalidTextRepresentation on every DB-touching page (bug in the
        # original #373 local mode; found while verifying FRONTEND-1a).
        from .auth import UserSession
        request.state.user_session = UserSession(
            user_id="00000000-0000-4000-8000-000000000001",
            email="local@localhost",
            expires_at=9_999_999_999,  # far future; never treated as expired
            raw_access_token="",
        )
    request.state.is_admin = False

    path = request.url.path

    if request.state.user_session is None and not _is_public_path(path):
        return RedirectResponse(url="/login", status_code=303)

    if request.state.user_session is not None:
        # Allowlist check (LIS-280) + per-request reads, in the
        # threadpool (BEN-153). Skipped for /auth/* because the user
        # is mid-OAuth-flow and the session-rejection response
        # shouldn't fight with the OAuth machinery.
        import anyio

        run_allowlist_check = not (
            path.startswith("/auth/")
            or path.startswith("/public/")
            or path.startswith("/__health")
        )
        allowed, is_admin, settings, fb_open = await anyio.to_thread.run_sync(
            _session_request_state,
            request.state.user_session.user_id,
            request.state.user_session.email,
            run_allowlist_check,
        )
        if not allowed:
            # Sign them out (clear cookies) so they don't keep retrying
            # the same auth'd request, then render a clean 403.
            resp = templates.TemplateResponse(
                request,
                "access_denied.html",
                {
                    "email": request.state.user_session.email,
                    "nav_section": None,
                    "is_alpha_view": True,
                },
                status_code=403,
            )
            resp.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
            resp.delete_cookie(REFRESH_TOKEN_COOKIE, path="/")
            return resp
        request.state.is_admin = is_admin
        request.state.user_settings = settings
        request.state.fb_open_count = fb_open
    else:
        request.state.user_settings = {}
        request.state.fb_open_count = 0
    return await call_next(request)


# Security headers middleware (LIS-280). Attached AFTER the session
# middleware so 303 redirects from auth still pick up the headers.
# `_security_headers_cache` resolves once at startup; calling
# build_security_headers per-request would re-derive the CSP string
# uselessly.
_security_headers_cache = security_service.build_security_headers(
    is_prod=os.environ.get("SENTRY_ENVIRONMENT", "local").lower() in ("prod", "production")
)


@app.middleware("http")
async def _attach_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in _security_headers_cache.items():
        # Don't clobber existing per-response settings (e.g., redirects
        # may set their own Cache-Control); only add if missing.
        response.headers.setdefault(header, value)
    return response


# Cross-machine staleness bound for user settings (theme, a11y,
# hyperfocus, active track cursor...). _save_user_settings invalidates
# in-process only; the OTHER Fly machine converges within this TTL
# instead of serving stale settings indefinitely.
_USER_SETTINGS_TTL_S = 30.0


def _user_settings(uid: str) -> dict:
    """Read this user's settings_json. Cached per-uid; invalidated on
    `_save_user_settings` (this machine) + a short TTL (the other
    machine). The middleware reads this on every request, so caching
    saves one round-trip per page load."""
    from . import cache as _cache

    def _load():
        with conn.cursor() as cur:
            cur.execute("SELECT settings_json FROM public.users WHERE id = %s", (uid,))
            row = cur.fetchone()
        if not row:
            return {}
        val = row["settings_json"]
        if val is None:
            return {}
        return val if isinstance(val, dict) else {}

    # Returning a copy isn't necessary — settings are read-only at the
    # callsites and any mutation goes through _save_user_settings,
    # which invalidates the cache.
    return _cache.get(
        f"user_settings:{uid}", loader=_load, ttl_s=_USER_SETTINGS_TTL_S
    )


def _save_user_settings(uid: str, settings: dict) -> None:
    from . import cache as _cache
    import json as _json
    # Assessment evidence is written only by its repository. Preserve the
    # current DB value across stale preference/progress/spend-counter saves.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE public.users SET settings_json = (%s::jsonb - 'track_assessments') || "
            "CASE WHEN settings_json ? 'track_assessments' THEN "
            "jsonb_build_object('track_assessments', settings_json->'track_assessments') "
            "ELSE '{}'::jsonb END WHERE id = %s",
            (_json.dumps(settings), uid),
        )
    conn.commit()
    _cache.invalidate(f"user_settings:{uid}")


def _active_jd(uid: str, settings: dict | None = None):
    """Return the active JD object or None. Active id lives in
    users.settings_json.active_jd_id; if it points at an archived or
    nonexistent JD, returns None.

    `settings` may be passed by callers that already loaded it (saves
    one round-trip; the middleware always loads it onto
    `request.state.user_settings`)."""
    if settings is None:
        settings = _user_settings(uid)
    jd_id = settings.get("active_jd_id")
    if not jd_id:
        return None
    jd = jd_repo.get(int(jd_id))
    if jd is None or jd.user_id != uid or jd.archived_at is not None:
        return None
    return jd


def _recent_content_axes(uid: str) -> set[str]:
    """Axes touched by content items the user has completed within the
    scheduler's lookback window. Used by the content-aligned scoring
    component to boost compose problems aligned with the day's reading
    / video / exercise."""
    horizon = datetime.utcnow() - timedelta(days=config.scheduler.content_aligned_recency_days)
    axes: set[str] = set()
    for p in content_repo.progress_for_user(uid).values():
        if p.status != "completed" or p.checked_at is None or p.checked_at < horizon:
            continue
        item = content_repo.get_by_id(p.content_id, user_id=uid)
        if item is None:
            continue
        axes.update(item.axes)
    return axes


def _build_session(
    uid: str,
    *,
    attempts: list[Attempt] | None = None,
    active_jd=None,
    recent_content_axes: set[str] | None = None,
    include_warmups_in_pool: bool = False,
) -> list:
    """Score and rank problems for today's queue.

    All inputs that require a Supabase round-trip are accepted as
    optional args so the caller (home()) can fetch once and reuse;
    fall back to fetching here when called from places that don't
    want to thread the data through (eg /today/next)."""
    # Accept caller-supplied attempts list; otherwise fetch once.
    if attempts is None:
        attempts = attempt_repo.all_for_user(uid)
    # all_for_user returns descending; keep the most recent per problem
    seen: dict[int, Attempt] = {}
    for a in attempts:
        if a.problem_id not in seen:
            seen[a.problem_id] = a
    states = {s.problem_id: s for s in review_repo.all_for_user(uid)}
    if active_jd is None:
        active_jd = _active_jd(uid)
    # Easy-first bias schedule:
    #   0 attempts   → 1.0  (full easy-first; warmups included)
    #   5 attempts   → 0.5  (mediums start mixing in)
    #   10+ attempts → 0.0  (bias dissolves; pure scheduler)
    attempt_count = len(attempts)
    bias = max(0.0, 1.0 - attempt_count / 10.0)
    # Very-new users (bias ≥ 0.7 → at most 3 attempts) get warmups
    # mixed into the candidate pool so the first thing they see can be
    # truly easy (5-10 min). Caller can force this on too.
    include_warmups = include_warmups_in_pool or bias >= 0.7
    pool = problem_repo.all_core()
    if include_warmups:
        pool = pool + problem_repo.all_warmups()
    strategy = ReviewStrategy(config.scheduler, now=datetime.utcnow())
    if recent_content_axes is None:
        recent_content_axes = _recent_content_axes(uid)
    # Daily mode: "remix" shuffles the ranked queue (review interleaving);
    # the default "path" keeps the deterministic progression.
    remix_rng = None
    if _user_settings(uid).get("daily_mode") == "remix":
        import random
        remix_rng = random.Random()
    return strategy.build(
        pool,
        seen,
        states,
        config.ui.session_size,
        recent_content_axes=recent_content_axes,
        jd_axis_weights=active_jd.axis_weights if active_jd else None,
        jd_signal_tags=set(active_jd.signal_tags) if active_jd else None,
        easy_first_bias=bias,
        remix_rng=remix_rng,
        include_warmups=include_warmups,
    )


def _attempted_slugs(attempts) -> set[str]:
    """Problem slugs the user has ever attempted.

    Cold checkpoints ask "have you retrieved this without help yet", which is
    a lifetime question rather than a today question.

    Ids are resolved in one pass over the already-loaded core + warmup
    problems, not with a `get_by_id` per attempt — this runs on every home
    render and a user with 200 attempts would otherwise mean 200 queries.
    """
    if not attempts:
        return set()
    wanted = {
        getattr(a, "problem_id", None)
        for a in attempts
        if getattr(a, "problem_id", None) is not None
    }
    if not wanted:
        return set()
    try:
        catalogue = problem_repo.all_core() + problem_repo.all_warmups()
    except Exception:  # noqa: BLE001 — a cold checkpoint is not worth a 500
        _log.warning("could not load problems to resolve attempted slugs")
        return set()
    return {p.slug for p in catalogue if p.id in wanted and p.slug}


def _compute_next_action(
    uid: str,
    *,
    scored,
    daily_reading,
    daily_watch,
    daily_exercise,
    progress_by_id,
    attempts: list[Attempt] | None = None,
    active_writing=None,
    last_reflection_at=None,
    content_by_id: dict | None = None,
    user_settings: dict | None = None,
    problems_by_id: dict | None = None,
):
    """Wraps daily_flow.compute_next. Heavy DB calls (attempts list,
    active writing, last reflection) are accepted as optional args so
    `home()` can fetch each once and pass through, saving 2-3
    round-trips per page load. Fallback fetches if a caller doesn't
    have the data on hand."""
    today = datetime.utcnow().date()
    if attempts is None:
        attempts = attempt_repo.all_for_user(uid)
    attempts_today_ids = {
        a.problem_id for a in attempts
        if a.started_at and a.started_at.date() == today
    }
    if last_reflection_at is None:
        refls = reflection_repo.list_for_user(uid, limit=1)
        last_reflection_at = refls[0].generated_at if refls else None
    if active_writing is None:
        active_writing = writing_repo.active_draft_today(uid)

    # Which content KINDS has the user completed today? Used by the
    # daily_flow to skip a slot once any item of that kind is done —
    # without this, finishing one reading just rotates a different
    # reading into the slot instead of advancing to watch.
    kinds_done_today: set[str] = set()
    if content_by_id is None:
        # Best-effort: build a tiny index just for content_ids that
        # show up as completed today.
        content_by_id = {}
        for cid, pr in (progress_by_id or {}).items():
            if (pr.status == "completed" and pr.checked_at
                    and pr.checked_at.date() == today):
                item = content_repo.get_by_id(cid, user_id=uid)
                if item:
                    content_by_id[cid] = item
    for cid, pr in (progress_by_id or {}).items():
        if (pr.status == "completed" and pr.checked_at
                and pr.checked_at.date() == today):
            item = content_by_id.get(cid)
            if item:
                kinds_done_today.add(item.kind)

    normalized_settings = dict(user_settings or {})
    active_track_raw = normalized_settings.get("active_track")
    if isinstance(active_track_raw, dict):
        active_slug = str(active_track_raw.get("slug") or "").strip()
        if active_slug:
            normalized_settings["active_track"] = _normalized_track_state(
                active_track_raw,
                slug=active_slug, settings=normalized_settings, user_id=uid,
            )

    if problems_by_id is None:
        needs_catalogue = normalized_settings.get("active_track") or normalized_settings.get("problem_schedule")
        problems_by_id = {
            p.id: p for p in problem_repo.all_core() + problem_repo.all_warmups()
        } if needs_catalogue else {}
    passing_ids = {a.problem_id for a in attempts if getattr(a, "test_passed", None) is True}

    return daily_flow_service.compute_next(
        today=today,
        user_settings=normalized_settings,
        user_id=uid,
        daily_reading=daily_reading,
        daily_watch=daily_watch,
        daily_exercise=daily_exercise,
        progress_by_content_id=progress_by_id,
        content_by_id=content_by_id,
        scored_problems=scored,
        problems_by_id=problems_by_id,
        attempts_today_problem_ids=attempts_today_ids,
        passing_problem_slugs={p.slug for pid, p in problems_by_id.items() if pid in passing_ids},
        available_problem_slugs={p.slug for p in problems_by_id.values()},
        active_writing=active_writing,
        last_reflection_at=last_reflection_at,
        kinds_done_today=kinds_done_today,
    )


def _assessment_snapshot(uid: str, run):
    if run is None:
        return {}, None
    responses = assessment_repo.responses_for_run(run.id, user_id=uid)
    scores = assess_service.measured_scores(run.final_scores or {}, responses)
    return scores, {
        "measured_axes": tuple(scores),
        "unknown_axes": tuple(axis for axis in assess_service.AXES if axis not in scores),
        "assessed_at": run.completed_at or run.started_at,
    }


def _suggested_problem_for_scores(uid: str, scores: dict[str, float], *, attempts: list[Attempt] | None = None):
    if not scores:
        return None
    if attempts is None:
        attempts = attempt_repo.all_for_user(uid)
    attempted = {a.problem_id for a in attempts}
    axes = sorted((axis for axis in assess_service.AXES if axis in scores), key=scores.__getitem__)
    # An exhausted or unavailable exercise list must not hide the next
    # useful recommendation on another measured axis.
    for axis in axes:
        for slug in assess_service.suggested_slugs_for_axis(axis):
            p = problem_repo.get_by_slug(slug)
            if p is not None and p.id not in attempted:
                return {"problem": p, "axis": axis, "axis_label": assess_service.AXIS_LABELS.get(axis, axis)}
    return None


def _credential_runs_for_aim(uid: str, *, limit: int = 10) -> list[dict[str, object]]:
    """Build a small view-model list for /aim evidence history.

    The base `CredentialRun` model doesn't carry filename or analysis
    metadata, so we enrich each run with:
    - primary filename (first uploaded file for the run, if any)
    - top axis chips (best 3 inferred axes from saved assessment)
    - saved summary markdown (if present)

    Implementation: batched. Previously this method did 2 round-trips per
    credential run (files_for_run + latest_assessment), turning 10 runs
    into 21 queries. On Fly→Supabase with even modest RTT that was
    several seconds of unaccounted /aim latency. We now do 3 queries
    total regardless of run count: list_completed_for_user, then one
    batched fetch each for files and assessments.
    """
    runs = credentials_repo.list_completed_for_user(uid, limit=limit)
    run_ids = [run.id for run in runs if run.id is not None]
    if not run_ids:
        return []

    first_files = credentials_repo.first_files_by_run(run_ids)
    latest_assessments = credentials_repo.latest_assessments_by_run(run_ids)

    rows: list[dict[str, object]] = []
    for run in runs:
        if run.id is None:
            continue
        primary_file = first_files.get(run.id)
        primary_filename = primary_file.filename if primary_file else None

        assessment = latest_assessments.get(run.id)
        summary_md: str | None = None
        top_axes: list[str] = []
        top_axis_keys: list[str] = []
        if assessment is not None:
            summary_md = (assessment.summary_md or "").strip() or None
            scored_axes = sorted(
                (
                    (axis, score)
                    for axis, score in (assessment.inferred_axis_scores or {}).items()
                    if isinstance(score, (int, float)) and score > 0
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            top_axis_keys = [axis for axis, _ in scored_axes]
            top_axes = [
                assess_service.AXIS_LABELS.get(axis, axis.replace("_", " ").title())
                for axis, _ in scored_axes[:3]
            ]

        rows.append(
            {
                "id": run.id,
                "completed_at": run.completed_at,
                "primary_filename": primary_filename,
                "top_axes": top_axes,
                "top_axis_keys": top_axis_keys,
                "summary_md": summary_md,
            }
        )
    return rows


def _quiz_answers_for_run(run_id: int, uid: str) -> list[str]:
    """Return normalized onboarding quiz answers for imposter detection.

    We only need to distinguish "not sure" from all other selections.
    """
    answers: list[str] = []
    for response in assessment_repo.responses_for_run(run_id, user_id=uid):
        q = assess_service.get_question(response.question_id)
        if q is None:
            continue
        if not (0 <= response.answer_index < len(q.options)):
            continue
        option_text = (q.options[response.answer_index].text or "").lower()
        if "not sure" in option_text or "unsure" in option_text:
            answers.append("not_sure")
        else:
            answers.append("yes")
    return answers


def _latest_credential_scores(uid: str) -> dict[str, float] | None:
    latest_run = credentials_repo.latest_completed(uid)
    if latest_run is None or latest_run.id is None:
        return None
    latest_assessment = credentials_repo.latest_assessment(latest_run.id)
    if latest_assessment is None:
        return None
    return latest_assessment.inferred_axis_scores or None


def _detect_and_save_imposter_signal(
    *,
    uid: str,
    run_id: int,
    assessment_scores: dict[str, float],
    settings: dict | None = None,
) -> imposter_service.ImposterSignal:
    """Detect onboarding imposter signal and persist to user settings."""
    target_settings = settings if settings is not None else _user_settings(uid)
    signal = imposter_service.detect(
        quiz_answers=_quiz_answers_for_run(run_id, uid),
        assessment_scores=assessment_scores,
        credential_scores=_latest_credential_scores(uid),
        now=datetime.utcnow(),
    )
    target_settings["imposter_signal"] = signal.as_dict()
    _save_user_settings(uid, target_settings)
    return signal


def _imposter_axes_for_intercept(
    *,
    signal: dict,
    assessment_scores: dict[str, float],
    credential_scores: dict[str, float] | None,
) -> list[dict[str, object]]:
    """Build top-three axis rows for the onboarding intercept template."""
    axes: list[str] = []
    seen: set[str] = set()

    raw_triggering = signal.get("triggering_axes")
    if isinstance(raw_triggering, list):
        for axis in raw_triggering:
            if not isinstance(axis, str) or axis not in assessment_scores:
                continue
            if axis in seen:
                continue
            seen.add(axis)
            axes.append(axis)

    if credential_scores:
        gap = credentials_service.compute_gap(credential_scores, assessment_scores)
        gap = {axis: value for axis, value in gap.items() if axis in assessment_scores}
        for axis in credentials_service.top_gaps(gap, n=3):
            if axis in seen:
                continue
            seen.add(axis)
            axes.append(axis)

    if len(axes) < 3 and assessment_scores:
        weakest_self = sorted(
            (
                (axis, float(score))
                for axis, score in assessment_scores.items()
                if axis not in seen
            ),
            key=lambda item: (item[1], item[0]),
        )
        for axis, _score in weakest_self:
            seen.add(axis)
            axes.append(axis)
            if len(axes) >= 3:
                break

    rows: list[dict[str, object]] = []
    for axis in axes[:3]:
        self_score = float(assessment_scores.get(axis, 0.0))
        credential_score: float | None = None
        if credential_scores and axis in credential_scores:
            credential_score = float(credential_scores[axis])
        rows.append(
            {
                "axis": axis,
                "axis_label": assess_service.AXIS_LABELS.get(
                    axis,
                    axis.replace("_", " ").title(),
                ),
                "self_pct": round(self_score * 100),
                "credential_pct": (
                    round(credential_score * 100)
                    if credential_score is not None
                    else None
                ),
            }
        )

    return rows


def _build_home_daily_slots(
    *,
    kinds_completed_today: set[str],
    attempted_problem_types_today: set[str],
    active_writing,
) -> list[dict[str, object]]:
    """Build the 5-segment home progress strip.

    BEN-99 / #299: map activity kinds to slots 1:1 so we don't mark
    work the operator didn't do.

    Mapping choice: `code_compose` feeds the Composing slot. Practicing
    stays tied to content-kind `exercise`. This keeps a single compose
    attempt from lighting both slots, while still allowing both slots to
    be done if the operator actually did both activities."""
    practicing_done = "exercise" in kinds_completed_today
    composing_done = "code_compose" in attempted_problem_types_today
    return [
        {"key": "reading", "label": "Reading", "done": "reading" in kinds_completed_today},
        {
            "key": "listening",
            "label": "Listening",
            "done": bool({"video", "podcast"} & kinds_completed_today),
        },
        {"key": "practicing", "label": "Practicing", "done": practicing_done},
        {"key": "composing", "label": "Composing", "done": composing_done},
        {"key": "writing", "label": "Writing", "done": active_writing is not None},
    ]


# Daily chain crumb (GH #304): content/problem pages can show
# "Step N of 4" only when reached through /today/next redirects.
_DAILY_CHAIN_TOTAL = 4
_DAILY_CHAIN_STEP_BY_KIND: dict[str, int] = {
    "reading": 1,
    "watch": 2,
    "exercise": 3,
    "practice": 4,
}


def _daily_chain_redirect_url(*, url: str, kind: str) -> str:
    """Attach one-shot daily-chain query params when kind is in flow."""
    step = _DAILY_CHAIN_STEP_BY_KIND.get(kind)
    if step is None:
        return url

    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "chain": "1",
            "step": str(step),
            "total": str(_DAILY_CHAIN_TOTAL),
        }
    )
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _daily_chain_step(
    request: Request,
    *,
    allowed_steps: set[int],
) -> dict[str, int] | None:
    """Validate `?chain=1&step=N&total=4` and return step payload."""
    if request.query_params.get("chain") != "1":
        return None

    try:
        step = int(request.query_params.get("step") or "")
        total = int(request.query_params.get("total") or "")
    except ValueError:
        return None

    if total != _DAILY_CHAIN_TOTAL:
        return None
    if step not in allowed_steps:
        return None
    if not 1 <= step <= total:
        return None

    return {"step": step, "total": total}


def _track_completion_counts(track, passed: set[int], exemptions: set[int] | None = None) -> dict:
    required = set(getattr(track, "required_section_indices", range(track.total_sections)))
    exemptions = (exemptions or set()) - passed
    return {
        "completed_count": len(passed & required),
        "exempt_count": len(exemptions & required),
        "satisfied_count": len((passed | exemptions) & required),
        "optional_exempt_count": len(exemptions - required),
        "total_sections": len(required),
        "optional_completed": len(passed - required),
        "optional_total": track.total_sections - len(required),
        "first_optional_index": next((i for i in range(track.total_sections) if i not in required), None),
    }


def _active_track_materials(settings: dict | None, user_id=None) -> dict | None:
    raw = (settings or {}).get("active_track")
    if not isinstance(raw, dict):
        return None
    slug = str(raw.get("slug") or "").strip()
    if not tracks_service.is_available_track(slug):
        return None

    track = get_track(slug)
    if track is None or not hasattr(track, "all_sections"):
        return None
    state = _normalized_track_state(raw, slug=slug, settings=settings, user_id=user_id)
    passed = _track_checkpoint_passed_sections(state=state, track=track)
    exempt = _track_exemptions(track, settings, user_id=user_id)
    indices = tracks_service.section_activity_indices(track, passed | exempt, state.get("preferred_section"))
    cards = {kind: {"idx": idx, "section": track.all_sections[idx],
                    "url": f"/content/{track_content.item_slug(slug, track.all_sections[idx].url)}",
                    "session": state.get("session_per_section", {}).get(str(idx), {})}
             for kind, idx in indices.items()}
    supplements = [{"idx": idx, "section": section, "completed": idx in passed, "exemption": idx in exempt,
                    "url": f"/content/{track_content.item_slug(slug, track.all_sections[idx].url)}"}
                   for idx, section in enumerate(track.all_sections) if section.optional]
    return {"track": track, "cards": cards, "supplements": supplements,
            **_track_completion_counts(track, passed, exempt)}


def _build_home_active_track_progress(*, settings: dict | None, user_id=None) -> dict[str, object] | None:
    """Return home-track progress payload when a valid active track exists."""
    active_track = (settings or {}).get("active_track")
    if not isinstance(active_track, dict):
        return None

    slug = active_track.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        return None

    if not tracks_service.is_available_track(slug):
        return None

    track = get_track(slug.strip())
    if track is None:
        return None

    normalized = _normalized_track_state(active_track, slug=slug.strip(), settings=settings, user_id=user_id)
    passed = _track_checkpoint_passed_sections(state=normalized, track=track)
    exempt = _track_exemptions(track, settings, user_id=user_id)
    counts = _track_completion_counts(track, passed, exempt)
    passed_count = counts["completed_count"]
    total = counts["total_sections"]

    if hasattr(track, "all_sections"):
        next_idx = tracks_service.next_section_index(track, passed | exempt, normalized.get("preferred_section"))
    else:
        try:
            cursor_hint = int(normalized.get("cursor", 0))
        except (TypeError, ValueError):
            cursor_hint = 0
        cursor_hint = max(0, cursor_hint)
        next_idx = None if cursor_hint >= total else cursor_hint

    pct = int(100 * counts["satisfied_count"] / max(1, total))
    return {
        "track_title": track.title,
        "track_slug": track.slug,
        # Keep `cursor` for back-compat with existing templates/tests.
        "cursor": passed_count,
        "passed_count": passed_count,
        "exempt_count": counts["exempt_count"],
        "next_section_number": (next_idx + 1) if next_idx is not None else 0,
        "total": total,
        "pct": pct,
        "optional_completed": counts["optional_completed"],
        "optional_total": counts["optional_total"],
    }


def _build_home_rail(
    *,
    attempts: list,
    progress_by_id: dict,
    scores: dict[str, float],
    now: datetime,
    active_track_progress: dict | None,
) -> dict[str, object]:
    """Compose the right-rail content for the Today surface (WS4).

    The rail surfaces three glance-able dashboard pieces alongside
    the primary relevant-now content: a small list of active
    initiatives, a 7-day activity signal, and the weakest skill axis.
    All inputs are pre-computed by the home route — this helper is
    pure aggregation, no I/O.

    Returned shape (everything optional so the template can degrade
    gracefully on a fresh user with no signal yet):

      {
        "initiatives": [
          {"slug": str, "title": str, "priority": int,
           "target_relative": str | None, "target_urgency": str | None,
           "is_pinned": bool},
          ...up to 3...
        ],
        "signal": {
          "attempts_7d": int,
          "content_7d": int,
          "active_today": bool,
        } | None,
        "weak_axis": {
          "label": str,
          "score_pct": int,   # 0-100
        } | None,
      }
    """
    horizon = now - timedelta(days=7)
    today_date = now.date()

    # ── Active initiatives — top 3 by priority then target date. The
    # pinned one (operator's currently-focused initiative) is hoisted
    # to the top regardless of priority order so it always renders
    # first. Cheap: load_initiatives reads from the file system.
    pinned_slug = (active_track_progress or {}).get("track_slug")
    try:
        all_initiatives = initiatives_service.load_initiatives()
    except Exception:
        all_initiatives = []
    active = [i for i in all_initiatives if i.status == "active"]
    active.sort(
        key=lambda i: (
            i.slug != pinned_slug,
            i.priority,
            i.target_date or "9999-12-31",
            i.title.lower(),
        )
    )

    rail_inits: list[dict] = []
    for init in active[:3]:
        target_relative, target_urgency = focus_service._format_target_date(
            init.target_date, now=now
        )
        rail_inits.append({
            "slug": init.slug,
            "title": init.title,
            "priority": init.priority,
            "target_relative": target_relative,
            "target_urgency": target_urgency,
            "is_pinned": init.slug == pinned_slug,
        })

    # ── 7-day signal. attempts_7d counts started_at; content_7d
    # counts content_progress rows completed within 7d; active_today
    # is True if EITHER an attempt OR a content completion happened
    # today (drives the "you're active today" rail microcopy).
    attempts_7d = sum(
        1 for a in attempts
        if a.started_at and a.started_at >= horizon
    )
    content_7d = sum(
        1 for pr in progress_by_id.values()
        if pr.status == "completed" and pr.checked_at and pr.checked_at >= horizon
    )
    active_today = any(
        a.started_at and a.started_at.date() == today_date for a in attempts
    ) or any(
        pr.status == "completed" and pr.checked_at and pr.checked_at.date() == today_date
        for pr in progress_by_id.values()
    )

    # ── Weak axis from the assessment scores. Map the raw axis key
    # to a human label via the same dict the rest of the home
    # surface uses. ``scores`` is empty for users who haven't taken
    # the assessment yet, in which case the rail card just doesn't
    # render.
    weak_axis: dict | None = None
    if scores:
        weakest = min(scores.items(), key=lambda kv: kv[1])
        axis_key, axis_val = weakest
        label = assess_service.AXIS_LABELS.get(axis_key, axis_key.replace("_", " ").title())
        weak_axis = {
            "label": label,
            "score_pct": int(round(axis_val * 100)),
        }

    signal = None
    if attempts_7d or content_7d or active_today:
        signal = {
            "attempts_7d": attempts_7d,
            "content_7d": content_7d,
            "active_today": active_today,
        }

    return {
        "initiatives": rail_inits,
        "signal": signal,
        "weak_axis": weak_axis,
    }


def _build_home_section_cards(
    *,
    done_today_items: list[tuple],
    daily_reading,
    daily_watch,
    daily_exercise,
) -> dict[str, dict[str, object]]:
    """Pick section-card items for home.

    BEN-33: when a slot is done today, keep showing the completed item
    (sticky audit trail) instead of rotating to the next unread pick."""
    done_by_kind: dict[str, tuple] = {}
    for item, pr in done_today_items:
        # done_today_items is already newest-first, so first hit wins.
        done_by_kind.setdefault(item.kind, (item, pr))

    watch_done_pair = next(
        (
            pair
            for pair in done_today_items
            if pair[0].kind in {"video", "podcast"}
        ),
        None,
    )

    reading_pair = done_by_kind.get("reading")
    exercise_pair = done_by_kind.get("exercise")

    return {
        "reading": {
            "item": reading_pair[0] if reading_pair else daily_reading,
            "done_today": reading_pair is not None,
        },
        "watch": {
            "item": watch_done_pair[0] if watch_done_pair else daily_watch,
            "done_today": watch_done_pair is not None,
        },
        "exercise": {
            "item": exercise_pair[0] if exercise_pair else daily_exercise,
            "done_today": exercise_pair is not None,
        },
    }


def _display_tz_from_settings(settings: dict | None) -> str:
    tz_name = (settings or {}).get("display_tz")
    if not isinstance(tz_name, str) or not tz_name.strip():
        return "UTC"
    tz_name = tz_name.strip()
    try:
        ZoneInfo(tz_name)
        return tz_name
    except ZoneInfoNotFoundError:
        return "UTC"


def _local_now_for_settings(
    settings: dict | None,
    *,
    now_utc: datetime | None = None,
) -> datetime:
    tz_name = _display_tz_from_settings(settings)
    tzinfo = ZoneInfo(tz_name)
    if now_utc is None:
        return datetime.now(tzinfo)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=ZoneInfo("UTC"))
    return now_utc.astimezone(tzinfo)


def _week_cutoff_utc(
    settings: dict | None,
    *,
    days: int = 7,
    now_utc: datetime | None = None,
) -> datetime:
    local_now = _local_now_for_settings(settings, now_utc=now_utc)
    local_cutoff = local_now - timedelta(days=days)
    return local_cutoff.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _format_local_stamp(ts: datetime | None, tz_name: str) -> str | None:
    if ts is None:
        return None
    tzinfo = ZoneInfo(tz_name)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(tzinfo).strftime("%a, %b %d")


def _format_local_stamp_with_time(ts: datetime | None, tz_name: str) -> str | None:
    if ts is None:
        return None
    tzinfo = ZoneInfo(tz_name)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(tzinfo).strftime("%Y-%m-%d %H:%M")


def _coerce_pct_int(value: object, *, clamp: bool) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
    else:
        return None

    if clamp:
        return max(0, min(100, parsed))
    if parsed < 0 or parsed > 100:
        return None
    return parsed


def _reflection_prompts_text(prompts: object) -> str:
    if not isinstance(prompts, list):
        return ""
    chunks: list[str] = []
    for entry in prompts:
        if isinstance(entry, dict):
            for key in ("label", "prompt", "text"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value)
        elif isinstance(entry, str) and entry.strip():
            chunks.append(entry)
    return " ".join(chunks).casefold()


def _has_calibration_prompt(refl: Reflection) -> bool:
    prompt_text = _reflection_prompts_text(refl.prompts)
    if not prompt_text:
        return False
    return "calibration" in prompt_text or (
        "predict" in prompt_text and "actual" in prompt_text
    )


def _trim_prose(text: str | None, *, max_chars: int = 140) -> str:
    cleaned = " ".join((text or "").strip().split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _build_calibration_chart_data(
    reflections: list[Reflection],
    *,
    tz_name: str,
) -> dict[str, object]:
    chart = {
        "view_width": 336,
        "view_height": 310,
        "plot_left": 48,
        "plot_top": 28,
        "plot_width": 240,
        "plot_height": 240,
        "plot_right": 288,
        "plot_bottom": 268,
        "axis_ticks": [0, 25, 50, 75, 100],
        "points": [],
    }

    points: list[dict[str, object]] = []
    plot_left = chart["plot_left"]
    plot_top = chart["plot_top"]
    plot_width = chart["plot_width"]
    plot_height = chart["plot_height"]
    plot_bottom = chart["plot_bottom"]

    for refl in reflections:
        payload = refl.calibration_json if isinstance(refl.calibration_json, dict) else None
        if payload is None:
            continue

        predicted_pct = _coerce_pct_int(payload.get("predicted_pct"), clamp=False)
        actual_pct = _coerce_pct_int(payload.get("actual_pct"), clamp=False)
        if predicted_pct is None or actual_pct is None:
            continue

        gap_md_raw = payload.get("gap_md")
        gap_md = gap_md_raw.strip() if isinstance(gap_md_raw, str) else ""
        gap_text = gap_md or f"{actual_pct - predicted_pct:+d} pts"

        prose = _trim_prose(refl.summary_md or refl.response_md)
        stamp = _format_local_stamp_with_time(refl.generated_at, tz_name) or "Unknown date"

        x = round(plot_left + (plot_width * (predicted_pct / 100.0)), 2)
        y = round(plot_bottom - (plot_height * (actual_pct / 100.0)), 2)

        tooltip_lines = [
            stamp,
            f"Predicted {predicted_pct}% · Actual {actual_pct}% · Gap {gap_text}",
        ]
        if prose:
            tooltip_lines.append(prose)

        points.append(
            {
                "reflection_id": refl.id,
                "generated_at": refl.generated_at,
                "predicted_pct": predicted_pct,
                "actual_pct": actual_pct,
                "gap_text": gap_text,
                "x": x,
                "y": y,
                "tooltip": "\n".join(tooltip_lines),
            }
        )

    points.sort(key=lambda p: p.get("generated_at") or datetime.min)
    total = len(points)
    for idx, point in enumerate(points):
        recency = 1.0 if total <= 1 else idx / (total - 1)
        point["opacity"] = round(0.35 + recency * 0.55, 2)
        point["intensity"] = round(0.5 + recency * 0.45, 2)
        point["radius"] = round(4.0 + recency * 1.6, 2)

    chart["points"] = points
    return chart


def _is_weekend_for_user(
    request: Request,
    uid: str,
    *,
    now_utc: datetime | None = None,
) -> bool:
    del uid
    settings = request.state.user_settings or {}
    return _local_now_for_settings(settings, now_utc=now_utc).weekday() in (5, 6)


def _render_rest_home(request: Request, uid: str):
    settings = request.state.user_settings or {}
    tz_name = _display_tz_from_settings(settings)
    local_now = _local_now_for_settings(settings)
    since_utc = _week_cutoff_utc(settings, days=7)

    attempts = attempt_repo.list_for_user_since(uid, since_utc)
    content_progress = content_repo.list_progress_since(uid, since_utc)
    writings = writing_repo.list_for_user_since(uid, since_utc)
    reflections = reflection_repo.list_for_user_since(uid, since_utc)

    # GH #229: surface a pre-generated, unanswered reflection prominently
    # so the operator can open it instead of clicking "Generate" and
    # waiting. A reflection is "ready" when it was created by the
    # Saturday cron (pregenerated=True) AND the operator hasn't written
    # a response yet (response_md still None).
    pregenerated_ready = next(
        (
            r for r in reflections
            if getattr(r, "pregenerated", False) and r.response_md is None
        ),
        None,
    )
    assessments = assessment_repo.completed_since(uid, since_utc)
    credentials = credentials_repo.completed_since(uid, since_utc)

    attempt_items: list[dict[str, str | None]] = []
    for attempt in attempts:
        problem = problem_repo.get_by_id(attempt.problem_id)
        href = f"/attempt/{attempt.id}/review" if attempt.id is not None else None
        if href is None and problem is not None:
            href = f"/problem/{problem.slug}"
        attempt_items.append(
            {
                "title": problem.title if problem else f"Problem #{attempt.problem_id}",
                "href": href,
                "meta": _format_local_stamp(attempt.started_at, tz_name),
            }
        )

    content_items: list[dict[str, str | None]] = []
    for progress in content_progress:
        item = content_repo.get_by_id(progress.content_id, user_id=uid)
        if item is None:
            continue
        stamp = _format_local_stamp(progress.checked_at, tz_name)
        content_items.append(
            {
                "title": item.title,
                "href": f"/content/{item.slug}",
                "meta": " · ".join(part for part in [item.kind.title(), stamp] if part),
            }
        )

    writing_items: list[dict[str, str | None]] = []
    for writing in writings:
        title = (writing.title or "").strip() or "Untitled draft"
        writing_items.append(
            {
                "title": title,
                "href": f"/writings/{writing.id}" if writing.id is not None else "/writings",
                "meta": _format_local_stamp(writing.updated_at, tz_name),
            }
        )

    reflection_items: list[dict[str, str | None]] = []
    for reflection in reflections:
        text = (reflection.summary_md or reflection.response_md or "").strip()
        if text:
            title = text[:80] + ("…" if len(text) > 80 else "")
        else:
            title = "Weekly reflection"
        reflection_items.append(
            {
                "title": title,
                "href": f"/reflect/{reflection.id}" if reflection.id is not None else "/reflect",
                "meta": _format_local_stamp(reflection.generated_at, tz_name),
            }
        )

    assessment_items: list[dict[str, str | None]] = []
    for run in assessments:
        top_axis = None
        if run.final_scores:
            top_axis = max(run.final_scores.items(), key=lambda item: item[1])[0]
        assessment_items.append(
            {
                "title": (
                    f"Assessment refresh · {assess_service.AXIS_LABELS.get(top_axis, top_axis)}"
                    if top_axis else "Assessment refresh"
                ),
                "href": f"/assess/{run.id}/result" if run.id is not None else "/onboarding",
                "meta": _format_local_stamp(run.completed_at, tz_name),
            }
        )

    credential_items: list[dict[str, str | None]] = []
    for run in credentials:
        credential_items.append(
            {
                "title": run.status_text or "Credential upload",
                "href": f"/credentials/{run.id}" if run.id is not None else "/credentials",
                "meta": _format_local_stamp(run.completed_at, tz_name),
            }
        )

    week_recap = {
        "attempts": {
            "label": "Problems attempted",
            "count": len(attempt_items),
            "items": attempt_items,
        },
        "content": {
            "label": "Content completed",
            "count": len(content_items),
            "items": content_items,
        },
        "writings": {
            "label": "Writings touched",
            "count": len(writing_items),
            "items": writing_items,
        },
        "reflections": {
            "label": "Reflections written",
            "count": len(reflection_items),
            "items": reflection_items,
        },
        "assessments": {
            "label": "Assessments retaken",
            "count": len(assessment_items),
            "items": assessment_items,
        },
        "credentials": {
            "label": "Credentials uploaded",
            "count": len(credential_items),
            "items": credential_items,
        },
    }
    week_recap["total"] = sum(int(section["count"]) for section in week_recap.values())

    return templates.TemplateResponse(
        request,
        "home_rest.html",
        {
            "config": config,
            "nav_section": "drill",
            "day_label": local_now.strftime("%A"),
            "display_name": settings.get("display_name"),
            "week_recap": week_recap,
            "pregenerated_ready": pregenerated_ready,
        },
    )


def _landing_stats() -> dict[str, int]:
    """Counts for the landing page, read off what actually ships.

    Prose on a marketing page rots the moment content/ changes, so the
    numbers are counted rather than written down. Cheap (a few directory
    listings) and cached, since the logged-out page is the most-hit route
    once the URL is public.
    """
    from .services import assessment as assess_svc

    def _count(subdir: str) -> int:
        d = REPO_ROOT / "content" / subdir
        if not d.is_dir():
            return 0
        return sum(
            1
            for f in d.iterdir()
            if f.is_file() and not f.name.startswith(".")
        )

    return {
        "problems": _count("problems"),
        "warmups": _count("warmups"),
        "readings": _count("readings"),
        "exercises": _count("exercises"),
        "tracks": _count("tracks"),
        "axes": len(assess_svc.AXES),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Today view. Heavily round-trip-bound (Postgres + later Sonnet).
    This route owns "fetch each thing once and share it" — every
    helper called below accepts pre-fetched data so the request makes
    ~10 round-trips instead of ~25-30 (which was 4-5 seconds of
    visible wait time).

    Unauthenticated, this is the landing page instead — "/" is the only
    entry in _PUBLIC_EXACT_PATHS, so the session middleware lets an
    anonymous request through to here rather than bouncing it to /login."""
    if request.state.user_session is None:
        return templates.TemplateResponse(
            request,
            "landing.html",
            {
                "nav_section": None,
                "is_alpha_view": True,
                "stats": _landing_stats(),
            },
        )

    uid = request.state.user_session.user_id
    # Middleware already loaded settings onto request.state — use it
    # rather than refetching. _user_settings() is also called by
    # _save_user_settings via routes that need a fresh read; here we
    # trust the per-request snapshot.
    settings = request.state.user_settings or {}

    if _is_weekend_for_user(request, uid):
        return _render_rest_home(request, uid)

    latest = assessment_repo.latest_completed(uid)
    if latest is None and not settings.get("onboarding_skipped"):
        return RedirectResponse(url="/onboarding", status_code=303)

    # Single fetch of these three; everything below reads from these.
    attempts = attempt_repo.all_for_user(uid)
    if imposter_service.maybe_decay(settings, attempts):
        _save_user_settings(uid, settings)
    progress_by_id = content_repo.progress_for_user(uid)
    active_jd = _active_jd(uid, settings=settings)
    active_writing = writing_repo.active_draft_today(uid)

    # Compute "axes touched by content recently completed" off the
    # progress dict we already have, so _recent_content_axes doesn't
    # round-trip again.
    horizon = datetime.utcnow() - timedelta(days=config.scheduler.content_aligned_recency_days)
    recent_axes: set[str] = set()
    # Pre-fetch only the items we need to inspect (those with recent
    # checked_at); avoids an N-per-item lookup.
    recently_completed_ids = [
        p.content_id for p in progress_by_id.values()
        if p.status == "completed" and p.checked_at and p.checked_at >= horizon
    ]
    # Combine with the daily content query below: we'll grab axes from
    # the items dict computed in the next step.

    # ONE query for all four content kinds (instead of 4 round-trips).
    content_by_kind = content_repo.all_by_kinds(["reading", "video", "podcast", "exercise"], user_id=uid)
    # Build an id → ContentItem index for fast lookups below.
    all_content_items = [item for items in content_by_kind.values() for item in items]
    content_by_id = {ci.id: ci for ci in all_content_items}
    # Now resolve recent_axes using the in-memory index — no extra RTs.
    for cid in recently_completed_ids:
        ci = content_by_id.get(cid)
        if ci:
            recent_axes.update(ci.axes)

    scored = _build_session(
        uid,
        attempts=attempts,
        active_jd=active_jd,
        recent_content_axes=recent_axes,
    )

    scores, assessment_coverage = _assessment_snapshot(uid, latest)
    # Suggested problem from weakest axis. Pass attempts to avoid a re-fetch.
    suggestion = (
        _suggested_problem_for_scores(uid, scores, attempts=attempts)
        if latest else None
    )

    axis_ratings = content_repo.axis_ratings_for_user(uid)
    daily = {
        kind: content_service.pick_daily(items, progress_by_id, scores, axis_ratings)
        for kind, items in content_by_kind.items()
    }
    watch_pick = daily.get("video") or daily.get("podcast")

    # Share due-problem lookup with checkpoint evidence when both need it.
    daily_problems = {
        p.id: p for p in problem_repo.all_core() + problem_repo.all_warmups()
    } if settings.get("problem_schedule") else None
    next_action = _compute_next_action(
        uid,
        scored=scored,
        daily_reading=daily.get("reading"),
        daily_watch=watch_pick,
        daily_exercise=daily.get("exercise"),
        progress_by_id=progress_by_id,
        attempts=attempts,
        active_writing=active_writing,
        content_by_id=content_by_id,  # avoid re-fetch of items for kinds_done_today
        user_settings=settings,
        problems_by_id=daily_problems,
    )

    due_review = daily_flow_service.compute_due_review(
        today=datetime.utcnow().date(), user_settings=settings,
        progress_by_content_id=progress_by_id, content_by_id=content_by_id,
        problems_by_id=daily_problems,
    ) if (next_action.get("kind") if isinstance(next_action, dict) else getattr(next_action, "kind", None)) in {"track_section", "track_checkpoint"} else None

    recent = problem_repo.list_recent_for_user(uid, limit=5)
    # The "has warmups" check is cheap because we already include them
    # in the candidate pool for new users; just sample from scored.
    has_warmups = any(s.problem.is_warmup for s in scored) or True

    today_date = datetime.now().strftime("%A, %B %d, %Y")
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    display_name = settings.get("display_name")

    # "Done today" tray — sweep content_progress for items completed
    # today, attach each one's ContentItem from the in-memory index.
    # Lets the user see at-a-glance what they finished and offers a
    # one-click "undo" to requeue an item back into the daily slot.
    today_only = datetime.now().date()
    done_today_items: list[tuple] = []
    for cid, pr in progress_by_id.items():
        if (pr.status == "completed" and pr.checked_at
                and pr.checked_at.date() == today_only):
            item = content_by_id.get(cid)
            if item:
                done_today_items.append((item, pr))
    # Sort newest-first by checked_at so the most recent completion
    # is on top — matches the "I just did this" mental model.
    done_today_items.sort(key=lambda pair: pair[1].checked_at or datetime.min, reverse=True)

    section_cards = _build_home_section_cards(
        done_today_items=done_today_items,
        daily_reading=daily.get("reading"),
        daily_watch=watch_pick,
        daily_exercise=daily.get("exercise"),
    )

    # Easy-first ramp progress. Mirrors the schedule in `_build_session`:
    #   0 attempts   → 1.0  (full ramp)
    #   5 attempts   → 0.5
    #   10+ attempts → 0.0  (ramp ends)
    # Surfaced on the Up next card so the user knows why they're seeing
    # easier problems and how close they are to the ramp ending.
    ramp_attempt_count = len(attempts)
    ramp_bias = max(0.0, 1.0 - ramp_attempt_count / 10.0)
    ramp_active = ramp_bias > 0

    # Daily progress: 5 slots, each "done today" or not. Mostly derived
    # from already-loaded data; for problem attempts we resolve the
    # problem_type once per unique attempted problem id when it's not
    # already present on the Attempt object. Renders as a compact
    # 5-segment bar at the top of home so the user can see at a glance
    # how much of today's plan is complete.
    kinds_completed_today = {item.kind for item, _pr in done_today_items}
    attempted_problem_types_today: set[str] = set()
    problem_type_by_id: dict[int, str | None] = {}
    for a in attempts:
        if not (a.started_at and a.started_at.date() == today_only):
            continue
        problem_type = getattr(a, "problem_type", None)
        if not isinstance(problem_type, str) or not problem_type:
            pid = int(a.problem_id)
            if pid not in problem_type_by_id:
                problem = problem_repo.get_by_id(pid)
                problem_type_by_id[pid] = problem.problem_type if problem else None
            problem_type = problem_type_by_id[pid]
        if isinstance(problem_type, str) and problem_type:
            attempted_problem_types_today.add(problem_type)

    daily_slots = _build_home_daily_slots(
        kinds_completed_today=kinds_completed_today,
        attempted_problem_types_today=attempted_problem_types_today,
        active_writing=active_writing,
    )
    daily_done = sum(1 for s in daily_slots if s["done"])
    daily_total = len(daily_slots)
    active_track_progress = _build_home_active_track_progress(settings=settings, user_id=uid)

    # Right-rail content (WS4 Today rebuild, 2026-05-28). Glance-able
    # dashboard surface alongside the primary relevant-now content:
    # top 3 active initiatives, 7-day signal, weakest axis. Pure
    # aggregation over data we already have — no new round-trips.
    home_rail = _build_home_rail(
        attempts=attempts,
        progress_by_id=progress_by_id,
        scores=scores,
        now=datetime.now(),
        active_track_progress=active_track_progress,
    )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "bubbles": _bubbles_for(request, "today"),
            "scored": scored,
            "recent": recent,
            "has_warmups": has_warmups,
            "config": config,
            "skill_scores": scores,
            "has_assessment": latest is not None,
            "has_weighted_jd": bool(active_jd and any(float(active_jd.axis_weights.get(axis, 0)) > 0 for axis in assess_service.AXES)),
            "axis_labels": assess_service.AXIS_LABELS,
            "suggestion": suggestion,
            "nav_section": "drill",
            "daily_reading": daily.get("reading"),
            "daily_watch": watch_pick,
            "daily_exercise": daily.get("exercise"),
            "reading_card_item": section_cards["reading"]["item"],
            "reading_card_done_today": section_cards["reading"]["done_today"],
            "watch_card_item": section_cards["watch"]["item"],
            "watch_card_done_today": section_cards["watch"]["done_today"],
            "exercise_card_item": section_cards["exercise"]["item"],
            "exercise_card_done_today": section_cards["exercise"]["done_today"],
            "progress_by_id": progress_by_id,
            "today_date": today_date,
            "active_jd": active_jd,
            "display_name": display_name,
            "yesterday": yesterday,
            "active_writing": active_writing,
            "next_action": next_action,
            "due_review": due_review,
            "done_today_items": done_today_items,
            "ramp_active": ramp_active,
            "ramp_attempt_count": ramp_attempt_count,
            "ramp_threshold": 10,
            "daily_slots": daily_slots,
            "daily_done": daily_done,
            "daily_total": daily_total,
            "active_track_progress": active_track_progress,
            "track_materials": _active_track_materials(settings, user_id=uid),
            "home_rail": home_rail,
            # One-shot orientation toast keyed off ?toast=... in the URL.
            # The onboarding/skip redirect sets ?toast=ramp_intro; any
            # other nav drops the param so the toast doesn't follow the
            # user around.
            "toast": request.query_params.get("toast"),
        },
    )


@app.get("/today/next", response_class=HTMLResponse)
def today_next(request: Request):
    """After completing an action, send the user to the next one.
    Used by the "Next →" button on content/problem/writing/reflect
    pages so the flow keeps moving without a manual hop through Today.

    Recomputes the next action fresh — completions in the same request
    cycle (303 redirects from POST handlers) are already persisted by
    the time this runs."""
    uid = request.state.user_session.user_id
    settings = request.state.user_settings or {}
    scored = _build_session(uid)
    progress_by_id = content_repo.progress_for_user(uid)
    latest = assessment_repo.latest_completed(uid)
    scores, assessment_coverage = _assessment_snapshot(uid, latest)
    axis_ratings = content_repo.axis_ratings_for_user(uid)
    daily_reading = content_service.pick_daily(
        content_repo.all_by_kind("reading", user_id=uid), progress_by_id, scores, axis_ratings
    )
    daily_watch = (
        content_service.pick_daily(content_repo.all_by_kind("video", user_id=uid), progress_by_id, scores, axis_ratings)
        or content_service.pick_daily(content_repo.all_by_kind("podcast", user_id=uid), progress_by_id, scores, axis_ratings)
    )
    daily_exercise = content_service.pick_daily(
        content_repo.all_by_kind("exercise", user_id=uid), progress_by_id, scores, axis_ratings
    )
    nxt = _compute_next_action(
        uid,
        scored=scored,
        daily_reading=daily_reading,
        daily_watch=daily_watch,
        daily_exercise=daily_exercise,
        progress_by_id=progress_by_id,
        user_settings=settings,
    )
    # 303 to the next action's URL. Caught-up state goes back to Today
    # where the hero card explains "you're done."
    target_url = "/" if nxt.kind == "caught_up" else nxt.url
    return RedirectResponse(
        url=_daily_chain_redirect_url(url=target_url, kind=nxt.kind),
        status_code=303,
    )


def _track_content_context(request: Request, item):
    if not item.slug.startswith("track-") or item.source_kind != "authored":
        return None
    from fastapi import HTTPException

    refs = track_content.references_for_slug(_tracks_by_slug, item.slug)
    if not refs:
        # Keep retired catalog rows for saved feedback, but never expose a
        # curriculum that has been withdrawn from the learner-ready catalog.
        raise HTTPException(404, "This track resource is unavailable pending audit.")
    contexts = []
    settings = request.state.user_settings or {}
    uid = request.state.user_session.user_id
    for ref in refs:
        track, idx = ref.track, ref.section_idx
        status, state = _track_status_and_state(settings, track.slug, user_id=uid)
        passed = _track_checkpoint_passed_sections(state=state, track=track)
        satisfied = passed | _track_exemptions(track, settings, user_id=uid)
        missing = tracks_service.missing_prerequisites(track, idx, satisfied)
        preferred = state.get("preferred_section")
        if isinstance(preferred, (int, str)) and not isinstance(preferred, bool):
            try:
                preferred = int(preferred)
            except ValueError:
                preferred = None
        else:
            preferred = None
        primary_url = f"/content/{track_content.item_slug(track.slug, ref.section.url)}"
        check_url = f"/tracks/{track.slug}/sections/{idx}"
        contexts.append({
            "track": track, "section": ref.section, "idx": idx,
            "status": status, "unlocked": idx in satisfied or not missing,
            "missing_prerequisites": missing, "check_url": check_url,
            "primary_url": primary_url, "is_primary": ref.is_primary,
            "is_preferred": idx == preferred,
            "continue_url": check_url if ref.is_primary else primary_url,
            "continue_label": "Continue to practice check" if ref.is_primary else "Return to main resource",
            "session": state.get("session_per_section", {}).get(str(idx), {}),
            "resources": [
                {"title": r.title, "kind": r.kind,
                 "url": f"/content/{track_content.item_slug(track.slug, r.url)}"}
                for r in ref.section.resources if r.url != ref.section.url
            ],
        })
    # Shared resources should return to the learner's selected section, but
    # a locked selection must not hide an available reference or bypass a gate.
    return min(contexts, key=lambda c: (
        not c["unlocked"], not (c["unlocked"] and c["is_preferred"]), not c["is_primary"],
    ))


def _require_track_content_access(request: Request, item):
    context = _track_content_context(request, item)
    if context and not context["unlocked"]:
        from fastapi import HTTPException
        raise HTTPException(403, "Complete this resource's prerequisites first.")
    return context


@app.get("/content/{slug}", response_class=HTMLResponse)
def view_content(request: Request, slug: str):
    item = content_repo.get_by_slug(slug, user_id=request.state.user_session.user_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    track_context = _track_content_context(request, item)
    if track_context and not track_context["unlocked"]:
        return templates.TemplateResponse(request, "track_content_locked.html", {
            "item": item,
            "track_context": track_context, "config": config, "nav_section": "learn",
        })
    if item.kind == "exercise" and item.source_kind == "authored":
        gpu_required, colab_url = content_service.exercise_frontmatter(item.slug)
        item.gpu_required = gpu_required
        item.colab_url = colab_url
    uid = request.state.user_session.user_id
    progress = content_repo.progress_for_user(uid).get(item.id)
    # Cross-link: attempts that built on this content (axis-overlapping
    # attempts within 7 days of marking it complete).
    pid_to_p = {p.id: p for p in problem_repo.all_core() + problem_repo.all_warmups()}
    attempts_after = crosslink_service.attempts_following_content(
        content=item,
        progress=progress,
        attempts=attempt_repo.all_for_user(uid),
        problem_by_id=pid_to_p,
    )
    chain_step = _daily_chain_step(request, allowed_steps={1, 2, 3})

    # Ng multi-pass ladder — only for items that are actually papers. A
    # book chapter has no abstract and no figures, so the ladder would be
    # theatre on one.
    paper_state = (progress.paper_state if progress else {}) or {}
    is_paper = not track_context and paper_reading_service.is_paper(item.url, item.source, item.kind)
    return templates.TemplateResponse(
        request,
        "content.html",
        {
            "item": item,
            "track_context": track_context,
            "progress": progress,
            "attempts_after": attempts_after,
            "chain_step": chain_step,
            "config": config,
            "is_paper": is_paper,
            "paper_state": paper_state,
            "paper_passes": paper_reading_service.visible_passes(paper_state) if is_paper else [],
            "paper_answers": paper_state.get("answers") or {},
            "paper_verdicts": paper_reading_service.VERDICTS,
            "paper_deep_read": paper_reading_service.is_deep_read(paper_state),
            "dimensions": paper_reading_service.DIMENSIONS,
            "nav_section": "learn",
        },
    )


@app.post("/content/{content_id}/pass", response_class=HTMLResponse)
async def content_advance_pass(request: Request, content_id: int):
    """Record a completed pass, plus whatever the reader wrote during it.

    One POST carries both because they happen together: you finish the
    figures, you answer the two pass-1 prompts, you decide whether to go
    on. Answers are optional — a blank stays blank, and nothing counts
    them (BEN-135: no score, ever).

    Async because the answer fields are dynamic (`q_<question key>`), so
    they have to come off `request.form()` rather than a fixed Form
    signature — coupling the route to the question spine would mean
    editing a route every time a prompt is added. The DB work then goes
    through the threadpool, per BEN-153: sync repo calls must not run on
    the event loop.
    """
    import anyio

    form = await request.form()
    to_pass_raw = str(form.get("to_pass") or "0")
    verdict = str(form.get("verdict") or "")
    answers = {
        k[len("q_"):]: v
        for k, v in form.items()
        if k.startswith("q_") and isinstance(v, str)
    }
    try:
        to_pass = int(to_pass_raw)
    except ValueError:
        to_pass = 0
    if verdict and verdict not in paper_reading_service.VERDICTS:
        return HTMLResponse("Unknown verdict", status_code=400)

    uid = request.state.user_session.user_id

    def _persist() -> str | None:
        item = content_repo.get_by_id(content_id, user_id=uid)
        if item is None:
            return None
        if _require_track_content_access(request, item):
            from fastapi import HTTPException
            raise HTTPException(409, "Use the section practice check; the source text is not stored in Bench.")
        progress = content_repo.progress_for_user(uid).get(content_id)
        state = (progress.paper_state if progress else {}) or {}
        if answers:
            state = paper_reading_service.save_answers(state, answers)
        if to_pass:
            state = paper_reading_service.advance(state, to_pass)
        if verdict:
            state = paper_reading_service.set_verdict(state, verdict)
        content_repo.save_paper_state(uid, content_id, state)
        return item.slug

    slug = await anyio.to_thread.run_sync(_persist)
    if slug is None:
        return HTMLResponse("Not found", status_code=404)
    return RedirectResponse(url=f"/content/{slug}", status_code=303)


@app.get("/papers", response_class=HTMLResponse)
def papers_corpus(request: Request):
    """Ng's understanding-level table: every paper you have opened,
    against how far you actually got.

    The point of the table in the lecture is triage — it shows you the
    pile you skimmed and parked, so you can tell a corpus you have
    genuinely read from one you have merely collected. Counts of papers
    are facts; there is deliberately no percentage or completion score
    anywhere on this page."""
    uid = request.state.user_session.user_id
    progress_by_id = content_repo.progress_for_user(uid)
    rows = []
    for item in content_repo.all_by_kind("reading", user_id=uid):
        if item.source_kind == "authored" and item.slug.startswith("track-"):
            continue
        if not paper_reading_service.is_paper(item.url, item.source, item.kind):
            continue
        pr = progress_by_id.get(item.id)
        state = (pr.paper_state if pr else {}) or {}
        reached = paper_reading_service.current_pass(state)
        rows.append({
            "item": item,
            "pass": reached,
            "verdict": state.get("verdict") or "",
            "answered": len(paper_reading_service.answered_keys(state)),
            "deep": paper_reading_service.is_deep_read(state),
        })
    rows.sort(key=lambda r: (-r["pass"], r["item"].title.lower()))
    started = [r for r in rows if r["pass"] > 0]
    return templates.TemplateResponse(
        request,
        "papers.html",
        {
            "config": config,
            "rows": rows,
            "started_count": len(started),
            "deep_count": sum(1 for r in rows if r["deep"]),
            "parked_count": sum(1 for r in rows if r["verdict"] in ("park", "drop")),
            "dimensions": paper_reading_service.DIMENSIONS,
            "nav_section": "drill",
        },
    )


@app.post("/content/{content_id}/check", response_class=HTMLResponse)
def check_content(
    request: Request,
    content_id: int,
    undo: int = 0,
    next: int = Form(0),
    initiative_slug: str = Form(""),
):
    item = content_repo.get_by_id(content_id, user_id=request.state.user_session.user_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    _require_track_content_access(request, item)
    if undo:
        content_repo.mark_unread(request.state.user_session.user_id, content_id)
    else:
        try:
            resolved_initiative = initiative_picker.resolve_initiative_slug(
                settings=request.state.user_settings,
                form_override=initiative_slug,
            )
        except initiative_picker.UnknownInitiativeError as exc:
            return HTMLResponse(str(exc), status_code=400)
        content_repo.mark_completed(
            request.state.user_session.user_id,
            content_id,
            initiative_slug=resolved_initiative,
        )
    # When the form ships `next=1`, advance through /today/next so the
    # daily flow nudges to whatever's left. Otherwise stay on the page.
    if next and not undo:
        context = _track_content_context(request, item)
        return RedirectResponse(url=context["continue_url"] if context else "/today/next", status_code=303)
    return RedirectResponse(url=f"/content/{item.slug}", status_code=303)


@app.post("/content/{content_id}/favorite", response_class=HTMLResponse)
def toggle_favorite(request: Request, content_id: int):
    item = content_repo.get_by_id(content_id, user_id=request.state.user_session.user_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    _require_track_content_access(request, item)
    content_repo.toggle_favorite(request.state.user_session.user_id, content_id)
    return RedirectResponse(url=f"/content/{item.slug}", status_code=303)


@app.post("/content/{content_id}/rate", response_class=HTMLResponse)
def rate_content(request: Request, content_id: int, rating: int = Form(...)):
    item = content_repo.get_by_id(content_id, user_id=request.state.user_session.user_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    _require_track_content_access(request, item)
    if rating == 0:
        content_repo.set_rating(request.state.user_session.user_id, content_id, None)
    else:
        content_repo.set_rating(request.state.user_session.user_id, content_id, max(1, min(5, rating)))
    return RedirectResponse(url=f"/content/{item.slug}", status_code=303)


@app.post("/content/{content_id}/reflect", response_class=HTMLResponse)
def reflect_content(request: Request, content_id: int, notes_md: str = Form("")):
    item = content_repo.get_by_id(content_id, user_id=request.state.user_session.user_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    _require_track_content_access(request, item)
    content_repo.save_reflection(request.state.user_session.user_id, content_id, notes_md)
    return RedirectResponse(url=f"/content/{item.slug}", status_code=303)


@app.get("/content/{content_id}/audio.json", response_class=JSONResponse)
def content_audio_manifest(request: Request, content_id: int):
    """BEN-135 audio-out: render (cache-aware) the item's text to a chunked
    playlist. `{"available": false}` when TTS has no key — the UI hides the
    player. Auth is enforced by the session middleware (unauth → /login);
    audio itself is owner-scoped at the chunk serve route below."""
    from .services import tts as tts_service

    uid = request.state.user_session.user_id
    item = content_repo.get_by_id(content_id, user_id=uid)
    if item is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if _require_track_content_access(request, item) or not item.content_md:
        return JSONResponse({"available": False})
    m = tts_service.manifest(
        content_repo,
        user_id=uid,
        content_id=content_id,
        version=item.version,
        text=item.content_md,
    )
    return JSONResponse(m or {"available": False})


@app.get("/content/{content_id}/audio/{chunk_ix}")
def content_audio_chunk(request: Request, content_id: int, chunk_ix: int):
    """Serve one cached audio chunk. OWNER-ONLY: the cache read filters
    WHERE user_id = <requester>, so audio for content the operator owns is
    never reachable by another user (they get 404), never anonymously (the
    session middleware bounces unauth to /login before this runs), and never
    from a public bucket. Private cache headers keep it out of shared caches."""
    from fastapi.responses import Response
    from .services import tts as tts_service

    uid = request.state.user_session.user_id
    item = content_repo.get_by_id(content_id, user_id=uid)
    if item is None:
        return HTMLResponse("not found", status_code=404)
    if _require_track_content_access(request, item):
        return HTMLResponse("Audio unavailable for an external track source.", status_code=404)
    key = tts_service.cache_key(
        content_id, item.version, tts_service.DEFAULT_VOICE, chunk_ix
    )
    row = content_repo.get_tts_chunk(uid, key)
    if row is None:
        return HTMLResponse("not found", status_code=404)
    return Response(
        content=bytes(row["audio"]),
        media_type=row["mime"],
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/content/{content_id}/recite")
async def recite_content(
    request: Request,
    content_id: int,
    audio: UploadFile = File(...),
    mode: str = Form("review"),
):
    """BEN-135 recite-and-grade: transcribe the spoken explanation, grade it
    against the source (NO score — see recitation.py), and fold the result
    into the successive-relearning schedule. A missed concept's only
    consequence is that it returns sooner. ``mode`` = "review" | "pretest"."""
    from datetime import datetime, timezone

    from .services import recitation, recitation_schedule
    from .services import transcription as tx

    uid = request.state.user_session.user_id
    item = content_repo.get_by_id(content_id, user_id=uid)
    if item is None or not item.content_md:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if _require_track_content_access(request, item):
        return JSONResponse({"error": "external_source", "detail": "Use the section practice check; the source text is not stored in Bench."}, status_code=409)
    mode = "pretest" if mode == "pretest" else "review"

    try:
        audio_bytes = await audio.read()
        result = tx.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "recite.webm",
            content_type=audio.content_type or "audio/webm",
        )
    except tx.TranscriptionError as e:
        return JSONResponse(
            {"error": "transcribe_failed", "detail": str(e)}, status_code=502
        )
    transcript = (result.get("text") or "").strip()

    graded = recitation.grade(item.content_md, transcript, mode=mode, user_id=uid)

    # Fold into the schedule: covered advance, missing reset to +1 (pretest =
    # baseline, no penalty). This is the ONLY consequence of a miss.
    progress = content_repo.progress_for_user(uid).get(content_id)
    prior_state = progress.recitation_state if progress else {}
    now = datetime.now(timezone.utc)
    new_state = recitation_schedule.apply_grade(
        prior_state,
        covered=graded.get("covered", []),
        missing=[m["concept"] for m in graded.get("missing", []) if m.get("concept")],
        now=now,
        pretest=(mode == "pretest"),
    )
    content_repo.save_recitation_state(uid, content_id, new_state)

    # Response carries the named gaps + scheduling DATA only — never a score.
    # The template turns `scheduled` into "N concepts return <day>".
    return JSONResponse({
        "mode": mode,
        "transcript": transcript,
        "method": graded.get("method"),
        "covered": graded.get("covered", []),
        "missing": graded.get("missing", []),
        "misstated": graded.get("misstated", []),
        "open_question": graded.get("open_question"),
        "error_text": graded.get("error_text"),
        "scheduled": len(new_state),
    })


@app.get("/attempt/{attempt_id}/review", response_class=HTMLResponse)
def view_attempt_review(request: Request, attempt_id: int):
    uid = request.state.user_session.user_id
    attempts = [a for a in attempt_repo.all_for_user(uid) if a.id == attempt_id]
    if not attempts:
        return HTMLResponse("Not found", status_code=404)
    a = attempts[0]
    p = problem_repo.get_by_id(a.problem_id)
    review = attempt_review_repo.latest_for_attempt(attempt_id)
    # Cross-link: content the user engaged with in the 7 days before
    # this attempt, intersected on skill axes.
    progress_by_id = content_repo.progress_for_user(uid)
    content_by_id = {cid: content_repo.get_by_id(cid, user_id=uid) for cid in progress_by_id}
    content_before = crosslink_service.content_before_attempt(
        attempt=a,
        problem=p,
        progress_by_id=progress_by_id,
        content_by_id={k: v for k, v in content_by_id.items() if v is not None},
    )
    # Interview-mode v1 — compose the per-phase time-vs-budget
    # breakdown. Falls back to default budgets if the attempt
    # predates migration 014 (no snapshotted budgets on the row);
    # returns empty if there's no per-phase time either. The
    # template knows to hide the section on empty.
    from .services import phase_budget as _phase_budget
    budgets_for_review = a.phase_budgets or (
        _phase_budget.default_budgets(p.time_bucket, p.problem_type)
        if p else {}
    )
    phase_breakdown = _phase_budget.compose_review_breakdown(
        a.time_per_phase, budgets_for_review
    )
    return templates.TemplateResponse(
        request,
        "attempt_review.html",
        {
            "problem": p,
            "attempt": a,
            "review": review,
            "content_before": content_before,
            "config": config,
            "nav_section": "drill",
            "phase_breakdown": phase_breakdown,
            "phase_budget_fmt": _phase_budget.fmt_seconds,
        },
    )


@app.get("/journal/{date}", response_class=HTMLResponse)
def journal_page(request: Request, date: str):
    uid = request.state.user_session.user_id
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return HTMLResponse("Bad date format. Use YYYY-MM-DD.", status_code=400)
    today = datetime.now().date()
    if target == today:
        return RedirectResponse(url="/", status_code=303)

    # Attempts that started on `target`
    day_start = datetime.combine(target, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    all_attempts = attempt_repo.all_for_user(uid)
    day_attempts = [
        a for a in all_attempts
        if a.started_at >= day_start and a.started_at < day_end
    ]
    # Attach problems
    day_attempts_with_p = []
    for a in day_attempts:
        p = problem_repo.get_by_id(a.problem_id)
        if p:
            day_attempts_with_p.append((a, p))

    # Content marked complete on `target`
    progress = content_repo.progress_for_user(uid)
    day_content = []
    for cid, pr in progress.items():
        if pr.status != "completed" or pr.checked_at is None:
            continue
        if pr.checked_at.date() != target:
            continue
        item = content_repo.get_by_id(cid, user_id=uid)
        if item:
            day_content.append((item, pr))

    # Feedback left on `target`
    fb_items = feedback_repo.list_for_user(uid, limit=500)
    day_feedback = [f for f in fb_items if f.created_at.date() == target]

    prev_day = target - timedelta(days=1)
    next_day = target + timedelta(days=1)
    next_is_today = (next_day == today)

    return templates.TemplateResponse(
        request,
        "journal.html",
        {
            "config": config,
            "target": target,
            "today_date": target.strftime("%A, %B %d, %Y"),
            "prev_url": f"/journal/{prev_day.isoformat()}",
            "next_url": "/" if next_is_today else f"/journal/{next_day.isoformat()}",
            "next_is_today": next_is_today,
            "day_attempts": day_attempts_with_p,
            "day_content": day_content,
            "day_feedback": day_feedback,
            "nav_section": "drill",
        },
    )


@app.get("/skills", response_class=HTMLResponse)
def skills_page(request: Request):
    # Legacy route kept for transition; canonical surface is /aim.
    return RedirectResponse(url="/aim#stand", status_code=302)


@app.get("/aim", response_class=HTMLResponse)
def aim_page(request: Request):
    import time as _t
    _aim_debug = os.environ.get("AIM_DEBUG") == "1"
    _steps: list[tuple[str, float]] = []
    _t0 = _t.perf_counter()

    def _mark(label: str) -> None:
        if _aim_debug:
            _steps.append((label, _t.perf_counter() - _t0))

    uid = request.state.user_session.user_id
    user_settings = request.state.user_settings or {}
    tz_name = _display_tz_from_settings(user_settings)
    _mark("settings+tz")

    latest_skill_run = assessment_repo.latest_completed(uid)
    skill_scores, assessment_coverage = _assessment_snapshot(uid, latest_skill_run)
    axis_to_chart = {
        axis: stat.key for stat in skill_stats.STATS for axis in stat.axes
    }
    _mark("latest_skill_run")

    suggestion = (
        _suggested_problem_for_scores(uid, skill_scores)
        if latest_skill_run else None
    )
    _mark("suggestion")

    jds_list = jd_repo.list_for_user(uid)
    _mark("jds_list")
    active_jd = _active_jd(uid)
    _mark("active_jd")
    reflections = reflection_repo.list_for_user(uid, limit=120)
    _mark(f"reflections({len(reflections)})")
    calibration_chart = _build_calibration_chart_data(reflections, tz_name=tz_name)
    _mark(f"calibration_chart({len(calibration_chart.get('points', []))} pts)")
    credential_runs = _credential_runs_for_aim(uid, limit=10)
    _mark(f"credential_runs({len(credential_runs)})")

    if _aim_debug:
        total_ms = (_t.perf_counter() - _t0) * 1000
        breakdown = " | ".join(f"{label}={dt * 1000:.0f}ms" for label, dt in _steps)
        print(f"[/aim debug] uid={uid} total={total_ms:.0f}ms steps: {breakdown}", flush=True)
    signal_value = user_settings.get("imposter_signal")
    imposter_signal = signal_value if isinstance(signal_value, dict) else None

    latest_credential_run = credential_runs[0] if credential_runs else None
    evidence = {
        "top_credential_axes": (
            list(latest_credential_run.get("top_axis_keys") or [])
            if latest_credential_run is not None
            else []
        ),
        "triggering_axes": (
            list(imposter_signal.get("triggering_axes") or [])
            if isinstance(imposter_signal, dict)
            else []
        ),
        "latest_credential_run_id": (
            latest_credential_run.get("id") if latest_credential_run is not None else None
        ),
    }

    return templates.TemplateResponse(
        request,
        "aim.html",
        {
            "config": config,
            "latest_skill_run": latest_skill_run,
            "skill_scores": skill_scores,
            "assessment_coverage": assessment_coverage,
            "axis_labels": assess_service.AXIS_LABELS,
            "axis_to_chart": axis_to_chart,
            "suggestion": suggestion,
            "jds": jds_list,
            "active_jd": active_jd,
            "calibration_chart": calibration_chart,
            "credential_runs": credential_runs,
            "imposter_signal": imposter_signal,
            "evidence": evidence,
            "nav_section": "aim",
        },
    )


@app.get("/signal", response_class=HTMLResponse)
def signal_page(request: Request, track: str = "all"):
    """The evidence half of readiness.

    `/readiness` answers "can I do the work". This answers the question
    a selection process actually reads: is there anything a stranger
    can look at that shows it — and what happened when I applied.

    Deliberately not a score. The thread that motivated this surface
    had someone at 14 rejections being told to do things they had
    already done; another point on it that a fellowship gives one bit
    of feedback, months late. A number here would be one more bit. The
    page shows the artifacts, the strength you assigned each one, and
    where applications actually died.
    """
    uid = request.state.user_session.user_id

    track_filter = track if track in ("technical", "governance", "all") else "all"
    all_c = criteria_service.all_criteria()
    shown = tuple(
        c for c in all_c
        if track_filter == "all" or c.track in (track_filter, "all")
    )

    try:
        artifacts = evidence_repo.by_criterion(uid)
    except Exception:  # noqa: BLE001 — the page must render on a cold DB
        artifacts = {}
    statuses = criteria_service.status_for(shown, artifacts)

    try:
        opps = opportunity_repo.list_for_user(uid)
        stats = opportunity_repo.outcome_stats(uid)
    except Exception:  # noqa: BLE001
        opps, stats = [], {"total": 0, "by_stage": {}, "rejected_late": 0}

    return templates.TemplateResponse(
        request,
        "signal.html",
        {
            "config": config,
            "statuses": statuses,
            "coverage": criteria_service.coverage(statuses),
            "next_actions": criteria_service.next_actions(statuses),
            "opportunities": opps,
            "opp_stats": stats,
            "stages": ["watching", "selected", "drafting", "submitted",
                       "interview", "decision", "closed"],
            "kinds": ["fellowship", "grant", "job", "program", "workshop"],
            "strengths": ["weak", "partial", "strong"],
            "track_filter": track_filter,
            "bubbles": _bubbles_for(request, "signal"),
            "nav_section": "signal",
        },
    )


@app.get("/signal/criterion/{slug}", response_class=HTMLResponse)
def signal_criterion(request: Request, slug: str):
    """One criterion in full — including what WEAK looks like, which is
    the section that does the work."""
    criterion = criteria_service.get(slug)
    if criterion is None:
        return HTMLResponse("Not found", status_code=404)
    uid = request.state.user_session.user_id
    try:
        rows = evidence_repo.by_criterion(uid).get(slug, [])
    except Exception:  # noqa: BLE001
        rows = []
    return templates.TemplateResponse(
        request,
        "signal_criterion.html",
        {
            "config": config,
            "criterion": criterion,
            "artifacts": rows,
            "strengths": ["weak", "partial", "strong"],
            "nav_section": "signal",
        },
    )


@app.post("/signal/evidence", response_class=HTMLResponse)
def signal_add_evidence(
    request: Request,
    criterion: str = Form(""),
    title: str = Form(""),
    url: str = Form(""),
    claim_md: str = Form(""),
    strength: str = Form("unrated"),
):
    uid = request.state.user_session.user_id
    slug = (criterion or "").strip()
    if criteria_service.get(slug) is None:
        return HTMLResponse("Unknown criterion", status_code=400)
    name = (title or "").strip()[:300]
    if not name:
        return HTMLResponse("A title is required", status_code=400)
    if strength not in criteria_service.STRENGTHS:
        strength = "unrated"
    evidence_repo.add(
        uid,
        criterion=slug,
        title=name,
        url=(url or "").strip()[:500] or None,
        claim_md=(claim_md or "").strip()[:2000] or None,
        strength=strength,
    )
    return RedirectResponse(url=f"/signal/criterion/{slug}", status_code=303)


@app.post("/signal/evidence/{artifact_id}/strength", response_class=HTMLResponse)
def signal_rate_evidence(
    request: Request,
    artifact_id: str,
    strength: str = Form("unrated"),
    criterion: str = Form(""),
):
    uid = request.state.user_session.user_id
    if strength not in criteria_service.STRENGTHS:
        return HTMLResponse("Bad strength", status_code=400)
    evidence_repo.set_strength(uid, artifact_id, strength)
    slug = (criterion or "").strip()
    dest = f"/signal/criterion/{slug}" if criteria_service.get(slug) else "/signal"
    return RedirectResponse(url=dest, status_code=303)


@app.post("/signal/evidence/{artifact_id}/delete", response_class=HTMLResponse)
def signal_delete_evidence(request: Request, artifact_id: str, criterion: str = Form("")):
    uid = request.state.user_session.user_id
    evidence_repo.delete(uid, artifact_id)
    slug = (criterion or "").strip()
    dest = f"/signal/criterion/{slug}" if criteria_service.get(slug) else "/signal"
    return RedirectResponse(url=dest, status_code=303)


@app.post("/signal/opportunity", response_class=HTMLResponse)
def signal_add_opportunity(
    request: Request,
    kind: str = Form("fellowship"),
    org: str = Form(""),
    title: str = Form(""),
    url: str = Form(""),
    location: str = Form(""),
    deadline: str = Form(""),
    stage: str = Form("watching"),
):
    from .repositories.signal_repository import KINDS, STAGES

    uid = request.state.user_session.user_id
    if kind not in KINDS or stage not in STAGES:
        return HTMLResponse("Bad kind or stage", status_code=400)
    org_s, title_s = (org or "").strip()[:200], (title or "").strip()[:300]
    if not org_s or not title_s:
        return HTMLResponse("Org and title are required", status_code=400)
    parsed_deadline = None
    raw = (deadline or "").strip()
    if raw:
        try:
            parsed_deadline = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return HTMLResponse("Deadline must be YYYY-MM-DD", status_code=400)
    opportunity_repo.add(
        uid,
        kind=kind,
        org=org_s,
        title=title_s,
        url=(url or "").strip()[:500] or None,
        location=(location or "").strip()[:200] or "unspecified",
        deadline=parsed_deadline,
        stage=stage,
    )
    return RedirectResponse(url="/signal", status_code=303)


@app.post("/signal/opportunity/{opp_id}/advance", response_class=HTMLResponse)
def signal_advance_opportunity(
    request: Request,
    opp_id: str,
    stage: str = Form(""),
    outcome: str = Form(""),
    feedback_md: str = Form(""),
):
    """Move an application along and KEEP what came back with it.

    Feedback appends rather than overwrites: the one durable artifact
    of a rejection is what the reviewer said, and it is worth more when
    you can read six of them side by side."""
    from .repositories.signal_repository import STAGES

    uid = request.state.user_session.user_id
    if stage not in STAGES:
        return HTMLResponse("Bad stage", status_code=400)
    opportunity_repo.advance(
        uid,
        opp_id,
        stage=stage,
        outcome=(outcome or "").strip()[:100] or None,
        feedback_md=(feedback_md or "").strip()[:4000] or None,
    )
    return RedirectResponse(url="/signal", status_code=303)


@app.get("/focus", response_class=HTMLResponse)
def focus_page(request: Request, show_unassigned: int = 0):
    """Cross-surface priority dashboard (BEN-80).

    "What am I working on, by priority" — joins bench-side activity
    with each initiative's linked GitHub repos (open PRs) and (later,
    BEN-81) Linear tickets. The surface the operator opens when they
    don't know what they were doing yesterday.

    Service composes the view; this route is just the assembly. Single
    fetch of attempts / reflections / content progress so the page
    isn't N+1 round-trip-bound.

    The ``show_unassigned`` query param (``/focus?show_unassigned=1``)
    surfaces the Unassigned bucket — activity whose initiative_slug is
    NULL (pre-tagging legacy or operator-explicit unassigned) or
    pointing at a now-closed initiative. Hidden by default to keep the
    primary dashboard clean.
    """
    uid = request.state.user_session.user_id
    settings = request.state.user_settings or {}

    attempts = attempt_repo.all_for_user(uid)
    reflections = reflection_repo.list_for_user(uid, limit=200)
    content_progress = content_repo.progress_for_user(uid)

    view = focus_service.compute_focus_view(
        user_id=uid,
        settings=settings,
        attempts=attempts,
        reflections=reflections,
        content_progress=content_progress,
        chat_outcomes_repo=chat_outcomes_repo,
        show_unassigned=bool(show_unassigned),
        # /focus route opts in to the audit-trail "closed" bucket; MCP
        # / legacy callers stay opted out so their view shape is
        # unchanged. The bucket renders as a collapsed <details>
        # section under the Active/Dormant ones.
        include_closed=True,
    )

    return templates.TemplateResponse(
        request,
        "focus.html",
        {
            "config": config,
            "view": view,
            "nav_section": "focus",
        },
    )


# ---------------------------------------------------------------------------
# /connecting — bi-directional networking tracker with warmth-decay scoring
# (WS6 / BEN-94, 2026-05-28). New surface for tracking contacts and the
# touchpoints with them; coldest contacts surface first so the operator
# knows who's overdue. See app/services/connecting.py for the warmth math
# and migrations_pg/013_contacts.sql for the schema.
# ---------------------------------------------------------------------------

@app.get("/connecting", response_class=HTMLResponse)
def connecting_index(request: Request, show_archived: int = 0):
    """List view. All contacts for the user, sorted coldest-first so
    the overdue ones are at the top of the page. Single round-trip for
    contacts + one DISTINCT ON for per-contact latest interaction; the
    service composes the warmth scores in memory."""
    uid = request.state.user_session.user_id
    contacts = contacts_repo.list_for_user(
        uid, include_archived=bool(show_archived)
    )
    latest_by_contact = contacts_repo.latest_interaction_by_contact(uid)
    view = connecting_service.compose_view(
        contacts=contacts,
        latest_by_contact=latest_by_contact,
        now=datetime.utcnow(),
    )
    return templates.TemplateResponse(
        request,
        "connecting.html",
        {
            "config": config,
            "view": view,
            "show_archived": bool(show_archived),
            "nav_section": "connecting",
            "days_since_phrase": connecting_service.days_since_phrase,
        },
    )


@app.post("/connecting")
def connecting_create(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    handle: str = Form(""),
    context: str = Form(""),
    cadence_days: int = Form(30),
):
    """Add a contact. After save the operator lands on the detail page
    so they can log the first interaction immediately (the "I just
    talked to this person, capture it" flow)."""
    uid = request.state.user_session.user_id
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        return RedirectResponse(url="/connecting", status_code=303)
    # Cadence clamp: schema CHECK enforces 1..3650 but we also clamp
    # here so a bad form submission gets a sensible default instead of
    # an IntegrityError page.
    cadence = max(1, min(3650, int(cadence_days or 30)))
    contact = contacts_repo.create(
        user_id=uid,
        name=cleaned_name,
        email=email,
        handle=handle,
        context=context,
        cadence_days=cadence,
    )
    return RedirectResponse(url=f"/connecting/{contact.id}", status_code=303)


@app.get("/connecting/{contact_id}", response_class=HTMLResponse)
def connecting_detail(request: Request, contact_id: int):
    """Per-contact view: details + interaction history + add-interaction
    form. 404 when the contact doesn't exist or belongs to another user
    (the repo's user_id gate handles the latter)."""
    uid = request.state.user_session.user_id
    contact = contacts_repo.get(contact_id, user_id=uid)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    interactions = contacts_repo.list_interactions_for_contact(
        contact_id, user_id=uid
    )
    # History includes notes and is capped; query actual touchpoints separately
    # so the detail badge agrees with the list even after many private notes.
    latest = contacts_repo.latest_interaction_for_contact(contact_id, user_id=uid)
    warmth, tier, days_since = connecting_service.compute_warmth(
        latest=latest,
        cadence_days=contact.cadence_days,
        now=datetime.utcnow(),
    )
    return templates.TemplateResponse(
        request,
        "connecting_detail.html",
        {
            "config": config,
            "contact": contact,
            "interactions": interactions,
            "warmth": warmth,
            "tier": tier,
            "days_since": days_since,
            "days_since_label": connecting_service.days_since_phrase(days_since),
            "nav_section": "connecting",
        },
    )


@app.post("/connecting/{contact_id}/interactions")
def connecting_log_interaction(
    request: Request,
    contact_id: int,
    kind: str = Form(...),
    direction: str = Form(""),
    occurred_at: str = Form(""),  # ISO date from <input type="date">
    notes: str = Form(""),
):
    """Append one interaction. Direction is optional ('' from the form
    means "leave NULL"); kind is required and validated against the
    repo's known vocab (which raises a ValueError → 422 if a bad
    value is submitted)."""
    uid = request.state.user_session.user_id
    contact = contacts_repo.get(contact_id, user_id=uid)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")

    # Parse occurred_at — accept "YYYY-MM-DD" from <input type="date">
    # or fall back to "now" if blank.
    if occurred_at:
        try:
            when = datetime.strptime(occurred_at, "%Y-%m-%d")
        except ValueError:
            when = datetime.utcnow()
    else:
        when = datetime.utcnow()

    kind = kind.strip()
    # These kinds already specify direction; the optional selector must
    # not contradict them or silently disable reply tracking.
    direction_val = {"received": "inbound", "sent": "outbound"}.get(kind, (direction or "").strip() or None)
    try:
        contacts_repo.add_interaction(
            contact_id=contact_id,
            user_id=uid,
            occurred_at=when,
            kind=kind.strip(),
            direction=direction_val,
            notes=notes,
        )
    except ValueError:
        # Bad kind / direction — bounce back to the detail page; in
        # practice the form is a constrained <select> so this is a
        # defense-in-depth path, not a UX one.
        raise HTTPException(status_code=422, detail="invalid kind or direction")
    return RedirectResponse(url=f"/connecting/{contact_id}", status_code=303)


@app.post("/connecting/{contact_id}/archive")
def connecting_archive(request: Request, contact_id: int):
    """Soft-delete. Preserves history; archived contacts are hidden from
    the default list view but reachable via ?show_archived=1."""
    uid = request.state.user_session.user_id
    contacts_repo.set_archived(contact_id, user_id=uid, archived=True)
    return RedirectResponse(url="/connecting", status_code=303)


@app.post("/connecting/{contact_id}/reopen")
def connecting_reopen(request: Request, contact_id: int):
    """Inverse of archive — un-archive a contact."""
    uid = request.state.user_session.user_id
    contacts_repo.set_archived(contact_id, user_id=uid, archived=False)
    return RedirectResponse(url=f"/connecting/{contact_id}", status_code=303)


@app.get("/news", response_class=HTMLResponse)
def news_index(
    request: Request,
    source: str = "",
    show_dismissed: int = 0,
):
    """RSS news index (rss-news-feed Phase 1).

    Lists ingested items newest-first, pinned-first. Optional
    ``?source=<slug>`` filter for one feed. ``?show_dismissed=1``
    reveals items previously dismissed.

    Phase 2 will add an ``?axis=<axis>`` filter (read against
    ``axes_json``); the column exists today (migration 012) but isn't
    populated until the LLM-tagger ships.
    """
    items = news_repo.list_recent(
        limit=100,
        source=source.strip() or None,
        include_dismissed=bool(show_dismissed),
    )
    sources_present = news_repo.list_sources_present()

    # Load the feed registry so the UI can render display names for
    # source chips. Slug → name mapping; falls through to slug-as-label
    # when a slug doesn't have a registry entry (e.g., feed was deleted
    # but items remain).
    from .services import news_poller as news_poller_service

    feeds = news_poller_service.load_feeds_from_toml(
        REPO_ROOT / "content" / "news_feeds.toml"
    )
    feed_names = {f.slug: f.name for f in feeds}

    return templates.TemplateResponse(
        request,
        "news.html",
        {
            "config": config,
            "items": items,
            "sources_present": sources_present,
            "feed_names": feed_names,
            "selected_source": source.strip(),
            "show_dismissed": bool(show_dismissed),
            "nav_section": "news",
        },
    )


@app.post("/news/{item_id}/pin", response_class=HTMLResponse)
def news_pin(request: Request, item_id: int, unpin: int = Form(0)):
    """Toggle an item's pin state. ``unpin=1`` clears the pin."""
    item = news_repo.get(item_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    news_repo.set_pinned(item_id, not bool(unpin))
    return RedirectResponse(url="/news", status_code=303)


@app.post("/news/{item_id}/dismiss", response_class=HTMLResponse)
def news_dismiss(request: Request, item_id: int, undismiss: int = Form(0)):
    """Toggle an item's dismissed state. ``undismiss=1`` restores it."""
    item = news_repo.get(item_id)
    if item is None:
        return HTMLResponse("Not found", status_code=404)
    news_repo.set_dismissed(item_id, not bool(undismiss))
    return RedirectResponse(url="/news", status_code=303)


@app.get("/decisions", response_class=HTMLResponse)
def decisions_index(request: Request, initiative: str = ""):
    """Chat-outcome log read surface (BEN-82, #212).

    Reads what the MCP server's ``log_chat_outcome`` tool wrote to
    ``user_settings.chat_outcomes``. Reverse-chronological. Optional
    ``?initiative=<slug>`` filter. Single page; v1 doesn't paginate
    because the list self-caps at 200 entries in the MCP storage layer.

    Mounted at /decisions (not /journal as the original BEN-82 spec
    requested) because /journal/{date} already exists as the daily
    attempts-review page. Nav label matches the URL for clarity.

    Out of scope for v1 (per the issue spec): no manual entry form
    (chat is the input surface), no edit/delete (append-only log), no
    search beyond the initiative filter.
    """
    from .services import journal as journal_service

    uid = request.state.user_session.user_id
    selected = initiative.strip() or None
    entries = journal_service.list_entries(
        chat_outcomes_repo, uid, initiative=selected, limit=200,
    )
    facets = journal_service.initiatives_with_counts(chat_outcomes_repo, uid)
    total = sum(count for _, count in facets)

    return templates.TemplateResponse(
        request,
        "decisions_index.html",
        {
            "config": config,
            "entries": entries,
            "facets": facets,
            "total": total,
            "selected": selected,
            "nav_section": "decisions",
        },
    )


@app.get("/decisions/{entry_id}", response_class=HTMLResponse)
def decisions_show(request: Request, entry_id: str):
    """Single-entry permalink. Lets /focus link straight to 'last
    decided on capstone' from the dashboard once that integration lands.
    """
    from .services import journal as journal_service

    uid = request.state.user_session.user_id
    entry = journal_service.get_entry(chat_outcomes_repo, uid, entry_id)
    if entry is None:
        return HTMLResponse("Decision entry not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "decisions_entry.html",
        {
            "config": config,
            "entry": entry,
            "nav_section": "decisions",
        },
    )


@app.get("/readiness", response_class=HTMLResponse)
def readiness_page(request: Request):
    """Readiness timeline evaluation.

    Pulls the user's latest assessment scores + their active JD's
    axis_weights and shows the gap analysis + projected time to
    readiness at different weekly intensities. The math lives in
    app/services/readiness.py — this route is just the assembly.

    If the user lacks either an assessment or an active JD with
    weighted axes, the page renders a "complete this first" state
    rather than a misleading 0%.
    """
    uid = request.state.user_session.user_id
    settings = request.state.user_settings or {}
    latest = assessment_repo.latest_completed(uid)
    scores, assessment_coverage = _assessment_snapshot(uid, latest)
    active_jd = _active_jd(uid, settings=settings)

    # Snapshot for the active JD.
    primary = readiness_service.compute(
        user_scores=scores,
        jd_axis_weights=(active_jd.axis_weights if active_jd else None),
        axes=assess_service.AXES,
    )
    primary_snapshot = readiness_service.snapshot_for_template(
        primary, assess_service.AXIS_LABELS,
    )

    # Comparison snapshots for the user's other (non-archived) JDs.
    # Cheap — the math is in-memory dictionary work on data we already
    # have. Lets the user eyeball "is this role the easiest fit, or
    # would Apollo be a faster path?"
    other_jds = []
    if active_jd is not None:
        for jd in jd_repo.list_for_user(uid):
            if jd.id == active_jd.id or jd.archived_at is not None:
                continue
            r = readiness_service.compute(
                user_scores=scores,
                jd_axis_weights=jd.axis_weights,
                axes=assess_service.AXES,
            )
            if r.has_data:
                other_jds.append({
                    "id": jd.id,
                    "title": jd.title,
                    "org": jd.org,
                    "readiness_pct_rounded": round(r.readiness_pct),
                    "total_hours_rounded": round(r.total_hours_needed),
                    "unknown_axes_count": len(r.unknown_axes),
                    "measured_axes_count": len(r.gaps),
                })
        other_jds.sort(key=lambda d: d["readiness_pct_rounded"], reverse=True)

    return templates.TemplateResponse(
        request,
        "readiness.html",
        {
            "config": config,
            "nav_section": "aim",
            "primary": primary_snapshot,
            "assessment_coverage": assessment_coverage,
            "axis_labels": assess_service.AXIS_LABELS,
            "active_jd": active_jd,
            "other_jds": other_jds,
            "has_assessment": latest is not None,
            "has_weighted_jd": bool(active_jd and any(float(active_jd.axis_weights.get(axis, 0)) > 0 for axis in assess_service.AXES)),
        },
    )


# Voices that are NOT offered as the code-review / reflect persona. Mira is a
# standalone research mentor with its own /mira surface and full system prompt;
# it lives in the voices registry (the single source of truth for the persona)
# but must never appear in the review-voice picker or be settable as the review
# default. Enforced here at the presentation layer so the registry in
# app/services/voices.py (CODEOWNERS-protected) stays untouched.
#
# "mats-empirical-drill" is the same shape: a full chat persona (a timed
# MATS Stage-2 drill partner) driven through a chat surface, not a review
# emphasis overlay. Exclude it from the review picker for the same reason.
_NON_REVIEW_VOICE_KEYS = frozenset({"mira", "mats-empirical-drill"})


def _review_voices():
    """The voices selectable as a code-review / reflect persona — every
    registry voice except the mentor-only ones (see _NON_REVIEW_VOICE_KEYS)."""
    from .services import voices as voices_service

    return [v for v in voices_service.all_voices() if v.key not in _NON_REVIEW_VOICE_KEYS]


@app.get("/voices", response_class=HTMLResponse)
def voices_page(request: Request):
    """Browse the mentor-voice roster. Lets the user scan all voices
    + their lenses + provocations before picking a default. Defaults
    are settable here via POST to /voices/prefer."""
    settings = request.state.user_settings or {}
    return templates.TemplateResponse(
        request,
        "voices.html",
        {
            "config": config,
            "voices": _review_voices(),
            "preferred_voice": settings.get("preferred_voice") or "default",
            "nav_section": "settings",
        },
    )


@app.post("/voices/prefer", response_class=HTMLResponse)
def voices_prefer(request: Request, voice_key: str = Form(...)):
    """Set the user's default review voice. Validates against the
    registry so the form can't poison settings with an unknown key."""
    from .services import voices as voices_service
    uid = request.state.user_session.user_id
    # Reject unknown keys and mentor-only voices (Mira isn't a review persona).
    if voice_key not in voices_service.valid_keys() or voice_key in _NON_REVIEW_VOICE_KEYS:
        return RedirectResponse(url="/voices?error=unknown", status_code=303)
    settings = _user_settings(uid)
    settings["preferred_voice"] = voice_key
    _save_user_settings(uid, settings)
    return RedirectResponse(url="/voices", status_code=303)


# ── MIRA — research-mentor chat surface (Phase 1a) ──────────────────────────
#
# MIRA is the *LLM-with-a-harness* surface (the inverse of Brain). Phase 1a is
# the chat loop only: no RAG, no tools. The agent loop lives in
# app/services/mira.py; these routes are the HTTP assembly + the SSE transport.


def _mira_coach_context(settings: dict, *, user_id=None, track: str = "", section: int = -1, problem: str = "") -> dict:
    if problem:
        item = problem_repo.get_by_slug(problem)
        if item is not None:
            return {"kind": "problem", "slug": item.slug}
        return {}
    if not track:
        active = settings.get("active_track")
        if isinstance(active, dict):
            track = str(active.get("slug") or "")
            curriculum = get_track(track) if tracks_service.is_available_track(track) else None
            if curriculum is not None:
                state = _normalized_track_state(active, slug=track, settings=settings, user_id=user_id)
                passed = _track_checkpoint_passed_sections(state=state, track=curriculum)
                chosen = tracks_service.next_section_index(curriculum, passed | _track_exemptions(curriculum, settings, user_id=user_id), state.get("preferred_section"))
                section = chosen if chosen is not None else -1
    curriculum = get_track(track) if tracks_service.is_available_track(track) else None
    if curriculum is not None and 0 <= section < curriculum.total_sections:
        return {"kind": "track", "slug": curriculum.slug, "section": section}
    return {}


def _mira_context_display(context: dict) -> dict:
    if context.get("kind") == "track":
        track = get_track(str(context.get("slug") or ""))
        idx = context.get("section")
        if track and isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < track.total_sections:
            return {"title": track.all_sections[idx].title, "url": f"/tracks/{track.slug}#section-{idx}"}
    if context.get("kind") == "problem":
        problem = problem_repo.get_by_slug(str(context.get("slug") or ""))
        if problem:
            return {"title": problem.title, "url": f"/problem/{problem.slug}"}
    return {"title": "Your practice", "url": "/"}


def _mira_coach_stage(turns: list) -> str | None:
    from .services.mira_coach import STAGES
    for turn in reversed(turns):
        source = getattr(turn, "provider_used", "") or ""
        if turn.role == "user" and source.startswith("coach:") and source[6:] in STAGES:
            index = STAGES.index(source[6:]) + 1
            return STAGES[index] if index < len(STAGES) else None
    return STAGES[0]


def _mira_session_view(request: Request, session=None, *, context=None, error="", draft="", status_code=200, stage_override=None, pending_session_id="", request_token="", force_new=False, submitted_context=None):
    from .services import mira_coach
    from uuid import uuid4
    request_token = request_token or str(uuid4())
    uid = request.state.user_session.user_id
    try:
        turns = mira_repo.list_turns(session.id, limit=200, fresh=True) if session else []
    except Exception:
        turns = []
        error = error or "Saved notes are temporarily unavailable. Your draft is still here; try again."
        status_code = 503
    try:
        recent = mira_repo.list_sessions(uid, limit=20)
    except Exception:
        recent = []
    meta = (session.meta or {}) if session else {}
    legacy = bool(session and meta.get("mode") != "coach")
    context = meta.get("context", {}) if session else (context or {})
    context = context if isinstance(context, dict) else {}
    try:
        work = _mira_context_display(context)
    except Exception:
        work = {"title": "your practice", "url": "/"}
    stage = stage_override if stage_override in mira_coach.STAGES else _mira_coach_stage(turns)
    return templates.TemplateResponse(request, "mira_coach.html", {
        "config": config, "session": session, "turns": turns, "legacy": legacy,
        "context": context, "work": work, "draft_user": uid, "pending_session_id": pending_session_id,
        "request_token": request_token, "force_new": force_new, "submitted_context": submitted_context,
        "confirmed_drafts": [{"stage": (t.provider_used or "")[6:], "text": t.content} for t in turns if t.role == "user" and (t.provider_used or "").startswith("coach:")],
        "recent_sessions": recent, "stage": stage, "stage_labels": mira_coach.STAGE_LABELS,
        "prompt": mira_coach.coaching_reply(stage, "") if stage else "",
        "stage_number": mira_coach.STAGES.index(stage) + 1 if stage else 4,
        "error": error, "draft": draft, "nav_section": "mira",
    }, status_code=status_code)


def _mira_gate(request: Request):
    """Keep coaching and owner-scoped research records behind sign-in.

    LIS_MIRA_ADMIN_ONLY remains the emergency switch for restricting Mira
    to operators. Practice coaching itself uses no provider or token budget.
    """
    if os.environ.get("LIS_MIRA_ADMIN_ONLY", "").strip() == "1":
        if not getattr(request.state, "is_admin", False):
            return HTMLResponse("Not found", status_code=404)
    return None


@app.get("/mira", response_class=HTMLResponse)
def mira_home(request: Request, track: str = "", section: int = -1, problem: str = "", persona: str = "", new: bool = False):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    context = _mira_coach_context(request.state.user_settings or {}, track=track, section=section, problem=problem, user_id=request.state.user_session.user_id)
    if not new:
        try:
            recent = mira_repo.list_sessions(request.state.user_session.user_id, limit=20)
            for candidate in recent:
                meta = candidate.meta or {}
                if meta.get("mode") == "coach" and meta.get("context", {}) == context:
                    turns = mira_repo.list_turns(candidate.id, limit=200, fresh=True)
                    if _mira_coach_stage(turns) is not None:
                        return _mira_session_view(request, candidate)
                    break
        except Exception:
            # A failed resume lookup must leave the new-note form usable.
            pass
    # Opening help should neither create empty conversations nor interrupt work.
    notice = "Open-ended research personas are now read-only. Use these prompts to guide your own practice." if persona else ""
    return _mira_session_view(request, context=context, error=notice, force_new=new)


@app.get("/mira/session/{session_id}", response_class=HTMLResponse)
def mira_session(request: Request, session_id: str):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    session = mira_repo.get_session(session_id, user_id=request.state.user_session.user_id)
    if session is None:
        return HTMLResponse("Conversation not found", status_code=404)
    return _mira_session_view(request, session)


@app.post("/mira/coach", response_class=HTMLResponse)
def mira_coach_submit(request: Request):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    return HTMLResponse(
        "<p>MIRA coaching is coming soon. Check back later.</p>"
        "<p><a href='/mira'>← Back to Mira</a></p>",
        status_code=200,
    )


@app.post("/mira/turn")
async def mira_turn_route(request: Request, session_id: str = Form(...), message: str = Form(...)):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    session = mira_repo.get_session(session_id, user_id=request.state.user_session.user_id)
    if session is None:
        return HTMLResponse("Conversation not found", status_code=404)
    return HTMLResponse("MIRA coaching is coming soon.", status_code=409)


# 6a/6b/6d: the agenda / memory / evals sub-surfaces. Same admin gate as
# the chat routes. Kind/category whitelists mirror the table CHECKs so a
# tampered form gets a quiet fallback instead of an IntegrityError page
# (same idea as the connecting cadence clamp).
_MIRA_AGENDA_KINDS = ("question", "experiment", "writing", "deadline")
_MIRA_MEMORY_CATEGORIES = ("goal", "fact", "preference", "context")


def _mira_surface_view(request: Request, template: str, **extra):
    """Shared render for the three list surfaces. Gating stays in the
    routes so it fires before any repo read."""
    ctx = {"config": config, "nav_section": "mira", **extra}
    return templates.TemplateResponse(request, template, ctx)


@app.get("/mira/agenda", response_class=HTMLResponse)
def mira_agenda(request: Request, linear_error: str = ""):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    try:
        _lc = linear_config_repo.get(uid)
        linear_connected = bool(_lc and _lc.vault_secret_id and _lc.team_id)
    except Exception:  # noqa: BLE001 — panel state must not 500 the page
        linear_connected = False
    return _mira_surface_view(
        request, "mira_agenda.html",
        items=mira_repo.list_agenda(uid), kinds=_MIRA_AGENDA_KINDS,
        linear_connected=linear_connected,
        linear_error=(linear_error or "")[:300],
    )


@app.post("/mira/agenda")
def mira_agenda_add(
    request: Request, title: str = Form(""),
    kind: str = Form("question"), why: str = Form(""),
):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    cleaned = (title or "").strip()
    if kind not in _MIRA_AGENDA_KINDS:
        kind = "question"
    if cleaned:
        mira_repo.add_agenda_item(
            user_id=uid, kind=kind, title=cleaned, why=(why or "").strip() or None
        )
    return RedirectResponse(url="/mira/agenda", status_code=303)


@app.post("/mira/agenda/{agenda_id}/linear")
def mira_agenda_push_linear(request: Request, agenda_id: str):
    """Push one agenda item into the user's Linear team as an issue.
    Broken/missing config degrades to a redirect with the error —
    the local agenda always keeps working."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from urllib.parse import quote

    from .services import linear_sync

    uid = request.state.user_session.user_id
    cfg = linear_config_repo.get(uid)
    if not cfg or not cfg.vault_secret_id or not cfg.team_id:
        return RedirectResponse(
            url="/mira/agenda?linear_error=" + quote("Connect Linear in Settings first."),
            status_code=303,
        )
    item = next((i for i in mira_repo.list_agenda(uid) if i["id"] == agenda_id), None)
    if item is None:
        return RedirectResponse(url="/mira/agenda", status_code=303)
    if item.get("linear_issue_id"):
        return RedirectResponse(url="/mira/agenda", status_code=303)  # already pushed
    description = "\n\n".join(
        part for part in (
            item.get("why") or "",
            item.get("notes_md") or "",
            f"—\nPushed from [Li's Bench agenda](https://bench.libearden.dev/mira/agenda) · kind: {item.get('kind')}",
        ) if part
    )
    try:
        key = linear_config_repo.api_key_for(uid)
        if not key:
            raise linear_sync.LinearSyncError("Connect Linear in Settings first.")
        issue = linear_sync.create_issue(key, cfg.team_id, item["title"], description)
    except linear_sync.LinearSyncError as e:
        return RedirectResponse(
            url="/mira/agenda?linear_error=" + quote(str(e)), status_code=303
        )
    mira_repo.set_agenda_linear(
        uid, agenda_id,
        issue_id=issue["id"], identifier=issue["identifier"], url=issue["url"],
    )
    return RedirectResponse(url="/mira/agenda", status_code=303)


@app.post("/mira/agenda/linear-refresh")
def mira_agenda_linear_refresh(request: Request):
    """Pull linked issues' workflow-state types and map them onto
    agenda statuses (started→active, completed→done, canceled→
    abandoned). Explicit button, not a cron — the user decides when
    a remote call happens (and sees its failure inline)."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from urllib.parse import quote

    from .services import linear_sync

    uid = request.state.user_session.user_id
    links = mira_repo.agenda_linear_links(uid)
    if not links:
        return RedirectResponse(url="/mira/agenda", status_code=303)
    try:
        key = linear_config_repo.api_key_for(uid)
        if not key:
            raise linear_sync.LinearSyncError("Connect Linear in Settings first.")
        states = linear_sync.fetch_issue_states(
            key, [l["linear_issue_id"] for l in links]
        )
    except linear_sync.LinearSyncError as e:
        return RedirectResponse(
            url="/mira/agenda?linear_error=" + quote(str(e)), status_code=303
        )
    for link in links:
        mapped = linear_sync.STATE_TO_AGENDA_STATUS.get(
            states.get(link["linear_issue_id"], "")
        )
        if mapped and mapped != link["status"]:
            mira_repo.set_agenda_status(uid, link["id"], mapped)
    return RedirectResponse(url="/mira/agenda", status_code=303)


@app.get("/mira/memory", response_class=HTMLResponse)
def mira_memory_page(request: Request):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    return _mira_surface_view(
        request, "mira_memory.html",
        memories=mira_repo.list_memories(uid), categories=_MIRA_MEMORY_CATEGORIES,
    )


@app.post("/mira/memory")
def mira_memory_add(
    request: Request, content: str = Form(""), category: str = Form("fact")
):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    cleaned = (content or "").strip()
    if category not in _MIRA_MEMORY_CATEGORIES:
        category = "fact"
    if cleaned:
        mira_repo.add_memory(user_id=uid, category=category, content=cleaned)
    return RedirectResponse(url="/mira/memory", status_code=303)


@app.get("/mira/kb", response_class=HTMLResponse)
def mira_kb_page(
    request: Request,
    q: str = "",
    kb_error: str = "",
    ingested: str = "",
    unchanged: str = "",
    failed: str = "",
):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from .services import kb_ingest

    uid = request.state.user_session.user_id
    docs = kb_repo.list_for_user(uid)
    total_bytes = sum(d.content_bytes for d in docs)
    query = (q or "").strip()[:200]
    hits = kb_repo.sparse_search(uid, query, k=8) if query else []
    try:
        git_cfg = vault_sync_repo.get(uid)
    except Exception:  # noqa: BLE001 — panel state must not 500 the page
        git_cfg = None
    return _mira_surface_view(
        request, "mira_kb.html",
        bubbles=_bubbles_for(request, "kb"),
        git_cfg=git_cfg,
        docs=docs,
        doc_count=len(docs),
        total_mb=round(total_bytes / (1024 * 1024), 1),
        quota_docs=kb_ingest.MAX_DOCS,
        quota_mb=kb_ingest.MAX_TOTAL_MB,
        search_q=query,
        hits=hits,
        kb_error=kb_error[:300],
        upload_counts={
            k: v for k, v in
            (("ingested", ingested), ("unchanged", unchanged), ("failed", failed))
            if v.isdigit()
        },
    )


@app.post("/mira/kb/upload", response_class=HTMLResponse)
def mira_kb_upload(request: Request, vault_zip: UploadFile = File(...)):
    """Obsidian vault import (v2.1 slice 1). The zip is processed
    entirely in memory — nothing user-supplied touches disk. Sync def
    on purpose: runs in the threadpool, where DB calls belong."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from urllib.parse import quote

    from .services import kb_ingest

    uid = request.state.user_session.user_id
    blob = vault_zip.file.read(kb_ingest.MAX_ZIP_MB * 1024 * 1024 + 1)
    if len(blob) > kb_ingest.MAX_ZIP_MB * 1024 * 1024:
        return RedirectResponse(
            url=f"/mira/kb?kb_error={quote(f'Zip is over {kb_ingest.MAX_ZIP_MB}MB. Export a smaller vault or split it.')}",
            status_code=303,
        )
    try:
        result = kb_ingest.ingest_zip(kb_repo, uid, blob)
    except kb_ingest.VaultImportError as exc:
        return RedirectResponse(url=f"/mira/kb?kb_error={quote(str(exc))}", status_code=303)
    except Exception:  # noqa: BLE001 — do not expose storage diagnostics to the learner
        return RedirectResponse(
            url=f"/mira/kb?kb_error={quote('Import could not finish. Retry the same archive; saved notes are retained.')}",
            status_code=303,
        )
    return RedirectResponse(
        url=(
            f"/mira/kb?ingested={result.docs_ingested}"
            f"&unchanged={result.docs_unchanged}&failed={len(result.errors)}"
        ),
        status_code=303,
    )


@app.post("/mira/kb/delete/{doc_id}", response_class=HTMLResponse)
def mira_kb_delete(request: Request, doc_id: str):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    kb_repo.delete_document(uid, doc_id)
    return RedirectResponse(url="/mira/kb", status_code=303)


@app.post("/mira/kb/git/connect", response_class=HTMLResponse)
def mira_kb_git_connect(
    request: Request,
    repo: str = Form(""),
    branch: str = Form(""),
    subdir: str = Form(""),
    token: str = Form(""),
):
    """Connect a git-hosted vault (v2.1 slice 5). Token optional —
    public repos need none; when given it goes to Supabase Vault and
    never round-trips to the page. The first sync runs inline so the
    user sees a result, not a promise."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from urllib.parse import quote

    from .services import kb_git_sync

    uid = request.state.user_session.user_id
    try:
        repo_n = kb_git_sync.normalize_repo(repo)
    except kb_git_sync.GitSyncError as e:
        return RedirectResponse(url=f"/mira/kb?kb_error={quote(str(e))}", status_code=303)
    tok = (token or "").strip()
    if len(tok) > 512:
        return RedirectResponse(url="/mira/kb?kb_error=Token+too+long", status_code=303)
    vault_sync_repo.set_config(
        uid,
        repo=repo_n,
        branch=(branch or "").strip()[:100],
        subdir=(subdir or "").strip().strip("/")[:200],
        token=tok or None,
    )
    try:
        kb_git_sync.sync_user(kb_repo, vault_sync_repo, uid)
    except kb_git_sync.GitSyncError as e:
        # Config is saved; the failure is visible in last_result AND
        # inline so a typo'd token gets fixed immediately.
        return RedirectResponse(url=f"/mira/kb?kb_error={quote(str(e))}", status_code=303)
    return RedirectResponse(url="/mira/kb", status_code=303)


@app.post("/mira/kb/git/sync", response_class=HTMLResponse)
def mira_kb_git_sync_now(request: Request):
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    from urllib.parse import quote

    from .services import kb_git_sync

    uid = request.state.user_session.user_id
    try:
        kb_git_sync.sync_user(kb_repo, vault_sync_repo, uid)
    except kb_git_sync.GitSyncError as e:
        return RedirectResponse(url=f"/mira/kb?kb_error={quote(str(e))}", status_code=303)
    return RedirectResponse(url="/mira/kb", status_code=303)


@app.post("/mira/kb/git/disconnect", response_class=HTMLResponse)
def mira_kb_git_disconnect(request: Request):
    """Removes the sync config AND its vault token. Already-ingested
    notes stay (they're the user's KB rows; delete them per-note or
    via account deletion)."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    vault_sync_repo.delete_for(uid)
    return RedirectResponse(url="/mira/kb", status_code=303)


@app.get("/mira/evals", response_class=HTMLResponse)
def mira_evals(request: Request):
    """Read-only: proposed_evals is Mira-authored (the agent loop drafts
    rows when a conversation converges on a testable hypothesis), so
    there is no user create form."""
    gated = _mira_gate(request)
    if gated is not None:
        return gated
    uid = request.state.user_session.user_id
    return _mira_surface_view(
        request, "mira_evals.html", evals=mira_repo.list_proposed_evals(uid)
    )


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request, type: str = "", tag: str = "", track: str = ""):
    """Library page with type + tag filters.

    Tag filter semantics (post-LIS-284 unification):
      A click on `?tag=X` matches if X (case-insensitive) appears in
      EITHER `domain_tags` (sub-topic) OR `axes` (canonical axis) for
      content, OR in any of problem.{domain_tags, competency_tags,
      structural_tags} for problems. No alias bridge — the data layer
      now carries `domain_tags` on content items directly (see
      migration 005 and docs/architecture/tag-vocabulary.md).
    """
    uid = request.state.user_session.user_id
    cores = problem_repo.all_core()
    warmups = problem_repo.all_warmups()
    attempted_ids = {a.problem_id for a in attempt_repo.all_for_user(uid)}

    needle = (tag or "").strip().lower() or None

    def _tag_match(haystack_tags: list[str]) -> bool:
        if needle is None:
            return True
        return any((t or "").strip().lower() == needle for t in haystack_tags)

    def keep(p):
        if type and p.problem_type != type:
            return False
        if needle is None:
            return True
        return _tag_match(
            (p.domain_tags or []) + (p.structural_tags or []) + (p.competency_tags or [])
        )
    cores = [p for p in cores if keep(p)]
    warmups = [p for p in warmups if keep(p)]
    # Facet chips: union of problem domain_tags + content domain_tags +
    # content axes — a single namespace now that content items carry
    # both sub-topics and axes. Sorted alphabetically; the UI
    # de-duplicates visually.
    all_problem_tags = {t for p in problem_repo.all_core() for t in (p.domain_tags or [])}
    all_content_tags: set[str] = set()
    for kind in ("reading", "video", "podcast", "exercise"):
        for c in content_repo.all_by_kind(kind, user_id=uid):
            all_content_tags.update(c.axes or [])
            all_content_tags.update(c.domain_tags or [])
    all_types = sorted({p.problem_type for p in problem_repo.all_core()} | {"reading", "video", "podcast", "exercise"})
    all_tags = sorted(all_problem_tags | all_content_tags)

    # Content surface (readings, videos, podcasts, exercises) with
    # favorited / rated state for the user.
    content_progress = content_repo.progress_for_user(uid)
    all_content = []
    for kind in ("reading", "video", "podcast", "exercise"):
        all_content.extend(content_repo.all_by_kind(kind, user_id=uid))
    # Derived resources retain their database identities if a track is retired,
    # but only current approved catalog references belong in the library.
    published = {c.slug for c in track_content.catalog_items(_tracks_by_slug)}
    all_content = [c for c in all_content if c.source_kind != "authored" or not c.slug.startswith("track-") or c.slug in published]
    if needle is not None:
        all_content = [c for c in all_content if _tag_match((c.domain_tags or []) + (c.axes or []))]
    if type:
        all_content = [c for c in all_content if c.kind == type]
    available_tracks = tracks_service.available_tracks(_tracks_by_slug)
    if track:
        selected = next((t for t in available_tracks if t.slug == track), None)
        slugs = ({track_content.item_slug(track, section.url) for section in selected.all_sections}
                 | {track_content.item_slug(track, r.url) for section in selected.all_sections for r in section.resources}
                 | {slug for section in selected.all_sections for slug in section.prep}) if selected else set()
        all_content = [c for c in all_content if c.slug in slugs]
        problems = {slug for section in selected.all_sections for slug in section.cold_checkpoint} if selected else set()
        cores = [p for p in cores if p.slug in problems]
        warmups = [p for p in warmups if p.slug in problems]
    track_content_states = {c.id: _track_content_context(request, c) for c in all_content if c.slug in published and c.source_kind == "authored"}
    favorites = [item for item in all_content if content_progress.get(item.id) and content_progress[item.id].favorited]

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "bubbles": _bubbles_for(request, "library"),
            "config": config,
            "cores": cores,
            "warmups": warmups,
            "all_content": all_content,
            "favorites": favorites,
            "content_progress": content_progress,
            "attempted_ids": attempted_ids,
            "all_types": all_types,
            "all_tags": all_tags,
            "active_type": type,
            "active_tag": tag,
            "active_track_filter": track,
            "available_tracks": available_tracks,
            "track_content_states": track_content_states,
            "track_materials": _active_track_materials(request.state.user_settings or {}, user_id=uid),
            "nav_section": "learn",
        },
    )


# --- Curriculum tracks ------------------------------------------------------


@app.get("/tracks", response_class=HTMLResponse)
def tracks_index(request: Request):
    settings = request.state.user_settings or {}

    track_rows: list[dict] = []
    for track in sorted(_tracks_by_slug.values(), key=lambda t: t.title.lower()):
        status, state = _track_status_and_state(settings, track.slug, user_id=request.state.user_session.user_id)
        checkpoint_passed = _track_checkpoint_passed_sections(state=state, track=track)
        exemptions = _track_exemptions(track, settings, user_id=request.state.user_session.user_id)
        next_idx = tracks_service.next_section_index(track, checkpoint_passed | exemptions, state.get("preferred_section"))
        cursor = track.total_sections if next_idx is None else next_idx

        track_rows.append(
            {
                "track": track,
                "first_section": tracks_service.section_at(track, tracks_service.next_section_index(track, set()) or 0),
                "is_available": tracks_service.is_available_track(track.slug),
                "status": status,
                "is_active": status == "active",
                "is_paused": status == "paused",
                "cursor": min(cursor, track.total_sections),
                "next_section_number": (next_idx + 1) if next_idx is not None else track.total_sections,
                **_track_completion_counts(track, checkpoint_passed, exemptions),
            }
        )

    active_row = next((row for row in track_rows if row["is_active"] and row["is_available"]), None)
    # "First-time visitor" detection for the zero-state CTA (Pattern C).
    # True when there are tracks to choose from but the operator has
    # never engaged with any of them — no active, no paused, no
    # checkpoints passed.
    has_started_any = any(
        row["is_active"] or row["is_paused"] or row["completed_count"] > 0
        for row in track_rows
    )
    return templates.TemplateResponse(
        request,
        "tracks_index.html",
        {
            "config": config,
            "track_rows": track_rows,
            "active_row": active_row,
            "has_started_any": has_started_any,
            "nav_section": "tracks",
            "is_admin": bool(getattr(request.state, "is_admin", False)),
        },
    )


def _track_page_context(request: Request, slug: str, gate_blocked: str = ""):
    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)

    uid = request.state.user_session.user_id
    settings = request.state.user_settings or {}
    status, state = _track_status_and_state(settings, slug, user_id=uid)

    checkpoint_passed = _track_checkpoint_passed_sections(state=state, track=track)
    exemptions = _track_exemptions(track, settings, user_id=uid)
    next_idx = tracks_service.next_section_index(track, checkpoint_passed | exemptions, state.get("preferred_section"))
    unlocked_sections = set(tracks_service.unlocked_section_indices(track, checkpoint_passed | exemptions))

    raw_passed_at = state.get("checkpoint_passed_at_per_section")
    passed_at_per_section = raw_passed_at if isinstance(raw_passed_at, dict) else {}
    raw_questions = state.get("checkpoint_questions_per_section")
    checkpoint_questions_per_section = raw_questions if isinstance(raw_questions, dict) else {}

    gate_blocked_title = ""
    if gate_blocked:
        try:
            _gp = problem_repo.get_by_slug(gate_blocked.strip())
            gate_blocked_title = _gp.title if _gp else gate_blocked.strip()
        except Exception:  # noqa: BLE001
            gate_blocked_title = gate_blocked.strip()

    from .services.track_checks import questions_for_section, questions_version
    from .services.track_exams import spec_for_section
    is_available = tracks_service.is_available_track(slug)
    chapter_rows: list[dict] = []
    section_idx = 0
    for chapter in track.chapters:
        section_rows: list[dict] = []
        for section in chapter.sections:
            is_completed = section_idx in checkpoint_passed
            is_current = section_idx == next_idx and next_idx is not None
            is_unlocked = section_idx in unlocked_sections
            dependency_idxs = tracks_service.dependencies_for(track, section_idx)
            response = state.get("checkpoint_response_per_section", {}).get(str(section_idx), {})
            version = questions_version(track, section_idx)
            stale_response = response if response and response.get("check_version") != version else {}
            section_rows.append(
                {
                    "idx": section_idx,
                    "content_url": f"/content/{track_content.item_slug(slug, section.url)}",
                    "resources": [{"title": r.title, "kind": r.kind, "url": f"/content/{track_content.item_slug(slug, r.url)}"} for r in section.resources if r.url != section.url],
                    "section": section,
                    "is_completed": is_completed,
                    "exemption": section_idx in exemptions,
                    "exam_url": f"/tracks/{slug}/sections/{section_idx}/exam" if is_available and spec_for_section(track, section_idx) else "",
                    "is_current": is_current,
                    "is_unlocked": is_unlocked,
                    "is_future": not is_completed and section_idx not in exemptions and not is_unlocked,
                    "dependency_numbers": [dep + 1 for dep in dependency_idxs],
                    "missing_prerequisites": tracks_service.missing_prerequisites(track, section_idx, checkpoint_passed | exemptions),
                    "checkpoint_text": section.checkpoint.strip() or _default_track_checkpoint_text(section),
                    "prep_items": _track_prep_items(section),
                    "gate": _track_gate_status(section, uid),
                    "checkpoint_questions": questions_for_section(track, section_idx),
                    "check_version": version,
                    "stale_response": stale_response,
                    "completed_at": passed_at_per_section.get(str(section_idx), ""),
                    "session": state.get("session_per_section", {}).get(str(section_idx), {}),
                    "response": {} if stale_response and not is_completed else response,
                }
            )
            section_idx += 1
        chapter_rows.append({"title": chapter.title, "sections": section_rows})

    cursor = track.total_sections if next_idx is None else next_idx

    return {
        "config": config,
        "track": track,
        "is_available": is_available,
        "current_row": next((row for chapter in chapter_rows for row in chapter["sections"] if row["is_current"]), None),
        "status": status,
        "is_active": status == "active",
        "is_paused": status == "paused",
        "cursor": min(cursor, track.total_sections),
        "next_section_number": (next_idx + 1) if next_idx is not None else 0,
        **_track_completion_counts(track, checkpoint_passed, exemptions),
        "chapter_rows": chapter_rows,
        "gate_blocked_title": gate_blocked_title,
        "nav_section": "tracks",
        "is_admin": bool(getattr(request.state, "is_admin", False)),
    }


@app.get("/tracks/{slug}", response_class=HTMLResponse)
def track_detail(request: Request, slug: str, gate_blocked: str = ""):
    context = _track_page_context(request, slug, gate_blocked)
    if isinstance(context, HTMLResponse):
        return context
    return templates.TemplateResponse(request, "track_detail.html", context)


@app.get("/tracks/{slug}/sections/{idx}", response_class=HTMLResponse)
def track_section_page(request: Request, slug: str, idx: int, gate_blocked: str = ""):
    context = _track_page_context(request, slug, gate_blocked)
    if isinstance(context, HTMLResponse):
        return context
    row = next((row for chapter in context["chapter_rows"] for row in chapter["sections"] if row["idx"] == idx), None)
    if row is None:
        return HTMLResponse("Not found", status_code=404)
    context["row"] = row
    return templates.TemplateResponse(request, "track_section.html", context)


def _track_exam_context(slug, idx):
    from fastapi import HTTPException
    from .services.track_exams import spec_for_section
    track = get_track(slug)
    if track is None or not tracks_service.is_available_track(slug):
        raise HTTPException(404, "Assessment not available for this track.")
    spec = spec_for_section(track, idx)
    if spec is None:
        raise HTTPException(404, "This section has no reviewed pilot assessment yet.")
    return track, tracks_service.section_at(track, idx), spec


def _track_exam_page(request, slug, idx, *, form=None, error="", status_code=200):
    import uuid
    track, section, spec = _track_exam_context(slug, idx)
    uid = request.state.user_session.user_id
    form = form or {}
    try:
        submissions = [record for record in track_assessment_repo.list_for_user(uid)
                       if record.get("track_slug") == slug and record.get("section_idx") == idx]
    except Exception:
        submissions = []
        error = error or "Submission history is unavailable. Your draft is preserved; retry before starting another submission."
        status_code = max(status_code, 503)
    return templates.TemplateResponse(request, "track_exam.html", {
        "config": config, "track": track, "section": section, "idx": idx, "spec": spec,
        "request_id": form.get("request_id") or str(uuid.uuid4()), "form": form,
        "error": error, "submissions": list(reversed(submissions)),
        "practical_gate": _track_gate_status(section, uid), "nav_section": "tracks",
    }, status_code=status_code)


@app.get("/tracks/{slug}/sections/{idx}/exam", response_class=HTMLResponse)
def track_exam(request: Request, slug: str, idx: int):
    return _track_exam_page(request, slug, idx)


@app.post("/tracks/{slug}/sections/{idx}/exam", response_class=HTMLResponse)
def track_exam_submit(request: Request, slug: str, idx: int,
                      answers: str = Form(""), modality: str = Form("written"),
                      assistance: str = Form(""), transcript_confirmed: str = Form(""),
                      exam_version: str = Form(""), request_id: str = Form(""),
                      artifact_url: str = Form("")):
    track, section, spec = _track_exam_context(slug, idx)
    form = {"answers": answers, "modality": modality, "assistance": assistance,
            "transcript_confirmed": transcript_confirmed == "1", "exam_version": exam_version,
            "request_id": request_id, "artifact_url": artifact_url}
    if exam_version != spec["version"]:
        return _track_exam_page(request, slug, idx, form=form, error="Assessment questions changed. Keep this draft and open the current assessment.", status_code=409)
    try:
        if not answers.strip() or len(answers) > 12000:
            raise ValueError("Write a response of up to 12000 characters.")
        if modality not in {"written", "oral"} or assistance not in {"none", "notes", "help"}:
            raise ValueError("Choose a response format and assistance declaration.")
        if modality == "oral" and not form["transcript_confirmed"]:
            raise ValueError("Review and confirm the transcript before submitting an oral response.")
        artifact = _track_artifact_url(artifact_url)
        track_assessment_repo.submit(request.state.user_session.user_id, request_id, spec,
            {"answers": answers.strip(), "artifact_url": artifact,
             "transcript_confirmed": form["transcript_confirmed"]}, modality, assistance)
    except ValueError as exc:
        return _track_exam_page(request, slug, idx, form=form, error=str(exc), status_code=400)
    except Exception:
        return _track_exam_page(request, slug, idx, form=form, error="Submission could not be confirmed. Your draft and retry token are preserved; retry this form.", status_code=503)
    return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}/exam#submissions", status_code=303)


def _track_exam_require_admin(request):
    from fastapi import HTTPException
    from .services import access
    if not access.is_admin(request.state.user_session.user_id):
        raise HTTPException(403, "Assessment review is available to the operator only.")


def _track_exam_review_page(request, owner_id="", attempt_id="", *, form=None, error="", status_code=200):
    from fastapi import HTTPException
    from .services.track_exams import spec_for_section
    _track_exam_require_admin(request)
    try:
        selected = track_assessment_repo.get(owner_id, attempt_id) if owner_id and attempt_id else None
        queue = track_assessment_repo.pending_reviews()
    except ValueError:
        raise HTTPException(404, "Submission not found.")
    except Exception:
        selected, queue = None, []
        error = error or "Assessment history is unavailable. Retry to confirm the current review status."
        status_code = 503
    if owner_id and attempt_id and selected is None and status_code != 503:
        raise HTTPException(404, "Submission not found.")
    track = get_track(selected["track_slug"]) if selected else None
    section = tracks_service.section_at(track, selected["section_idx"]) if track else None
    spec = spec_for_section(track, selected["section_idx"]) if track and tracks_service.is_available_track(track.slug) else None
    return templates.TemplateResponse(request, "track_exam_review.html", {
        "config": config, "queue": queue, "selected": selected, "track": track,
        "section": section, "spec": spec, "form": form or {}, "error": error,
        "practical_gate": _track_gate_status(section, owner_id) if section else None,
        "nav_section": "tracks",
    }, status_code=status_code)


@app.get("/track-assessments/review", response_class=HTMLResponse)
def track_exam_review_queue(request: Request, owner_id: str = "", attempt_id: str = ""):
    return _track_exam_review_page(request, owner_id, attempt_id)


def _track_exam_record_review(request, owner_id, attempt_id, form):
    from fastapi import HTTPException
    from .services.track_exams import spec_for_section
    _track_exam_require_admin(request)
    try:
        record = track_assessment_repo.get(owner_id, attempt_id)
        if not record:
            raise HTTPException(404, "Submission not found.")
        track = get_track(record["track_slug"])
        spec = spec_for_section(track, record["section_idx"]) if track and tracks_service.is_available_track(track.slug) else None
        if not spec or form.get("exam_version") != spec["version"] or record["spec_version"] != spec["version"]:
            return _track_exam_review_page(request, owner_id, attempt_id, form=form, error="This assessment version changed. The saved response cannot be graded against a different rubric.", status_code=409)
        scores = {c["id"]: int(form.get("score_" + c["id"], "")) for c in spec["criteria"]}
        evidence = {c["id"]: str(form.get("evidence_" + c["id"], "")).strip() for c in spec["criteria"]}
        section = tracks_service.section_at(track, record["section_idx"])
        gate = _track_gate_status(section, owner_id)
        if gate and not gate["passed"]:
            return _track_exam_review_page(request, owner_id, attempt_id, form=form, error="The learner's required practical checks must pass before final review. Ratings are preserved below; retry after the practical work is verified.", status_code=409)
        practical = {"verified_slugs": [item["slug"] for item in gate["items"] if item["passed"]], "checked_at": datetime.now(timezone.utc).isoformat()} if gate else {}
        track_assessment_repo.review(owner_id, attempt_id, request.state.user_session.user_id, spec, scores, evidence, practical)
    except HTTPException:
        raise
    except ValueError as exc:
        return _track_exam_review_page(request, owner_id, attempt_id, form=form, error=str(exc), status_code=400)
    except Exception:
        return _track_exam_review_page(request, owner_id, attempt_id, form=form, error="Review could not be confirmed saved. Ratings are preserved; retry this form.", status_code=503)
    from urllib.parse import urlencode
    return RedirectResponse(url="/track-assessments/review?" + urlencode({"owner_id": owner_id, "attempt_id": attempt_id}), status_code=303)


@app.post("/track-assessments/{owner_id}/{attempt_id}/review", response_class=HTMLResponse)
async def track_exam_record_review(request: Request, owner_id: str, attempt_id: str):
    import anyio
    form = dict(await request.form())
    return await anyio.to_thread.run_sync(_track_exam_record_review, request, owner_id, attempt_id, form)


@app.post("/tracks/{slug}/request", response_class=HTMLResponse)
def track_request(request: Request, slug: str):
    track = get_track(slug)
    if track is None:
        return HTMLResponse("Track not found.", status_code=404)
    if tracks_service.is_available_track(slug):
        return RedirectResponse(url=f"/tracks/{slug}", status_code=303)
    feedback_repo.request_track(request.state.user_session.user_id, slug, track.title)
    return RedirectResponse(url="/feedback/inbox", status_code=303)


@app.post("/tracks/{slug}/activate", response_class=HTMLResponse)
def track_activate(request: Request, slug: str):
    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)

    if not tracks_service.is_available_track(slug):
        return HTMLResponse("This track is pending audit. Request it from Tracks; your progress is preserved.", status_code=409)

    uid = request.state.user_session.user_id
    settings = _user_settings(uid)
    paused_tracks = _paused_tracks(settings)

    active_raw = settings.get("active_track")
    active_slug = ""
    if isinstance(active_raw, dict):
        active_slug = str(active_raw.get("slug") or "").strip()

    if active_slug and active_slug != slug:
        paused_tracks[active_slug] = _normalized_track_state(active_raw, slug=active_slug, settings=settings, user_id=uid)

    if active_slug == slug and isinstance(active_raw, dict):
        next_active = _normalized_track_state(active_raw, slug=slug, settings=settings, user_id=uid)
        paused_tracks.pop(slug, None)
    else:
        paused = paused_tracks.pop(slug, None)
        if isinstance(paused, dict):
            next_active = _normalized_track_state(paused, slug=slug, settings=settings, user_id=uid)
        else:
            next_active = _normalized_track_state({}, slug=slug, settings=settings, user_id=uid)

    settings["active_track"] = next_active
    if paused_tracks:
        settings["paused_tracks"] = paused_tracks
    elif "paused_tracks" in settings:
        del settings["paused_tracks"]
    _save_user_settings(uid, settings)

    return RedirectResponse(url=f"/tracks/{slug}", status_code=303)


@app.post("/tracks/clear-active", response_class=HTMLResponse)
def track_clear_active(request: Request):
    uid = request.state.user_session.user_id
    settings = _user_settings(uid)

    active_raw = settings.get("active_track")
    if isinstance(active_raw, dict):
        active_slug = str(active_raw.get("slug") or "").strip()
        if active_slug:
            paused_tracks = _paused_tracks(settings)
            paused_tracks[active_slug] = _normalized_track_state(active_raw, slug=active_slug, settings=settings, user_id=uid)
            settings["paused_tracks"] = paused_tracks
        if "active_track" in settings:
            del settings["active_track"]
        _save_user_settings(uid, settings)

    return RedirectResponse(url="/tracks", status_code=303)


def _track_section_edit_context(request: Request, slug: str, idx: int):
    from fastapi import HTTPException

    track = get_track(slug)
    if track is None:
        raise HTTPException(404, "Track not found.")
    if not tracks_service.is_available_track(slug):
        raise HTTPException(409, "This track is pending audit; your progress is preserved.")
    uid = request.state.user_session.user_id
    settings = dict(_user_settings(uid))
    raw = settings.get("active_track")
    if not isinstance(raw, dict) or raw.get("slug") != slug:
        raise HTTPException(400, "Track is not active.")
    state = _normalized_track_state(raw, slug=slug, settings=settings, user_id=uid)
    passed = set(state["checkpoint_passed_sections"])
    section = tracks_service.section_at(track, idx)
    if section is None or idx in passed or not tracks_service.is_unlocked(track, idx, passed | _track_exemptions(track, settings, user_id=uid)):
        raise HTTPException(400, "Choose an unfinished, unlocked section of your active track.")
    return uid, settings, state, track, section


def _track_response_matches(state, idx, record):
    saved = state.get("checkpoint_response_per_section", {}).get(str(idx), {})
    return all(saved.get(key) == record.get(key)
               for key in ("answers", "confidence", "artifact_url", "updated_at"))


def _save_track_checkpoint_questions(uid, slug, idx, questions):
    # Question generation can update usage settings. Preserve those changes and
    # avoid restoring an old active track if the learner switched during it.
    settings = dict(_user_settings(uid))
    raw = settings.get("active_track")
    is_active = isinstance(raw, dict) and raw.get("slug") == slug
    paused = dict(_paused_tracks(settings))
    raw = raw if is_active else paused.get(slug)
    if not isinstance(raw, dict):
        return
    state = _normalized_track_state(raw, slug=slug, settings=settings, user_id=uid)
    if idx not in state["checkpoint_passed_sections"]:
        state["checkpoint_questions_per_section"].setdefault(str(idx), questions)
    if is_active:
        settings["active_track"] = state
    else:
        paused[slug] = state
        settings["paused_tracks"] = paused
    _save_user_settings(uid, settings)


def _save_track_section_state(uid, settings, state, slug, idx):
    settings["active_track"] = state
    _save_user_settings(uid, settings)
    return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)


@app.post("/tracks/{slug}/sections/{idx}/session", response_class=HTMLResponse)
def track_section_session(request: Request, slug: str, idx: int,
                          stopping_point: str = Form(""), artifact_url: str = Form(""),
                          next_action: str = Form("")):
    uid, settings, state, track, section = _track_section_edit_context(request, slug, idx)
    if len(stopping_point) > 2000 or len(next_action) > 500:
        return HTMLResponse("Stopping point or next action is too long.", status_code=400)
    try:
        artifact_url = _track_artifact_url(artifact_url)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    state["session_per_section"][str(idx)] = {
        "stopping_point": stopping_point.strip(), "artifact_url": artifact_url,
        "next_action": next_action.strip(), "updated_at": _utc_iso_now(),
    }
    state["preferred_section"] = idx
    return _save_track_section_state(uid, settings, state, slug, idx)


@app.post("/tracks/{slug}/sections/{idx}/focus", response_class=HTMLResponse)
def track_section_focus(request: Request, slug: str, idx: int):
    uid, settings, state, track, section = _track_section_edit_context(request, slug, idx)
    state["preferred_section"] = idx
    return _save_track_section_state(uid, settings, state, slug, idx)


@app.post("/tracks/{slug}/sections/{idx}/feedback", response_class=HTMLResponse)
def track_section_feedback(request: Request, slug: str, idx: int,
                           answers: str = Form(""), confidence: str = Form(""),
                           artifact_url: str = Form(""), request_ai: int = Form(0),
                           check_version: str = Form("")):
    uid, settings, state, track, section = _track_section_edit_context(request, slug, idx)
    if not answers.strip() or len(answers) > 6000 or confidence not in {"clear", "uncertain", "stuck"}:
        return HTMLResponse("Save an explanation up to 6000 characters and choose clear, uncertain, or stuck.", status_code=400)
    try:
        artifact_url = _track_artifact_url(artifact_url)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    from .services.track_checks import questions_version
    record = {"answers": answers.strip(), "confidence": confidence, "check_version": check_version[:100],
              "artifact_url": artifact_url, "updated_at": _utc_iso_now(), "feedback": {}}
    previous = state["checkpoint_response_per_section"].get(str(idx), {})
    if (previous.get("check_version") == questions_version(track, idx)
            and record["check_version"] != previous["check_version"]):
        # An older browser tab may still submit. Keep its draft, but do not
        # revoke the newer check response or replace the current form's work.
        previous = dict(previous)
        previous["previous_checks"] = [*previous.get("previous_checks", []), record]
        state["checkpoint_response_per_section"][str(idx)] = previous
        return _save_track_section_state(uid, settings, state, slug, idx)
    if previous and previous.get("check_version") != record["check_version"]:
        old = {key: value for key, value in previous.items() if key != "previous_checks"}
        old["questions"] = state["checkpoint_questions_per_section"].get(str(idx), [])
        record["previous_checks"] = [*previous.get("previous_checks", []), old]
    elif previous.get("previous_checks"):
        record["previous_checks"] = previous["previous_checks"]
    if record["check_version"] == questions_version(track, idx):
        state["checkpoint_questions_per_section"][str(idx)] = _track_socratic_questions_for_section(track=track, idx=idx, user_id=uid)
    state["checkpoint_response_per_section"][str(idx)] = record
    # Save the learner's work before making an optional external request.
    _save_track_section_state(uid, settings, state, slug, idx)
    record = dict(record)
    if record["check_version"] != questions_version(track, idx):
        return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)
    try:
        from .services.track_feedback import review_checkpoint
        record["feedback"] = review_checkpoint(
            track=track, section=section, answers=record["answers"],
            confidence=confidence, artifact_url=artifact_url, user_id=uid,
            request_ai=bool(request_ai),
        )
    except Exception:
        record["feedback"] = {"summary": "Your answers are saved. Feedback is unavailable right now.",
                              "next_action": "Review your explanation against the checkpoint, or try feedback again.",
                              "questions": [], "source": "unavailable"}
    # Feedback may record API usage in settings. Merge into the latest settings
    # instead of overwriting that usage (or another section's saved work).
    settings = dict(_user_settings(uid))
    current = settings.get("active_track")
    if isinstance(current, dict) and current.get("slug") == slug:
        state = _normalized_track_state(current, slug=slug, settings=settings, user_id=uid)
    else:
        paused = dict(_paused_tracks(settings))
        if slug not in paused:
            return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)
        state = _normalized_track_state(paused[slug], slug=slug, settings=settings, user_id=uid)
        if not _track_response_matches(state, idx, record):
            return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)
        state["checkpoint_response_per_section"][str(idx)] = record
        paused[slug] = state
        settings["paused_tracks"] = paused
        _save_user_settings(uid, settings)
        return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)
    if _track_response_matches(state, idx, record):
        state["checkpoint_response_per_section"][str(idx)] = record
        return _save_track_section_state(uid, settings, state, slug, idx)
    return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)


@app.post("/tracks/{slug}/sections/{idx}/complete", response_class=HTMLResponse)
def track_section_complete(
    request: Request,
    slug: str,
    idx: int,
    checkpoint_pass: int = Form(0),
):
    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)

    if not tracks_service.is_available_track(slug):
        return HTMLResponse("This track is pending audit. Request it from Tracks; your progress is preserved.", status_code=409)

    uid = request.state.user_session.user_id
    settings = _user_settings(uid)
    active_raw = settings.get("active_track")
    if not isinstance(active_raw, dict) or str(active_raw.get("slug") or "").strip() != slug:
        return HTMLResponse("Track is not active.", status_code=400)
    if idx < 0:
        return HTMLResponse("Invalid section index.", status_code=400)
    if idx >= track.total_sections:
        return HTMLResponse("Not found", status_code=404)

    active_track = _normalized_track_state(active_raw, slug=slug, settings=settings, user_id=uid)
    checkpoint_passed = _track_checkpoint_passed_sections(state=active_track, track=track)

    if idx in checkpoint_passed:
        return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)

    if not tracks_service.is_unlocked(track, idx, checkpoint_passed | _track_exemptions(track, settings, user_id=uid)):
        return HTMLResponse("Cannot complete a locked section.", status_code=400)

    # Practical application gate. When a section names a bench problem,
    # the learner must have RUN it green before the checkpoint counts.
    # Understanding checks are self-reported by construction; a test run
    # is not, which is the whole point of gating here.
    section = tracks_service.section_at(track, idx)
    gate = _track_gate_status(section, uid) if section is not None else None
    if gate is not None and not gate["passed"]:
        from urllib.parse import quote

        blocked = gate["remaining"][0]["slug"]
        return RedirectResponse(
            url=f"/tracks/{slug}/sections/{idx}?gate_blocked={quote(blocked)}",
            status_code=303,
        )

    from .services.track_checks import questions_version
    section_key = str(idx)
    checkpoint_questions_per_section = dict(active_track.get("checkpoint_questions_per_section", {}))
    if not checkpoint_pass:
        _save_track_checkpoint_questions(uid, slug, idx, _track_socratic_questions_for_section(track=track, idx=idx, user_id=uid))
        return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)
    response = active_track.get("checkpoint_response_per_section", {}).get(section_key, {})
    if response and response.get("check_version") != questions_version(track, idx):
        return HTMLResponse("The understanding check has been updated. Your previous answer is preserved; answer the current questions before completing this section.", status_code=409)
    if not str(response.get("answers") or "").strip() or response.get("confidence") != "clear":
        return HTMLResponse("Save your checkpoint answers and choose clear before marking this section passed. If uncertain or stuck, use the feedback to retry.", status_code=400)

    checkpoint_passed_sections = list(active_track.get("checkpoint_passed_sections", []))
    if idx not in checkpoint_passed_sections:
        checkpoint_passed_sections.append(idx)
    active_track["checkpoint_passed_sections"] = checkpoint_passed_sections
    # Back-compat mirror.
    active_track["completed_sections"] = list(checkpoint_passed_sections)

    checkpoint_passed_at_per_section = dict(active_track.get("checkpoint_passed_at_per_section", {}))
    checkpoint_passed_at_per_section[section_key] = _utc_iso_now()
    active_track["checkpoint_passed_at_per_section"] = checkpoint_passed_at_per_section
    # Back-compat mirror.
    active_track["completed_at_per_section"] = dict(checkpoint_passed_at_per_section)

    checkpoint_questions_per_section.pop(section_key, None)
    active_track["checkpoint_questions_per_section"] = checkpoint_questions_per_section

    next_idx = tracks_service.next_section_index(track, set(checkpoint_passed_sections) | _track_exemptions(track, settings, user_id=uid), active_track.get("preferred_section"))
    active_track["cursor"] = track.total_sections if next_idx is None else next_idx

    settings["active_track"] = active_track
    _save_user_settings(uid, settings)

    return RedirectResponse(url=f"/tracks/{slug}/sections/{idx}", status_code=303)


@app.get("/tracks/{slug}/sections/{idx}/drafts", response_class=HTMLResponse)
def track_section_drafts(request: Request, slug: str, idx: int):
    """Per-section content-draft review surface (BEN-88).

    Lists pending drafts under content/<kind>/_drafts/ that were
    generated for this track section, with promote/discard affordances.
    Drafts are not loaded by the live content cache (the loader uses a
    non-recursive glob), so showing them here is the operator's only
    gateway from draft to live.
    """
    from .services import content_drafts

    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)
    if not tracks_service.is_available_track(slug):
        return HTMLResponse("This track is pending audit.", status_code=409)
    section = tracks_service.section_at(track, idx)
    if section is None:
        return HTMLResponse("Section out of range", status_code=404)

    # Filter to drafts whose slug matches the per-node naming convention
    # used by content_generation: "<track_slug>-s<idx>-<kind>-draft".
    prefix = f"{track.slug}-s{idx:02d}-"
    all_drafts = content_drafts.list_all_drafts(config.app.content_dir)
    section_drafts = [d for d in all_drafts if d.slug.startswith(prefix)]

    return templates.TemplateResponse(
        request,
        "track_section_drafts.html",
        {
            "config": config,
            "track": track,
            "section": section,
            "section_idx": idx,
            "drafts": section_drafts,
            "nav_section": "tracks",
        },
    )


@app.post("/tracks/{slug}/sections/{idx}/drafts/{kind}/{draft_slug}/promote", response_class=HTMLResponse)
def track_section_draft_promote(
    request: Request, slug: str, idx: int, kind: str, draft_slug: str
):
    """Promote one draft from _drafts/ to live."""
    from .services import content_drafts

    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)
    if not tracks_service.is_available_track(slug):
        return HTMLResponse("This track is pending audit.", status_code=409)
    try:
        content_drafts.promote(config.app.content_dir, kind, draft_slug)
    except content_drafts.DraftError as exc:
        return HTMLResponse(f"Promote failed: {exc}", status_code=400)
    return RedirectResponse(
        url=f"/tracks/{slug}/sections/{idx}/drafts", status_code=303
    )


@app.post("/tracks/{slug}/sections/{idx}/drafts/{kind}/{draft_slug}/discard", response_class=HTMLResponse)
def track_section_draft_discard(
    request: Request, slug: str, idx: int, kind: str, draft_slug: str
):
    """Permanently delete one draft. Operator's own data; safe."""
    from .services import content_drafts

    track = get_track(slug)
    if track is None:
        return HTMLResponse("Not found", status_code=404)
    if not tracks_service.is_available_track(slug):
        return HTMLResponse("This track is pending audit.", status_code=409)
    try:
        content_drafts.discard(config.app.content_dir, kind, draft_slug)
    except content_drafts.DraftError as exc:
        return HTMLResponse(f"Discard failed: {exc}", status_code=400)
    return RedirectResponse(
        url=f"/tracks/{slug}/sections/{idx}/drafts", status_code=303
    )


@app.get("/problem/{slug}", response_class=HTMLResponse)
def view_problem(request: Request, slug: str, warmup: int = 0, mode: str = ""):
    p = problem_repo.get_by_slug(slug)
    if p is None:
        return HTMLResponse("Not found", status_code=404)
    em_phases = visible_phases(p) if config.em.default_enabled else []
    em_prompts = resolve_prompts(p) if em_phases else {}
    em_mode = resolve_mode(p) if em_phases else "bypass"
    grouped_refs = group_refs_by_phase(p.references)
    interview_mode = mode == "interview" and not p.is_warmup
    # Voice picker: the dropdown above "run tests" lets the user pick
    # which named-thinker persona reviews this attempt. Default is the
    # user's saved preference, falling back to the platform default.
    settings = request.state.user_settings or {}
    preferred_voice = settings.get("preferred_voice") or "default"
    chain_step = _daily_chain_step(request, allowed_steps={4})
    return templates.TemplateResponse(
        request,
        "problem.html",
        {
            "bubbles": _bubbles_for(request, "problem"),
            "problem": p,
            "is_warmup_session": bool(warmup) or p.is_warmup,
            "config": config,
            "em_phases": em_phases,
            "em_prompts": em_prompts,
            "em_mode": em_mode,
            "grouped_refs": grouped_refs,
            "interview_mode": interview_mode,
            "voices": _review_voices(),
            "preferred_voice": preferred_voice,
            "chain_step": chain_step,
        },
    )


@app.get("/warmup", response_class=HTMLResponse)
def warmup_pick(request: Request):
    uid = request.state.user_session.user_id
    warmups = problem_repo.all_warmups()
    last_by = {}
    for a in attempt_repo.all_for_user(uid):
        if a.problem_id not in last_by:
            last_by[a.problem_id] = a
    pick = pick_warmup(warmups, last_by, config.warmup.recency_floor_days, datetime.utcnow())
    if pick is None:
        return HTMLResponse("No warmups available.", status_code=404)
    return RedirectResponse(url=f"/problem/{pick.slug}?warmup=1", status_code=303)


@app.post("/hint/{slug}", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["hint"])
def request_hint(
    request: Request,
    slug: str,
    phase: str = Form(...),
    count_so_far: int = Form(0),
    current_notes: str = Form(""),
    code: str = Form(""),
    prior_hints_json: str = Form("[]"),
):
    """Return one hint at the requested tier for a given problem+phase.
    Tier escalation is computed from `count_so_far` (the JS keeps a
    running count per phase) AND prior hint texts (so Claude can
    avoid repeating itself across calls). HTMX swaps the rendered
    HTML into the hint slot for that phase."""
    p = problem_repo.get_by_slug(slug)
    if p is None:
        return HTMLResponse("Not found", status_code=404)
    import json as _json
    try:
        prior = _json.loads(prior_hints_json) if prior_hints_json else []
        if not isinstance(prior, list):
            prior = []
        prior = [str(h) for h in prior if h]
    except _json.JSONDecodeError:
        prior = []
    result = hint_service.get_hint(
        p, phase=phase, current_notes=current_notes,
        code=code if phase in ("implement", "verify") else None,
        count_so_far=max(0, int(count_so_far)),
        prior_hints=prior,
        user_id=request.state.user_session.user_id,
    )
    # Render as compact HTML fragment for hx-swap=innerHTML.
    tier = result["tier"]
    label = result["tier_label"]
    hint = result["hint"]
    method = result.get("method", "fallback")
    method_badge = "Claude (Haiku)" if method == "claude" else "fallback"
    exhausted = result.get("exhausted", False)
    badge_class = "hint-tier--exhausted" if exhausted else f"hint-tier--{tier}"
    return HTMLResponse(
        f'<div class="hint hint--tier-{tier}">'
        f'  <header class="hint__head">'
        f'    <span class="hint__tier {badge_class}">'
        f'      tier {tier}/{hint_service.MAX_TIER} · {label}'
        f'    </span>'
        f'    <span class="hint__method muted">{method_badge}</span>'
        f'  </header>'
        f'  <p class="hint__body">{_e(hint)}</p>'
        f'</div>'
    )


def _e(s: str) -> str:
    """Minimal HTML escape for hint bodies (Claude output is untrusted)."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@app.post("/submit/{slug}", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["submit"])
def submit(
    request: Request,
    slug: str,
    code: str = Form(...),
    user_tests_code: str = Form(""),
    language: str = Form("python"),
    confidence: int = Form(3),
    looked_at_solution: int = Form(0),
    looked_at_pitfalls: int = Form(0),
    started_at_iso: str = Form(""),
    explore_notes: str = Form(""),
    brainstorm_notes: str = Form(""),
    plan_notes: str = Form(""),
    verify_notes: str = Form(""),
    time_per_phase_json: str = Form(""),
    notes_md: str = Form(""),
    interview_mode_bool: int = Form(0),
    hints_used_json: str = Form(""),
    # Voice picker on the problem page. Empty / unknown values fall
    # through to the platform default in voices_service.get().
    voice_key: str = Form(""),
    # Per-attempt initiative tagging (migration 011). Empty form value
    # falls back to settings.active_initiative; if that's also empty,
    # the attempt records initiative_slug=NULL ("unassigned").
    initiative_slug: str = Form(""),
    # Interview-mode v1 (migration 014). The form submits the budgets
    # that were active at start-time so historical review pages stay
    # accurate even when the problem's TOML budgets are retuned later.
    # cutoff is True if the JS auto-submitted because session time
    # ran out.
    phase_budgets_json: str = Form(""),
    cutoff_bool: int = Form(0),
):
    p = problem_repo.get_by_slug(slug)
    if p is None:
        return HTMLResponse("Not found", status_code=404)
    try:
        resolved_initiative = initiative_picker.resolve_initiative_slug(
            settings=request.state.user_settings,
            form_override=initiative_slug,
        )
    except initiative_picker.UnknownInitiativeError as exc:
        return HTMLResponse(str(exc), status_code=400)

    from datetime import timezone
    started_at = datetime.fromisoformat(started_at_iso) if started_at_iso else datetime.utcnow()
    # Normalize to naive UTC. The browser's Date.toISOString() yields
    # tz-aware ("…Z"); the rest of the app uses datetime.utcnow() which
    # is naive. Mixing them breaks downstream comparisons.
    if started_at.tzinfo is not None:
        started_at = started_at.astimezone(timezone.utc).replace(tzinfo=None)
    ended_at = datetime.utcnow()
    user_tests = user_tests_code if user_tests_code.strip() else None

    if language == "rust":
        if not p.rust_crate_dir:
            return HTMLResponse("This problem has no Rust crate.", status_code=400)
        crate_dir = config.app.content_dir / "rust" / p.rust_crate_dir
        result = run_rust_tests(
            crate_dir,
            code,
            config.runner.rust_timeout_seconds,
            user_tests=user_tests,
        )
    else:
        if not p.test_code_python:
            return HTMLResponse("This problem has no Python tests.", status_code=400)
        result = run_python_tests(
            code,
            p.test_code_python,
            config.runner.python_timeout_seconds,
            user_tests=user_tests,
        )

    import json as _json
    try:
        tpp = _json.loads(time_per_phase_json) if time_per_phase_json else None
        if tpp is not None and not isinstance(tpp, dict):
            tpp = None
    except _json.JSONDecodeError:
        tpp = None
    # Hints are submitted as {"plan": 2, "implement": 1, ...} by the
    # per-phase "Stuck?" affordance. Whitelist keys to EM phases and
    # ints to defend against form tampering.
    try:
        hints_raw = _json.loads(hints_used_json) if hints_used_json else None
        if not isinstance(hints_raw, dict):
            hints_raw = None
    except _json.JSONDecodeError:
        hints_raw = None
    from .models import EM_PHASES as _EM
    hints_used = (
        {k: int(v) for k, v in hints_raw.items() if k in _EM and isinstance(v, (int, float)) and int(v) > 0}
        if hints_raw else None
    ) or None

    # Phase budgets snapshot. The form sends the budgets that were
    # active when the operator clicked Start; we fall back to the
    # problem's loaded budgets if the form payload is missing or
    # malformed. Whitelist phase keys + int values to defend against
    # form tampering.
    try:
        pb_raw = _json.loads(phase_budgets_json) if phase_budgets_json else None
    except _json.JSONDecodeError:
        pb_raw = None
    if isinstance(pb_raw, dict):
        phase_budgets_snapshot = {
            k: int(v) for k, v in pb_raw.items()
            if k in _EM and isinstance(v, (int, float)) and int(v) >= 0
        }
        if set(phase_budgets_snapshot.keys()) != set(_EM):
            # Partial payload — prefer the problem's loaded budgets
            # over a half-filled snapshot.
            phase_budgets_snapshot = dict(p.phase_budgets) if p.phase_budgets else None
    else:
        phase_budgets_snapshot = dict(p.phase_budgets) if p.phase_budgets else None

    attempt = Attempt(
        id=None,
        user_id=request.state.user_session.user_id,
        problem_id=p.id,
        problem_version=p.version,
        started_at=started_at,
        ended_at=ended_at,
        language_used=language,
        final_code=code,
        solved_without_lookup=(not bool(looked_at_solution)) and result.passed,
        confidence_1_to_5=confidence,
        time_to_first_edit_seconds=None,
        edit_count=0,
        looked_at_solution=bool(looked_at_solution),
        looked_at_pitfalls=bool(looked_at_pitfalls),
        test_passed=result.passed,
        test_output=result.output[-8000:],
        notes_md=notes_md.strip() or None,
        explore_notes=explore_notes or None,
        brainstorm_notes=brainstorm_notes or None,
        plan_notes=plan_notes or None,
        verify_notes=verify_notes or None,
        time_per_phase=tpp,
        interview_mode=bool(interview_mode_bool) and not p.is_warmup,
        hints_used=hints_used,
        user_tests_code=user_tests,
        initiative_slug=resolved_initiative,
        # Migration 014 (interview-mode v1) — only meaningful for
        # interview-mode attempts. Free-practice attempts can still
        # carry budgets (the form sends them either way) but cutoff
        # only fires in interview mode.
        phase_budgets=phase_budgets_snapshot,
        cutoff=bool(cutoff_bool) and bool(interview_mode_bool),
    )
    attempt_id = attempt_repo.insert(attempt)
    attempt.id = attempt_id

    from .services import problem_schedule

    settings = dict(_user_settings(attempt.user_id))
    previous_schedule = settings.get("problem_schedule") or {}
    schedule = problem_schedule.apply_attempt(previous_schedule, attempt, now=ended_at)
    if schedule != previous_schedule:
        settings["problem_schedule"] = schedule
        _save_user_settings(attempt.user_id, settings)

    # LLM review. Skipped silently if ANTHROPIC_API_KEY isn't set.
    review = None
    if not p.is_warmup:
        from .models import AttemptReview
        # Voice: per-submission form override, then user-preferred,
        # then platform default. voices_service.get() defends against
        # unknown keys so we don't need to validate here.
        chosen_voice = voice_key.strip() or (request.state.user_settings or {}).get("preferred_voice") or "default"
        review_result = review_service.review_attempt(
            p, attempt,
            voice_key=chosen_voice,
            user_id=request.state.user_session.user_id,
        )
        review = AttemptReview(
            id=None,
            attempt_id=attempt_id,
            method=review_result["method"],
            model_used=review_result["model_used"],
            summary_md=review_result["summary_md"],
            per_phase=review_result["per_phase"],
            overall_score=review_result["overall_score"],
            error_text=review_result["error_text"],
            created_at=datetime.utcnow(),
        )
        attempt_review_repo.insert(review)

    if not p.is_warmup:
        state = review_repo.get(request.state.user_session.user_id, p.id)
        from .models import ReviewState as RS
        new_state = RS(
            user_id=request.state.user_session.user_id,
            problem_id=p.id,
            last_attempt_id=attempt_id,
            last_due_score=0.0,
            next_due_at=None,
            lapses=(state.lapses if state else 0) + (0 if result.passed else 1),
            ease_factor=None,
        )
        review_repo.upsert(new_state)

    return templates.TemplateResponse(
        request,
        "_result.html",
        {
            "problem": p,
            "passed": result.passed,
            "hidden_passed": result.hidden_passed,
            "user_passed": result.user_passed,
            "output": result.output,
            "review": review,
            # Only the inserted attempt acknowledges these exact stored strings.
            "autosave_confirmed": {
                "user": attempt.user_id,
                "path": f"/problem/{slug}",
                "form": "solve-form",
                "cutoff": attempt.cutoff,
                "fields": {
                    "code": attempt.final_code,
                    "user_tests_code": attempt.user_tests_code or "",
                    "explore_notes": attempt.explore_notes or "",
                    "brainstorm_notes": attempt.brainstorm_notes or "",
                    "plan_notes": attempt.plan_notes or "",
                    "verify_notes": attempt.verify_notes or "",
                    "notes_md": attempt.notes_md or "",
                },
            },
        },
    )


# --- Onboarding + adaptive assessment ---------------------------------------


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request):
    return templates.TemplateResponse(request, "onboarding.html", {"config": config})


@app.post("/onboarding/skip", response_class=HTMLResponse)
def onboarding_skip(request: Request):
    uid = request.state.user_session.user_id
    settings = _user_settings(uid)
    settings["onboarding_skipped"] = True
    _save_user_settings(uid, settings)
    # ?toast=ramp_intro fires a one-shot orientation banner on the
    # next home render so the user understands why everything looks
    # easy. Disappears as soon as they navigate anywhere else.
    return RedirectResponse(url="/?toast=ramp_intro", status_code=303)


@app.post("/onboarding/tracks", response_class=HTMLResponse)
def onboarding_tracks(request: Request):
    uid = request.state.user_session.user_id
    settings = _user_settings(uid)
    settings["onboarding_skipped"] = True
    _save_user_settings(uid, settings)
    return RedirectResponse(url="/tracks", status_code=303)


@app.post("/onboarding/start", response_class=HTMLResponse)
def onboarding_start(request: Request):
    uid = request.state.user_session.user_id
    run_id = assessment_repo.start_run(uid)
    return RedirectResponse(url=f"/assess/{run_id}", status_code=303)


@app.get("/assess/{run_id}", response_class=HTMLResponse)
def assess_question(request: Request, run_id: int):
    uid = request.state.user_session.user_id
    run = assessment_repo.get_run(run_id, user_id=uid)
    if run is None or run.user_id != uid:
        return HTMLResponse("Run not found.", status_code=404)
    if run.completed_at is not None:
        return RedirectResponse(url=f"/assess/{run_id}/result", status_code=303)
    responses = assessment_repo.responses_for_run(run_id, user_id=uid)
    answered_ids = [r.question_id for r in responses]
    next_q = assess_service.pick_next(answered_ids)
    if next_q is None:
        assessment_repo.complete_run(run_id, user_id=uid)
        return RedirectResponse(url=f"/assess/{run_id}/result", status_code=303)
    return templates.TemplateResponse(
        request,
        "assess_question.html",
        {
            "run_id": run_id,
            "question": next_q,
            "answered_count": len(answered_ids),
            "max_questions": assess_service.MAX_QUESTIONS,
            "min_questions": assess_service.MIN_QUESTIONS,
        },
    )


@app.post("/assess/{run_id}/answer", response_class=HTMLResponse)
def assess_answer(
    request: Request,
    run_id: int,
    question_id: str = Form(...),
    answer_index: int = Form(...),
):
    uid = request.state.user_session.user_id
    run = assessment_repo.get_run(run_id, user_id=uid)
    if run is None or run.user_id != uid:
        return HTMLResponse("Run not found.", status_code=404)
    if run.completed_at is not None:
        return RedirectResponse(url=f"/assess/{run_id}/result", status_code=303)
    try:
        assessment_repo.record_response(
            run_id, question_id, answer_index, user_id=uid,
        )
    except ValueError:
        return HTMLResponse("Answer does not match the current question.", status_code=409)
    return RedirectResponse(url=f"/assess/{run_id}", status_code=303)


@app.get("/assess/{run_id}/result", response_class=HTMLResponse)
def assess_result(request: Request, run_id: int):
    uid = request.state.user_session.user_id
    run = assessment_repo.get_run(run_id, user_id=uid)
    if run is None or run.user_id != uid:
        return HTMLResponse("Run not found.", status_code=404)
    if run.completed_at is None:
        return RedirectResponse(url=f"/assess/{run_id}", status_code=303)
    scores, assessment_coverage = _assessment_snapshot(uid, run)
    suggestion = _suggested_problem_for_scores(uid, scores)

    # Recommend a daily mode from the results, and adopt it as the
    # default ONLY if the user hasn't chosen one themselves — a retake
    # never silently overrides an explicit /settings choice.
    recommended_mode = assess_service.recommended_daily_mode(scores)
    settings = _user_settings(uid)
    if "daily_mode" not in settings:
        if recommended_mode == "remix":
            settings["daily_mode"] = "remix"
            _save_user_settings(uid, settings)
        # "path" is the absent-key default — nothing to store.
    mode_label = {k or "path": label for k, label, _ in DAILY_MODES}[
        recommended_mode
    ]

    return templates.TemplateResponse(
        request,
        "assess_result.html",
        {
            "run": run,
            "skill_scores": scores,
            "assessment_coverage": assessment_coverage,
            "axis_labels": assess_service.AXIS_LABELS,
            "suggestion": suggestion,
            "recommended_mode": recommended_mode,
            "recommended_mode_label": mode_label,
        },
    )


@app.get("/assess/{run_id}/complete", response_class=HTMLResponse)
def assess_complete(request: Request, run_id: int):
    """Finalize onboarding and route through the imposter intercept when active."""
    uid = request.state.user_session.user_id
    run = assessment_repo.get_run(run_id, user_id=uid)
    if run is None or run.user_id != uid:
        return HTMLResponse("Run not found.", status_code=404)
    if run.completed_at is None:
        return RedirectResponse(url=f"/assess/{run_id}", status_code=303)

    settings = _user_settings(uid)
    scores, _coverage = _assessment_snapshot(uid, run)
    signal = _detect_and_save_imposter_signal(
        uid=uid,
        run_id=run_id,
        assessment_scores=scores,
        settings=settings,
    )

    if signal.state != "none":
        return RedirectResponse(url="/onboarding/imposter-intercept", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.get("/onboarding/imposter-intercept", response_class=HTMLResponse)
def onboarding_imposter_intercept(request: Request):
    uid = request.state.user_session.user_id
    settings = request.state.user_settings or {}
    signal = settings.get("imposter_signal")
    if not isinstance(signal, dict) or signal.get("state") in (None, "none"):
        return RedirectResponse(url="/", status_code=303)

    latest_assessment = assessment_repo.latest_completed(uid)
    assessment_scores, _coverage = _assessment_snapshot(uid, latest_assessment)
    credential_scores = _latest_credential_scores(uid)
    # Stored severity may include formerly zero-filled unknown axes. Reuse
    # the detector on today's measured overlap without rewriting history.
    gap_signal = imposter_service.detect(
        quiz_answers=[],
        assessment_scores=assessment_scores,
        credential_scores=credential_scores,
    )
    not_sure_rate = signal.get("not_sure_rate", 0.0)
    not_sure_state = "none"
    if type(not_sure_rate) in (int, float) and 0.0 <= not_sure_rate <= 1.0:
        if not_sure_rate >= imposter_service.DEFAULT_NOT_SURE_STRONG:
            not_sure_state = "strong"
        elif not_sure_rate >= imposter_service.DEFAULT_NOT_SURE_MILD:
            not_sure_state = "mild"
    current_states = (gap_signal.state, not_sure_state)
    signal_state = "strong" if "strong" in current_states else "mild" if "mild" in current_states else "none"
    if signal_state == "none":
        return RedirectResponse(url="/", status_code=303)
    has_credential_gap = gap_signal.state != "none"
    axis_rows = _imposter_axes_for_intercept(
        signal=gap_signal.as_dict(),
        assessment_scores=assessment_scores,
        credential_scores=credential_scores,
    )
    credential_phrase = (
        "much lower."
        if gap_signal.state == "strong"
        else "lower than what your credentials suggest."
    )

    return templates.TemplateResponse(
        request,
        "onboarding_imposter_intercept.html",
        {
            "axis_rows": axis_rows,
            "has_credential_gap": has_credential_gap,
            "credential_phrase": credential_phrase,
            "signal_state": signal_state,
        },
    )


# Timezone list comes from stdlib zoneinfo (IANA tzdb). Loaded once at
# import; the list doesn't change between restarts.
from zoneinfo import (
    ZoneInfo,
    ZoneInfoNotFoundError,
    available_timezones as _zoneinfo_available,
)
_AVAILABLE_TZS: list[str] = sorted(_zoneinfo_available())
_AVAILABLE_TZS_SET = set(_AVAILABLE_TZS)
# Surfaced as quick picks at the top of the dropdown. Keep short so the
# UI doesn't grow unbounded; users can still type any of the 598 zones.
_COMMON_TZS: list[str] = [
    "UTC",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
]


def _build_tz_groups() -> list[tuple[str, list[str]]]:
    """Return [(group_label, [zones])] for a native <select> with optgroups.

    The first group is the curated quick-picks (in our chosen order, not
    alphabetical). The rest are alphabetical by region prefix
    (Africa/America/Asia/...). Etc/* gets its own bucket at the end since
    it's a grab-bag of UTC offsets and historical names that users
    rarely want unless they really mean it.
    """
    groups: dict[str, list[str]] = {}
    etc: list[str] = []
    for zone in _AVAILABLE_TZS:
        if "/" not in zone:
            # Bare names like "UTC", "GMT", "EST" — bucket with Etc/*
            etc.append(zone)
            continue
        region, _, _ = zone.partition("/")
        if region == "Etc":
            etc.append(zone)
            continue
        groups.setdefault(region, []).append(zone)
    out: list[tuple[str, list[str]]] = []
    out.append(("Common", _COMMON_TZS))
    for region in sorted(groups):
        out.append((region, groups[region]))
    if etc:
        out.append(("Etc / UTC offsets", sorted(etc)))
    return out


_TZ_GROUPS = _build_tz_groups()


# Selectable UI themes, as (key, label, blurb).
#
# A theme overrides only the ~9 shared color primitives, in
# `static/css/main.css` under `:root[data-theme="<key>"]`. The empty key
# is the built-in dark default and renders no attribute at all.
#
# Adding one: author the block, then add a row here. See docs/THEMES.md
# for the token contract, the contrast floors, and a generation prompt.
THEMES: tuple[tuple[str, str, str], ...] = (
    ("", "Dark", "The default bench palette — near-black, amber accent."),
    (
        "hyperbolic",
        "Hyperbolic Time Chamber",
        "An endless white void. Light, with a vaporwave orchid accent.",
    ),
)

# Whitelist for the save handler — keeps a hand-crafted POST from
# injecting an arbitrary value into the rendered data-theme attribute.
THEME_KEYS = frozenset(key for key, _, _ in THEMES if key)


# Daily content modes, as (key, label, blurb). The empty key = "path",
# the built-in default: the scheduler's deterministic progression, which
# naturally re-queues unfinished work (completion-gated picks stay put
# until done). "remix" shuffles the ranked queue for interleaved review.
# The onboarding assessment recommends one (assessment.recommended_daily_mode);
# the user can override any time in /settings.
DAILY_MODES: tuple[tuple[str, str, str], ...] = (
    (
        "",
        "Path",
        "Steady progression — a deterministic sequence that queues what "
        "you didn't finish. Recommended while learning new material.",
    ),
    (
        "remix",
        "Remix",
        "Shuffled order over the same smart scoring — interleaved "
        "review. Recommended once you're solid across the axes.",
    ),
)
DAILY_MODE_KEYS = frozenset(key for key, _, _ in DAILY_MODES if key)


def _validate_tz(s: str) -> bool:
    """Empty (= system default) is OK; otherwise must be an IANA zone."""
    s = (s or "").strip()
    if not s:
        return True
    return s in _AVAILABLE_TZS_SET


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, profile_error: str = "", profile_tz: str = "", llm_error: str = "", linear_error: str = ""):
    from .services import onboarding_bubbles as _ob_service

    uid = request.state.user_session.user_id
    latest = assessment_repo.latest_completed(uid)
    settings = _user_settings(uid)
    a11y = settings.get("a11y", {})
    # When the POST handler bounces back with a validation error, it
    # passes the rejected value via query string so the form can
    # repopulate it (no session/flash plumbing for a single-user app).
    error_fields = set(profile_error.split(",")) if profile_error else set()
    # Active-initiative picker: surface the active set so the template
    # can render a dropdown. Done/dormant are excluded — see
    # initiative_picker.resolve_initiative_slug for why (they're not
    # valid write-targets).
    all_inits = initiatives_service.load_initiatives()
    active_initiatives = [
        {"slug": i.slug, "title": i.title}
        for i in all_inits
        if i.status == "active"
    ]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "latest_run": latest,
            "config": config,
            "axis_labels": assess_service.AXIS_LABELS,
            "skill_scores": _assessment_snapshot(uid, latest)[0],
            "nav_section": "settings",
            "display_name": settings.get("display_name"),
            "display_tz": profile_tz or settings.get("display_tz"),
            # `session_email` is the GitHub-OAuth identity from the JWT.
            # Use it for any "signed in as" / profile email UI copy.
            "session_email": request.state.user_session.email,
            "tz_options": _AVAILABLE_TZS,
            "tz_common": _COMMON_TZS,
            "tz_groups": _TZ_GROUPS,
            "profile_errors": error_fields,
            "hyperfocus": bool(settings.get("hyperfocus")),
            "a11y": {
                "reduce_motion": bool(a11y.get("reduce_motion")),
                "larger_text": bool(a11y.get("larger_text")),
                "high_contrast": bool(a11y.get("high_contrast")),
            },
            "active_initiative": settings.get("active_initiative") or "",
            "active_initiatives": active_initiatives,
            "theme": settings.get("theme") or "",
            "themes": THEMES,
            "glass_level": settings.get("glass_level", 50),
            "daily_mode": settings.get("daily_mode") or "",
            "daily_modes": DAILY_MODES,
            **_llm_settings_context(uid),
            "llm_error": llm_error if llm_error in ("key", "url") else "",
            **_linear_settings_context(uid),
            "linear_error": linear_error[:300],
            "bubbles": _bubbles_for(request, "settings"),
            "tips_enabled": _ob_service.tips_enabled(settings),
        },
    )


@app.post("/settings/profile", response_class=HTMLResponse)
def settings_save_profile(
    request: Request,
    display_name: str = Form(""),
    display_tz: str = Form(""),
):
    uid = request.state.user_session.user_id
    # Validate before touching state. Collect *all* field errors so the
    # user sees a complete diagnosis instead of fixing one and finding
    # another on retry.
    errors: list[str] = []
    if not _validate_tz(display_tz):
        errors.append("tz")
    if errors:
        # PRG with a query string carrying the error + bad values, so a
        # refresh of the GET doesn't resubmit the invalid POST.
        from urllib.parse import urlencode
        qs = urlencode({
            "profile_error": ",".join(errors),
            "profile_tz": display_tz.strip(),
        })
        return RedirectResponse(url=f"/settings?{qs}", status_code=303)
    s = _user_settings(uid)
    s["display_name"] = display_name.strip() or None
    # Keep `display_email` untouched in settings_json for potential
    # future hosted/shared mode; local profile UI is GitHub-managed.
    s["display_tz"] = display_tz.strip() or None
    _save_user_settings(uid, s)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/initiative", response_class=HTMLResponse)
def settings_save_initiative(
    request: Request,
    active_initiative: str = Form(""),
):
    """Persist the operator's preferred default initiative.

    The empty string means "no default" — write paths then record
    initiative_slug=NULL. Any non-empty value must match an active
    initiative; we reject silently-stale entries here so settings
    never carries an invalid slug.

    Per the per-attempt-tagging proposal, this is also the slug the
    /focus ★ pin reads (which it already did before this PR — adding
    the UI to set it is the new piece).
    """
    uid = request.state.user_session.user_id
    chosen = (active_initiative or "").strip()

    if chosen:
        # Validate against active initiatives. Stricter than the picker:
        # we want to refuse to PERSIST a stale slug. The picker is
        # forgiving on reads (returns None if stale); persistence is
        # the right boundary to be strict at.
        all_inits = initiatives_service.load_initiatives()
        active_slugs = {i.slug for i in all_inits if i.status == "active"}
        if chosen not in active_slugs:
            return HTMLResponse(
                f"unknown or non-active initiative slug: {chosen!r}",
                status_code=400,
            )

    s = _user_settings(uid)
    if chosen:
        s["active_initiative"] = chosen
    else:
        # Empty form value clears any prior default.
        s.pop("active_initiative", None)
    _save_user_settings(uid, s)
    return RedirectResponse(url="/settings", status_code=303)


def _linear_settings_context(uid: str) -> dict:
    """Linear panel state. Soft-fails to disconnected — the settings
    page must render even if this row is unreadable."""
    try:
        cfg = linear_config_repo.get(uid)
    except Exception:  # noqa: BLE001
        cfg = None
    return {
        "linear_connected": bool(cfg and cfg.vault_secret_id),
        "linear_team_name": (cfg.team_name or "") if cfg else "",
        "linear_account_label": (cfg.account_label or "") if cfg else "",
    }


@app.post("/settings/linear", response_class=HTMLResponse)
def settings_save_linear(
    request: Request,
    linear_api_key: str = Form(""),
    linear_team_key: str = Form(""),
):
    """Connect Linear (v2.1 slice 6). Verifies the key live, resolves
    the team by its key ("BEN") — or auto-selects when the account has
    exactly one — and stores the key in Vault. The key never
    round-trips to the page."""
    from urllib.parse import quote

    from .services import linear_sync

    uid = request.state.user_session.user_id
    key = (linear_api_key or "").strip()
    team_key = (linear_team_key or "").strip().upper()
    if not key or len(key) > 512:
        return RedirectResponse(url="/settings?linear_error=key", status_code=303)
    try:
        info = linear_sync.verify_key(key)
    except linear_sync.LinearSyncError as e:
        return RedirectResponse(
            url=f"/settings?linear_error={quote(str(e))}", status_code=303
        )
    teams = info["teams"]
    team = None
    if team_key:
        team = next((t for t in teams if t["key"].upper() == team_key), None)
        if team is None:
            return RedirectResponse(
                url=f"/settings?linear_error={quote('No team with key ' + team_key + ' is visible to that API key.')}",
                status_code=303,
            )
    elif len(teams) == 1:
        team = teams[0]
    else:
        names = ", ".join(f"{t['key']} ({t['name']})" for t in teams[:8])
        return RedirectResponse(
            url=f"/settings?linear_error={quote('Multiple teams visible — enter one team key: ' + names)}",
            status_code=303,
        )
    linear_config_repo.set_config(
        uid,
        api_key=key,
        team_id=team["id"],
        team_name=f"{team['key']} — {team['name']}",
        account_label=info["account_label"],
    )
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/linear/disconnect", response_class=HTMLResponse)
def settings_linear_disconnect(request: Request):
    uid = request.state.user_session.user_id
    linear_config_repo.delete_for(uid)
    return RedirectResponse(url="/settings", status_code=303)


def _llm_settings_context(uid: str) -> dict:
    """AI-provider panel state. Soft-fails to the bench default — the
    settings page must render even if this row is unreadable. Key
    material is never in this context; `key_hint` is the last 4."""
    try:
        cfg = llm_config_repo.get(uid)
    except Exception:  # noqa: BLE001
        cfg = None
    return {
        "llm_provider": cfg.provider if cfg else "bench",
        "llm_key_hint": (cfg.key_hint or "") if cfg else "",
        "llm_base_url": (cfg.base_url or "") if cfg else "",
    }


@app.post("/settings/llm", response_class=HTMLResponse)
def settings_save_llm(
    request: Request,
    llm_provider: str = Form("bench"),
    llm_api_key: str = Form(""),
    llm_base_url: str = Form(""),
):
    """Persist the user's AI-provider choice (Bench v2 BYO-key).

    'bench' clears any stored key (vault secret included). The other
    providers store/rotate the key in Supabase Vault; an empty key
    field on an existing config keeps the current key so provider or
    URL edits don't force re-entry. The key never round-trips to the
    page — only its last-4 hint does."""
    from .repositories.llm_config_repository import PROVIDERS

    uid = request.state.user_session.user_id
    provider = (llm_provider or "bench").strip()
    if provider not in PROVIDERS:
        return HTMLResponse("Bad provider", status_code=400)

    if provider == "bench":
        llm_config_repo.delete_for(uid)
        return RedirectResponse(url="/settings", status_code=303)

    key = (llm_api_key or "").strip()
    base_url = (llm_base_url or "").strip() if provider == "omniroute" else ""
    existing = None
    try:
        existing = llm_config_repo.get(uid)
    except Exception:  # noqa: BLE001
        existing = None
    has_stored_key = bool(existing and existing.vault_secret_id)
    if not key and not has_stored_key:
        return RedirectResponse(url="/settings?llm_error=key", status_code=303)
    if provider == "omniroute":
        if not base_url.startswith("https://"):
            return RedirectResponse(url="/settings?llm_error=url", status_code=303)
        # Origin only — the SDK appends /v1/messages itself.
        base_url = base_url.rstrip("/")
    if len(key) > 512:
        return RedirectResponse(url="/settings?llm_error=key", status_code=303)

    llm_config_repo.set_config(
        uid,
        provider=provider,
        api_key=key or None,
        base_url=base_url or None,
    )
    return RedirectResponse(url="/settings", status_code=303)


def _bubbles_for(request: Request, surface: str):
    """SurfaceState for this page's onboarding strips, or None — a
    bubble must never be the reason a page 500s."""
    from .services import onboarding_bubbles as ob

    try:
        uid = request.state.user_session.user_id
        return ob.bubble_state(_user_settings(uid), surface)
    except Exception:  # noqa: BLE001
        return None


def _bubbles_next_url(raw: str) -> str:
    """The no-JS fallback redirects wherever the form says — but only
    to a local path (open-redirect guard)."""
    nxt = (raw or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        return "/"
    return nxt


@app.post("/settings/mira-voice", response_class=HTMLResponse)
def settings_mira_voice(request: Request, enabled: str = Form("0")):
    """Persist the spoken-replies preference (v2.1 voice PTT). Same
    204-for-fetch shape as /settings/glass; the no-JS fallback is the
    toggle simply not persisting (audio is an enhancement, never the
    only path)."""
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    if enabled == "1":
        s["mira_speak_replies"] = True
    else:
        s.pop("mira_speak_replies", None)
    _save_user_settings(uid, s)
    if request.headers.get("X-Requested-With") == "fetch":
        return HTMLResponse(status_code=204, content="")
    return RedirectResponse(url="/mira", status_code=303)


@app.post("/settings/bubbles", response_class=HTMLResponse)
def settings_bubbles_dismiss(
    request: Request,
    surface: str = Form(""),
    tip: str = Form(""),
    action: str = Form("seen"),
    next_url: str = Form("/", alias="next"),
):
    """Advance or skip the first-run tour (design handoff 1b). HTMX
    gets two out-of-band slot fragments back; the no-JS form gets a
    303 to the page it came from, which re-renders the next tip
    server-side. Same endpoint, both paths."""
    from .services import onboarding_bubbles as ob

    uid = request.state.user_session.user_id
    try:
        updated = ob.mark(_user_settings(uid), surface, tip, action)
    except ValueError:
        return HTMLResponse("Bad bubble dismiss", status_code=400)
    _save_user_settings(uid, updated)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "_bubbles_oob.html",
            {
                "surface": surface,
                "dismissed_anchor": ob.anchor_of(surface, tip),
                "bubble_next_url": _bubbles_next_url(next_url),
                "bubbles": ob.bubble_state(updated, surface),
            },
        )
    return RedirectResponse(url=_bubbles_next_url(next_url), status_code=303)


@app.post("/settings/bubbles/enabled", response_class=HTMLResponse)
def settings_bubbles_enabled(
    request: Request,
    enabled: str = Form("0"),
    next_url: str = Form("/settings", alias="next"),
):
    from .services import onboarding_bubbles as ob

    uid = request.state.user_session.user_id
    _save_user_settings(uid, ob.set_enabled(_user_settings(uid), enabled == "1"))
    if request.headers.get("HX-Request"):
        return HTMLResponse(status_code=204, content="")
    return RedirectResponse(url=_bubbles_next_url(next_url), status_code=303)


@app.post("/settings/theme", response_class=HTMLResponse)
def settings_save_theme(request: Request, theme: str = Form("")):
    """Persist the user's chosen UI theme.

    Stored as a bare `theme` key in settings_json and rendered as
    `data-theme` on <html> by base.html. Empty string = the default
    (dark), which needs no attribute. Unknown values are rejected so a
    hand-crafted POST can't inject an arbitrary attribute value.
    """
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    choice = (theme or "").strip()
    if choice and choice not in THEME_KEYS:
        choice = ""
    if choice:
        s["theme"] = choice
    else:
        s.pop("theme", None)
    _save_user_settings(uid, s)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/glass", response_class=HTMLResponse)
def settings_save_glass(request: Request, glass_level: int = Form(50)):
    """FRONTEND-1b: persist the shared glassiness level (0-100).

    One value for every surface (operator decision on the spec's open
    question). 50 = the shipped default look; absent key = same. Values
    clamp rather than reject — a slider can't express intent worth
    erroring over. Returns 204 for the island's fetch() (marked with
    X-Requested-With) and redirects for the no-JS form fallback."""
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    level = max(0, min(100, glass_level))
    if level == 50:
        s.pop("glass_level", None)  # default = absent key
    else:
        s["glass_level"] = level
    _save_user_settings(uid, s)
    if request.headers.get("X-Requested-With") == "fetch":
        return HTMLResponse(status_code=204, content="")
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/daily-mode", response_class=HTMLResponse)
def settings_save_daily_mode(request: Request, daily_mode: str = Form("")):
    """Persist the daily content mode ("path" = default = absent key,
    "remix" = shuffled review). Unknown values are rejected."""
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    choice = (daily_mode or "").strip()
    if choice and choice not in DAILY_MODE_KEYS:
        choice = ""
    if choice:
        s["daily_mode"] = choice
    else:
        s.pop("daily_mode", None)
    _save_user_settings(uid, s)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/hyperfocus", response_class=HTMLResponse)
def settings_save_hyperfocus(
    request: Request,
    enabled: int = Form(0),
    next: str = Form(""),
):
    """BEN-142 — toggle the distraction-stripped shell.

    Takes an optional `next` so the exit control in the header can put the
    user back where they were. Without it, leaving hyperfocus from the middle
    of a problem would dump them on /settings, which is exactly the kind of
    context loss the mode exists to prevent.

    `next` is treated as untrusted: same-origin relative paths only. A form
    field that feeds a redirect is an open-redirect the moment it isn't.
    """
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    s["hyperfocus"] = bool(enabled)
    _save_user_settings(uid, s)

    dest = (next or "").strip()
    if not dest.startswith("/") or dest.startswith("//"):
        dest = "/settings"
    return RedirectResponse(url=dest, status_code=303)


@app.post("/settings/accessibility", response_class=HTMLResponse)
def settings_save_a11y(
    request: Request,
    reduce_motion: int = Form(0),
    larger_text: int = Form(0),
    high_contrast: int = Form(0),
):
    uid = request.state.user_session.user_id
    s = _user_settings(uid)
    s["a11y"] = {
        "reduce_motion": bool(reduce_motion),
        "larger_text": bool(larger_text),
        "high_contrast": bool(high_contrast),
    }
    _save_user_settings(uid, s)
    return RedirectResponse(url="/settings", status_code=303)


# --- Credentials upload + skill-gap evaluation ------------------------------


@app.get("/credentials", response_class=HTMLResponse)
def credentials_index(request: Request):
    # Legacy route kept for transition; canonical surface is /aim.
    return RedirectResponse(url="/aim#evidence", status_code=302)


@app.post("/credentials", response_class=HTMLResponse)
async def credentials_upload(request: Request, file: UploadFile = File(...)):
    uid = request.state.user_session.user_id
    filename = (file.filename or "").strip()
    if (not filename or filename in {".", ".."} or len(filename) > 200
            or "/" in filename or "\\" in filename
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
        return HTMLResponse("Use a filename without directory paths or control characters.", status_code=400)
    raw = await file.read(10 * 1024 * 1024 + 1)
    if not raw:
        return HTMLResponse("Empty file.", status_code=400)
    if len(raw) > 10 * 1024 * 1024:
        return HTMLResponse("File too large (10MB max).", status_code=413)

    import hashlib
    sha = hashlib.sha256(raw).hexdigest()

    run_id = credentials_repo.start_run(uid)
    # Store the file on disk under data/credentials/<uid>/<run_id>/
    storage = REPO_ROOT / "data" / "credentials" / str(uid) / str(run_id)
    storage.mkdir(parents=True, exist_ok=True)
    # The supplied name is display metadata; only a generated name controls storage.
    from uuid import uuid4
    (storage / (uuid4().hex + Path(filename).suffix.lower())).write_bytes(raw)

    extracted = credentials_service.extract_text(filename, raw)
    credentials_repo.record_file(
        run_id=run_id,
        filename=filename,
        content_type=file.content_type,
        byte_size=len(raw),
        sha256=sha,
        extracted_text=extracted,
    )
    credentials_repo.complete_run(run_id, "uploaded")
    return RedirectResponse(url=f"/credentials/{run_id}", status_code=303)


@app.get("/credentials/{run_id}", response_class=HTMLResponse)
def credentials_review(request: Request, run_id: int):
    uid = request.state.user_session.user_id
    run = credentials_repo.get_run(run_id)
    if run is None or run.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    files = credentials_repo.files_for_run(run_id)
    assessment = credentials_repo.latest_assessment(run_id)
    return templates.TemplateResponse(
        request,
        "credentials_review.html",
        {
            "config": config,
            "run": run,
            "files": files,
            "assessment": assessment,
            "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "nav_section": "aim",
        },
    )


@app.post("/credentials/{run_id}/analyze", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["credentials_analyze"])
def credentials_analyze(request: Request, run_id: int):
    uid = request.state.user_session.user_id
    run = credentials_repo.get_run(run_id)
    if run is None or run.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    files = credentials_repo.files_for_run(run_id)
    text = "\n\n---\n\n".join((f.extracted_text or "") for f in files)
    result = credentials_service.analyze(text, user_id=uid)
    credentials_repo.save_assessment(
        run_id=run_id,
        inferred_axis_scores=result["axis_scores"],
        summary_md=result["summary"],
        rationale=result["rationale"],
        method=result["method"],
        model_used=result["model_used"],
    )
    # Stash the iac profile on the user's settings_json so the JD
    # detail page can render the side-by-side block without joining
    # against credential_assessments. The schema is intentionally a
    # free-form bag (no migration needed).
    iac = result.get("iac_profile")
    if iac:
        settings = _user_settings(uid)
        settings["iac_profile"] = iac
        if result.get("iac_evidence_md"):
            settings["iac_evidence_md"] = result["iac_evidence_md"]
        _save_user_settings(uid, settings)
    return RedirectResponse(url=f"/credentials/{run_id}/gap", status_code=303)


@app.get("/credentials/{run_id}/gap", response_class=HTMLResponse)
def credentials_gap(request: Request, run_id: int):
    uid = request.state.user_session.user_id
    run = credentials_repo.get_run(run_id)
    if run is None or run.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    assessment = credentials_repo.latest_assessment(run_id)
    if assessment is None:
        return RedirectResponse(url=f"/credentials/{run_id}", status_code=303)
    user_assessment = assessment_repo.latest_completed(uid)
    user_scores, _coverage = _assessment_snapshot(uid, user_assessment)

    gap = credentials_service.compute_gap(assessment.inferred_axis_scores, user_scores)
    # The existing comparison formula fills missing axes with zero; only
    # measured assessment axes can support a displayed gap or suggestion.
    gap = {axis: value for axis, value in gap.items() if axis in user_scores}
    top_gap_axes = credentials_service.top_gaps(gap, n=3)
    attempted_ids = {a.problem_id for a in attempt_repo.all_for_user(uid)}
    suggestions: list = []
    for axis in top_gap_axes:
        for slug in assess_service.suggested_slugs_for_axis(axis):
            p = problem_repo.get_by_slug(slug)
            if p is None or p.id in attempted_ids:
                continue
            suggestions.append({
                "axis": axis,
                "axis_label": assess_service.AXIS_LABELS.get(axis, axis),
                "problem": p,
                "gap": gap[axis],
            })
            break  # one suggestion per axis

    return templates.TemplateResponse(
        request,
        "credentials_gap.html",
        {
            "config": config,
            "run": run,
            "assessment": assessment,
            "credential_scores": assessment.inferred_axis_scores,
            "user_scores": user_scores,
            "unknown_axes": tuple(axis for axis in assess_service.AXES if axis not in user_scores),
            "axis_labels": assess_service.AXIS_LABELS,
            "gap": gap,
            "top_gap_axes": top_gap_axes,
            "suggestions": suggestions,
            "nav_section": "aim",
        },
    )


# --- JDs: paste / parse / activate ------------------------------------------


@app.get("/jds", response_class=HTMLResponse)
def jds_index(request: Request):
    # Legacy route kept for transition; canonical surface is /aim.
    return RedirectResponse(url="/aim#aim", status_code=302)


@app.post("/jds", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["jd_parse"])
def jds_create(request: Request, source_text: str = Form(...), title: str = Form(""), org: str = Form("")):
    uid = request.state.user_session.user_id
    if not source_text.strip():
        return HTMLResponse("Empty JD.", status_code=400)
    # URL-paste path: if the user pasted only a URL, fetch the listing
    # and use the fetched body + extracted (title, org) metadata. We
    # fall through to the literal-text path if the fetch fails (offline,
    # auth-walled board, malformed HTML, etc.).
    url_only = jd_service.looks_like_url(source_text)
    fetched_title: str | None = None
    fetched_org: str | None = None
    if url_only:
        fetched = jd_service.fetch_from_url(url_only)
        if fetched is not None:
            source_text = fetched["source_text"]
            fetched_title = fetched["title"]
            fetched_org = fetched["org"]
    parsed = jd_service.parse(source_text, user_id=request.state.user_session.user_id)
    auto_title, auto_org = jd_service.derive_title(source_text)
    from .models import JD
    # Precedence: user-typed > URL-fetched metadata > URL-slug derivation
    # (only relevant when the user pasted a URL and the fetch failed) >
    # first-line heuristic. The URL-slug step prevents the raw URL from
    # ending up as the displayed title on home / settings / readiness.
    slug_title = jd_service.title_from_url(url_only) if url_only else None
    resolved_title = (title.strip() or fetched_title or slug_title or auto_title)[:200]
    resolved_org = (org.strip() or fetched_org or auto_org)
    jd = JD(
        id=None,
        user_id=uid,
        title=resolved_title,
        org=resolved_org,
        source_text=source_text,
        axis_weights=parsed["axis_weights"],
        signal_tags=parsed["signal_tags"],
        summary=parsed.get("summary"),
        method=parsed["method"],
        model_used=parsed.get("model_used"),
        parsed_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        archived_at=None,
        iac_profile=parsed.get("iac_profile"),
        iac_evidence_md=parsed.get("iac_evidence_md"),
        iac_fit_md=None,
    )
    new_id = jd_repo.insert(jd)
    # Auto-activate freshly-pasted JDs.
    settings = _user_settings(uid)
    settings["active_jd_id"] = new_id
    _save_user_settings(uid, settings)
    return RedirectResponse(url=f"/aim/jd/{new_id}", status_code=303)


@app.get("/jds/{jd_id}", response_class=HTMLResponse)
def jds_show(request: Request, jd_id: int):
    # Legacy route kept for transition; canonical detail URL is /aim/jd/{id}.
    return RedirectResponse(url=f"/aim/jd/{jd_id}", status_code=302)


@app.get("/aim/jd/{jd_id}", response_class=HTMLResponse)
def aim_jd_show(request: Request, jd_id: int):
    uid = request.state.user_session.user_id
    jd = jd_repo.get(jd_id)
    if jd is None or jd.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    settings = _user_settings(uid)
    is_active = settings.get("active_jd_id") == jd.id and jd.archived_at is None

    user_iac_raw = settings.get("iac_profile")
    user_iac = user_iac_raw if isinstance(user_iac_raw, dict) else None
    iac_fit_md = jd.iac_fit_md
    if jd.iac_profile and user_iac and not iac_fit_md:
        fit = jd_service.interpret_iac_fit(jd.iac_profile, user_iac, user_id=uid)
        if fit:
            try:
                jd_repo.set_iac_fit(jd.id, fit)
            except Exception:
                pass
            iac_fit_md = fit

    return templates.TemplateResponse(
        request,
        "jd_detail.html",
        {
            "config": config,
            "jd": jd,
            "is_active": is_active,
            "axis_labels": assess_service.AXIS_LABELS,
            "iac_labels": jd_service.IAC_LABELS,
            "iac_keys": jd_service.IAC_KEYS,
            "user_iac": user_iac,
            "iac_fit_md": iac_fit_md,
            "back_to_aim_url": "/aim#aim",
            "nav_section": "aim",
        },
    )


@app.post("/jds/{jd_id}/activate", response_class=HTMLResponse)
def jds_activate(request: Request, jd_id: int):
    uid = request.state.user_session.user_id
    jd = jd_repo.get(jd_id)
    if jd is None or jd.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    settings = _user_settings(uid)
    settings["active_jd_id"] = jd_id
    _save_user_settings(uid, settings)
    return RedirectResponse(url=f"/aim/jd/{jd_id}", status_code=303)


@app.post("/jds/clear-active", response_class=HTMLResponse)
def jds_clear_active(request: Request):
    uid = request.state.user_session.user_id
    settings = _user_settings(uid)
    if "active_jd_id" in settings:
        del settings["active_jd_id"]
        _save_user_settings(uid, settings)
    return RedirectResponse(url="/aim#aim", status_code=303)


@app.post("/jds/{jd_id}/archive", response_class=HTMLResponse)
def jds_archive(request: Request, jd_id: int):
    uid = request.state.user_session.user_id
    jd = jd_repo.get(jd_id)
    if jd is None or jd.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    jd_repo.archive(jd_id)
    settings = _user_settings(uid)
    if settings.get("active_jd_id") == jd_id:
        del settings["active_jd_id"]
        _save_user_settings(uid, settings)
    return RedirectResponse(url="/aim#aim", status_code=303)


# --- Feedback inbox ---------------------------------------------------------


@app.post("/feedback", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["feedback"])
def feedback_create(
    request: Request,
    url: str = Form(...),
    body: str = Form(...),
    page_title: str = Form(""),
    theme: str = Form(""),
    viewport_width: int = Form(0),
    images: list[UploadFile] = File(default=[]),
):
    uid = request.state.user_session.user_id
    body = body.strip()
    if not body:
        return HTMLResponse("empty — nothing to save", status_code=400)

    from urllib.parse import urlsplit
    try:
        parsed_feedback_url = urlsplit(url)
        if url.startswith("//") or parsed_feedback_url.scheme not in ("", "http", "https") or any(ord(c) < 32 for c in url):
            raise ValueError("invalid context URL")
        url = parsed_feedback_url.path or "/"
        if not url.startswith("/") or url.startswith("//"):
            raise ValueError("invalid context path")
    except ValueError:
        return HTMLResponse("Use a valid page path for feedback.", status_code=400)

    # Validate attachments BEFORE inserting the feedback row so a
    # rejected image doesn't leave a half-saved report.
    _FB_IMG_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    _FB_IMG_MAX_BYTES = 2 * 1024 * 1024
    _FB_IMG_MAX_COUNT = 3
    staged: list[tuple[str, str, bytes]] = []
    for up in (images or [])[: _FB_IMG_MAX_COUNT + 1]:
        if not up or not up.filename:
            continue
        if len(staged) >= _FB_IMG_MAX_COUNT:
            return HTMLResponse(
                f"too many images — max {_FB_IMG_MAX_COUNT}", status_code=400
            )
        ctype = (up.content_type or "").lower()
        if ctype not in _FB_IMG_TYPES:
            return HTMLResponse(
                "unsupported image type — png/jpeg/webp/gif only", status_code=400
            )
        data = up.file.read(_FB_IMG_MAX_BYTES + 1)
        if len(data) > _FB_IMG_MAX_BYTES:
            return HTMLResponse("image too large — max 2 MB each", status_code=400)
        if data:
            staged.append((up.filename[:200], ctype, data))

    fb_id = feedback_repo.insert(
        user_id=uid,
        url=url[:500],
        body=body,
        page_title=(page_title or None) and page_title[:300],
        theme=(theme or None),
        viewport_width=viewport_width or None,
    )
    for filename, ctype, data in staged:
        feedback_repo.insert_attachment(
            feedback_id=fb_id,
            user_id=uid,
            filename=filename,
            content_type=ctype,
            data=data,
        )
    feedback_inbox_service.regenerate_inbox(feedback_repo, uid, REPO_ROOT)

    # Saving feedback succeeds independently of GitHub. Both promotion
    # entry points use the same durable claim before any external create.
    from .services import access as access_service
    if access_service.is_admin(uid):
        from .services import github_feedback as gh_service
        from html import escape
        try:
            fb = feedback_repo.get(fb_id)
            result = gh_service.promote_feedback(feedback_repo, fb, actor_id=uid, auto_promoted=True) if fb else None
        except Exception:
            _log.exception("Could not confirm feedback promotion")
            result = None
        if result and result.status == "linked":
            return HTMLResponse(
                f"saved as feedback #{fb_id} · "
                f'<a href="{escape(result.issue_url, quote=True)}" target="_blank" rel="noopener">'
                f"opened gh#{result.issue_number} ↗</a>"
            )
        status = "GitHub promotion is not configured" if result and result.status == "unconfigured" else "GitHub promotion needs review"
        return HTMLResponse(f'saved as feedback #{fb_id} · {status}. <a href="/feedback/inbox">Check the inbox</a>.')

    # Non-admin submission. Returned HTML is swapped into #fb-status;
    # the client-side script then wraps it with an "open inbox"
    # affordance and a checkmark.
    return HTMLResponse(f"saved as feedback #{fb_id}")


_FB_TAB_STATUSES = ("open", "backlog", "closed")


def _fb_return_to(value: str) -> str:
    """Whitelist a `return_to` form value against the tab set so the
    redirect after an action lands on a valid inbox tab. Defaults to
    "open" when the value is missing or unrecognized.

    Operator review 2026-05-28: closing an item from the open tab
    should keep the operator on the open tab (the row drops out of
    the list because it's no longer in status=open), not bounce
    them to the closed tab where they have to navigate back."""
    cleaned = (value or "").strip()
    return cleaned if cleaned in _FB_TAB_STATUSES else "open"
# "closed" is a UI bucket that unions archived + dismissed (mirrors how
# GitHub treats closed issues regardless of resolution reason).
_FB_CLOSED_DB_STATUSES = ("archived", "dismissed")


def _fb_counts(uid: str) -> dict[str, int]:
    with feedback_repo.conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS n FROM feedback WHERE user_id = %s GROUP BY status",
            (uid,),
        )
        rows = cur.fetchall()
    by_status = {r["status"]: r["n"] for r in rows}
    return {
        "open": by_status.get("open", 0),
        "backlog": by_status.get("backlog", 0),
        "closed": by_status.get("archived", 0) + by_status.get("dismissed", 0),
    }


def _sync_closed_linked_feedback(items) -> dict:
    """Auto-archive inbox rows whose linked GH issue is now closed.

    Why this runs during inbox render: feedback is the local source of
    truth, but issue closure often happens in GitHub first (merge,
    duplicate, wontfix). Opportunistic sync on view keeps the inbox
    from drifting without adding a background worker.

    Returns a diagnostic dict the template can render as a small
    banner so the operator can see WHY sync didn't happen. Shape:

      {
        "changed":         bool,  # was any row archived this tick
        "linked_total":    int,   # open items with a gh_issue_url
        "skipped_reason":  str | None,  # "no_linked"|"no_token"|None
        "error":           str | None,  # exception text if crashed
        "closed_count":    int,   # how many GH issues came back closed
      }

    Operator review 2026-05-28: when the bench/GH sync wasn't
    auto-archiving items whose linked PR merged, there was no signal
    in the UI to diagnose why. Now the inbox surface tells the
    operator if the token's missing / the call crashed / etc.
    """
    from .services import github_feedback as gh_service

    result: dict = {
        "changed": False,
        "linked_total": 0,
        "skipped_reason": None,
        "error": None,
        "closed_count": 0,
    }

    linked_urls = [fb.gh_issue_url for fb in items if fb.status == "open" and fb.gh_issue_url]
    result["linked_total"] = len(linked_urls)
    if not linked_urls:
        result["skipped_reason"] = "no_linked"
        return result

    # Probe for the token explicitly so the diagnostic can distinguish
    # "no token configured" from "token rejected the call." This
    # mirrors the early-exit inside fetch_closed_issue_urls but lets
    # us surface a cleaner UI message.
    if not os.environ.get("GITHUB_FEEDBACK_TOKEN", "").strip():
        result["skipped_reason"] = "no_token"
        return result

    try:
        closed_urls = gh_service.fetch_closed_issue_urls(linked_urls)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _log.warning("feedback_inbox: GH state sync crashed: %s", msg)
        result["error"] = msg
        return result

    result["closed_count"] = len(closed_urls)
    if not closed_urls:
        # Sync ran cleanly but nothing was closed on the GH side yet —
        # silent success. UI shows no banner.
        return result

    for fb in items:
        if fb.status != "open" or not fb.gh_issue_url:
            continue
        if fb.gh_issue_url not in closed_urls:
            continue
        feedback_repo.set_status(
            fb.id,
            "archived",
            "Auto-closed: linked GitHub issue is closed.",
        )
        result["changed"] = True
    return result


@app.get("/feedback/attachment/{attachment_id}")
def feedback_attachment(request: Request, attachment_id: int):
    """Serve a feedback image. Owner-or-admin only — attachments may
    contain screenshots of the submitter's own data."""
    from fastapi.responses import Response
    from .services import access as access_service

    uid = request.state.user_session.user_id
    att = feedback_repo.get_attachment(attachment_id)
    if att is None:
        return HTMLResponse("not found", status_code=404)
    if att["user_id"] != uid and not access_service.is_admin(uid):
        return HTMLResponse("not found", status_code=404)
    return Response(
        content=bytes(att["bytes"]),
        media_type=att["content_type"],
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/feedback/inbox", response_class=HTMLResponse)
def feedback_inbox(request: Request, status: str = "open", scope: str = ""):
    """Feedback inbox. Admins (LIS-301) get an extra `?scope=all` mode
    that shows feedback from EVERY user, plus a Promote-to-issue
    button on each unpromoted row. Non-admins always see their own
    submissions (unchanged from prior behavior)."""
    uid = request.state.user_session.user_id
    if status not in _FB_TAB_STATUSES:
        status = "open"

    from .services import access as access_service
    admin = access_service.is_admin(uid)
    # Admin default = all (more useful surface for the operator);
    # they can switch to ?scope=mine via the toggle. Non-admins
    # never see anyone else's rows regardless of the scope param.
    show_all = admin and scope != "mine"

    if show_all:
        if status == "closed":
            items = feedback_repo.list_all_closed(limit=100)
        else:
            items = feedback_repo.list_all(status=status, limit=200)
        counts = feedback_repo.counts_all()
    elif status == "closed":
        # Union archived + dismissed, newest first, capped.
        with feedback_repo.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM feedback
                 WHERE user_id = %s AND status IN ('archived','dismissed')
                 ORDER BY COALESCE(processed_at, created_at) DESC
                 LIMIT 100
                """,
                (uid,),
            )
            rows = cur.fetchall()
        from .repositories.feedback_repository import _row_to_feedback
        items = [_row_to_feedback(r) for r in rows]
        counts = _fb_counts(uid)
    else:
        items = feedback_repo.list_for_user(uid, status=status)
        counts = _fb_counts(uid)

    # Keep open-tab state aligned with linked GH issues. We re-query
    # after any mutation so rendered items + tab counts are coherent.
    # The sync_result dict carries diagnostic state ({changed,
    # skipped_reason, error, ...}) so the template can render a banner
    # explaining why sync didn't auto-archive items if that's the case.
    sync_result: dict | None = None
    if status == "open":
        sync_result = _sync_closed_linked_feedback(items)
        if sync_result.get("changed"):
            if show_all:
                items = feedback_repo.list_all(status=status, limit=200)
                counts = feedback_repo.counts_all()
            else:
                items = feedback_repo.list_for_user(uid, status=status)
                counts = _fb_counts(uid)

    attachments_by_fb = feedback_repo.attachments_meta([f.id for f in items if f.id])
    from .services import github_feedback as gh_service
    promotion_search_urls = {fb.id: gh_service.promotion_search_url(fb.id) for fb in items if fb.id}

    return templates.TemplateResponse(
        request,
        "feedback_inbox.html",
        {
            "config": config,
            "items": items,
            "attachments_by_fb": attachments_by_fb,
            "promotion_search_urls": promotion_search_urls,
            "active_status": status,
            "counts": counts,
            "tab_statuses": _FB_TAB_STATUSES,
            "is_admin": admin,
            "show_all": show_all,
            "sync_result": sync_result,
            "nav_section": "settings",
        },
    )


@app.post("/feedback/{fb_id}/archive", response_class=HTMLResponse)
def feedback_archive(
    request: Request,
    fb_id: int,
    processing_notes: str = Form(""),
    return_to: str = Form(""),
):
    uid = request.state.user_session.user_id
    fb = feedback_repo.get(fb_id)
    from .services import access as access_service
    if fb is None or (fb.user_id != uid and not access_service.is_admin(uid)):
        return HTMLResponse("Not found", status_code=404)
    feedback_repo.set_status(fb_id, "archived", processing_notes or None)
    if fb.gh_issue_url:
        from .services import github_feedback as gh_service

        try:
            if not gh_service.close_gh_issue(
                fb.gh_issue_url,
                state_reason="completed",
            ):
                _log.warning(
                    "feedback_archive: GH close failed for feedback_id=%s",
                    fb_id,
                )
        except Exception as e:
            _log.warning("feedback_archive: GH close crashed for %s: %s", fb_id, e)
    feedback_inbox_service.regenerate_inbox(feedback_repo, fb.user_id, REPO_ROOT)
    return RedirectResponse(
        url=f"/feedback/inbox?status={_fb_return_to(return_to)}", status_code=303
    )


@app.post("/feedback/{fb_id}/backlog", response_class=HTMLResponse)
def feedback_backlog(
    request: Request,
    fb_id: int,
    processing_notes: str = Form(""),
    return_to: str = Form(""),
):
    """Defer an item to the backlog — acknowledged but not now (v2 work,
    spec lift, etc.). Mirrors the GitHub-issue "no milestone yet" state."""
    uid = request.state.user_session.user_id
    fb = feedback_repo.get(fb_id)
    from .services import access as access_service
    if fb is None or (fb.user_id != uid and not access_service.is_admin(uid)):
        return HTMLResponse("Not found", status_code=404)
    feedback_repo.set_status(fb_id, "backlog", processing_notes or None)
    if fb.gh_issue_url:
        from .services import github_feedback as gh_service

        try:
            if not gh_service.comment_on_gh_issue(fb.gh_issue_url, "Deferred to backlog"):
                _log.warning(
                    "feedback_backlog: GH comment failed for feedback_id=%s",
                    fb_id,
                )
        except Exception as e:
            _log.warning("feedback_backlog: GH comment crashed for %s: %s", fb_id, e)
    feedback_inbox_service.regenerate_inbox(feedback_repo, fb.user_id, REPO_ROOT)
    return RedirectResponse(
        url=f"/feedback/inbox?status={_fb_return_to(return_to)}", status_code=303
    )


@app.post("/feedback/{fb_id}/reopen", response_class=HTMLResponse)
def feedback_reopen(request: Request, fb_id: int, return_to: str = Form("")):
    """Move an item back to open (from backlog or closed)."""
    uid = request.state.user_session.user_id
    fb = feedback_repo.get(fb_id)
    from .services import access as access_service
    if fb is None or (fb.user_id != uid and not access_service.is_admin(uid)):
        return HTMLResponse("Not found", status_code=404)
    feedback_repo.set_status(fb_id, "open")
    if fb.gh_issue_url:
        from .services import github_feedback as gh_service

        try:
            if not gh_service.reopen_gh_issue(fb.gh_issue_url):
                _log.warning(
                    "feedback_reopen: GH reopen failed for feedback_id=%s",
                    fb_id,
                )
        except Exception as e:
            _log.warning("feedback_reopen: GH reopen crashed for %s: %s", fb_id, e)
    feedback_inbox_service.regenerate_inbox(feedback_repo, fb.user_id, REPO_ROOT)
    return RedirectResponse(
        url=f"/feedback/inbox?status={_fb_return_to(return_to)}", status_code=303
    )


@app.post("/feedback/{fb_id}/dismiss", response_class=HTMLResponse)
def feedback_dismiss(request: Request, fb_id: int, return_to: str = Form("")):
    uid = request.state.user_session.user_id
    fb = feedback_repo.get(fb_id)
    from .services import access as access_service
    if fb is None or (fb.user_id != uid and not access_service.is_admin(uid)):
        return HTMLResponse("Not found", status_code=404)
    feedback_repo.set_status(fb_id, "dismissed")
    if fb.gh_issue_url:
        from .services import github_feedback as gh_service

        try:
            if not gh_service.close_gh_issue(
                fb.gh_issue_url,
                state_reason="not_planned",
                labels=["wontfix"],
            ):
                _log.warning(
                    "feedback_dismiss: GH close failed for feedback_id=%s",
                    fb_id,
                )
        except Exception as e:
            _log.warning("feedback_dismiss: GH close crashed for %s: %s", fb_id, e)
    feedback_inbox_service.regenerate_inbox(feedback_repo, fb.user_id, REPO_ROOT)
    return RedirectResponse(
        url=f"/feedback/inbox?status={_fb_return_to(return_to)}", status_code=303
    )


# Manual and automatic promotion share a durable claim; uncertain outcomes
# require linking an existing issue, never an automatic second create.
@app.post("/feedback/{fb_id}/promote", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS.get("feedback_promote", "30/hour"))
def feedback_promote(request: Request, fb_id: int):
    from .services import access as access_service
    from .services import github_feedback as gh_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)

    fb = feedback_repo.get(fb_id)
    if fb is None:
        return HTMLResponse("Not found", status_code=404)
    if fb.gh_issue_url:
        # Idempotent: already promoted. Bounce to the existing issue.
        return RedirectResponse(url=fb.gh_issue_url, status_code=303)

    result = gh_service.promote_feedback(feedback_repo, fb, actor_id=uid)
    if result.status == "linked":
        return RedirectResponse(url="/feedback/inbox", status_code=303)
    if result.status == "uncertain":
        return HTMLResponse('The GitHub outcome needs review. Another issue will not be created automatically. '
            '<a href="/feedback/inbox">Find and link the existing issue in the inbox</a>.', status_code=409)
    return HTMLResponse('GitHub promotion is unavailable or not configured. Your feedback is saved. '
        '<a href="/feedback/inbox">Return to the inbox</a>.', status_code=503)


@app.post("/feedback/{fb_id}/reconcile", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS.get("feedback_promote", "30/hour"))
def feedback_reconcile(request: Request, fb_id: int, issue_url: str = Form("")):
    from .services import access as access_service
    from .services import github_feedback as gh_service
    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)
    fb = feedback_repo.get(fb_id)
    if fb is None:
        return HTMLResponse("Not found", status_code=404)
    result = gh_service.reconcile_feedback(feedback_repo, fb, issue_url=issue_url, actor_id=uid)
    if result.status == "linked":
        return RedirectResponse(url="/feedback/inbox", status_code=303)
    if result.status == "invalid":
        return HTMLResponse('Use an existing issue from the configured repository containing this feedback ID. '
            '<a href="/feedback/inbox">Return to the inbox</a>.', status_code=400)
    return HTMLResponse('The issue link could not be confirmed. No new issue was created. '
        '<a href="/feedback/inbox">Return to the inbox</a>.', status_code=409 if result.status == "uncertain" else 503)


# --- Writings ---------------------------------------------------------------

_PUBLIC_WRITING_ESSAYS = (
    {
        "title": "Tag vocabulary",
        "blurb": (
            "How the bench tags problems and content, why migration 005 "
            "removed alias-bridging, and how precision/recall tradeoffs "
            "show up in the library filter."
        ),
        "url": "https://docs.libearden.dev/architecture/tag-vocabulary/",
        "updated_at": "2026-05-16",
    },
    {
        "title": "Imposter-signal detection and mitigation",
        "blurb": (
            "Design notes for detecting self-underrating signals, "
            "acknowledging them without clinical framing, and adapting "
            "daily flow until mastery evidence catches up."
        ),
        "url": "https://docs.libearden.dev/architecture/imposter-syndrome/",
        "updated_at": "2026-05-18",
    },
    {
        "title": "Rest days (Saturday + Sunday)",
        "blurb": (
            "Why the bench enforces weekend recovery as part of the "
            "learning system, including research grounding and concrete "
            "scheduler/product decisions."
        ),
        "url": "https://docs.libearden.dev/architecture/rest-days/",
        "updated_at": "2026-05-18",
    },
    {
        "title": "Curriculum tracks (ARENA 3.0 and beyond)",
        "blurb": (
            "The track model that overlays sequential curricula onto the "
            "existing daily-flow engine, starting with ARENA 3.0 and "
            "preserving the bench's content source-of-truth patterns."
        ),
        "url": "https://docs.libearden.dev/architecture/tracks/",
        "updated_at": "2026-05-18",
    },
    {
        "title": "Autonomous coding agents",
        "blurb": (
            "An architecture write-up for how Charlie routes work by "
            "complexity tier, enforces CODEOWNERS guardrails, and fits into "
            "the repo's human-review deployment loop."
        ),
        "url": "https://docs.libearden.dev/development/agents/",
        "updated_at": "2026-05-17",
    },
)


@app.get("/writing", response_class=HTMLResponse)
def writing_index(request: Request):
    return templates.TemplateResponse(
        request,
        "writing.html",
        {
            "config": config,
            "essays": _PUBLIC_WRITING_ESSAYS,
            "nav_section": "",
            "is_alpha_view": True,
        },
    )


@app.get("/writings", response_class=HTMLResponse)
def writings_index(request: Request):
    uid = request.state.user_session.user_id
    drafts = writing_repo.list_for_user(uid, status="draft")
    published = writing_repo.list_for_user(uid, status="published")
    return templates.TemplateResponse(
        request,
        "writings_index.html",
        {
            "config": config,
            "drafts": drafts,
            "published": published,
            "nav_section": "write",
        },
    )


@app.post("/writings", response_class=HTMLResponse)
def writings_new(request: Request, initiative_slug: str = Form("")):
    """Start a new draft. If `from_today=1` is present, pre-populate
    the body with references to today's reading + reflection + most
    recent attempt as a scaffolding seed."""
    uid = request.state.user_session.user_id
    try:
        resolved_initiative = initiative_picker.resolve_initiative_slug(
            settings=request.state.user_settings,
            form_override=initiative_slug,
        )
    except initiative_picker.UnknownInitiativeError as exc:
        return HTMLResponse(str(exc), status_code=400)
    # Build seed body from today's context
    sources: list[dict] = []
    body_lines = []
    # Today's daily picks
    progress = content_repo.progress_for_user(uid)
    scores: dict = {}
    latest = assessment_repo.latest_completed(uid)
    if latest:
        scores, _coverage = _assessment_snapshot(uid, latest)
    materials = _active_track_materials(request.state.user_settings or {}, user_id=uid)
    track_reading = materials["cards"].get("reading") if materials else None
    if track_reading:
        section = track_reading["section"]
        sources.append({"kind": "track_section", "track_slug": materials["track"].slug,
                        "section_index": track_reading["idx"], "title": section.title})
        body_lines.append(f"## From today's track reading — {section.title}")
        body_lines.append(f"Track section: {track_reading['url']}")
        if track_reading["session"].get("stopping_point"):
            body_lines.append(track_reading["session"]["stopping_point"])
        body_lines.append("")
    elif materials is None:
        todays_reading = content_service.pick_daily(content_repo.all_by_kind("reading", user_id=uid), progress, scores)
        if todays_reading:
            sources.append({"kind": "reading", "id": todays_reading.id, "slug": todays_reading.slug, "title": todays_reading.title})
            body_lines.append(f"## From today's reading — {todays_reading.title}")
            pr = progress.get(todays_reading.id)
            if pr and pr.notes_md:
                body_lines.append(pr.notes_md)
            body_lines.append("")
    # Most recent attempt
    attempts = attempt_repo.all_for_user(uid)
    if attempts:
        a = attempts[0]
        p = problem_repo.get_by_id(a.problem_id)
        if p:
            sources.append({"kind": "attempt", "id": a.id, "title": p.title})
            body_lines.append(f"## From recent attempt — {p.title}")
            if a.notes_md:
                body_lines.append(a.notes_md)
            body_lines.append("")
    body_seed = "\n".join(body_lines) if body_lines else ""
    title_seed = f"Draft · {datetime.now().strftime('%Y-%m-%d')}"
    new_id = writing_repo.insert(
        uid,
        title=title_seed,
        body_md=body_seed,
        source_refs=sources,
        initiative_slug=resolved_initiative,
    )
    return RedirectResponse(url=f"/writings/{new_id}", status_code=303)


@app.get("/writings/{writing_id}", response_class=HTMLResponse)
def writings_show(request: Request, writing_id: int):
    uid = request.state.user_session.user_id
    w = writing_repo.get(writing_id)
    if w is None or w.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    source_refs = []
    for saved_ref in w.source_refs or []:
        ref = dict(saved_ref)
        if ref.get("kind") == "reading":
            # Old drafts saved numeric IDs; resolve through the owned
            # catalogue so removed/private readings never gain a link.
            ref.pop("slug", None)
            content_id = ref.get("id")
            item = content_repo.get_by_id(content_id, user_id=uid) if isinstance(content_id, int) and not isinstance(content_id, bool) else None
            if item is not None:
                ref["slug"] = item.slug
        source_refs.append(ref)
    return templates.TemplateResponse(
        request,
        "writing_detail.html",
        {
            "config": config,
            "w": w,
            "source_refs": source_refs,
            "nav_section": "write",
        },
    )


@app.post("/writings/{writing_id}/save", response_class=HTMLResponse)
def writings_save(request: Request, writing_id: int, title: str = Form(""), body_md: str = Form("")):
    uid = request.state.user_session.user_id
    w = writing_repo.get(writing_id)
    if w is None or w.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    writing_repo.update(writing_id, title=title, body_md=body_md)
    return RedirectResponse(url=f"/writings/{writing_id}", status_code=303)


@app.post("/writings/{writing_id}/status", response_class=HTMLResponse)
def writings_set_status(
    request: Request, writing_id: int, status: str = Form(...),
    title: str = Form(""), body_md: str = Form(""), editor_snapshot: str = Form(...),
):
    uid = request.state.user_session.user_id
    w = writing_repo.get(writing_id)
    if w is None or w.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    if status not in ("draft", "published", "archived"):
        return HTMLResponse("Bad status", status_code=400)
    if editor_snapshot != "1":
        return HTMLResponse("Editor snapshot required", status_code=422)
    if not writing_repo.save_with_status(
        writing_id, user_id=uid, title=title, body_md=body_md, status=status,
    ):
        return HTMLResponse("Not found", status_code=404)
    return RedirectResponse(url=f"/writings/{writing_id}", status_code=303)


@app.post("/writings/{writing_id}/delete", response_class=HTMLResponse)
def writings_delete(request: Request, writing_id: int):
    """Permanently delete one of the operator's own writings.

    Hard delete — no soft "archive" path here because the existing
    archived status is unused in the UI (no view shows archived rows),
    so it'd just hide the draft in the DB forever. Single-tenant,
    operator's own data, ownership-guarded; safe to actually delete.

    The form on /writings uses a JS confirm() to catch accidental clicks.
    """
    uid = request.state.user_session.user_id
    w = writing_repo.get(writing_id)
    if w is None or w.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    writing_repo.delete(writing_id, user_id=uid)
    return RedirectResponse(url="/writings", status_code=303)


# --- Reflection / Hamming mode ------------------------------------------------
#
# Weekly review surface. The user opens /reflect, sees the latest
# reflection (if any) plus a button to generate a fresh one. The
# generator pulls last-N-days activity and asks Sonnet (with the
# anti-sycophancy Hamming framing in app/services/hamming.py) for a
# specific, data-grounded prompt set. The user writes a reply inline,
# which autosaves and persists on submit.

_HAMMING_WINDOW_DAYS = 7


def _build_week_summary(uid: str, days: int = _HAMMING_WINDOW_DAYS):
    """Gather the structured payload that feeds hamming.generate()."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    all_attempts = attempt_repo.all_for_user(uid)
    week_attempts = [a for a in all_attempts if a.started_at and a.started_at >= cutoff]
    # Map problem_id -> Problem so we can resolve tags/axes.
    pid_to_problem = {p.id: p for p in problem_repo.all_core() + problem_repo.all_warmups()}
    # Content: pull progress + content metadata for items finished or
    # rated within the window.
    prog_by_id = content_repo.progress_for_user(uid)
    content_summary: list[dict] = []
    # Externally-captured readings the user added via /library/add and
    # wrote notes about. Highest-signal reflect input we have: the user
    # actively chose these and wrote in their own words. Threaded down
    # to the LLM prompt so generated prompts can reference them by name.
    external_readings: list[str] = []
    for cid, pr in prog_by_id.items():
        ci = content_repo.get_by_id(cid, user_id=uid)
        if ci is None:
            continue
        # Use checked_at as the proxy for "engaged this week."
        if pr.checked_at and pr.checked_at >= cutoff:
            content_summary.append({
                "title": ci.title,
                "kind": ci.kind,
                "status": pr.status,
                "rating_1_to_5": pr.rating_1_to_5,
            })
            # User-added (created_by_user_id set by insert_user_item)
            # with substantive notes — pull out separately for the
            # reflect prompt context.
            if (
                getattr(ci, "created_by_user_id", None)
                and pr.notes_md
                and len(pr.notes_md.strip()) > 20
            ):
                excerpt = pr.notes_md.strip().replace("\n", " ")[:200]
                external_readings.append(f"{ci.title} — {excerpt}")
    writings_by_status = {"draft": 0, "published": 0, "archived": 0}
    for w in writing_repo.list_for_user(uid):
        if w.updated_at and w.updated_at >= cutoff:
            writings_by_status[w.status] = writings_by_status.get(w.status, 0) + 1
    # Self-feedback opened this week.
    fb_rows = feedback_repo.list_for_user(uid, limit=500)
    fb_in_window = sum(1 for f in fb_rows if f.created_at >= cutoff)
    return hamming_service.summarize_week(
        attempts=week_attempts,
        problem_by_id=pid_to_problem,
        content_progress=content_summary,
        writings_count_by_status=writings_by_status,
        feedback_opened_count=fb_in_window,
        external_readings=external_readings[:8],  # cap to keep payload tight
    )


@app.get("/reflect", response_class=HTMLResponse)
def reflect_index(request: Request):
    uid = request.state.user_session.user_id
    refls = reflection_repo.list_for_user(uid, limit=20)
    latest = refls[0] if refls else None
    # Headline summary the user sees before deciding to generate.
    week = _build_week_summary(uid)
    return templates.TemplateResponse(
        request,
        "reflect.html",
        {
            "config": config,
            "latest": latest,
            "history": refls[1:] if len(refls) > 1 else [],
            "week": week,
            "window_days": _HAMMING_WINDOW_DAYS,
            "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "nav_section": "reflect",
        },
    )


@app.post("/reflect/generate", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS["reflect_generate"])
def reflect_generate(request: Request, initiative_slug: str = Form("")):
    """Pull this week's activity, ask Claude (or fallback) for a prompt
    set, persist a new reflection row, and land on its detail page."""
    uid = request.state.user_session.user_id
    try:
        resolved_initiative = initiative_picker.resolve_initiative_slug(
            settings=request.state.user_settings,
            form_override=initiative_slug,
        )
    except initiative_picker.UnknownInitiativeError as exc:
        return HTMLResponse(str(exc), status_code=400)
    now = datetime.utcnow()
    period_start = now - timedelta(days=_HAMMING_WINDOW_DAYS)
    week = _build_week_summary(uid)
    result = hamming_service.generate(week, days=_HAMMING_WINDOW_DAYS, user_id=uid)
    from .models import Reflection
    refl = Reflection(
        id=None,
        user_id=uid,
        period_start=period_start,
        period_end=now,
        generated_at=now,
        prompts=result["prompts"],
        response_md=None,
        response_updated_at=None,
        summary_md=result.get("summary"),
        method=result["method"],
        model_used=result.get("model_used"),
        initiative_slug=resolved_initiative,
    )
    new_id = reflection_repo.insert(refl)
    return RedirectResponse(url=f"/reflect/{new_id}", status_code=303)


@app.get("/reflect/{refl_id}", response_class=HTMLResponse)
def reflect_show(request: Request, refl_id: int):
    uid = request.state.user_session.user_id
    refl = reflection_repo.get(refl_id)
    if refl is None or refl.user_id != uid:
        return HTMLResponse("Not found", status_code=404)
    has_calibration_prompt = _has_calibration_prompt(refl)
    return templates.TemplateResponse(
        request,
        "reflect_detail.html",
        {
            "config": config,
            "refl": refl,
            "has_calibration_prompt": has_calibration_prompt,
            "nav_section": "reflect",
        },
    )


@app.post("/reflect/{refl_id}/save", response_class=HTMLResponse)
def reflect_save(
    request: Request,
    refl_id: int,
    response_md: str = Form(""),
    calibration_predicted_pct: str = Form(""),
    calibration_actual_pct: str = Form(""),
    calibration_gap_md: str = Form(""),
):
    uid = request.state.user_session.user_id
    refl = reflection_repo.get(refl_id)
    if refl is None or refl.user_id != uid:
        return HTMLResponse("Not found", status_code=404)

    calibration_json = None
    if _has_calibration_prompt(refl):
        predicted_pct = _coerce_pct_int(calibration_predicted_pct, clamp=True)
        actual_pct = _coerce_pct_int(calibration_actual_pct, clamp=True)
        gap_md = calibration_gap_md.strip()

        payload: dict[str, object] = {}
        if predicted_pct is not None:
            payload["predicted_pct"] = predicted_pct
        if actual_pct is not None:
            payload["actual_pct"] = actual_pct
        if gap_md:
            payload["gap_md"] = gap_md

        if payload:
            calibration_json = payload

    reflection_repo.save_response(
        refl_id,
        response_md.strip() or None,
        calibration_json=calibration_json,
    )
    return RedirectResponse(url=f"/reflect/{refl_id}", status_code=303)


# --- External content ingestion -----------------------------------------------
#
# Users can paste an external course / reading / video into the local
# rotation. Stored alongside authored content via the same content_items
# table; `source_kind='user'` flags it so the startup loader doesn't
# touch it.

# Curated source pull-down. New entries land in the "Other" free-text
# slot — surfaced if the user types something unrecognized.
_KNOWN_SOURCES: list[str] = [
    "DeepLearning.ai",
    "BlueDot Impact",
    "fast.ai",
    "Coursera",
    "edX",
    "ARENA",
    "Distill",
    "ARC Evals",
    "Anthropic Blog",
    "OpenAI Blog",
    "AI Alignment Forum",
    "LessWrong",
    "ML Twitter / X",
    "arXiv",
    "GitHub repo",
    "Personal",
]


def _slugify(text: str) -> str:
    """Lowercase, dash-separated, ASCII-only. Truncates to 60 chars so
    URL paths stay readable. Caller appends a uniqueness suffix."""
    import re
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return (s or "untitled")[:60]


def _unique_user_slug(base: str) -> str:
    """Append a short hash suffix until the slug is unique. Keeps the
    base slug readable while guaranteeing no collision with existing
    authored or user content."""
    import secrets
    candidate = f"x-{base}"
    if not content_repo.slug_exists(candidate):
        return candidate
    for _ in range(20):
        suffix = secrets.token_hex(2)
        candidate = f"x-{base}-{suffix}"
        if not content_repo.slug_exists(candidate):
            return candidate
    # Astronomically unlikely fallthrough — long random tail.
    return f"x-{base}-{secrets.token_hex(6)}"


@app.post("/library/add/parse-url", response_class=JSONResponse)
@_rate_limiter.limit(RATE_LIMITS["parse_url"])
async def parse_external_url(request: Request, url: str = Form(...)):
    """Take a URL, fetch + Claude-parse it, return {title, source, axes,
    summary_md} JSON for the form to pre-fill. Best-effort: any failure
    returns {ok: False, reason: ...} and the user fills in manually.

    Kept as a separate POST endpoint (vs. inline on the form-render
    GET) so the user can paste, click Parse, and see the result
    without losing what they've already typed."""
    from .services import external_capture
    u = (url or "").strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return JSONResponse({"ok": False, "reason": "url-format"}, status_code=400)
    fetched = await external_capture.fetch_body(u)
    if fetched is None:
        return JSONResponse({"ok": False, "reason": "fetch-failed"})
    from starlette.concurrency import run_in_threadpool

    parsed = await run_in_threadpool(
        external_capture.parse_with_claude, u, fetched, list(assess_service.AXES),
        user_id=request.state.user_session.user_id,
    )
    if parsed is None:
        # Partial degrade: at least return the og:title if we got it.
        return JSONResponse({
            "ok": True,
            "title": fetched.get("page_title", "")[:200],
            "source": "",
            "axes": [],
            "summary_md": "",
            "degraded": True,
        })
    return JSONResponse({"ok": True, **parsed})


@app.get("/library/add", response_class=HTMLResponse)
def new_content_form(request: Request, error: str = ""):
    """Paste form for external content (DeepLearning.ai videos, BlueDot
    readings, etc.). Renders the empty form; POST creates the row.

    Hosted at /library/add rather than /content/new to avoid colliding
    with the /content/{slug} catch-all that registers earlier."""
    return templates.TemplateResponse(
        request,
        "content_new.html",
        {
            "config": config,
            "known_sources": _KNOWN_SOURCES,
            "axes": assess_service.AXES,
            "axis_labels": assess_service.AXIS_LABELS,
            "error": error,
            "nav_section": "learn",
        },
    )


@app.post("/library/add", response_class=HTMLResponse)
def create_external_content(
    request: Request,
    title: str = Form(...),
    kind: str = Form(...),
    source: str = Form(""),
    source_other: str = Form(""),
    url: str = Form(""),
    duration_min: str = Form(""),
    axes_csv: str = Form(""),   # comma-separated axis keys from the checkboxes
    notes_md: str = Form(""),
):
    uid = request.state.user_session.user_id
    title = (title or "").strip()
    if not title:
        return RedirectResponse(url="/library/add?error=title", status_code=303)
    if kind not in ("reading", "video", "podcast", "exercise"):
        return RedirectResponse(url="/library/add?error=kind", status_code=303)
    # Source: prefer the dropdown selection; fall through to "Other"
    # free-text if the dropdown was left blank or set to "Other".
    if source.strip().lower() == "other" or not source.strip():
        source_val = source_other.strip() or None
    else:
        source_val = source.strip()
    # Duration: optional integer.
    dur: int | None = None
    if duration_min.strip():
        try:
            dur = max(1, int(duration_min))
        except ValueError:
            dur = None
    # Axes: whitelist against the known set so the form can't inject
    # arbitrary tags into the scheduler's axis space.
    valid_axes = set(assess_service.AXES)
    axes = [a.strip() for a in axes_csv.split(",") if a.strip() in valid_axes]
    # URL: lightly validate so we don't store junk. Empty is fine.
    url_val: str | None = None
    if url.strip():
        u = url.strip()
        if u.startswith(("http://", "https://")):
            url_val = u[:500]
        else:
            return RedirectResponse(url="/library/add?error=url", status_code=303)
    slug = _unique_user_slug(_slugify(title))
    new_id = content_repo.insert_user_item(
        user_id=uid,
        slug=slug,
        kind=kind,
        title=title,
        source=source_val,
        url=url_val,
        duration_min=dur,
        axes=axes,
        notes_md=notes_md.strip() or None,
    )
    return RedirectResponse(url=f"/content/{slug}", status_code=303)


# --- Auth: GitHub OAuth via Supabase ----------------------------------------
#
# Phase 3 of the multi-user migration. The flow:
#
#   1. User hits /login → page with "Continue with GitHub" button.
#   2. Click → GET /auth/signin/github. Server asks Supabase for the
#      OAuth URL and 303s there.
#   3. GitHub authenticates the user, redirects back to Supabase's
#      callback (configured in the GitHub OAuth app).
#   4. Supabase swaps the code for tokens, then redirects to our
#      /auth/callback?#access_token=...&refresh_token=... (fragment).
#   5. /auth/callback renders a JS bridge page that extracts the
#      fragment and POSTs to /auth/session.
#   6. /auth/session writes HTTP-only cookies, 303s to /.
#   7. From there, every request's middleware decodes the cookie's
#      JWT to set request.state.user_session.

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    """Sign-in page. If you're already signed in, sends you to /."""
    if request.state.user_session is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"config": config, "error": error, "nav_section": "", "is_alpha_view": True},
    )


@app.get("/about")
def about_redirect(request: Request):
    """Permanently redirect /about → libearden.dev/about.

    The bench is a tool; the operator's about/bio content lives on the
    portfolio at libearden.dev. Keeping a /about page on the bench
    duplicated content and confused the boundary (operator review
    2026-05-27). Redirect preserves any external links / bookmarks
    that picked up the old URL.
    """
    return RedirectResponse(
        url="https://libearden.dev/about",
        status_code=301,
    )


# ---------- Request-access flow (LIS-280 v2) -------------------------------
#
# Public form for visitors who don't have access yet. Two endpoints:
#   GET  /request-access           — show the form (optionally
#                                    prefilled with ?email=...)
#   POST /auth/request-access      — insert into access_requests, send
#                                    operator email, render the thanks
#                                    page.
#
# Rate-limited under `request_access` (see app/services/rate_limit.py).
# Honeypot field (`website`) bounces bots without a CAPTCHA. Soft
# dedupe via has_recent_pending().

_ACCESS_REQUEST_STATUSES = ("pending", "granted", "declined")

@app.get("/request-access", response_class=HTMLResponse)
def request_access_page(request: Request, email: str = ""):
    return templates.TemplateResponse(
        request,
        "request_access.html",
        {
            "form": {"email": email, "name": "", "github_handle": "", "note": ""},
            "error": None,
            "nav_section": "",
            "is_alpha_view": True,
        },
    )



@app.post("/auth/request-access", response_class=HTMLResponse)
@_rate_limiter.limit(RATE_LIMITS.get("request_access", "5/hour"))
def request_access_submit(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    github_handle: str = Form(""),
    note: str = Form(""),
    website: str = Form(""),  # honeypot — must stay empty
):
    """Persist the request and notify the operator. Soft-failing on
    the email side so a missing/broken Resend config doesn't cost
    legitimate submissions."""
    from .services.notifications import (
        send_operator_email, format_access_request_email,
    )

    # Honeypot: if a bot filled `website`, pretend success and bail.
    # We don't want them to know the field is the trap.
    if website.strip():
        return templates.TemplateResponse(
            request,
            "request_access_thanks.html",
            {"request_id": 0, "email": email, "nav_section": "", "is_alpha_view": True},
        )

    name_s = (name or "").strip()
    email_s = (email or "").strip()
    if not name_s or "@" not in email_s:
        return templates.TemplateResponse(
            request,
            "request_access.html",
            {
                "form": {"email": email_s, "name": name_s,
                         "github_handle": github_handle, "note": note},
                "error": "Name and a valid email are required.",
                "nav_section": "",
                "is_alpha_view": True,
            },
            status_code=400,
        )

    # Idempotency: if there's already a pending request from this
    # email in the last 5 minutes, show the thanks page without
    # inserting a duplicate row.
    if access_request_repo.has_recent_pending(email_s):
        return templates.TemplateResponse(
            request,
            "request_access_thanks.html",
            {"request_id": 0, "email": email_s, "nav_section": "", "is_alpha_view": True},
        )

    new_id = access_request_repo.insert(
        name=name_s,
        email=email_s,
        github_handle=(github_handle or "").strip() or None,
        note=(note or "").strip() or None,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    subject, body_text = format_access_request_email(
        name=name_s, email=email_s,
        github_handle=(github_handle or "").strip() or None,
        note=(note or "").strip() or None,
        ip=request.client.host if request.client else None,
        request_id=new_id,
    )
    send_operator_email(subject=subject, body_text=body_text)

    return templates.TemplateResponse(
        request,
        "request_access_thanks.html",
        {"request_id": new_id, "email": email_s,
         "nav_section": "", "is_alpha_view": True},
    )


# --- Voice transcription (replaces Chrome Web Speech) ----------------------
#
# Chrome's Web Speech API routes audio through speech.googleapis.com,
# which is unreachable in many privacy-extension / DNS-filtered browser
# environments. The 2026-05-17 operator trace (issues #80 → #88 → #90)
# confirmed deterministic `error: network` failures even with mic capture
# working. This route accepts a MediaRecorder blob, ships it to Groq's
# Whisper-Large-v3-Turbo, and returns the transcript. Audio never touches
# Google. See `app/services/transcription.py` for the spend-cap +
# upstream-call details.


@app.post("/api/transcribe")
@_rate_limiter.limit(RATE_LIMITS["transcribe"])
async def api_transcribe(request: Request, audio: UploadFile = File(...)):
    """Transcribe a MediaRecorder audio blob to text.

    Requires signed-in user (auth middleware enforces; signed-out hits
    the redirect to /login before reaching this handler).

    Spend-capped via `transcription_service.over_cap_for(uid)` — at the
    daily ceiling, returns 429 so the client can show a friendly
    "daily dictation budget reached" state. Rate-limited per
    `RATE_LIMITS["transcribe"]` to backstop a runaway loop.

    Audio payload comes as multipart/form-data with field name `audio`.
    Filename + content-type are forwarded to the upstream so the
    Whisper model knows the format (webm/opus from Chrome MediaRecorder
    by default; the upstream auto-detects from extension)."""
    import logging as _logging
    from .services import transcription as transcribe_service

    log = _logging.getLogger(__name__)
    uid = request.state.user_session.user_id

    if transcribe_service.over_cap_for(uid):
        log.info("api.transcribe.cap_reached user_id=%s", uid)
        return JSONResponse(
            {"error": "transcription_cap_reached",
             "detail": "Daily dictation budget reached. Resets at UTC midnight."},
            status_code=429,
        )

    try:
        audio_bytes = await audio.read()
    except Exception as e:
        log.warning(
            "api.transcribe.read_failure user_id=%s exc_type=%s msg=%r",
            uid, type(e).__name__, str(e)[:120],
        )
        return JSONResponse(
            {"error": "audio_read_failed"},
            status_code=400,
        )

    if not audio_bytes:
        return JSONResponse({"error": "empty_audio"}, status_code=400)

    try:
        result = transcribe_service.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            content_type=audio.content_type or "audio/webm",
        )
    except transcribe_service.TranscriptionError as e:
        log.warning(
            "api.transcribe.failure user_id=%s exc_type=%s msg=%r",
            uid, type(e).__name__, str(e)[:120],
        )
        # Differentiate "you sent something invalid" (4xx) from "we
        # failed talking to upstream" (5xx). Anything mentioning "size"
        # or "empty" is a client error; everything else is upstream.
        msg_low = str(e).lower()
        if "exceeds" in msg_low or "empty" in msg_low:
            return JSONResponse(
                {"error": "audio_invalid", "detail": str(e)[:200]},
                status_code=400,
            )
        return JSONResponse(
            {"error": "transcription_failed"},
            status_code=502,
        )

    duration_s = result.get("duration_seconds") or 0
    if duration_s > 0:
        transcribe_service.record_seconds_for(uid, duration_s)

    return JSONResponse({"text": result.get("text", "")})


@app.get("/admin/diag/recent-events", response_class=HTMLResponse)
def admin_diag_recent_events(request: Request):
    from .services import access as access_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)

    events = diag_log_service.recent_events()
    return templates.TemplateResponse(
        request,
        "admin/diag_recent_events.html",
        {
            "events": events,
            "events_text": "\n".join(events) if events else "(no events yet)",
            "event_count": len(events),
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "nav_section": "settings",
        },
    )


@app.get("/admin/access-requests", response_class=HTMLResponse)
def admin_access_requests(request: Request, status: str = "pending"):
    from .services import access as access_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)

    if status not in _ACCESS_REQUEST_STATUSES:
        status = "pending"

    items = access_request_repo.list_recent(status=status, limit=200)
    counts = access_request_repo.counts_by_status()
    allowlist_items = allowlist_repo.list_active()
    return templates.TemplateResponse(
        request,
        "admin_access_requests.html",
        {
            "config": config,
            "items": items,
            "active_status": status,
            "tab_statuses": _ACCESS_REQUEST_STATUSES,
            "counts": counts,
            "allowlist_items": allowlist_items,
            "nav_section": "settings",
        },
    )


@app.post("/admin/access-requests/{req_id}/status", response_class=HTMLResponse)
def admin_access_request_set_status(
    request: Request,
    req_id: int,
    status: str = Form(...),
    processed_note: str = Form(""),
):
    from .services import access as access_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)
    if status not in ("granted", "declined"):
        return HTMLResponse("Bad status", status_code=400)

    # rate limit deferred: requires edit to CODEOWNERS-protected app/services/rate_limit.py
    note = (processed_note or "").strip() or None
    req = access_request_repo.get(req_id)
    access_request_repo.set_status(req_id, status, note)
    # Approval IS the grant now (Bench v2): sync the DB allowlist so
    # the person can sign in without a deploy. Declining revokes, so
    # flipping a granted request to declined also pulls access.
    if req is not None:
        if status == "granted":
            allowlist_repo.grant(
                req.email, added_by=uid, access_request_id=req_id, note=note
            )
        else:
            allowlist_repo.revoke(req.email)
        _db_allowlist_cache_clear()
    return RedirectResponse(url="/admin/access-requests", status_code=303)


@app.post("/admin/allowlist/add", response_class=HTMLResponse)
def admin_allowlist_add(
    request: Request,
    email: str = Form(...),
    note: str = Form(""),
):
    """Direct grant for people who never filed an access request
    (demo cohorts, in-person invites)."""
    from .services import access as access_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)
    email_s = (email or "").strip().lower()
    if "@" not in email_s or len(email_s) > 320:
        return HTMLResponse("Bad email", status_code=400)

    allowlist_repo.grant(email_s, added_by=uid, note=(note or "").strip() or None)
    _db_allowlist_cache_clear()
    return RedirectResponse(url="/admin/access-requests", status_code=303)


@app.post("/admin/allowlist/revoke", response_class=HTMLResponse)
def admin_allowlist_revoke(request: Request, email: str = Form(...)):
    from .services import access as access_service

    uid = request.state.user_session.user_id
    if not access_service.is_admin(uid):
        return HTMLResponse("Not authorized", status_code=403)

    allowlist_repo.revoke((email or "").strip().lower())
    _db_allowlist_cache_clear()
    return RedirectResponse(url="/admin/access-requests", status_code=303)


@app.get("/auth/signin/github")
def auth_signin_github(request: Request):
    """Start the GitHub OAuth handshake under PKCE flow.

    Generates a (verifier, challenge) pair. The verifier rides in a
    short-lived HTTP-only cookie so the /auth/callback handler can
    swap it back in. The challenge goes on the OAuth URL so Supabase
    can bind the exchange to it."""
    from .auth import (
        build_oauth_authorize_url,
        generate_pkce_pair,
        set_pkce_verifier_cookie,
    )

    ua_prefix = (request.headers.get("user-agent") or "")[:60]
    referrer = request.headers.get("referer")
    cookie_names = sorted(request.cookies.keys())
    _log.info(
        "auth.signin.github.entry ua_prefix=%r referrer=%r cookie_names=%s",
        ua_prefix,
        referrer,
        cookie_names,
    )

    base = str(request.base_url).rstrip("/")
    redirect_to = f"{base}/auth/callback"
    try:
        verifier, challenge = generate_pkce_pair()
        _log.info(
            "auth.signin.github.pkce_generated verifier_len=%s",
            len(verifier),
        )

        url = build_oauth_authorize_url(
            provider="github",
            redirect_to=redirect_to,
            code_challenge=challenge,
        )

        from urllib.parse import urlparse

        _log.info(
            "auth.signin.github.oauth_url_built redirect_host=%s",
            urlparse(url).netloc,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/login?error={type(e).__name__}: {str(e)[:120]}",
            status_code=303,
        )
    response = RedirectResponse(url=url, status_code=303)
    set_pkce_verifier_cookie(response, verifier)
    return response


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(
    request: Request,
    code: str = "",
    error: str = "",
    error_description: str = "",
):
    """Receive Supabase's PKCE callback. Reads the auth code from the
    query string and the verifier from the cookie, posts both to
    Supabase's token endpoint, sets session cookies on success.

    On any failure, bounces to /login with a descriptive error."""
    from .auth import (
        PKCE_VERIFIER_COOKIE,
        clear_pkce_verifier_cookie,
        exchange_code_for_session,
        parse_access_token,
        set_session_cookies,
    )

    safe_error = " ".join((error or "").split())[:120] if error else None
    has_pkce_verifier_cookie = PKCE_VERIFIER_COOKIE in request.cookies
    _log.info(
        "auth.callback.entry has_code=%s error=%r has_pkce_verifier_cookie=%s",
        bool(code),
        safe_error,
        has_pkce_verifier_cookie,
    )

    if error:
        msg = error_description or error
        return RedirectResponse(url=f"/login?error={msg[:140]}", status_code=303)
    if not code:
        return RedirectResponse(
            url="/login?error=missing+auth+code", status_code=303,
        )
    verifier = request.cookies.get(PKCE_VERIFIER_COOKIE)
    if not verifier:
        return RedirectResponse(
            url="/login?error=missing+pkce+verifier+(cookie+lost+between+requests)",
            status_code=303,
        )
    try:
        tokens = exchange_code_for_session(code, verifier)
        _log.info("auth.callback.token_exchange success")
    except Exception as e:
        _log.warning(
            "auth.callback.token_exchange failed exception_type=%s message_prefix=%r",
            type(e).__name__,
            str(e)[:120],
        )
        return RedirectResponse(
            url=f"/login?error={type(e).__name__}: {str(e)[:140]}",
            status_code=303,
        )
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not access:
        return RedirectResponse(
            url="/login?error=Supabase+returned+no+access_token",
            status_code=303,
        )

    jwt_alg = "unknown"
    try:
        import jwt as _jwt

        jwt_alg = str(_jwt.get_unverified_header(access).get("alg", "unknown"))
    except Exception:
        pass

    parsed_session = parse_access_token(access)
    if parsed_session is None:
        _log.warning("auth.callback.jwt_decode failed alg=%s", jwt_alg)
    else:
        _log.info(
            "auth.callback.jwt_decode success user_id=%s",
            parsed_session.user_id,
        )

    response = RedirectResponse(url="/", status_code=303)
    set_session_cookies(response, access, refresh)
    clear_pkce_verifier_cookie(response)
    return response


@app.post("/auth/logout")
def auth_logout():
    """Clear session cookies. Doesn't actually revoke the Supabase
    refresh token (that requires a server-to-Supabase call we'll add
    in Phase 4); for now the cookie clear is enough — the user is
    logged out of *this* browser."""
    from .auth import clear_session_cookies
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookies(response)
    return response


@app.get("/auth/me", response_class=HTMLResponse)
def auth_me(request: Request):
    """Diagnostic: show the current session. Useful to verify the
    cookie is parsing and the JWT claims look right. Remove or gate
    behind SENTRY_ENVIRONMENT=local before public deploy."""
    sess = request.state.user_session
    if sess is None:
        return HTMLResponse(
            "<pre>not signed in. <a href='/login'>sign in →</a></pre>"
        )
    from datetime import datetime as _dt
    expires = _dt.utcfromtimestamp(sess.expires_at).isoformat() if sess.expires_at else "?"
    return HTMLResponse(
        "<pre style='font-family: ui-monospace; padding: 1.5rem'>"
        f"user_id:    {sess.user_id}\n"
        f"email:      {sess.email or '(none)'}\n"
        f"expires_at: {expires}Z\n"
        "</pre>"
        "<p><a href='/'>/</a> · <form method='post' action='/auth/logout' style='display:inline'>"
        "<button type='submit'>log out</button></form></p>"
    )


# --- Reset progress (Phase 6 onboarding-testing affordance) ----------------
#
# Two-step UX:
#   GET  /settings/reset  → preview page with counts of every row that
#                          would be deleted. No mutation.
#   POST /settings/reset  → executes the deletes inside one transaction
#                          (so partial failure leaves no half-state),
#                          clears the onboarding_skipped flag in
#                          settings_json, then 303s to / which the
#                          home() redirect rule sends to /onboarding
#                          (because there's no completed assessment
#                          anymore).
#
# Scope: clears practice/learning state. Keeps user-authored content
# (JDs, writings, feedback, credentials) so resets are cheap to do
# repeatedly without losing real work.

_RESET_TABLES_ORDER = (
    # Order chosen so FK-dependent rows go first. attempt_reviews
    # cascades from attempts; we delete the parent and let CASCADE
    # do the work. content_progress and review_state have no
    # dependents on the same user.
    "reflections",
    "sessions",
    "review_state",
    "attempts",            # CASCADE wipes attempt_reviews
    "assessment_runs",     # CASCADE wipes assessment_responses
    "content_progress",
)

# Full-account-deletion table order. Strict superset of _RESET_TABLES_ORDER:
# adds the user-authored content that reset deliberately preserves
# (writings, JDs, feedback, credentials, chat outcomes). The public.users
# row itself is also cleared at the end of the handler so a fresh
# sign-in lands on /onboarding instead of inheriting stale settings.
#
# Auth deletion (Supabase auth.users) is NOT performed here — the
# postgres role doesn't have permission for auth.users mutations, and
# revoking the GitHub OAuth grant is the operator's job from GitHub
# settings. We sign them out via cookie clear as the closest cleanup.
_DELETE_ACCOUNT_TABLES_ORDER = (
    "reflections",
    "sessions",
    "review_state",
    "attempts",            # CASCADE wipes attempt_reviews
    "assessment_runs",     # CASCADE wipes assessment_responses
    "content_progress",
    "writings",
    "jds",
    "feedback",            # CASCADE wipes feedback_attachments
    "credential_runs",     # CASCADE wipes credential_files + credential_assessments
    "chat_outcomes",
    # Added 2026-08-18 (launch-week audit): these landed after the
    # original account-deletion audit with user_id but NO FK to
    # public.users, so the final users-row delete did not cascade —
    # a deleted account orphaned its CRM contacts and Mira history.
    # test_delete_account_covers_all_user_tables now pins the full set.
    "contacts",            # CASCADE wipes contact_interactions
    "mira_sessions",       # CASCADE wipes mira_turns
    "mira_memory",
    "research_agenda",
    "proposed_evals",
    "kb_documents",       # v2.1 vaults; CASCADE wipes kb_chunks
    "user_linear_configs",
    "user_vault_syncs",
    "evidence_artifacts",
    "opportunities",      # CASCADE wipes opportunity_events

    # BYO-key routing row. The row itself would also cascade from the
    # users delete, but the handler additionally calls
    # llm_config_repo.delete_for() first — the vault secret is outside
    # any table cascade's reach.
    "user_llm_configs",
)


def _reset_counts(uid: str) -> dict[str, int]:
    """Per-table count of rows that belong to this user. Used for the
    preview page so the user can confirm what they're about to
    delete."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in _RESET_TABLES_ORDER:
            cur.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = %s",
                (uid,),
            )
            counts[table] = int(cur.fetchone()["c"])
    return counts


@app.get("/settings/reset", response_class=HTMLResponse)
def settings_reset_preview(request: Request):
    """Render the preview of what a reset would delete. No mutation."""
    uid = request.state.user_session.user_id
    counts = _reset_counts(uid)
    settings = request.state.user_settings or {}
    return templates.TemplateResponse(
        request,
        "settings_reset.html",
        {
            "config": config,
            "counts": counts,
            "total_rows": sum(counts.values()),
            "has_skipped_flag": bool(settings.get("onboarding_skipped")),
            "nav_section": "settings",
        },
    )


@app.post("/settings/reset", response_class=HTMLResponse)
def settings_reset_execute(
    request: Request,
    confirm: str = Form(""),
    typed_total: str = Form(""),
):
    """Execute the reset. Requires both `confirm=yes` and a typed row
    total that matches the server-side count so JS-only gating can't
    be bypassed with a crafted POST."""
    uid = request.state.user_session.user_id
    expected_total = str(sum(_reset_counts(uid).values()))
    if confirm != "yes" or typed_total != expected_total:
        return RedirectResponse(url="/settings/reset", status_code=303)

    # All deletes in one transaction so a mid-way failure leaves no
    # half-state. Connection is autocommit=True, so we explicitly
    # open a transaction.
    with conn.transaction():
        with conn.cursor() as cur:
            for table in _RESET_TABLES_ORDER:
                cur.execute(
                    f"DELETE FROM {table} WHERE user_id = %s",
                    (uid,),
                )

    # Clear the onboarding-skipped flag so the next GET / sends the
    # user back to /onboarding instead of straight to home.
    settings = _user_settings(uid)
    settings.pop("onboarding_skipped", None)
    _save_user_settings(uid, settings)

    return RedirectResponse(url="/", status_code=303)


# ---------- Full-account deletion -----------------------------------------
#
# Operator-requested 2026-05-27. Wider scope than /settings/reset: deletes
# user-authored content too (writings, JDs, feedback, credentials, chat
# outcomes). Two-step UX:
#   GET  /settings/delete-account  — preview + typed-confirmation form
#   POST /settings/delete-account  — execute deletion + sign out
#
# Auth deletion (Supabase auth.users row) is NOT performed — postgres
# role doesn't have permission, and revoking the GitHub OAuth grant is
# the user's job. We clear the session cookie as the closest analog.


def _delete_account_counts(uid: str) -> dict[str, int]:
    """Row counts across the wider _DELETE_ACCOUNT_TABLES_ORDER. The
    confirmation page renders this so the user sees exactly what's
    about to be wiped."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in _DELETE_ACCOUNT_TABLES_ORDER:
            cur.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = %s",
                (uid,),
            )
            counts[table] = int(cur.fetchone()["c"])
    return counts


@app.get("/settings/delete-account", response_class=HTMLResponse)
def settings_delete_account_preview(request: Request):
    """Render the preview of what account-deletion would wipe. No mutation."""
    uid = request.state.user_session.user_id
    counts = _delete_account_counts(uid)
    return templates.TemplateResponse(
        request,
        "settings_delete_account.html",
        {
            "config": config,
            "counts": counts,
            "total_rows": sum(counts.values()),
            "session_email": request.state.user_session.email,
            "nav_section": "settings",
        },
    )


@app.post("/settings/delete-account", response_class=HTMLResponse)
def settings_delete_account_execute(
    request: Request,
    confirm: str = Form(""),
    typed_phrase: str = Form(""),
):
    """Execute account deletion. Requires both ``confirm=yes`` and a
    typed phrase that matches the literal string ``DELETE MY ACCOUNT``.
    Server-side double-check defends against crafted POSTs that bypass
    the typed-confirmation gate in the UI."""
    uid = request.state.user_session.user_id
    if confirm != "yes" or typed_phrase.strip() != "DELETE MY ACCOUNT":
        return RedirectResponse(url="/settings/delete-account", status_code=303)

    # Vault-backed rows first: their secrets can't be reached by the
    # generic table sweep below. If either raises, the deletion aborts
    # and the user retries — never leave a paying user's key behind.
    llm_config_repo.delete_for(uid)
    linear_config_repo.delete_for(uid)
    vault_sync_repo.delete_for(uid)

    # All deletes in one transaction so a mid-way failure leaves no
    # half-state (e.g., writings wiped but attempts intact).
    with conn.transaction():
        with conn.cursor() as cur:
            for table in _DELETE_ACCOUNT_TABLES_ORDER:
                cur.execute(
                    f"DELETE FROM {table} WHERE user_id = %s",
                    (uid,),
                )
            # Clear the public.users row itself so a fresh sign-in
            # via the same GitHub identity gets clean settings_json
            # (and is treated as a new account by /onboarding).
            cur.execute("DELETE FROM public.users WHERE id = %s", (uid,))

    # Sign out — clear the session cookie. The Supabase auth.users
    # row stays (not our table to mutate), but with the session cookie
    # gone the user is fully signed out from this browser.
    response = RedirectResponse(url="/login?deleted=1", status_code=303)
    response.delete_cookie("sb-access-token", path="/")
    response.delete_cookie("sb-refresh-token", path="/")
    return response
