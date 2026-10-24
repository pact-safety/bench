"""Switching curricula preserves learner work without rewriting reading history."""
from copy import deepcopy

from tests.unit.test_tracks_routes import _signed_in_client, _check_version


def test_switch_clear_and_resume_preserve_each_tracks_work(monkeypatch):
    def saved_state(slug, idx, completed):
        return {
            "slug": slug,
            "checkpoint_passed_sections": completed,
            "checkpoint_passed_at_per_section": {str(i): "2026-09-24T10:00:00Z" for i in completed},
            "preferred_section": idx,
            "session_per_section": {str(idx): {
                "stopping_point": f"{slug}: cell 4",
                "next_action": f"{slug}: trace the next shape",
                "artifact_url": f"https://example.com/{slug}/notebook",
                "updated_at": "2026-09-24T11:00:00Z",
            }},
            "checkpoint_questions_per_section": {str(idx): [f"Explain {slug}."]},
            "checkpoint_response_per_section": {str(idx): {
                "answers": f"My {slug} explanation",
                "check_version": _check_version(slug, idx),
                "confidence": "uncertain",
                "artifact_url": f"https://example.com/{slug}/evidence",
                "feedback": {"source": "self_review", "summary": f"Revisit {slug}."},
                "updated_at": "2026-09-24T11:01:00Z",
            }},
            "started_at": "2026-09-24T09:00:00Z",
        }

    unrelated_settings = {"profile": {"goal": "interview"}, "daily_mode": "deep", "onboarding_skipped": True}
    settings = {
        **deepcopy(unrelated_settings),
        "paused_tracks": {
            "graph": saved_state("graph", 2, [0]),
            "arena_3": saved_state("arena_3", 1, [0]),
        },
    }
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m

    # Curriculum activation must not mark unrelated library items read,
    # erase their recitations, or alter their saved reflections.
    def forbidden_content_write(*args, **kwargs):
        raise AssertionError("Track switching mutated independent content progress")

    for method in (
        "mark_completed", "mark_unread", "toggle_favorite", "set_rating",
        "save_reflection", "save_recitation_state", "save_paper_state",
    ):
        monkeypatch.setattr(m.content_repo, method, forbidden_content_write)

    def activate(slug):
        response = client.post(f"/tracks/{slug}/activate", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == f"/tracks/{slug}"
        assert slug not in settings.get("paused_tracks", {})
        return deepcopy(settings["active_track"])

    track_a = activate("graph")
    assert track_a["preferred_section"] == track_a["cursor"] == 2
    assert track_a["checkpoint_passed_sections"] == [0]
    track_b = activate("arena_3")
    assert settings["paused_tracks"]["graph"] == track_a

    response = client.post("/tracks/clear-active", follow_redirects=False)
    assert response.status_code == 303
    assert "active_track" not in settings
    assert settings["paused_tracks"]["arena_3"] == track_b
    assert settings["paused_tracks"]["graph"] == track_a

    assert activate("graph") == track_a
    html = client.get("/tracks/graph/sections/2").text
    assert "graph: cell 4" in html
    assert "My graph explanation" in html
    assert "https://example.com/graph/notebook" in html
    assert settings["paused_tracks"]["arena_3"] == track_b
    assert activate("arena_3") == track_b
    assert settings["paused_tracks"]["graph"] == track_a
    for key, value in unrelated_settings.items():
        assert settings[key] == value
