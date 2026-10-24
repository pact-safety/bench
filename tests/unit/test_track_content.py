from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import track_content
from app.services.tracks import Track, TrackChapter, TrackResource, TrackSection, available_tracks, load_all_tracks


def section(url="https://example.com/lesson", **changes):
    defaults = dict(title="Lesson", url=url, kind="external_reading", duration_min=30,
                    axes=("training_mechanics",), domain_tags=("pytorch",),
                    notes="Read the examples carefully.")
    return TrackSection(**(defaults | changes))


def track(*sections, slug="arena_3"):
    return Track(slug=slug, title="Curriculum", description="", source_url="https://example.com",
                 chapters=(TrackChapter(title="Chapter", sections=tuple(sections)),), body_md="")


def catalog(*sections):
    item = track(*sections)
    return {item.slug: item}


@pytest.mark.parametrize("kind", ["reading", "video", "podcast", "exercise"])
def test_primary_types_keep_authored_metadata(kind):
    item, = track_content.catalog_items(catalog(section(kind=f"external_{kind}")))
    assert item.kind == kind
    assert item.duration_min == 30
    assert item.axes == ["training_mechanics"]
    assert item.domain_tags == ["pytorch"]
    assert item.source_kind == "authored"
    assert item.created_by_user_id is None
    assert "Read the examples carefully." in item.content_md


def test_supplements_use_own_kind_without_inheriting_section_duration_or_notes():
    extra = TrackResource(title="Video explanation", url="https://example.com/video", kind="video")
    primary, supplement = track_content.catalog_items(catalog(section(kind="external_exercise", resources=(extra,))))
    assert primary.kind == "exercise"
    assert supplement.kind == "video"
    assert supplement.duration_min is None
    assert supplement.domain_tags == primary.domain_tags
    assert "Read the examples carefully." not in supplement.content_md


def test_identity_survives_reordering_and_title_changes_and_separates_tracks():
    original = section()
    slug = track_content.catalog_items(catalog(original))[0].slug
    changed = track_content.catalog_items(catalog(section("https://example.com/new"), replace(original, title="Renamed")))
    assert changed[1].slug == slug
    assert slug == track_content.item_slug("arena_3", original.url)
    assert slug != track_content.item_slug("ml4good-prework-fall-2026", original.url)


def test_dedup_preserves_primary_metadata_and_merges_tags_and_references():
    extra = TrackResource(title="Supplement", url="https://example.com/shared", kind="reading")
    first = section(resources=(extra,))
    second = section(extra.url, title="Primary video", kind="external_video", domain_tags=("autograd",))
    tracks = catalog(first, second)
    items = track_content.catalog_items(tracks)
    assert len(items) == 2
    shared = next(item for item in items if item.url == extra.url)
    assert shared.title == "Primary video"
    assert shared.kind == "video"
    assert shared.duration_min == 30
    assert shared.domain_tags == ["pytorch", "autograd"]
    references = track_content.references_for_slug(tracks, shared.slug)
    assert [(ref.section_idx, ref.is_primary) for ref in references] == [(0, False), (1, True)]


def test_pending_tracks_and_empty_urls_are_not_published():
    pending = track(section(), slug="mats")
    tracks = {pending.slug: pending, **catalog(section(""))}
    assert track_content.catalog_items(tracks) == []
    assert track_content.references_for_slug(tracks, track_content.item_slug("mats", section().url)) == []


def test_sync_skips_unchanged_and_updates_same_slug_when_metadata_changes():
    tracks = catalog(section())
    repo = Mock()
    repo.hashes_by_slug.return_value = {}
    assert track_content.sync_track_content(tracks, repo) == 1
    item = repo.upsert.call_args.args[0]
    digest = repo.upsert.call_args.kwargs["content_hash"]
    assert len(digest) == 64
    repo.hashes_by_slug.return_value = {item.slug: digest}
    repo.upsert.reset_mock()
    assert track_content.sync_track_content(tracks, repo) == 1
    repo.upsert.assert_not_called()
    assert track_content.sync_track_content(catalog(section(title="Revised")), repo) == 1
    assert repo.upsert.call_args.args[0].slug == item.slug
    assert repo.upsert.call_args.kwargs["content_hash"] != digest


def test_catalog_rejects_unknown_resource_types():
    with pytest.raises(ValueError, match="kind"):
        track_content.catalog_items(catalog(section(kind="external_unknown")))


def test_authored_catalog_publishes_every_approved_primary_and_supplement():
    tracks = load_all_tracks(Path(__file__).resolve().parents[2] / "content" / "tracks")
    items = track_content.catalog_items(tracks)
    expected_slugs = {
        track_content.item_slug(track.slug, url)
        for track in available_tracks(tracks)
        for section in track.all_sections
        for url in (section.url, *(resource.url for resource in section.resources))
        if url
    }
    assert {item.slug for item in items} == expected_slugs
    video = next(item for item in items if item.url == "https://www.youtube.com/watch?v=IvgV6QcsC64")
    assert video.kind == "video"
    assert video.duration_min is None
