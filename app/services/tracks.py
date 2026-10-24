"""Track loader for sequential curriculum tracks.

Tracks are authored as markdown files under ``content/tracks/*.md`` using
YAML frontmatter for structure and markdown body text for human-readable
notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class TrackResource:
    title: str
    url: str
    kind: str = "reading"


@dataclass(frozen=True)
class TrackSection:
    title: str
    url: str
    kind: str
    duration_min: int | None
    domain_tags: tuple[str, ...]
    axes: tuple[str, ...]
    # Optional explicit dependency edges by flattened section index.
    # None means "use the legacy sequential fallback".
    depends_on: tuple[int, ...] | None = None
    # Capability assertion for the section's completion checkpoint.
    checkpoint: str = ""
    # Bench content slugs (exercises/readings) to work BEFORE opening the
    # external notebook. The pedagogy: a learner who has already traced the
    # shapes and named the subgoals does not face a blank function body.
    prep: tuple[str, ...] = ()
    # BEN-143 — cold checkpoints. Problem slugs the learner re-implements in
    # Compose, away from the notebook that produced the answer.
    #
    # The section's own "understanding check" is warm: you have just read the
    # material and you self-assess. That is exactly what ARENA's Colab
    # autocomplete already lets you fake. A cold checkpoint asks for the same
    # capability later, in an editor with no completions, and the test result
    # comes from actually running the code.
    #
    # Empty is the honest default. Bench's problem set is transformer- and
    # LLM-shaped, so several Chapter 0 sections (ray tracing, CNNs, VAEs)
    # genuinely have no counterpart — inventing a loose mapping would make
    # the checkpoint a formality, which is worse than not having one.
    cold_checkpoint: tuple[str, ...] = ()
    optional: bool = False
    resources: tuple[TrackResource, ...] = ()
    notes: str = ""
    check_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackChapter:
    title: str
    sections: tuple[TrackSection, ...]


@dataclass(frozen=True)
class Track:
    slug: str
    title: str
    description: str
    source_url: str
    chapters: tuple[TrackChapter, ...]
    body_md: str

    @property
    def all_sections(self) -> tuple[TrackSection, ...]:
        """Flattened in-order section list."""
        return tuple(section for chapter in self.chapters for section in chapter.sections)

    @property
    def total_sections(self) -> int:
        return len(self.all_sections)

    @property
    def required_section_indices(self) -> tuple[int, ...]:
        return tuple(idx for idx, section in enumerate(self.all_sections) if not section.optional)

    @property
    def total_required_sections(self) -> int:
        return len(self.required_section_indices)


_tracks_by_slug: dict[str, Track] = {}

# Preserve pending curricula and their saved progress without offering them
# as learner-ready until their content and gates have been audited.
AVAILABLE_TRACK_SLUGS: tuple[str, ...] = ("ml4good-prework-fall-2026", "arena_3")


def is_available_track(slug: str) -> bool:
    """Whether a curriculum is approved for learner-facing use."""
    return slug in AVAILABLE_TRACK_SLUGS


def available_tracks(catalog: dict[str, Track] | None = None) -> tuple[Track, ...]:
    """Return loaded, audited curricula in the recommended catalog order."""
    catalog = _tracks_by_slug if catalog is None else catalog
    return tuple(catalog[slug] for slug in AVAILABLE_TRACK_SLUGS if slug in catalog)


def get_available_track(slug: str) -> Track | None:
    """Return a loaded curriculum only when it is learner-ready."""
    return get_track(slug) if is_available_track(slug) else None


def set_tracks(tracks_by_slug: dict[str, Track] | None) -> None:
    """Replace the in-memory track lookup map.

    Startup code calls this after loading track configs so other
    services (for example daily_flow) can resolve active-track slugs
    without importing app.main.
    """
    global _tracks_by_slug
    _tracks_by_slug = dict(tracks_by_slug or {})


def get_track(slug: str) -> Track | None:
    """Return a loaded track by slug, if present."""
    return _tracks_by_slug.get(slug)


def _require_non_empty_str(raw: dict, key: str, path: Path) -> str:
    val = raw.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{path}: missing required field '{key}'")
    return val.strip()


def _as_string_tuple(raw: object, field_path: str, path: Path) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{path}: {field_path} must be a list")
    out: list[str] = []
    for idx, val in enumerate(raw):
        if not isinstance(val, str):
            raise ValueError(f"{path}: {field_path}[{idx}] must be a string")
        cleaned = val.strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def _as_index_tuple(raw: object, field_path: str, path: Path) -> tuple[int, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{path}: {field_path} must be a list")

    out: list[int] = []
    for idx, val in enumerate(raw):
        if type(val) is not int:
            raise ValueError(f"{path}: {field_path}[{idx}] must be an integer")
        dep_idx = val
        if dep_idx < 0:
            raise ValueError(f"{path}: {field_path}[{idx}] must be >= 0")
        if dep_idx not in out:
            out.append(dep_idx)
    return tuple(out)


def _as_resources(raw: object, field_path: str, path: Path) -> tuple[TrackResource, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{path}: {field_path} must be a list")
    resources = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: {field_path}[{idx}] must be a mapping")
        title = _require_non_empty_str(entry, "title", path)
        url = _require_non_empty_str(entry, "url", path)
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid or any(char.isspace() for char in url):
            raise ValueError(f"{path}: {field_path}[{idx}].url must be an HTTP(S) URL")
        kind = entry.get("kind", "reading")
        if not isinstance(kind, str) or kind not in {"reading", "video", "podcast", "exercise"}:
            raise ValueError(f"{path}: {field_path}[{idx}].kind must be reading, video, podcast, or exercise")
        resources.append(TrackResource(title=title, url=url, kind=kind))
    return tuple(resources)


def _parse_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")

    fm_raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML frontmatter") from exc
    if not isinstance(fm, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    return fm, body


def _parse_track_file(path: Path) -> Track:
    fm, body = _parse_frontmatter(path.read_text(), path)

    slug = _require_non_empty_str(fm, "slug", path)
    title = _require_non_empty_str(fm, "title", path)

    raw_chapters = fm.get("chapters", [])
    if raw_chapters is None:
        raw_chapters = []
    if not isinstance(raw_chapters, list):
        raise ValueError(f"{path}: chapters must be a list")

    chapters: list[TrackChapter] = []
    for chapter_idx, raw_chapter in enumerate(raw_chapters):
        chapter_field = f"chapters[{chapter_idx}]"
        if not isinstance(raw_chapter, dict):
            raise ValueError(f"{path}: {chapter_field} must be a mapping")

        chapter_title = _require_non_empty_str(raw_chapter, "title", path)

        raw_sections = raw_chapter.get("sections", [])
        if raw_sections is None:
            raw_sections = []
        if not isinstance(raw_sections, list):
            raise ValueError(f"{path}: {chapter_field}.sections must be a list")

        sections: list[TrackSection] = []
        for section_idx, raw_section in enumerate(raw_sections):
            section_field = f"{chapter_field}.sections[{section_idx}]"
            if not isinstance(raw_section, dict):
                raise ValueError(f"{path}: {section_field} must be a mapping")

            section_title = _require_non_empty_str(raw_section, "title", path)
            duration_raw = raw_section.get("duration_min")
            if duration_raw in (None, ""):
                duration_min = None
            else:
                try:
                    duration_min = int(duration_raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{path}: {section_field}.duration_min must be an integer") from exc

            has_custom_dependencies = "depends_on" in raw_section or "prerequisites" in raw_section
            depends_on_raw = raw_section.get("depends_on")
            if depends_on_raw is None and "prerequisites" in raw_section:
                depends_on_raw = raw_section.get("prerequisites")

            depends_on = (
                _as_index_tuple(depends_on_raw, f"{section_field}.depends_on", path)
                if has_custom_dependencies
                else None
            )

            checkpoint_raw = raw_section.get("checkpoint")
            if checkpoint_raw is None:
                checkpoint_raw = raw_section.get("checkpoint_assertion")
            checkpoint = str(checkpoint_raw or "").strip()

            prep = _as_string_tuple(
                raw_section.get("prep", []), f"{section_field}.prep", path
            )

            optional = raw_section.get("optional", False)
            if not isinstance(optional, bool):
                raise ValueError(f"{path}: {section_field}.optional must be a boolean")
            notes = raw_section.get("notes", "")
            if not isinstance(notes, str):
                raise ValueError(f"{path}: {section_field}.notes must be a string")

            sections.append(
                TrackSection(
                    title=section_title,
                    url=str(raw_section.get("url", "")).strip(),
                    kind=str(raw_section.get("kind", "")).strip(),
                    duration_min=duration_min,
                    domain_tags=_as_string_tuple(
                        raw_section.get("domain_tags", []),
                        f"{section_field}.domain_tags",
                        path,
                    ),
                    axes=_as_string_tuple(
                        raw_section.get("axes", []),
                        f"{section_field}.axes",
                        path,
                    ),
                    depends_on=depends_on,
                    checkpoint=checkpoint,
                    prep=prep,
                    optional=optional,
                    notes=notes.strip(),
                    check_questions=_as_string_tuple(raw_section.get("check_questions", []), f"{section_field}.check_questions", path),
                    resources=_as_resources(raw_section.get("resources", []), f"{section_field}.resources", path),
                    cold_checkpoint=_as_string_tuple(
                        raw_section.get("cold_checkpoint", []),
                        f"{section_field}.cold_checkpoint",
                        path,
                    ),
                )
            )

        chapters.append(TrackChapter(title=chapter_title, sections=tuple(sections)))

    track = Track(
        slug=slug,
        title=title,
        description=str(fm.get("description", "")).strip(),
        source_url=str(fm.get("source_url", "")).strip(),
        chapters=tuple(chapters),
        body_md=body.strip(),
    )

    for idx, section in enumerate(track.all_sections):
        if section.depends_on is None:
            continue
        for dep_idx in section.depends_on:
            if dep_idx >= track.total_sections:
                raise ValueError(
                    f"{path}: section {idx} depends on missing section index {dep_idx}"
                )
            if dep_idx == idx:
                raise ValueError(f"{path}: section {idx} cannot depend on itself")

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(idx: int) -> None:
        if idx in visiting:
            raise ValueError(f"{path}: dependency cycle involving section {idx}")
        if idx in visited:
            return
        visiting.add(idx)
        # Include sequential fallback edges: an explicit forward edge can
        # cycle through a later section whose dependencies were omitted.
        for dependency in dependencies_for(track, idx):
            visit(dependency)
        visiting.remove(idx)
        visited.add(idx)

    for idx in range(track.total_sections):
        visit(idx)
    return track


def load_all_tracks(tracks_dir: Path) -> dict[str, Track]:
    """Parse every ``content/tracks/*.md`` into a Track keyed by slug."""
    if not tracks_dir.exists():
        return {}

    tracks: dict[str, Track] = {}
    for path in sorted(tracks_dir.glob("*.md")):
        track = _parse_track_file(path)
        if track.slug in tracks:
            raise ValueError(f"{path}: duplicate track slug '{track.slug}'")
        tracks[track.slug] = track
    return tracks


def section_at(track: Track, cursor: int) -> TrackSection | None:
    """Return the section at cursor index, or None if cursor is invalid."""
    sections = track.all_sections
    if 0 <= cursor < len(sections):
        return sections[cursor]
    return None


def dependencies_for(track: Track, idx: int) -> tuple[int, ...]:
    """Return prerequisite section indexes for a section.

    Back-compat: when a section has no explicit dependency metadata, we
    preserve the original sequential progression by requiring the
    previous section (except section 0).
    """
    section = section_at(track, idx)
    if section is None:
        return ()
    if section.depends_on is not None:
        return section.depends_on
    if idx <= 0:
        return ()
    return (idx - 1,)


def missing_prerequisites(track: Track, idx: int, completed: set[int]) -> tuple[tuple[int, str], ...]:
    """Return unsatisfied direct dependencies as stable index/title pairs."""
    if idx in completed:
        return ()
    return tuple((dep, track.all_sections[dep].title)
                 for dep in dependencies_for(track, idx) if dep not in completed)


def is_unlocked(track: Track, idx: int, checkpoint_passed_sections: set[int]) -> bool:
    """Return whether the section's prerequisites are currently satisfied."""
    if idx < 0 or idx >= track.total_sections:
        return False
    if idx in checkpoint_passed_sections:
        return True
    return not missing_prerequisites(track, idx, checkpoint_passed_sections)


def unlocked_section_indices(track: Track, checkpoint_passed_sections: set[int]) -> tuple[int, ...]:
    """Return all currently-unlocked section indexes that are not passed."""
    out: list[int] = []
    for idx in range(track.total_sections):
        if idx in checkpoint_passed_sections:
            continue
        if is_unlocked(track, idx, checkpoint_passed_sections):
            out.append(idx)
    return tuple(out)


def recommended_section_indices(track: Track) -> tuple[int, ...]:
    """Recommend a learning order without changing persisted section indexes."""
    if track.slug == "ml4good-prework-fall-2026":
        # Start with the independent Atlas readings, then camp preparation,
        # before the technical sequence. Availability still enforces deps.
        preferred = (5, 6, 7, 8, 9, 10, 0, 1, 2, 3, 4)
        return tuple(idx for idx in preferred if idx < track.total_sections) + tuple(
            idx for idx in range(track.total_sections) if idx not in preferred
        )
    return tuple(range(track.total_sections))


def next_available_section_index(track: Track, checkpoint_passed_sections: set[int]) -> int | None:
    """Return the first unlocked required section, or None when complete/blocked."""
    unlocked = set(unlocked_section_indices(track, checkpoint_passed_sections))
    for idx in recommended_section_indices(track):
        if idx not in unlocked:
            continue
        if not track.all_sections[idx].optional:
            return idx
    return None


def next_section_index(
    track: Track, completed: set[int], preferred_section: object = None,
) -> int | None:
    """Honor an available saved selection, otherwise choose required work."""
    # Form values are strings, but booleans/floats must not silently choose
    # another section through int() coercion.
    if isinstance(preferred_section, (int, str)) and not isinstance(preferred_section, bool):
        try:
            preferred = int(preferred_section)
        except ValueError:
            preferred = -1
        if preferred not in completed and is_unlocked(track, preferred, completed):
            return preferred
    return next_available_section_index(track, completed)


def section_activity_indices(
    track: Track, completed: set[int], preferred_section: object = None,
) -> dict[str, int]:
    """Choose parallel reading/watch/exercise sections without changing progress."""
    selected = next_section_index(track, completed, preferred_section)
    unlocked = unlocked_section_indices(track, completed)
    order = ([selected] if selected is not None else []) + [idx for idx in unlocked if idx != selected]
    kinds = {
        "reading": "reading", "external_reading": "reading",
        "watch": "watch", "external_watch": "watch", "video": "watch", "external_video": "watch",
        "podcast": "watch", "external_podcast": "watch",
        "exercise": "exercise", "external_exercise": "exercise",
    }
    activities: dict[str, int] = {}
    for idx in order:
        section = track.all_sections[idx]
        if section.optional and idx != selected:
            continue
        kind = kinds.get(section.kind.strip().lower())
        if kind is not None:
            activities.setdefault(kind, idx)
    return activities


def cold_checkpoint_slugs(track: Track, idx: int) -> tuple[str, ...]:
    """Problem slugs that verify a section cold, or () when it has none."""
    section = section_at(track, idx)
    if section is None:
        return ()
    return section.cold_checkpoint
