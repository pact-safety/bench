"""Top-nav coverage.

Originally guarded a 9-label flat rail (Drill/Learn/Tracks/Reflect/
Write/Aim/Focus/Decisions/News, issue #127). After the 2026-05-28
WS2 grammar pass, the nav is hybrid grouped: 5 affordances at the
top — one direct link (Today) plus four dropdown groups (Prep,
Ingest, Produce, Assess) — and the sub-routes live inside the
group dropdowns.

What this file now guards:
- The five top-level affordances render in the expected order on
  every page (public + signed-in).
- Activating a sub-route lights up the correct group, so the user
  always knows where they are.
- /aim still exists and renders the consolidated page (Skills + JDs
  + Credentials), and /skills still redirects to /aim.
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime
from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _client():
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app), m


def _set_fake_session_cookie(client, *, user_id: str = _USER_UUID) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": user_id,
                "email": "test@example.com",
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    client, m = _client()
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


# ─── Nav-shape extraction helpers ──────────────────────────────────

def _primary_nav_html(page_html: str) -> str:
    """The <nav class="header-nav nav--hybrid"> block from base.html.
    Matches with or without the nav--hybrid modifier so the test
    survives a future single-class rename."""
    match = re.search(
        r'<nav class="header-nav[^"]*" aria-label="Primary">(.*?)</nav>',
        page_html,
        re.S,
    )
    assert match, "expected primary header nav in response html"
    return match.group(1)


def _top_level_labels(page_html: str) -> list[str]:
    """Top-level affordances — direct links + group triggers, in
    document order. The current shape: one `.header-nav__link`
    (Today) plus four `.nav__group-trigger` buttons. The test
    asserts the visible label set without caring about which tag
    rendered it."""
    nav = _primary_nav_html(page_html)
    # Pull labels from both .header-nav__link <a> tags and
    # .nav__group-trigger <button> tags, in source order.
    pattern = re.compile(
        r'(?:<a class="header-nav__link[^"]*" href="[^"]+">|'
        r'<summary class="nav__group-trigger[^"]*"[^>]*>)'
        r'([^<]+?)</(?:a|summary)>',
        re.S,
    )
    return [m.strip() for m in pattern.findall(nav)]


def _active_top_level(page_html: str) -> list[str]:
    """Top-level affordances currently rendered with `is-active`."""
    nav = _primary_nav_html(page_html)
    pattern = re.compile(
        r'(?:<a class="header-nav__link\s+is-active[^"]*" href="[^"]+">|'
        r'<summary class="nav__group-trigger\s+is-active[^"]*"[^>]*>)'
        r'([^<]+?)</(?:a|summary)>',
        re.S,
    )
    return [m.strip() for m in pattern.findall(nav)]


# ─── Shape ────────────────────────────────────────────────────────

def test_primary_nav_renders_hybrid_affordance_set_on_public_page():
    """Six top-level affordances, in this order, on every non-admin
    page. 'Connect' came online when /connecting landed (WS6);
    originally labeled 'Relationships', renamed 2026-05-28 to
    action-verb framing consistent with the rest of the set. 'Mira'
    is absent here because this is a SIGNED-OUT page — since v2.1
    slice 3 the link shows for every session (test_mira_admin_gate.py
    covers the open gate + the LIS_MIRA_ADMIN_ONLY emergency flip)."""
    client, _m = _client()
    r = client.get("/request-access")

    assert r.status_code == 200
    assert _top_level_labels(r.text) == [
        "Today",
        "Prep",
        "Ingest",
        "Produce",
        "Assess",
        "Connect",
    ]


# ─── Active-state mapping ─────────────────────────────────────────

def test_today_affordance_is_active_on_journal_page(monkeypatch):
    """/journal/<date> sets nav_section='drill'; that lights up the
    top-level Today link, not a group."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.attempt_repo, "all_for_user", return_value=[]), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.feedback_repo, "list_for_user", return_value=[]):
        r = client.get("/journal/2000-01-01")

    assert r.status_code == 200
    assert _active_top_level(r.text) == ["Today"]


def test_ingest_group_is_active_on_library_add_page(monkeypatch):
    """/library and /library/add are in the Ingest group."""
    client, _m = _signed_in_client(monkeypatch)

    r = client.get("/library/add")

    assert r.status_code == 200
    assert _active_top_level(r.text) == ["Ingest"]


def test_produce_group_is_active_on_reflect_detail_page(monkeypatch):
    """/reflect is in the Produce group."""
    client, m = _signed_in_client(monkeypatch)

    from app.models import Reflection

    reflection = Reflection(
        id=1,
        user_id=_USER_UUID,
        period_start=datetime(2026, 5, 10, 0, 0, 0),
        period_end=datetime(2026, 5, 17, 0, 0, 0),
        generated_at=datetime(2026, 5, 17, 0, 0, 0),
        prompts=[{"label": "Pattern", "prompt": "What changed?"}],
        response_md=None,
        response_updated_at=None,
        summary_md=None,
        method="keyword_fallback",
        model_used=None,
    )

    with patch.object(m.reflection_repo, "get", return_value=reflection):
        r = client.get("/reflect/1")

    assert r.status_code == 200
    assert _active_top_level(r.text) == ["Produce"]


def test_produce_group_is_active_on_writings_index_page(monkeypatch):
    """/writings is in the Produce group."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.writing_repo, "list_for_user", return_value=[]):
        r = client.get("/writings")

    assert r.status_code == 200
    assert _active_top_level(r.text) == ["Produce"]


def test_aim_route_renders_consolidated_page(monkeypatch):
    """After #128 consolidation: /aim renders the Skills+JDs+
    Credentials aggregate page directly. /aim is in the Assess group."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.jd_repo, "list_for_user", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m.credentials_repo, "list_completed_for_user", return_value=[]):
        r = client.get("/aim", follow_redirects=False)

    assert r.status_code == 200
    assert _active_top_level(r.text) == ["Assess"]


def test_aim_route_shows_multiple_stored_credential_runs(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    from app.models import CredentialAssessment, CredentialFile, CredentialRun

    run_new = CredentialRun(
        id=11,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 18, 9, 0, 0),
        completed_at=datetime(2026, 5, 18, 9, 2, 0),
        status_text="uploaded",
    )
    run_old = CredentialRun(
        id=9,
        user_id=_USER_UUID,
        started_at=datetime(2026, 5, 16, 10, 0, 0),
        completed_at=datetime(2026, 5, 16, 10, 2, 0),
        status_text="uploaded",
    )

    _first_files = {
        11: CredentialFile(
            id=1,
            run_id=11,
            filename="resume-v3.pdf",
            content_type="application/pdf",
            byte_size=2048,
            sha256="abc",
            extracted_text="text",
            uploaded_at=datetime(2026, 5, 18, 9, 1, 0),
        ),
    }

    _latest_assessments = {
        11: CredentialAssessment(
            id=1,
            run_id=11,
            inferred_axis_scores={
                "debugging": 0.91,
                "eval_design": 0.83,
                "data_pipeline": 0.72,
                "algorithmic": 0.40,
            },
            summary_md="Strong **debugging** examples and concrete eval ownership.",
            rationale={},
            method="keyword_fallback",
            model_used=None,
            created_at=datetime(2026, 5, 18, 9, 3, 0),
        ),
    }

    with patch.object(m.assessment_repo, "latest_completed", return_value=None), \
         patch.object(m.jd_repo, "list_for_user", return_value=[]), \
         patch.object(m.reflection_repo, "list_for_user", return_value=[]), \
         patch.object(m.credentials_repo, "list_completed_for_user", return_value=[run_new, run_old]), \
         patch.object(
             m.credentials_repo,
             "first_files_by_run",
             side_effect=lambda run_ids: {rid: _first_files[rid] for rid in run_ids if rid in _first_files},
         ), \
         patch.object(
             m.credentials_repo,
             "latest_assessments_by_run",
             side_effect=lambda run_ids: {rid: _latest_assessments[rid] for rid in run_ids if rid in _latest_assessments},
         ):
        r = client.get("/aim", follow_redirects=False)

    assert r.status_code == 200
    assert "Stored credentials" in r.text
    assert "resume-v3.pdf" in r.text
    assert "Credential run #9" in r.text  # filename fallback when no file row exists
    assert "Debugging real ML code" in r.text
    assert "Eval design" in r.text
    assert "Data pipelines" in r.text
    assert "Re-analyze" in r.text
    assert 'href="/credentials/11"' in r.text
    assert 'href="/credentials/9"' in r.text
    assert r.text.index("resume-v3.pdf") < r.text.index("Credential run #9")


def test_skills_route_redirects_to_aim_anchor(monkeypatch):
    """Inverse of the above: /skills is now the legacy redirect target."""
    client, _m = _signed_in_client(monkeypatch)

    r = client.get("/skills", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers.get("location", "").startswith("/aim")


def test_primary_groups_use_native_disclosures_and_truthful_next_label():
    client, _ = _client()
    nav = _primary_nav_html(client.get('/request-access').text)
    assert nav.count('<details class="nav__group">') == 4
    assert nav.count('<summary class="nav__group-trigger') == 4
    assert 'role="menu"' not in nav
    assert 'aria-expanded="false"' not in nav
    assert 'Continue next step' in nav
    assert 'pick a problem' not in nav.lower()
