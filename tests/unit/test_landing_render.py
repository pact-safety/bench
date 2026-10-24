"""The landing page renders for an anonymous visitor, and its numbers are
counted rather than written down."""

from __future__ import annotations

from app.main import _landing_stats


def test_stats_are_counted_from_shipped_content():
    stats = _landing_stats()
    for key in ("problems", "warmups", "readings", "exercises", "tracks", "axes"):
        assert key in stats, f"landing template reads stats.{key}"
        assert isinstance(stats[key], int)
    # The page says "42 problems" etc. by interpolating these. A zero here
    # would render "0 problems" on the front door rather than failing loudly,
    # so assert the content directories were actually found.
    assert stats["problems"] > 0
    assert stats["axes"] > 0


def test_axes_count_matches_the_assessment_service():
    """The copy claims a number of skill axes; it must be the real one."""
    from app.services import assessment as assess_svc

    assert _landing_stats()["axes"] == len(assess_svc.AXES)


def test_anonymous_get_root_renders_landing_not_a_redirect(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m

    client = TestClient(m.app)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200, (
        f"anonymous / returned {resp.status_code}; the landing page is the "
        "logged-out front door and must not bounce to /login"
    )
    body = resp.text
    assert "Request access" in body
    assert "For researchers" in body
    assert "For programs" in body
