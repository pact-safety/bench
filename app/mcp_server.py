"""MCP server scaffold for BEN-81.

Exposes operator state to claude.ai connectors and Claude Code so a chat
session can ask "what am I working on?" and get a synthesized answer
without copy-paste. Wraps existing bench services rather than
re-implementing the join logic.

**Scaffold status (2026-05-24).** The four BEN-81 tools are wired here
with real implementations where the substrate exists (`focus_service`,
`initiatives_service`) and stub-but-shaped implementations where it
doesn't (`log_chat_outcome`, which writes to user_settings JSON until
migration 009 lands a proper ``chat_outcomes`` table).

Public mounting requires ``BENCH_MCP_TOKEN``. The token is bound to
``BENCH_MCP_USER_ID`` when more than one user is allowlisted; a sole
allowlisted user is an unambiguous fallback. Missing or ambiguous
configuration leaves MCP unmounted while the web app continues running.
Direct in-process tool tests can still build a server without HTTP transport.

References:
- MCP spec: https://modelcontextprotocol.io/specification
- BEN-81 (Linear issue)
- Companion route: BEN-82 ``/decisions`` is the human read-surface for
  `log_chat_outcome` entries.
"""

from __future__ import annotations

import json
import hmac
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP


log = logging.getLogger("bench.mcp")


# ---------------------------------------------------------------------------
# Storage for log_chat_outcome
#
# Post-PR-B of the chat_outcomes cutover: writes + reads both go through
# ChatOutcomesRepository (migration 009 table). The legacy JSON path on
# `public.users.settings_json.chat_outcomes` is no longer touched.
#
# The user_settings_loader / user_settings_saver kwargs on build_mcp_server
# are kept in the signature for backward compatibility — other tools may
# still want access to settings — but log_chat_outcome no longer reads/writes
# the JSON column at all.
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_chat_outcomes_via_repo(
    *,
    user_id: str,
    initiative: str | None,
    repo: Any,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Read chat outcomes via the ChatOutcomesRepository.

    Returns a list of dicts so callers (MCP tool returns) stay JSON-safe.
    Repo failures degrade gracefully — empty list rather than 500 — so a
    transient DB error doesn't take down the whole MCP response.
    """
    try:
        rows = repo.list_for_user(user_id, initiative_slug=initiative, limit=limit)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat_outcomes repo read failed: %s", exc)
        return []
    return [
        {
            "id": co.id,
            "initiative": co.initiative_slug,
            "decisions": co.decisions,
            "next_actions": co.next_actions,
            "chat_url": co.chat_url,
            "created_at": co.created_at.isoformat() if co.created_at else None,
        }
        for co in rows
    ]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_mcp_server(
    *,
    user_id: str,
    focus_service: Any,
    initiatives_service: Any,
    attempt_repo: Any,
    reflection_repo: Any,
    content_repo: Any,
    user_settings_loader: Callable[[str], dict],
    user_settings_saver: Callable[[str, dict], None],
    chat_outcomes_repo: Any | None = None,
    server_name: str = "bench",
) -> FastMCP:
    """Wire the FastMCP server with the four BEN-81 tools.

    All bench services are injected so unit tests can pass mocks. In
    production the bench's startup builds one of these per operator
    user_id (single-tenant today; the user_id parameter is the contract
    for the multi-tenant future).

    Two FastMCP configuration choices worth noting:

    - ``streamable_http_path="/"`` — FastMCP otherwise mounts its endpoint
      at ``/mcp`` *inside* its sub-app, which combined with our outer
      ``app.mount("/mcp", ...)`` would make the URL ``/mcp/mcp``. Mounting
      at the sub-app root keeps the public URL just ``/mcp``.

    - ``transport_security.allowed_hosts`` — FastMCP's DNS-rebinding
      protection rejects any Host header not in its allowlist. The
      default permits only localhost, which 421s every production
      request. We read ``BENCH_MCP_ALLOWED_HOSTS`` (comma-separated)
      and pass the values through. Falls back to a permissive wildcard
      if the env var is unset — operator behind Cloudflare + Fly + our
      own bearer token already has defense-in-depth, and a missing
      env var shouldn't brick the connector.
    """
    from mcp.server.transport_security import TransportSecuritySettings
    allowed_hosts_raw = os.environ.get("BENCH_MCP_ALLOWED_HOSTS", "").strip()
    if allowed_hosts_raw:
        allowed_hosts = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )
    else:
        # Env var unset → fall back to disabled DNS-rebinding protection.
        # The bearer-token middleware in this module + Fly's TLS + the
        # bench's CSP cover the same threat model with less moving parts.
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    mcp = FastMCP(
        server_name,
        streamable_http_path="/",
        transport_security=transport_security,
    )

    @mcp.tool()
    def get_current_focus() -> dict[str, Any]:
        """Return the operator's current cross-surface focus view.

        Composes per-initiative bench activity (last 7d), open PRs across
        linked GitHub repos, and a placeholder for Linear data (pending
        a proper per-prefix query). Mirrors the /focus dashboard.

        Returns a JSON-friendly dict with one row per active/dormant
        initiative.
        """
        # Pull fresh data on every call — caching is the FastAPI layer's
        # job, and tools should be honest about freshness.
        settings = user_settings_loader(user_id) or {}
        attempts = attempt_repo.all_for_user(user_id)
        reflections = reflection_repo.list_for_user(user_id, limit=200)
        progress = content_repo.progress_for_user(user_id)

        view = focus_service.compute_focus_view(
            user_id=user_id,
            settings=settings,
            attempts=attempts,
            reflections=reflections,
            content_progress=progress,
        )
        return {
            "generated_at": view.generated_at.isoformat() if view.generated_at else None,
            "active_initiative_slug": view.active_initiative_slug,
            "rows": [
                {
                    "initiative": {
                        "slug": row.initiative.slug,
                        "title": row.initiative.title,
                        "status": row.initiative.status,
                        "priority": row.initiative.priority,
                    },
                    "activity": asdict(row.activity),
                    "open_prs_count": len(row.open_prs),
                    "open_prs_state": row.pr_fetch_state,
                    "linear_state": row.linear_state,
                }
                for row in view.rows
            ],
            "integration_notes": list(view.integration_notes),
        }

    @mcp.tool()
    def get_initiative_state(name: str) -> dict[str, Any] | None:
        """Return one initiative by slug, with its recent chat outcomes
        appended.

        ``name`` is the initiative slug (e.g., "bench", "capstone",
        "anthropic-fellows"). Returns None when no such initiative exists.
        """
        initiative = initiatives_service.get_initiative(name.strip())
        if initiative is None:
            return None
        outcomes = _list_chat_outcomes_via_repo(
            user_id=user_id,
            initiative=initiative.slug,
            repo=chat_outcomes_repo,
            limit=10,
        ) if chat_outcomes_repo is not None else []
        return {
            "slug": initiative.slug,
            "title": initiative.title,
            "status": initiative.status,
            "priority": initiative.priority,
            "linear": {
                "team": initiative.linear.team,
                "ticket_prefix": initiative.linear.ticket_prefix,
                "label": initiative.linear.label,
            },
            "github_repos": list(initiative.github.repos),
            "bench_surface": initiative.bench.surface,
            "target_date": initiative.target_date,
            "notes": initiative.notes,
            "recent_chat_outcomes": outcomes,
        }

    @mcp.tool()
    def log_chat_outcome(
        initiative: str,
        decisions: str,
        next_actions: str,
        chat_url: str | None = None,
    ) -> dict[str, Any]:
        """Append a chat-outcome entry to the operator's journal.

        Called by claude.ai / Claude Code at the end of a substantive
        session to record: which initiative the chat advanced, what was
        decided, and what next actions surfaced. The /decisions route
        (BEN-82) is the human read surface.

        Returns the saved entry (including its generated id) so the
        client can show a confirmation.
        """
        if not initiative.strip():
            raise ValueError("initiative is required")
        if not decisions.strip() and not next_actions.strip():
            raise ValueError(
                "at least one of decisions or next_actions must be non-empty"
            )
        # Post-PR-B: table-only write. The JSON parachute that lived
        # here through PR A is gone — chat_outcomes_repo is the single
        # canonical store. Repo errors propagate to the MCP client as
        # tool failures rather than being silently swallowed.
        if chat_outcomes_repo is None:
            raise RuntimeError(
                "chat_outcomes_repo not configured — MCP server was built "
                "without a repo handle. Check app.main:_build_mcp_server_or_none."
            )
        new_id = chat_outcomes_repo.insert(
            user_id=user_id,
            initiative_slug=initiative.strip(),
            decisions=decisions.strip(),
            next_actions=next_actions.strip(),
            chat_url=(chat_url or "").strip() or None,
            source="mcp",
        )
        return {
            "id": new_id,
            "initiative": initiative.strip(),
            "decisions": decisions.strip(),
            "next_actions": next_actions.strip(),
            "chat_url": (chat_url or "").strip() or None,
            "created_at": _now_iso(),
        }

    @mcp.tool()
    def list_open_threads(limit: int = 20) -> dict[str, Any]:
        """List active threads of work, grouped by initiative.

        For each active initiative: title, status, recent bench activity
        counts, open-PR counts, recent chat outcomes. Designed for a
        chat-opening summary so the operator (or Claude) can pick up the
        thread they were on without remembering it from memory.

        Composition wraps get_current_focus + recent chat outcomes per
        initiative.
        """
        focus = get_current_focus()
        threads: list[dict[str, Any]] = []
        for row in focus["rows"]:
            slug = row["initiative"]["slug"]
            outcomes = _list_chat_outcomes_via_repo(
                user_id=user_id, initiative=slug,
                repo=chat_outcomes_repo, limit=3,
            ) if chat_outcomes_repo is not None else []
            threads.append(
                {
                    "initiative": row["initiative"],
                    "activity": row["activity"],
                    "open_prs_count": row["open_prs_count"],
                    "recent_chat_outcomes": outcomes,
                }
            )
        return {
            "generated_at": focus["generated_at"],
            "active_initiative_slug": focus["active_initiative_slug"],
            "threads": threads[:limit],
        }

    return mcp


# ---------------------------------------------------------------------------
# Auth shim
#
# When `BENCH_MCP_TOKEN` is set, ASGI middleware enforces the bearer
# token before any request reaches FastMCP. Missing configuration fails closed.
# ---------------------------------------------------------------------------


class _BearerTokenMiddleware:
    """ASGI bearer-token gate; missing configuration never dispatches HTTP tools."""

    def __init__(self, app: Any, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if not self.token:
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"error":"unavailable"}'})
            return
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        if not auth_header.startswith("Bearer ") or not hmac.compare_digest(
            auth_header[7:].encode("utf-8"), self.token.encode("utf-8")
        ):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"error": "unauthorized"}).encode("utf-8"),
            })
            return
        await self.app(scope, receive, send)


def auth_token_from_env() -> str | None:
    """Read the bearer token from the environment.

    Single env var by design: rotating it is one fly secrets set call;
    no per-user tokens in scope for single-tenant alpha. When
    multi-tenant lands, swap to per-user tokens stored in user_settings.
    """
    val = os.environ.get("BENCH_MCP_TOKEN", "").strip()
    return val or None
