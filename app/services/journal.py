"""Journal — read surface for chat outcomes (BEN-82, GH #212).

PR A of the chat_outcomes table cutover (see
``docs/proposals/chat-outcomes-table.md``): this module now delegates
to ``ChatOutcomesRepository`` (migration 009) for all reads. The old
JSON storage (``user_settings.chat_outcomes``) stays as a write-side
parachute for one release; PR B removes it.

Public API is kept stable so /decisions and /focus consumers don't
rebuild around the storage swap. Each function takes a repo handle +
user_id rather than a settings dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import ChatOutcome
    from ..repositories.chat_outcomes_repository import ChatOutcomesRepository


@dataclass(frozen=True)
class JournalEntry:
    """One chat outcome normalized for rendering. Mirrors the legacy
    shape so templates and tests downstream don't need to change."""
    id: str
    initiative: str
    decisions: str
    next_actions: str
    chat_url: str | None
    created_at: datetime


def _from_chat_outcome(co: "ChatOutcome") -> JournalEntry:
    return JournalEntry(
        id=co.id,
        initiative=co.initiative_slug,
        decisions=co.decisions or "",
        next_actions=co.next_actions or "",
        chat_url=co.chat_url if (co.chat_url and co.chat_url.strip()) else None,
        created_at=co.created_at,
    )


def list_entries(
    repo: "ChatOutcomesRepository",
    user_id: str,
    *,
    initiative: str | None = None,
    limit: int = 50,
) -> list[JournalEntry]:
    """Reverse-chronological list, optionally filtered by initiative."""
    rows = repo.list_for_user(user_id, initiative_slug=initiative, limit=limit)
    return [_from_chat_outcome(co) for co in rows]


def get_entry(
    repo: "ChatOutcomesRepository",
    user_id: str,
    entry_id: str,
) -> JournalEntry | None:
    if not isinstance(entry_id, str) or not entry_id:
        return None
    co = repo.get(entry_id, user_id=user_id)
    return _from_chat_outcome(co) if co else None


def initiatives_with_counts(
    repo: "ChatOutcomesRepository",
    user_id: str,
) -> list[tuple[str, int]]:
    """Return ``[(slug, count), ...]`` sorted by count desc then slug."""
    return repo.initiatives_with_counts(user_id)
