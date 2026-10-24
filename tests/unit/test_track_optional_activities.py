"""Optional refreshers do not become default work or required completion gates."""
from datetime import date

import pytest
import yaml

from app.services import daily_flow, tracks


def load_section(tmp_path, **fields):
    raw = {"slug": "test-track", "title": "Test track", "chapters": [{"title": "Work", "sections": [
        {"title": "Read", "url": "https://example.com/read", "kind": "external_reading", **fields}
    ]}]}
    (tmp_path / "track.md").write_text("---\n" + yaml.safe_dump(raw) + "---\n")
    return tracks.load_all_tracks(tmp_path)["test-track"]


def test_old_authored_sections_keep_defaults(tmp_path):
    track = load_section(tmp_path)
    section = track.all_sections[0]
    assert section.optional is False
    assert section.resources == ()
    assert section.notes == ""
    assert track.required_section_indices == (0,)
    assert track.total_required_sections == 1


def test_optional_resources_and_notes_are_typed_and_preserved(tmp_path):
    track = load_section(tmp_path, optional=True, notes="  Try a small example.  ", resources=[
        {"title": " Reference ", "url": "https://example.com/reference"},
        {"title": "Examples", "url": "http://example.com/examples"},
    ])
    section = track.all_sections[0]
    assert section.optional is True
    assert section.notes == "Try a small example."
    assert [(r.title, r.url) for r in section.resources] == [
        ("Reference", "https://example.com/reference"), ("Examples", "http://example.com/examples")]
    assert track.required_section_indices == ()
    assert track.total_required_sections == 0


@pytest.mark.parametrize("fields,message", [
    ({"optional": "false"}, "optional"), ({"optional": 1}, "optional"),
    ({"optional": None}, "optional"), ({"notes": []}, "notes"),
    ({"resources": {}}, "resources"), ({"resources": ["url"]}, "resources"),
    ({"resources": [{"title": "", "url": "https://example.com"}]}, "title"),
    ({"resources": [{"title": 1, "url": "https://example.com"}]}, "title"),
    ({"resources": [{"title": "Ref", "url": "javascript:alert(1)"}]}, "url"),
    ({"resources": [{"title": "Ref", "url": "//example.com"}]}, "url"),
    ({"resources": [{"title": "Ref", "url": "https:///missing-host"}]}, "url"),
    ({"resources": [{"title": "Ref", "url": 123}]}, "url"),
])
def test_authored_optional_metadata_is_validated(tmp_path, fields, message):
    with pytest.raises(ValueError, match=message):
        load_section(tmp_path, **fields)


@pytest.fixture
def track(monkeypatch):
    monkeypatch.setattr(tracks, 'is_available_track', lambda slug: slug == 'test-track')
    definitions = [
        ("Coding", "external_exercise", (), False),
        ("Technical reading", "external_reading", (0,), False),
        ("Atlas reading", "external_reading", (), False),
        ("Playlist", "external_video", (), False),
        ("Math", "external_reading", (), True),
        ("Tensor practice", "external_exercise", (0,), True),
    ]
    sections = tuple(tracks.TrackSection(title=title, url=f"https://example.com/{idx}", kind=kind,
        duration_min=30, domain_tags=(), axes=(), depends_on=deps, optional=optional)
        for idx, (title, kind, deps, optional) in enumerate(definitions))
    result = tracks.Track("test-track", "Test track", "", "", (tracks.TrackChapter("Work", sections),), "")
    tracks.set_tracks({result.slug: result})
    yield result
    tracks.set_tracks({})


def test_default_selection_stops_after_required_work_but_optional_stays_available(track):
    completed = {0, 1, 2, 3}
    assert track.required_section_indices == (0, 1, 2, 3)
    assert track.total_required_sections == 4
    assert tracks.next_section_index(track, completed) is None
    assert tracks.next_available_section_index(track, completed) is None
    assert tracks.unlocked_section_indices(track, completed) == (4, 5)
    assert tracks.next_section_index(track, completed, "4") == 4
    assert tracks.next_section_index(track, set(), "5") == 0


def test_activity_lanes_surface_independent_reading_and_watch_while_coding(track):
    assert tracks.section_activity_indices(track, set()) == {"exercise": 0, "reading": 2, "watch": 3}
    assert tracks.section_activity_indices(track, {0}) == {"reading": 1, "watch": 3}
    assert tracks.section_activity_indices(track, {0}, 2)["reading"] == 2


def test_optional_activity_requires_explicit_selection_and_never_reappears_completed(track):
    assert tracks.section_activity_indices(track, set(), 4) == {"reading": 4, "exercise": 0, "watch": 3}
    assert tracks.section_activity_indices(track, {0, 1, 2, 3}) == {}
    assert tracks.section_activity_indices(track, {0, 1, 2, 3}, 4) == {"reading": 4}
    assert tracks.section_activity_indices(track, {0, 1, 2, 3, 4}, 4) == {}
    assert tracks.section_activity_indices(track, set(), 5)["exercise"] == 0


def test_daily_flow_counts_required_sections_and_labels_optional_selection(track):
    action = daily_flow.compute_next(today=date(2026, 9, 25), user_settings={"active_track": {"slug": track.slug}})
    assert action.why == "Test track — section 1 of 4"
    action = daily_flow.compute_next(today=date(2026, 9, 25), user_settings={"active_track": {
        "slug": track.slug, "checkpoint_passed_sections": [0, 1, 2, 3], "preferred_section": 4}})
    assert action.title == "Math"
    assert "optional" in action.why.lower()
