"""Promote a `feedback` row to a GitHub Issue (LIS-301).

Why this exists
---------------
The in-app feedback widget records to Postgres. GitHub Issues is where
*actionable* work lives (CI, branch links, milestones, labels). Two
separate stores means operator-typed feedback gets re-keyed by hand
and non-operator user submissions tend to languish unread. This
module is the bridge:

  - Operator submits → auto-promote (issue gets created immediately).
  - Non-operator submits → row sits in admin inbox; operator clicks
    "Promote →" to fire `create_gh_issue` on demand.

Durable promotion
-----------------
Both submission paths use `promote_feedback`: a committed database claim
precedes the external create. An unknown outcome retains that claim and
requires reconciliation with an existing issue; it never automatically
retries creation. The feedback row remains the source of truth.

Tested by patching `_post_github` so unit tests don't hit the real
API. The format helpers are pure functions.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


_log = logging.getLogger(__name__)
_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"
_USER_AGENT = "lis-bench/1.0 (+https://bench.libearden.dev)"


# Defaults are fine for the canonical deploy; both are overridable via
# env so a fork or alternate-repo target can be wired up without code
# changes.
_DEFAULT_REPO = "LiBearden/research-engineer-interview-prep"


def _repo() -> str:
    """`OWNER/REPO` to create issues against. Defaults to the canonical
    public repo for this app; override via `GITHUB_FEEDBACK_REPO` env."""
    return os.environ.get("GITHUB_FEEDBACK_REPO", _DEFAULT_REPO).strip()


def _token() -> str:
    """The fine-grained PAT or classic-PAT with `issues: write` scope
    on the target repo. Set via `flyctl secrets set` in production."""
    return os.environ.get("GITHUB_FEEDBACK_TOKEN", "").strip()


# ---------- Pure formatters (unit-testable without network) -----------------


def _truncate(text: str, limit: int) -> str:
    """One-line title from a possibly-multiline feedback body."""
    s = " ".join(text.split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _public_page_path(url: str | None) -> str:
    # Auth callbacks and application filters can contain private values.
    # The route plus private feedback ID is enough to locate the report.
    try:
        return urllib.parse.urlsplit(url or "").path or "/"
    except ValueError:
        return "(unavailable)"


def format_issue_title(body: str, url: str | None = None) -> str:
    """Short title for the GitHub issue. Strategy: first ~80 chars of
    the body, prefixed with `[feedback]` so the operator can filter
    the issue list. The full body lands in the issue body, so we don't
    have to be precious about losing detail in the title.

    If the feedback body is empty (edge case), fall back to the page
    URL so the title at least points somewhere useful."""
    text = (body or "").strip()
    if not text:
        text = f"feedback on {_public_page_path(url) if url else 'unspecified page'}"
    return f"[feedback] {_truncate(text, 80)}"


def format_issue_body(
    *,
    feedback_id: int,
    body: str,
    url: str | None,
    page_title: str | None,
    theme: str | None,
    viewport_width: int | None,
    submitter_email: str | None,
    submitter_user_id: str | None,
    auto_promoted: bool,
) -> str:
    """Markdown body for the GitHub issue.

    Carries report text and page context with a private-inbox lookup ID.
    Identity and URL query/fragment metadata are deliberately excluded;
    submitter arguments remain accepted for existing callers."""
    lines = [
        (body or "_(no body)_").strip(),
        "",
        "---",
        "",
        "### Context",
        "",
    ]
    if url:
        lines.append(f"- **Page**: `{_public_page_path(url)}`")
    if page_title:
        lines.append(f"- **Title**: {page_title}")
    if theme:
        lines.append(f"- **Theme**: {theme}")
    if viewport_width:
        lines.append(f"- **Viewport**: {viewport_width}px")
    # Keep identity in the private inbox; GitHub's default target is public.
    promotion_note = "auto-promoted (operator submission)" if auto_promoted else "promoted from inbox"
    lines.extend([
        "",
        f"_{promotion_note} · `feedback_id={feedback_id}`_",
    ])
    return "\n".join(lines)


@dataclass(frozen=True)
class PromotionResult:
    status: str
    issue_url: str | None = None
    issue_number: int | None = None


def _configured_repo() -> str | None:
    repo = _repo()
    return repo if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo) else None


def promotion_search_url(feedback_id: int) -> str:
    """Search only the configured repository for this report's public marker."""
    repo = _configured_repo()
    if not repo:
        return ""
    query = urllib.parse.urlencode({"q": f'is:issue in:body "feedback_id={int(feedback_id)}"'})
    return f"https://github.com/{repo}/issues?{query}"


def _configured_issue(issue_url: str) -> tuple[str, int] | None:
    repo = _configured_repo()
    try:
        parsed = urllib.parse.urlsplit(issue_url.strip())
    except ValueError:
        return None
    if (not repo or parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.query or parsed.fragment):
        return None
    match = re.fullmatch(r"/" + re.escape(repo) + r"/issues/([1-9][0-9]*)/?", parsed.path, re.IGNORECASE)
    if not match:
        return None
    number = int(match.group(1))
    return f"https://github.com/{repo}/issues/{number}", number


def promote_feedback(repo, fb, *, actor_id: str, auto_promoted: bool = False) -> PromotionResult:
    """Claim once before creating; ambiguous outcomes require reconciliation."""
    if fb.gh_issue_url:
        return PromotionResult("linked", fb.gh_issue_url, fb.gh_issue_number)
    if fb.promoted_at is not None:
        return PromotionResult("uncertain")
    if not _token() or not _configured_repo():
        return PromotionResult("unconfigured")
    title = format_issue_title(body=fb.body, url=fb.url)
    body = format_issue_body(feedback_id=fb.id, body=fb.body, url=fb.url,
        page_title=fb.page_title, theme=fb.theme, viewport_width=fb.viewport_width,
        submitter_email=None, submitter_user_id=None, auto_promoted=auto_promoted)
    try:
        claimed = repo.claim_promotion(fb_id=fb.id, promoted_by=actor_id)
        if not claimed:
            current = repo.get(fb.id)
            if current and current.gh_issue_url:
                return PromotionResult("linked", current.gh_issue_url, current.gh_issue_number)
            return PromotionResult("uncertain")
    except Exception:
        _log.exception("Could not claim feedback promotion %s", fb.id)
        return PromotionResult("unavailable")
    try:
        result = create_gh_issue(title=title, body=body)
        if result is not None:
            issue_url, number = result
            verified = _configured_issue(issue_url)
            if verified and type(number) is int and verified[1] == number:
                if repo.mark_promoted(fb_id=fb.id, gh_issue_url=verified[0],
                                     gh_issue_number=number, promoted_by=actor_id):
                    return PromotionResult("linked", verified[0], number)
    except Exception:
        _log.exception("Feedback promotion %s has an uncertain outcome", fb.id)
    # Even a timeout can mean GitHub accepted the issue. Retain the claim.
    return PromotionResult("uncertain")


def reconcile_feedback(repo, fb, *, issue_url: str, actor_id: str) -> PromotionResult:
    """Attach an existing, matching issue after a read-only GitHub verification."""
    if fb.gh_issue_url:
        return PromotionResult("linked", fb.gh_issue_url, fb.gh_issue_number)
    target = _configured_issue(issue_url)
    if target is None or fb.promoted_at is None:
        return PromotionResult("invalid")
    token = _token()
    if not token:
        return PromotionResult("unavailable")
    canonical_url, number = target
    try:
        document = _github_request_json(method="GET", path=f"/repos/{_configured_repo()}/issues/{number}",
                                        token=token, payload=None)
        if document is None:
            return PromotionResult("unavailable")
        if (not isinstance(document, dict) or "pull_request" in document
                or type(document.get("number")) is not int or document["number"] != number
                or not isinstance(document.get("html_url"), str)
                or _configured_issue(document["html_url"]) != target
                or not isinstance(document.get("body"), str)
                or f"`feedback_id={fb.id}`" not in document["body"]):
            return PromotionResult("invalid")
        if repo.mark_promoted(fb_id=fb.id, gh_issue_url=canonical_url,
                             gh_issue_number=number, promoted_by=actor_id):
            return PromotionResult("linked", canonical_url, number)
    except Exception:
        _log.exception("Could not reconcile feedback promotion %s", fb.id)
        return PromotionResult("unavailable")
    return PromotionResult("uncertain")


# ---------- Network ---------------------------------------------------------


def create_gh_issue(
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> tuple[str, int] | None:
    """POST /repos/{owner}/{repo}/issues. Returns (html_url, number) on
    success, None on any failure.

    Labels default to `["feedback", "triage"]`. The operator can change
    or strip them later via GH's UI; we don't try to keep them in sync."""
    token = _token()
    if not token:
        _log.info("skip GH issue (GITHUB_FEEDBACK_TOKEN not set)")
        return None

    repo = _repo()
    payload = {
        "title": title,
        "body": body,
        "labels": labels if labels is not None else ["feedback", "triage"],
    }
    return _post_github(repo=repo, token=token, payload=payload)


def close_gh_issue(
    url: str,
    *,
    state_reason: str = "completed",
    labels: list[str] | None = None,
) -> bool:
    """Best-effort close for a linked issue URL.

    We intentionally return a bool instead of raising so callers can
    keep the local feedback status as source-of-truth even when GitHub
    is unavailable.
    """
    token = _token()
    if not token:
        _log.warning("skip GH close (GITHUB_FEEDBACK_TOKEN not set)")
        return False

    endpoint = _issue_endpoint(url)
    if endpoint is None:
        return False

    labels_ok = True
    if labels:
        labels_ok = _github_request_json(
            method="POST",
            path=f"{endpoint}/labels",
            token=token,
            payload={"labels": labels},
        ) is not None

    close_doc = _github_request_json(
        method="PATCH",
        path=endpoint,
        token=token,
        payload={
            "state": "closed",
            "state_reason": state_reason,
        },
    )
    return close_doc is not None and labels_ok


def reopen_gh_issue(url: str) -> bool:
    """Best-effort reopen for a linked issue URL."""
    token = _token()
    if not token:
        _log.warning("skip GH reopen (GITHUB_FEEDBACK_TOKEN not set)")
        return False

    endpoint = _issue_endpoint(url)
    if endpoint is None:
        return False

    doc = _github_request_json(
        method="PATCH",
        path=endpoint,
        token=token,
        payload={"state": "open"},
    )
    return doc is not None


def comment_on_gh_issue(url: str, body: str) -> bool:
    """Best-effort comment for a linked issue URL."""
    token = _token()
    if not token:
        _log.warning("skip GH comment (GITHUB_FEEDBACK_TOKEN not set)")
        return False

    endpoint = _issue_endpoint(url)
    if endpoint is None:
        return False

    doc = _github_request_json(
        method="POST",
        path=f"{endpoint}/comments",
        token=token,
        payload={"body": body},
    )
    return doc is not None


def fetch_closed_issue_urls(urls: list[str]) -> set[str]:
    """Return the subset of linked issue URLs that are currently closed.

    Sequential-by-design: inbox loads at most a few hundred rows and in
    practice only a small fraction are GH-linked, so simple GET calls are
    enough without introducing async complexity.
    """
    token = _token()
    if not token:
        _log.warning("skip GH state sync (GITHUB_FEEDBACK_TOKEN not set)")
        return set()

    closed: set[str] = set()
    for issue_url in urls:
        endpoint = _issue_endpoint(issue_url)
        if endpoint is None:
            continue
        doc = _github_request_json(
            method="GET",
            path=endpoint,
            token=token,
            payload=None,
        )
        if not isinstance(doc, dict):
            continue
        if doc.get("state") == "closed":
            closed.add(issue_url)
    return closed


def _post_github(
    *, repo: str, token: str, payload: dict[str, Any]
) -> tuple[str, int] | None:
    """Bare HTTP POST against GitHub's REST v3. Stdlib only so we don't
    bring in `requests` for one call. Returns (html_url, number) or None.

    `User-Agent` is required by GitHub's API — anonymous Python-urllib
    UAs sometimes get rejected. The app-identifying UA also helps
    rate-limit attribution."""
    doc = _github_request_json(
        method="POST",
        path=f"/repos/{repo}/issues",
        token=token,
        payload=payload,
    )
    if not isinstance(doc, dict):
        return None

    html_url = doc.get("html_url")
    number = doc.get("number")
    if isinstance(html_url, str) and isinstance(number, int):
        return html_url, number
    _log.warning("GH issue response missing html_url/number: %r", doc)
    return None


def _issue_endpoint(issue_url: str) -> str | None:
    parsed = _parse_issue_url(issue_url)
    if parsed is None:
        return None
    owner, repo, issue_number = parsed
    return f"/repos/{owner}/{repo}/issues/{issue_number}"


def _parse_issue_url(issue_url: str) -> tuple[str, str, int] | None:
    """Extract (owner, repo, issue_number) from a GitHub issue URL."""
    raw = (issue_url or "").strip()
    if not raw:
        _log.warning("invalid GH issue URL: empty")
        return None

    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception as e:
        _log.warning("invalid GH issue URL %r: %s", issue_url, e)
        return None

    host = parsed.netloc.lower()
    if host not in {"github.com", "www.github.com"}:
        _log.warning("invalid GH issue URL host %r: %r", host, issue_url)
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 4 or parts[2] != "issues":
        _log.warning("invalid GH issue URL path: %r", issue_url)
        return None

    owner, repo, issue_text = parts[0], parts[1], parts[3]
    try:
        issue_number = int(issue_text)
    except ValueError:
        _log.warning("invalid GH issue number in URL: %r", issue_url)
        return None

    if issue_number <= 0:
        _log.warning("invalid GH issue number in URL: %r", issue_url)
        return None

    return owner, repo, issue_number


def _github_request_json(
    *,
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | list[Any] | None:
    """Issue a GitHub API request and parse JSON on success."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url=f"{_GITHUB_API_BASE}{path}",
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            if not (200 <= resp.status < 300):
                _log.warning("GH %s %s returned non-2xx: %s", method, path, resp.status)
                return None
            raw = resp.read()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                _log.warning("GH %s %s returned invalid JSON: %s", method, path, e)
                return None
    except urllib.error.HTTPError as e:
        body = e.read()[:200]
        _log.warning("GH %s %s HTTPError %s: %s", method, path, e.code, body)
        return None
    except Exception as e:
        _log.warning("GH %s %s failed: %s", method, path, e)
        return None
