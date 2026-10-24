"""Unit tests for app.services.github_feedback (LIS-301).

Format helpers are pure functions — direct assertion. The network
function (`create_gh_issue`) is exercised by monkeypatching the
bottom-half `_post_github` so we don't dial GitHub in tests; that's
the same boundary the prod code crosses anyway.

What we don't test here: the `_post_github` HTTP machinery itself.
That's stdlib `urllib.request`, well-trodden; if it changes shape,
the integration smoke test on a real deploy will catch it."""

from __future__ import annotations

import pytest

from app.services import github_feedback as gh


def test_format_title_truncates_long_bodies():
    long = "Here's a very long feedback body that goes on and on and on " * 5
    title = gh.format_issue_title(body=long)
    # Prefix preserved + total length capped + ellipsis applied.
    assert title.startswith("[feedback] ")
    assert len(title) <= len("[feedback] ") + 80
    assert title.endswith("…")


def test_format_title_falls_back_when_body_empty():
    """Empty body → title points at the page URL so it's not just '[feedback] '."""
    title = gh.format_issue_title(body="", url="/onboarding")
    assert "[feedback]" in title
    assert "/onboarding" in title


def test_format_body_includes_all_context_fields():
    body = gh.format_issue_body(
        feedback_id=42,
        body="Hint Tier 3 leaks the answer.",
        url="/problem/softmax",
        page_title="Softmax — Li's Bench",
        theme="dark",
        viewport_width=1440,
        submitter_email="dana@example.com",
        submitter_user_id="00000000-0000-0000-0000-000000000099",
        auto_promoted=False,
    )
    assert "Hint Tier 3 leaks the answer." in body
    assert "/problem/softmax" in body
    assert "Softmax — Li's Bench" in body
    assert "dark" in body
    assert "1440px" in body
    assert "dana@example.com" not in body
    # Audit footer: feedback id + promotion mode are how the operator
    # ties this issue back to the row.
    assert "feedback_id=42" in body
    assert "promoted from inbox" in body


def test_format_body_omits_user_id_when_email_missing():
    body = gh.format_issue_body(
        feedback_id=1,
        body="x",
        url=None,
        page_title=None,
        theme=None,
        viewport_width=None,
        submitter_email=None,
        submitter_user_id="abc-uuid",
        auto_promoted=True,
    )
    # The feedback ID provides the private lookup without publishing identity.
    assert "abc-uuid" not in body
    # Distinct footer phrasing for the auto-promote path.
    assert "auto-promoted" in body


def test_format_body_omits_missing_optional_fields():
    """No theme / no viewport / no page_title means those bullets are
    just absent — no empty `- **Theme**:` artifacts."""
    body = gh.format_issue_body(
        feedback_id=1, body="x", url="/foo",
        page_title=None, theme=None, viewport_width=None,
        submitter_email="a@b.com", submitter_user_id=None,
        auto_promoted=False,
    )
    assert "Theme" not in body
    assert "Viewport" not in body
    assert "Title" not in body


def test_create_issue_skips_when_token_missing(monkeypatch):
    """No GITHUB_FEEDBACK_TOKEN → return None and never call urlopen."""
    monkeypatch.delenv("GITHUB_FEEDBACK_TOKEN", raising=False)
    assert gh.create_gh_issue(title="x", body="y") is None


def test_create_issue_calls_post_with_expected_payload(monkeypatch):
    """When configured, create_gh_issue dispatches to _post_github with
    the right repo, token, and JSON shape; happy path returns the
    (url, number) tuple from the response."""
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "ghp_fake")
    monkeypatch.setenv("GITHUB_FEEDBACK_REPO", "test/repo")

    captured: dict = {}
    def _fake_post(*, repo: str, token: str, payload: dict):
        captured["repo"] = repo
        captured["token"] = token
        captured["payload"] = payload
        return ("https://github.com/test/repo/issues/123", 123)
    monkeypatch.setattr(gh, "_post_github", _fake_post)

    result = gh.create_gh_issue(title="hi", body="b", labels=["custom"])
    assert result == ("https://github.com/test/repo/issues/123", 123)
    assert captured["repo"] == "test/repo"
    assert captured["token"] == "ghp_fake"
    assert captured["payload"]["title"] == "hi"
    assert captured["payload"]["body"] == "b"
    assert captured["payload"]["labels"] == ["custom"]


def test_create_issue_defaults_labels(monkeypatch):
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "ghp_fake")

    captured: dict = {}
    def _fake_post(*, repo, token, payload):
        captured["payload"] = payload
        return ("u", 1)
    monkeypatch.setattr(gh, "_post_github", _fake_post)

    gh.create_gh_issue(title="x", body="y")
    assert captured["payload"]["labels"] == ["feedback", "triage"]


def test_close_issue_skips_when_token_missing(monkeypatch):
    monkeypatch.delenv("GITHUB_FEEDBACK_TOKEN", raising=False)
    assert gh.close_gh_issue("https://github.com/test/repo/issues/1") is False


def test_close_issue_adds_labels_then_closes(monkeypatch):
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "ghp_fake")

    calls: list[dict] = []

    def _fake_request(*, method: str, path: str, token: str, payload: dict | None):
        calls.append({
            "method": method,
            "path": path,
            "token": token,
            "payload": payload,
        })
        return {}

    monkeypatch.setattr(gh, "_github_request_json", _fake_request)

    ok = gh.close_gh_issue(
        "https://github.com/test/repo/issues/44",
        state_reason="not_planned",
        labels=["wontfix"],
    )
    assert ok is True
    assert calls == [
        {
            "method": "POST",
            "path": "/repos/test/repo/issues/44/labels",
            "token": "ghp_fake",
            "payload": {"labels": ["wontfix"]},
        },
        {
            "method": "PATCH",
            "path": "/repos/test/repo/issues/44",
            "token": "ghp_fake",
            "payload": {
                "state": "closed",
                "state_reason": "not_planned",
            },
        },
    ]


def test_fetch_closed_issue_urls_returns_only_closed(monkeypatch):
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "ghp_fake")

    def _fake_request(*, method: str, path: str, token: str, payload: dict | None):
        assert method == "GET"
        if path.endswith("/issues/11"):
            return {"state": "closed"}
        if path.endswith("/issues/12"):
            return {"state": "open"}
        return None

    monkeypatch.setattr(gh, "_github_request_json", _fake_request)

    urls = [
        "https://github.com/test/repo/issues/11",
        "https://github.com/test/repo/issues/12",
        "https://example.com/not-github/13",
    ]
    assert gh.fetch_closed_issue_urls(urls) == {
        "https://github.com/test/repo/issues/11"
    }
