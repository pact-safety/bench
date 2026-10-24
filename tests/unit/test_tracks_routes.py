"""Route tests for curriculum tracks pages + state transitions."""

from __future__ import annotations


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _sample_tracks():
    from app.services import tracks as tracks_service

    arena = tracks_service.Track(
        slug="arena_3",
        title="ARENA 3.0",
        description="Alignment curriculum",
        source_url="https://example.com/arena",
        chapters=(
            tracks_service.TrackChapter(
                title="Chapter 0",
                sections=(
                    tracks_service.TrackSection(
                        title="0.1 Prerequisites",
                        url="https://example.com/0.1",
                        kind="external_reading",
                        duration_min=45,
                        domain_tags=("python",),
                        axes=("algorithmic",),
                    ),
                    tracks_service.TrackSection(
                        title="0.2 Setup",
                        url="https://example.com/0.2",
                        kind="external_exercise",
                        duration_min=30,
                        domain_tags=("setup",),
                        axes=("transformer_internals",),
                    ),
                ),
            ),
        ),
        body_md="Track notes",
    )

    prework = tracks_service.Track(
        slug="prework",
        title="Prework",
        description="Warmup track",
        source_url="",
        chapters=(
            tracks_service.TrackChapter(
                title="Start",
                sections=(
                    tracks_service.TrackSection(
                        title="Read primer",
                        url="https://example.com/prework",
                        kind="external_reading",
                        duration_min=20,
                        domain_tags=("ml",),
                        axes=("algorithmic",),
                    ),
                ),
            ),
        ),
        body_md="",
    )

    graph = tracks_service.Track(
        slug="graph",
        title="Graph Track",
        description="Dependency fan-out sample",
        source_url="",
        chapters=(
            tracks_service.TrackChapter(
                title="Nodes",
                sections=(
                    tracks_service.TrackSection(
                        title="Node A",
                        url="https://example.com/graph/a",
                        kind="external_reading",
                        duration_min=20,
                        domain_tags=("graph",),
                        axes=("algorithmic",),
                        checkpoint="Explain node A from memory",
                    ),
                    tracks_service.TrackSection(
                        title="Node B",
                        url="https://example.com/graph/b",
                        kind="external_exercise",
                        duration_min=20,
                        domain_tags=("graph",),
                        axes=("algorithmic",),
                        depends_on=(0,),
                    ),
                    tracks_service.TrackSection(
                        title="Node C",
                        url="https://example.com/graph/c",
                        kind="external_exercise",
                        duration_min=20,
                        domain_tags=("graph",),
                        axes=("algorithmic",),
                        depends_on=(0,),
                    ),
                ),
            ),
        ),
        body_md="",
    )

    return {"arena_3": arena, "prework": prework, "graph": graph}


def _check_version(slug, idx):
    from app.services.track_checks import questions_version
    return questions_version(_sample_tracks()[slug], idx)


def _signed_in_client(monkeypatch, settings: dict):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.auth as auth_module
    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    def _save(_uid: str, next_settings: dict) -> None:
        payload = dict(next_settings)
        settings.clear()
        settings.update(payload)

    monkeypatch.setattr(m, "_user_settings", lambda _uid: settings)
    monkeypatch.setattr(m, "_save_user_settings", _save)
    sample = _sample_tracks()
    monkeypatch.setattr(m, "_tracks_by_slug", sample)
    # `app.main.get_track` delegates to `tracks_service.get_track`, which
    # reads its own module-level cache. Both have to be patched so the
    # detail / activate / complete routes find the sample tracks.
    from app.services import tracks as tracks_service
    monkeypatch.setattr(tracks_service, "_tracks_by_slug", sample)
    monkeypatch.setattr(tracks_service, "AVAILABLE_TRACK_SLUGS", tuple(sample))
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="test@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client


def test_get_tracks_renders(monkeypatch):
    settings: dict = {}
    client = _signed_in_client(monkeypatch, settings)

    r = client.get("/tracks", follow_redirects=False)

    assert r.status_code == 200
    assert "Ready to study" in r.text
    assert "ARENA 3.0" in r.text
    assert "/tracks/arena_3" in r.text


def test_get_tracks_shows_first_time_framing_when_no_engagement(monkeypatch):
    """New learners can review the curriculum before activating it."""
    settings: dict = {}  # no active_track, no paused_tracks
    client = _signed_in_client(monkeypatch, settings)

    r = client.get("/tracks", follow_redirects=False)

    assert r.status_code == 200
    assert "Ready to study" in r.text
    assert "Read notes and start" in r.text
    assert "30-minute block" in r.text
    assert 'action="/tracks/arena_3/activate"' not in r.text
    assert "start with ARENA 3.0" not in r.text
    assert "architecture/tracks/" not in r.text


def test_get_tracks_offers_continue_when_track_is_active(monkeypatch):
    settings = {"active_track": {"slug": "arena_3", "cursor": 0}}
    client = _signed_in_client(monkeypatch, settings)

    r = client.get("/tracks", follow_redirects=False)

    assert r.status_code == 200
    assert "Continue your track" in r.text
    assert 'href="/tracks/arena_3#section-0"' in r.text


def test_get_tracks_offers_review_and_resume_when_progress_exists(monkeypatch):
    """Paused work retains a review path and visible completion count."""
    settings = {
        "paused_tracks": {
            "arena_3": {
                "slug": "arena_3",
                "cursor": 0,
                "checkpoint_passed_sections": [0],
            },
        },
    }
    client = _signed_in_client(monkeypatch, settings)

    r = client.get("/tracks", follow_redirects=False)

    assert r.status_code == 200
    assert "Review and resume" in r.text
    assert "1/2 core practice checks completed" in r.text


def test_get_track_detail_success_and_404(monkeypatch):
    settings: dict = {}
    client = _signed_in_client(monkeypatch, settings)

    ok = client.get("/tracks/arena_3", follow_redirects=False)
    missing = client.get("/tracks/missing", follow_redirects=False)

    assert ok.status_code == 200
    assert "Chapter 0" in ok.text
    assert "0.1 Prerequisites" in ok.text

    assert missing.status_code == 404
    assert missing.text == "Not found"


def test_activate_sets_active_track(monkeypatch):
    settings: dict = {}
    client = _signed_in_client(monkeypatch, settings)

    r = client.post("/tracks/arena_3/activate", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers.get("location") == "/tracks/arena_3"
    active = settings.get("active_track")
    assert isinstance(active, dict)
    assert active.get("slug") == "arena_3"
    assert active.get("cursor") == 0
    assert active.get("checkpoint_passed_sections") == []
    assert active.get("completed_sections") == []


def test_activate_from_other_active_preserves_old_cursor_in_paused_tracks(monkeypatch):
    settings = {
        "active_track": {
            "slug": "prework",
            "cursor": 1,
            "started_at": "2026-05-18T10:00:00",
            "completed_sections": [0],
            "completed_at_per_section": {"0": "2026-05-18T10:10:00"},
        }
    }
    client = _signed_in_client(monkeypatch, settings)

    r = client.post("/tracks/arena_3/activate", follow_redirects=False)

    assert r.status_code == 303
    assert settings["active_track"]["slug"] == "arena_3"
    assert settings["paused_tracks"]["prework"]["cursor"] == 1
    assert settings["paused_tracks"]["prework"]["completed_sections"] == [0]


def test_clear_active_preserves_progress_in_paused(monkeypatch):
    settings = {
        "active_track": {
            "slug": "arena_3",
            "cursor": 1,
            "started_at": "2026-05-18T10:00:00",
            "completed_sections": [0],
            "completed_at_per_section": {"0": "2026-05-18T10:05:00"},
        }
    }
    client = _signed_in_client(monkeypatch, settings)

    r = client.post("/tracks/clear-active", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers.get("location") == "/tracks"
    assert "active_track" not in settings
    assert settings["paused_tracks"]["arena_3"]["cursor"] == 1
    assert settings["paused_tracks"]["arena_3"]["completed_sections"] == [0]


def test_complete_requires_current_authored_check_before_checkpoint_pass(monkeypatch):
    settings = {
        "active_track": {
            "slug": "arena_3",
            "cursor": 0,
            "started_at": "2026-05-18T10:00:00",
            "completed_sections": [],
            "completed_at_per_section": {},
        }
    }
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m

    from app.services.track_checks import questions_for_section
    expected = questions_for_section(_sample_tracks()["arena_3"], 0)
    def forbidden_review(*args, **kwargs):
        raise AssertionError("Understanding checks must not review a fabricated attempt")
    monkeypatch.setattr(m.review_service, "review_attempt", forbidden_review)
    initial = client.get("/tracks/arena_3/sections/0")
    assert expected[0] in initial.text
    assert 'name="check_version"' in initial.text

    first = client.post("/tracks/arena_3/sections/0/complete", follow_redirects=False)

    assert first.status_code == 303
    active_after_first = settings["active_track"]
    assert active_after_first["checkpoint_passed_sections"] == []
    assert active_after_first["completed_sections"] == []
    assert active_after_first["checkpoint_questions_per_section"]["0"] == expected

    detail = client.get("/tracks/arena_3/sections/0", follow_redirects=False)
    assert detail.status_code == 200
    assert "Explain from memory" in detail.text
    assert "Complete practice check" not in detail.text
    assert "Save answers" in detail.text
    assert expected[0] in detail.text

    saved = client.post(
        "/tracks/arena_3/sections/0/feedback",
        data={"answers": "I can explain and demonstrate the mechanism.", "confidence": "clear", "check_version": _check_version("arena_3", 0)},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "Complete practice check" in client.get("/tracks/arena_3/sections/0").text

    second = client.post(
        "/tracks/arena_3/sections/0/complete",
        data={"checkpoint_pass": "1"},
        follow_redirects=False,
    )

    assert second.status_code == 303
    active_after_second = settings["active_track"]
    assert active_after_second["cursor"] == 1
    assert active_after_second["checkpoint_passed_sections"] == [0]
    assert active_after_second["completed_sections"] == [0]
    assert "0" not in active_after_second.get("checkpoint_questions_per_section", {})
    stamp = active_after_second["checkpoint_passed_at_per_section"]["0"]
    assert isinstance(stamp, str)
    assert stamp


def test_complete_rejects_locked_section(monkeypatch):
    settings = {
        "active_track": {
            "slug": "graph",
            "cursor": 0,
            "started_at": "2026-05-18T10:00:00",
            "checkpoint_passed_sections": [],
            "completed_sections": [],
            "completed_at_per_section": {},
        }
    }
    client = _signed_in_client(monkeypatch, settings)

    r = client.post("/tracks/graph/sections/2/complete", follow_redirects=False)

    assert r.status_code == 400
    assert r.text == "Cannot complete a locked section."
    assert settings["active_track"]["cursor"] == 0
    assert settings["active_track"]["checkpoint_passed_sections"] == []
    assert settings["active_track"]["completed_sections"] == []


def test_checkpoint_pass_unlocks_dependency_fanout(monkeypatch):
    settings = {
        "active_track": {
            "slug": "graph",
            "cursor": 1,
            "started_at": "2026-05-18T10:00:00",
            "checkpoint_passed_sections": [0],
            "completed_sections": [0],
            "checkpoint_passed_at_per_section": {"0": "2026-05-18T10:05:00"},
            "completed_at_per_section": {"0": "2026-05-18T10:05:00"},
        }
    }
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m

    from app.services.track_checks import questions_for_section
    expected = questions_for_section(_sample_tracks()["graph"], 2)

    first = client.post("/tracks/graph/sections/2/complete", follow_redirects=False)
    assert first.status_code == 303
    assert settings["active_track"]["checkpoint_questions_per_section"]["2"] == expected

    saved = client.post(
        "/tracks/graph/sections/2/feedback",
        data={"answers": "I can explain and demonstrate the mechanism.", "confidence": "clear", "check_version": _check_version("graph", 2)},
        follow_redirects=False,
    )
    assert saved.status_code == 303

    second = client.post(
        "/tracks/graph/sections/2/complete",
        data={"checkpoint_pass": "1"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    active = settings["active_track"]
    assert active["checkpoint_passed_sections"] == [0, 2]
    assert active["completed_sections"] == [0, 2]
    assert active["cursor"] == 1


def test_reactivation_resumes_saved_cursor(monkeypatch):
    settings = {
        "paused_tracks": {
            "arena_3": {
                "slug": "arena_3",
                "cursor": 2,
                "started_at": "2026-05-18T10:00:00",
                "completed_sections": [0, 1],
                "completed_at_per_section": {
                    "0": "2026-05-18T10:05:00",
                    "1": "2026-05-18T10:15:00",
                },
            }
        }
    }
    client = _signed_in_client(monkeypatch, settings)

    r = client.post("/tracks/arena_3/activate", follow_redirects=False)

    assert r.status_code == 303
    active = settings["active_track"]
    assert active["slug"] == "arena_3"
    assert active["cursor"] == 2
    assert active["checkpoint_passed_sections"] == [0, 1]
    assert active["completed_sections"] == [0, 1]
    assert "arena_3" not in settings.get("paused_tracks", {})
