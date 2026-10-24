"""Linear GraphQL client for the per-user agenda sync (v2.1 slice 6).

Deliberately tiny: three operations against api.linear.app/graphql
with the user's own personal API key (fetched from Vault at call
time, never cached). All network failures raise LinearSyncError with
a user-renderable message — callers degrade to the local agenda.

Cloudflare note: Linear fronts with CF, so every request carries an
explicit User-Agent (the bench's established rule for outbound calls
to CF-fronted APIs — error code 1010 otherwise).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

_log = logging.getLogger(__name__)

_ENDPOINT = "https://api.linear.app/graphql"
_UA = "lis-bench/1.0 (+https://bench.libearden.dev)"
_TIMEOUT_S = 10


class LinearSyncError(RuntimeError):
    """Message is safe to render to the user."""


def _gql(api_key: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        _ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            # Personal API keys are sent bare (no Bearer prefix) per
            # Linear's docs; OAuth tokens differ, which we don't use.
            "Authorization": api_key,
            "User-Agent": _UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise LinearSyncError(
                "Linear rejected the API key. Re-check it in Settings."
            ) from e
        raise LinearSyncError(f"Linear API error (HTTP {e.code}). Try again.") from e
    except Exception as e:  # noqa: BLE001 — network/timeout/DNS
        raise LinearSyncError("Could not reach Linear. Try again.") from e
    if payload.get("errors"):
        # Never log the key; the message list is safe.
        msg = "; ".join(
            str(err.get("message", "unknown")) for err in payload["errors"][:3]
        )
        raise LinearSyncError(f"Linear said: {msg}")
    return payload.get("data") or {}


def verify_key(api_key: str) -> dict:
    """{'account_label': str, 'teams': [{'id','name','key'}]} or raises."""
    data = _gql(
        api_key,
        """
        query {
          viewer { name email }
          teams(first: 50) { nodes { id name key } }
        }
        """,
    )
    viewer = data.get("viewer") or {}
    label = viewer.get("name") or viewer.get("email") or "connected"
    teams = [
        {"id": t["id"], "name": t["name"], "key": t["key"]}
        for t in (data.get("teams") or {}).get("nodes", [])
    ]
    if not teams:
        raise LinearSyncError(
            "The key works but no teams are visible to it. Check the key's scope."
        )
    return {"account_label": label, "teams": teams}


def create_issue(
    api_key: str, team_id: str, title: str, description: str
) -> dict:
    """{'id','identifier','url'} for the created issue, or raises."""
    data = _gql(
        api_key,
        """
        mutation($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue { id identifier url }
          }
        }
        """,
        {"input": {"teamId": team_id, "title": title[:255], "description": description}},
    )
    result = data.get("issueCreate") or {}
    if not result.get("success") or not result.get("issue"):
        raise LinearSyncError("Linear did not create the issue. Try again.")
    return result["issue"]


def fetch_issue_states(api_key: str, issue_ids: list[str]) -> dict[str, str]:
    """{issue_id: state_type} for the given ids. state_type is Linear's
    workflow-state *type* (triage/backlog/unstarted/started/completed/
    canceled) — stable across custom workflows, unlike state names."""
    if not issue_ids:
        return {}
    data = _gql(
        api_key,
        """
        query($ids: [ID!]!) {
          issues(filter: { id: { in: $ids } }, first: 100) {
            nodes { id state { type } }
          }
        }
        """,
        {"ids": issue_ids[:100]},
    )
    out: dict[str, str] = {}
    for node in (data.get("issues") or {}).get("nodes", []):
        state = (node.get("state") or {}).get("type")
        if node.get("id") and state:
            out[node["id"]] = state
    return out


# Linear workflow-state type → agenda status. Only movements the
# agenda's CHECK constraint allows; unknown types leave status alone.
STATE_TO_AGENDA_STATUS = {
    "started": "active",
    "completed": "done",
    "canceled": "abandoned",
}
