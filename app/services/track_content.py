"""Publish approved curriculum resources through the existing content library."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from ..models import ContentItem
from ..repositories import ContentRepository
from .tracks import Track, TrackSection, available_tracks


_KINDS = {"reading", "video", "podcast", "exercise"}


@dataclass(frozen=True)
class TrackContentReference:
    track: Track
    section_idx: int
    section: TrackSection
    title: str
    url: str
    kind: str
    is_primary: bool


def item_slug(track_slug: str, url: str) -> str:
    # Titles and curriculum order change; neither may move a learner's notes
    # or rating onto a different resource. Keep fragments as source identity.
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()
    return f"track-{track_slug}-{digest}"


def _kind(raw: str) -> str:
    kind = raw.removeprefix("external_")
    if kind not in _KINDS:
        raise ValueError(f"Unsupported track content kind: {raw!r}")
    return kind


def _references(tracks: dict[str, Track]) -> list[TrackContentReference]:
    references = []
    for track in available_tracks(tracks):
        for idx, section in enumerate(track.all_sections):
            if section.url.strip():
                references.append(TrackContentReference(
                    track, idx, section, section.title, section.url.strip(),
                    _kind(section.kind), True,
                ))
            for resource in section.resources:
                if resource.url.strip():
                    references.append(TrackContentReference(
                        track, idx, section, resource.title, resource.url.strip(),
                        _kind(resource.kind), False,
                    ))
    return references


def references_for_slug(
    tracks: dict[str, Track], slug: str,
) -> list[TrackContentReference]:
    """Return curriculum contexts for an item, including repeated resources."""
    return [ref for ref in _references(tracks) if item_slug(ref.track.slug, ref.url) == slug]


def catalog_items(tracks: dict[str, Track]) -> list[ContentItem]:
    """Derive one authored item per URL within each approved track."""
    grouped: dict[str, list[TrackContentReference]] = {}
    for ref in _references(tracks):
        grouped.setdefault(item_slug(ref.track.slug, ref.url), []).append(ref)

    items = []
    for slug, references in grouped.items():
        # A reference in an earlier section must not erase the resource's own
        # type or duration when it is also a primary lesson elsewhere.
        ref = next((row for row in references if row.is_primary), references[0])
        content_md = f"Part of {ref.track.title}: {ref.section.title}."
        if ref.is_primary and ref.section.notes:
            content_md += f"\n\n{ref.section.notes}"
        items.append(ContentItem(
            id=0,
            slug=slug,
            kind=ref.kind,
            title=ref.title,
            source=ref.track.title,
            url=ref.url,
            duration_min=ref.section.duration_min if ref.is_primary else None,
            axes=list(dict.fromkeys(axis for row in references for axis in row.section.axes)),
            domain_tags=list(dict.fromkeys(tag for row in references for tag in row.section.domain_tags)),
            content_md=content_md,
            authored_by="Bench curriculum",
        ))
    return items


def sync_track_content(tracks: dict[str, Track], repo: ContentRepository) -> int:
    """Upsert approved resources, preserving IDs and skipping unchanged items."""
    items = catalog_items(tracks)
    if not items:
        return 0
    hashes = repo.hashes_by_slug()
    for item in items:
        encoded = json.dumps(asdict(item), sort_keys=True, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if hashes.get(item.slug) != digest:
            repo.upsert(item, content_hash=digest)
    return len(items)
