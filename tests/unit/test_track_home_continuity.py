from pathlib import Path

from app.services import tracks
from app.services.track_content import item_slug


def _catalog(monkeypatch):
    import app.main as m
    catalog = tracks.load_all_tracks(Path(__file__).resolve().parents[2] / "content/tracks")
    monkeypatch.setattr(tracks, "_tracks_by_slug", catalog)
    return m, catalog["ml4good-prework-fall-2026"]


def test_active_track_reading_and_watch_follow_curriculum(monkeypatch):
    m, track = _catalog(monkeypatch)
    settings = {"active_track": {"slug": track.slug, "checkpoint_passed_sections": []}}
    context = m._active_track_materials(settings)
    assert context["cards"]["reading"]["idx"] == 5
    assert "Capabilities" in context["cards"]["reading"]["section"].title
    assert context["cards"]["watch"]["idx"] == 10
    assert context["cards"]["exercise"]["idx"] == 0
    settings["active_track"]["checkpoint_passed_sections"] = [5]
    assert m._active_track_materials(settings)["cards"]["reading"]["idx"] == 6
    settings.pop("active_track")
    assert m._active_track_materials(settings) is None


def test_optional_progress_never_inflates_core_completion(monkeypatch):
    m, track = _catalog(monkeypatch)
    optional = next(i for i, section in enumerate(track.all_sections) if section.optional)
    state = {"active_track": {"slug": track.slug, "checkpoint_passed_sections": [0, optional]}}
    progress = m._build_home_active_track_progress(settings=state)
    assert progress["passed_count"] == 1
    assert progress["total"] == 11
    assert progress["optional_completed"] == 1


def test_track_cards_replace_unrelated_completed_reading(monkeypatch):
    m, track = _catalog(monkeypatch)
    from types import SimpleNamespace
    from starlette.requests import Request
    context = m._active_track_materials({"active_track": {"slug": track.slug, "checkpoint_passed_sections": []}})
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
    request.state.user_session = None
    request.state.user_settings = {}
    old = SimpleNamespace(slug="unrelated-reading", title="Unrelated completed reading", id=999, kind="reading", axes=[], source="", duration_min=10)
    html = m.templates.get_template("home.html").render(request=request, config=m.config,
        track_materials=context, reading_card_item=old, reading_card_done_today=True,
        progress_by_id={}, scored=[], recent=[], daily_slots=[], daily_done=0, daily_total=5,
        done_today_items=[], skill_scores={}, axis_labels={}, home_rail={})
    assert "AI Safety Atlas" in html
    assert "Unrelated completed reading" not in html
    assert f"/content/{item_slug(track.slug, track.all_sections[5].url)}" in html
