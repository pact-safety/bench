"""Integration tests for Aim consolidation routes."""

from __future__ import annotations

from datetime import datetime

import pytest


pytestmark = pytest.mark.integration


def _insert_test_jd(user_id: str) -> int:
    from app import main as m
    from app.models import JD

    now = datetime.utcnow()
    jd_id = m.jd_repo.insert(
        JD(
            id=None,
            user_id=user_id,
            title="Research Engineer (test)",
            org="Acme Labs",
            source_text="Build retrieval pipelines and eval loops.",
            axis_weights={axis: 0.5 for axis in m.assess_service.AXES},
            signal_tags=["retrieval", "evaluation"],
            summary="Test JD summary",
            method="keyword_fallback",
            model_used=None,
            parsed_at=now,
            created_at=now,
            archived_at=None,
            iac_profile=None,
            iac_evidence_md=None,
            iac_fit_md=None,
        )
    )
    return jd_id


def test_legacy_skill_jd_credential_routes_redirect_to_aim_with_302(signed_in_user):
    client, _user = signed_in_user

    r = client.get("/skills", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/aim#stand"

    r = client.get("/jds", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/aim#aim"

    r = client.get("/credentials", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/aim#evidence"


def test_legacy_jd_detail_route_redirects_to_aim_detail_with_302(signed_in_user):
    client, _user = signed_in_user

    r = client.get("/jds/42", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/aim/jd/42"


def test_aim_page_renders_expected_sections(signed_in_user):
    client, _user = signed_in_user

    r = client.get("/aim", follow_redirects=False)
    assert r.status_code == 200
    assert "Where you stand" in r.text
    assert "Where you're going" in r.text
    assert "Your evidence" in r.text
    assert 'id="stand" open' in r.text
    assert 'id="aim"' in r.text
    assert 'id="evidence"' in r.text


def test_aim_jd_detail_route_renders_existing_template_with_back_link(signed_in_user):
    client, user = signed_in_user
    jd_id = _insert_test_jd(user["user_id"])

    r = client.get(f"/aim/jd/{jd_id}", follow_redirects=False)
    assert r.status_code == 200
    assert "Research Engineer (test)" in r.text
    assert "Back to Aim" in r.text
    assert 'href="/aim#aim"' in r.text
