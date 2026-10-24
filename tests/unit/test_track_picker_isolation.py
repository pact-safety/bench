"""Curriculum resources cannot bypass track selection and dependency gates."""
from types import SimpleNamespace

import pytest

from app.models import ContentItem
from app.services.content import pick_daily


def _item(slug, item_id=1, **kwargs):
    return ContentItem(id=item_id, slug=slug, kind="reading", title=slug, **kwargs)


@pytest.mark.parametrize("slug", ["track-active-locked-resource", "track-other-course-resource"])
def test_daily_picker_never_selects_curriculum_resources(slug):
    resource = _item(slug, axes=["transformer_internals"], duration_min=1)
    authored = _item("authored-reading", item_id=2, duration_min=60)

    assert pick_daily([resource, authored], {}, {}) is authored


def test_daily_picker_returns_none_when_only_curriculum_resources_exist():
    assert pick_daily([_item("track-only-resource")], {}, {}) is None


def test_unread_curriculum_resource_does_not_replace_completed_authored_content():
    resource = _item("track-locked-resource")
    authored = _item("authored-reading", item_id=2)
    progress = {authored.id: SimpleNamespace(status="completed")}

    assert pick_daily([resource, authored], progress, {}) is authored


def test_user_added_track_prefixed_title_remains_eligible():
    user_item = _item("track-gradients-abc", source_kind="user")

    assert pick_daily([user_item], {}, {}) is user_item
