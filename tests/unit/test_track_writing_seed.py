"""Draft seeds follow the same active-track reading as Today."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from app.services import tracks
from app.services.track_content import item_slug


@pytest.fixture
def writing_seed(monkeypatch):
    import app.main as m

    catalogue = tracks.load_all_tracks(Path(__file__).resolve().parents[2] / "content/tracks")
    monkeypatch.setattr(tracks, "_tracks_by_slug", catalogue)
    track = catalogue["ml4good-prework-fall-2026"]
    unrelated = SimpleNamespace(id=99, title="Generic reading", slug="generic")
    progress = {99: SimpleNamespace(notes_md="Independent reading notes")}
    pick = Mock(return_value=unrelated)
    catalogue_read = Mock(return_value=[unrelated])
    insert = Mock(return_value=73)
    monkeypatch.setattr(m.content_service, "pick_daily", pick)
    monkeypatch.setattr(m.content_repo, "all_by_kind", catalogue_read)
    monkeypatch.setattr(m.content_repo, "progress_for_user", lambda uid: progress)
    monkeypatch.setattr(m.assessment_repo, "latest_completed", lambda uid: None)
    monkeypatch.setattr(m.attempt_repo, "all_for_user", lambda uid: [])
    monkeypatch.setattr(m.writing_repo, "insert", insert)

    def create(settings):
        request = Request({"type": "http", "method": "POST", "path": "/writings", "headers": []})
        request.state.user_session = SimpleNamespace(user_id="test-user")
        request.state.user_settings = settings
        response = m.writings_new(request, initiative_slug="")
        assert response.status_code == 303
        assert response.headers["location"] == "/writings/73"
        assert insert.call_args.args == ("test-user",)
        return insert.call_args.kwargs

    return SimpleNamespace(create=create, track=track, pick=pick, catalogue_read=catalogue_read,
                           progress=progress, unrelated=unrelated, main=m)


def test_track_reading_seeds_atlas_and_saved_stopping_point(writing_seed):
    track = writing_seed.track
    saved = "Stopped after comparing benchmark scores with deployment performance."
    result = writing_seed.create({"active_track": {
        "slug": track.slug, "checkpoint_passed_sections": [],
        "session_per_section": {"5": {"stopping_point": saved, "next_action": "Read the limitations"}},
    }})
    assert result["source_refs"] == [{"kind": "track_section", "track_slug": track.slug,
        "section_index": 5, "title": track.all_sections[5].title}]
    assert "AI Safety Atlas 1: Capabilities" in result["body_md"]
    assert f"Track section: /content/{item_slug(track.slug, track.all_sections[5].url)}" in result["body_md"]
    assert saved in result["body_md"]
    assert "Generic reading" not in result["body_md"]
    writing_seed.pick.assert_not_called()
    writing_seed.catalogue_read.assert_not_called()


def test_no_active_track_retains_generic_reading_and_notes(writing_seed):
    result = writing_seed.create({})
    assert result["source_refs"] == [{"kind": "reading", "id": 99, "slug": "generic", "title": "Generic reading"}]
    assert "## From today's reading — Generic reading" in result["body_md"]
    assert "Independent reading notes" in result["body_md"]
    writing_seed.catalogue_read.assert_called_once_with("reading", user_id="test-user")
    writing_seed.pick.assert_called_once_with([writing_seed.unrelated], writing_seed.progress, {})


def test_finished_active_track_does_not_seed_unrelated_reading(writing_seed):
    result = writing_seed.create({"active_track": {
        "slug": writing_seed.track.slug,
        "checkpoint_passed_sections": list(writing_seed.track.required_section_indices),
    }})
    assert result["source_refs"] == []
    assert result["body_md"] == ""
    writing_seed.pick.assert_not_called()
    writing_seed.catalogue_read.assert_not_called()


def test_finished_track_still_preserves_recent_attempt_seed(writing_seed, monkeypatch):
    monkeypatch.setattr(writing_seed.main.attempt_repo, "all_for_user", lambda uid: [
        SimpleNamespace(id=8, problem_id=4, notes_md="Remember the gradient reset")])
    monkeypatch.setattr(writing_seed.main.problem_repo, "get_by_id", lambda pid: SimpleNamespace(title="Optimizer step"))
    result = writing_seed.create({"active_track": {
        "slug": writing_seed.track.slug,
        "checkpoint_passed_sections": list(writing_seed.track.required_section_indices),
    }})
    assert result["source_refs"] == [{"kind": "attempt", "id": 8, "title": "Optimizer step"}]
    assert "Remember the gradient reset" in result["body_md"]
    assert "Generic reading" not in result["body_md"]
    writing_seed.pick.assert_not_called()
