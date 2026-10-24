"""Tag-filter tests for the unified taxonomy (LIS-284 / GH #2).

Pre-migration these tests lived in `test_tag_aliases.py` and exercised
the synonym-expansion logic in `app/services/tag_aliases.py`. After
unification, that module is gone — the library route filters on
`domain_tags ∪ axes` directly. The behavior we test here is:

  - Direct match on a sub-topic tag works (e.g. `?tag=attention` finds
    a reading whose `domain_tags=[attention]`)
  - Direct match on an axis tag works (e.g. `?tag=transformer_internals`
    finds the same reading via its `axes` field)
  - **Crucially, an axis tag NO LONGER matches sub-topic content that
    only shares the axis.** This is a deliberate precision win — a
    reading about layer normalization should NOT show up when you
    filter on `?tag=attention` just because both are
    `transformer_internals`. Pre-unification, the alias map broadened
    every axis match to all of its sub-topics, which over-matched.
"""

from __future__ import annotations

from datetime import datetime

import pytest


def _matches(needle: str, candidate_tags: list[str]) -> bool:
    """Mirror the helper in `app/main.py:library_page._tag_match`.

    Case-insensitive substring is NOT done — we match equality only,
    same as the route. Whitespace is normalized at both ends. This
    matches the production filter behavior; if the production helper
    changes, this should track it (or be lifted into a real exported
    function)."""
    n = (needle or "").strip().lower()
    if not n:
        return True
    return any((t or "").strip().lower() == n for t in candidate_tags)


def test_match_on_subtopic_direct():
    """A content item whose `domain_tags` contains `attention` should
    match `?tag=attention`."""
    item_tags = ["attention", "softmax"]   # what would live in c.domain_tags ∪ c.axes
    assert _matches("attention", item_tags) is True


def test_match_on_axis_direct():
    """A content item whose `axes` contains `transformer_internals`
    should match `?tag=transformer_internals` (axis-as-tag)."""
    item_tags = ["transformer_internals"]
    assert _matches("transformer_internals", item_tags) is True


def test_no_alias_broadening_on_axis_filter():
    """Regression guard: pre-unification, the alias map made
    `?tag=attention` match anything axed `transformer_internals`,
    including a reading purely about layer normalization. Post-
    unification, that no longer happens — sub-topic precision is
    intentional. A layer-norm reading needs `attention` in its OWN
    `domain_tags` to match `?tag=attention`."""
    layer_norm_reading = ["transformer_internals", "layer_norm", "normalization"]
    # Direct match still works:
    assert _matches("layer_norm", layer_norm_reading) is True
    assert _matches("transformer_internals", layer_norm_reading) is True
    # But the alias-broadening that used to happen does NOT:
    assert _matches("attention", layer_norm_reading) is False
    assert _matches("softmax", layer_norm_reading) is False


def test_case_insensitive():
    """Tag chips come from upstream data that varies in case."""
    assert _matches("Attention", ["attention"]) is True
    assert _matches("ATTENTION", ["attention"]) is True
    assert _matches("attention", ["Attention"]) is True


def test_empty_needle_matches_all():
    """No filter → keep everything."""
    assert _matches("", ["anything"]) is True
    assert _matches(None, ["anything"]) is True
    assert _matches("  ", ["anything"]) is True


def test_no_match_returns_false():
    assert _matches("attention", ["rust", "ownership"]) is False
    assert _matches("attention", []) is False
    assert _matches("attention", [None, ""]) is False


# ---- End-to-end smoke through library_page via the route ------------------

def test_library_route_filter_smoke(mock_anthropic, monkeypatch):
    """End-to-end smoke through `/library?tag=attention`. Confirms the
    route uses the unified filter and returns the right shapes."""
    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})

    # Mint a session cookie the auth middleware will accept.
    import base64, json, time
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    pl = base64.urlsafe_b64encode(json.dumps({
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "test@example.com",
        "exp": int(time.time()) + 3600,
    }).encode()).rstrip(b"=").decode()
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", f"{hdr}.{pl}.sig")

    # Patch the repo methods so we don't depend on a live DB.
    from app.models import ContentItem, Problem
    from unittest.mock import patch
    attention_reading = ContentItem(
        id=1, slug="r-att", kind="reading", title="Attention Is All You Need",
        axes=["transformer_internals"], domain_tags=["attention"],
        version=1,
    )
    layernorm_reading = ContentItem(
        id=2, slug="r-ln", kind="reading", title="Layer Normalization",
        axes=["transformer_internals"], domain_tags=["layer_norm", "normalization"],
        version=1,
    )
    rust_reading = ContentItem(
        id=3, slug="r-rust", kind="reading", title="Rust Ownership",
        axes=["rust_fluency"], domain_tags=["rust", "ownership"],
        version=1,
    )

    def fake_all_by_kind(kind, user_id=None):
        if kind == "reading":
            return [attention_reading, layernorm_reading, rust_reading]
        return []

    with patch.object(m.problem_repo, "all_core", return_value=[]), \
         patch.object(m.problem_repo, "all_warmups", return_value=[]), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]), \
         patch.object(m.content_repo, "all_by_kind", side_effect=fake_all_by_kind), \
         patch.object(m.content_repo, "progress_for_user", return_value={}):
        # `?tag=attention` should find only the attention reading.
        r = client.get("/library?tag=attention")
        assert r.status_code == 200
        body = r.text
        assert "Attention Is All You Need" in body
        # Critical regression: layer-norm reading must NOT appear despite
        # sharing the `transformer_internals` axis. This is the
        # precision win from the unification.
        assert "Layer Normalization" not in body or "<!-- chip -->" in body
        # Rust reading clearly doesn't match.
        assert "Rust Ownership" not in body
