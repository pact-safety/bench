"""Per-node multi-modal content generator for BEN-88 (Tracks B).

**Scaffold status (2026-05-24): the LLM call is deliberately stubbed.**

The operator's hard constraint for this sub-issue:

> Generated content (exercises, debugging problems) must go to an
> operator-review state before going live in a track. Never auto-publish
> generated curriculum — hallucinated or subtly-wrong exercises reaching
> the live track is the main risk.

This module ships the **substrate**: a pure-functional generator that
takes a track + section index + target kind and produces a Draft-shaped
markdown blob conforming to the existing content frontmatter. The Sonnet
prompt and live API call are explicit TODO points the operator wires in
when they're satisfied with the review surface.

The stub produces a *placeholder* content draft per call so the rest of
the pipeline (draft persistence, review surface, promote workflow) can
be exercised end-to-end without burning API credits or risking
hallucinated curriculum. Drafts produced by the stub are labeled in
their content_md so it's obvious they're placeholders.

When wiring the live call:
- Use Haiku 4.5 first (templated task; Sonnet's reasoning isn't earning
  the cost). Mirrors hamming.py's #223 lesson.
- Cache the system prompt with cache_control: ephemeral.
- Return ONE draft per call; operator decides per-draft promote/discard.
- Pass the section's axes + domain_tags as the constraint vocabulary.

The Socratic check (BEN-89) is a separate concern handled in
``app/main.py:_track_socratic_questions_for_section``. This module
generates *content* (readings, exercises, problems); not understanding
checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from . import tracks as tracks_service


ContentKind = Literal["reading", "video", "podcast", "exercise"]
_VALID_KINDS: tuple[ContentKind, ...] = ("reading", "video", "podcast", "exercise")


class GenerationError(ValueError):
    """Raised when a generation request is invalid (unknown kind, bad
    track/section reference, etc.). NOT raised for LLM-side failures —
    those return a "fallback" draft instead."""


@dataclass(frozen=True)
class GeneratedDraft:
    """Result of a single per-node content generation."""
    kind: ContentKind
    slug: str               # for the file at content/<kind>/_drafts/<slug>.md
    frontmatter_md: str     # full markdown file content (frontmatter + body)
    is_placeholder: bool    # True when produced by the stub (no LLM call)
    section_title: str
    track_slug: str


def _placeholder_slug(track_slug: str, section_idx: int, kind: ContentKind) -> str:
    """Slugify a draft so re-runs don't collide across nodes/kinds."""
    return f"{track_slug}-s{section_idx:02d}-{kind}-draft"


def _placeholder_frontmatter_md(
    *,
    kind: ContentKind,
    slug: str,
    track: tracks_service.Track,
    section: tracks_service.TrackSection,
) -> str:
    """Emit a placeholder draft with the right shape. Labeled as
    [PLACEHOLDER] in title + body so the operator can't miss what's
    happening if a placeholder accidentally lands in production.

    The frontmatter matches the existing reading/video/exercise schema
    so promote() into the live directory works without further edits.
    """
    today = date.today().isoformat()
    axes_yaml = ", ".join(section.axes) if section.axes else ""
    tags_yaml = ", ".join(section.domain_tags) if section.domain_tags else ""

    body_warning = (
        "**This is a placeholder draft.** The LLM-backed generator is "
        "not wired in this scaffold. Replace the content here with the "
        "actual generated material before promoting to live.\n\n"
        f"Section being scaffolded: {section.title}\n\n"
        f"Track: {track.title} ({track.slug})\n\n"
        f"Operator next step: wire the Sonnet/Haiku call in "
        f"app/services/content_generation.py and replace this placeholder."
    )

    return (
        "---\n"
        f"slug: {slug}\n"
        f"kind: {kind}\n"
        f'title: "[PLACEHOLDER] {section.title} — {kind} draft"\n'
        f'source: "Auto-generated from track {track.slug}"\n'
        f'url: "{section.url}"\n'
        f"duration_min: {section.duration_min or 20}\n"
        f"axes: [{axes_yaml}]\n"
        f"domain_tags: [{tags_yaml}]\n"
        f"authored_by: ben_88_scaffold_v0\n"
        f"authored_date: {today}\n"
        f"version: 1\n"
        f"---\n\n"
        f"{body_warning}\n"
    )


def generate_draft_for_node(
    *,
    track: tracks_service.Track,
    section_idx: int,
    kind: ContentKind,
) -> GeneratedDraft:
    """Produce ONE content draft for a track node.

    Stub: returns a placeholder draft. The full implementation will call
    Haiku with the section title + axes + domain_tags as constraint
    vocabulary, parse the response, and return a real draft. Until then,
    callers can still exercise the persistence + review + promote flow
    end-to-end against placeholders.
    """
    if kind not in _VALID_KINDS:
        raise GenerationError(f"unknown kind {kind!r}; valid: {_VALID_KINDS}")

    section = tracks_service.section_at(track, section_idx)
    if section is None:
        raise GenerationError(
            f"section_idx={section_idx} is out of range for track "
            f"{track.slug!r} (has {track.total_sections} sections)"
        )

    slug = _placeholder_slug(track.slug, section_idx, kind)
    frontmatter_md = _placeholder_frontmatter_md(
        kind=kind, slug=slug, track=track, section=section,
    )

    # ---- TODO: wire live LLM call here ----
    # When the operator is satisfied with the review surface, replace
    # the placeholder with:
    #
    #   from anthropic import Anthropic
    #   from . import spend_cap
    #
    #   client = Anthropic()
    #   resp = client.messages.create(
    #       model="claude-haiku-4-5",
    #       max_tokens=900,
    #       system=[{
    #           "type": "text",
    #           "text": SYSTEM_PROMPT_BY_KIND[kind],
    #           "cache_control": {"type": "ephemeral"},
    #       }],
    #       messages=[{"role": "user", "content": _build_user_prompt(track, section)}],
    #   )
    #   spend_cap.record_usage_for(uid, resp)
    #   frontmatter_md = _parse_generated_content(resp, slug=slug, ...)
    #
    # Note: SYSTEM_PROMPT_BY_KIND should constrain the output to the
    # frontmatter schema used by content/<kind>/*.md, and explicitly
    # warn against fabricating citations / URLs that aren't real.

    return GeneratedDraft(
        kind=kind,
        slug=slug,
        frontmatter_md=frontmatter_md,
        is_placeholder=True,
        section_title=section.title,
        track_slug=track.slug,
    )
