"""Deterministic understanding checks grounded in authored track content."""

from __future__ import annotations

import hashlib
import json

from app.services.tracks import Track, section_at


CHECK_VERSION = 'authored-v1'


def questions_for_section(track: Track, section_idx: int) -> list[str]:
    """Return authored questions, or an explicitly labeled checkpoint rehearsal."""
    section = section_at(track, section_idx)
    if section is None:
        return []
    if section.check_questions:
        return list(section.check_questions)
    # A checkpoint is a capability to rehearse, not evidence that an exercise
    # was attempted. Never fabricate an attempt to obtain reviewer questions.
    if section.checkpoint:
        return [
            f'Checkpoint rehearsal for {section.title}: {section.checkpoint} '
            'How would you demonstrate this capability with a small concrete example?',
            f'For the checkpoint in {section.title}, what assumption or boundary '
            'case could make that example misleading, and how would you check it?',
            f'Which part of the checkpoint in {section.title} can you explain '
            'without the source, and which part needs another look?',
        ]
    return [
        f'After studying {section.title}, which central idea can you explain '
        'with an example from the linked material?',
        f'What question about {section.title} remains unresolved, and which '
        'part of the source would you revisit?',
    ]


def questions_version(track: Track, section_idx: int) -> str:
    """Identify the exact check content so old responses are not silently reused."""
    section = section_at(track, section_idx)
    if section is None:
        return ''
    content = {
        'track': track.slug,
        'index': section_idx,
        'title': section.title,
        'url': section.url,
        'checkpoint': section.checkpoint,
        'questions': questions_for_section(track, section_idx),
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()
    return f'{CHECK_VERSION}:{digest}'
