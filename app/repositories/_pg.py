"""Shared psycopg helpers for repository conversions.

Postgres returns richer Python types than SQLite did (real bools, real
datetimes, dicts/lists from JSONB, UUID objects from UUID columns), so
the per-table `_row_to_X` helpers stay short. This file centralizes
the few non-trivial conversions.
"""

from __future__ import annotations

import json
from typing import Any


def jsonb(v: Any) -> Any:
    """Normalize a JSONB column value.

    psycopg's default adapter decodes JSONB to Python dicts/lists, so
    most callers get the structured value directly. We still defend
    against:
      - None (column nullable, no value)
      - str (older-style migrations where the value was inserted as
        TEXT and Postgres auto-cast it to JSONB on read — rare)
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return json.loads(v.decode("utf-8"))
    if isinstance(v, str):
        return json.loads(v)
    # memoryview, etc. — best effort.
    return json.loads(str(v))


def uuid_str(v: Any) -> str | None:
    """A UUID column comes back as `uuid.UUID`. We use strings
    everywhere downstream (templates, JSON serialization, scheduler)
    so cast once at the boundary."""
    if v is None:
        return None
    return str(v)


def naive_utc(dt: Any) -> Any:
    """Postgres TIMESTAMPTZ returns tz-aware datetimes. The rest of
    the app was written against the SQLite era's naive-UTC convention
    and uses `datetime.utcnow()` (naive) for comparisons. Strip tz at
    the read boundary so cross-row comparisons stop raising
    `TypeError: can't compare offset-naive and offset-aware datetimes`.

    This is shared across repos. Anywhere you load a TIMESTAMPTZ field
    out of Postgres into a dataclass, pipe it through this helper."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        from datetime import timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
