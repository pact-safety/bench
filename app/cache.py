"""In-process read-through cache for rarely-changing rows.

Postgres round-trips from a residential US connection to Supabase
us-east-1 are ~150ms each. Home page made ~10 RT → ~1.5s minimum wait.
Most of those round-trips are reading rows that change ONCE per app
lifetime (the authored content), or once-per-mutation (user settings).
Cache them in process memory and the cost drops to a single read at
warmup + invalidations on writes.

Scope (intentionally minimal):

- **problems** — authored markdown, only changes when content_loader
  upserts at startup. Cache forever; invalidate on `upsert()`.
- **content_items** — same. The user's "Add external content" route
  is the only runtime mutator; invalidate there too.
- **per-user settings** — `users.settings_json`. Changes when user
  edits profile / accessibility / skips onboarding / activates JD.
  Per-uid cache; invalidate on `_save_user_settings` — AND a short
  TTL, because invalidation is in-process only: with 2 Fly machines
  behind the LB, a settings save on machine A used to leave machine
  B serving the stale copy forever. The TTL is the cross-machine
  convergence bound; the explicit invalidate keeps the writing
  machine instant.

What's NOT cached:
- Anything filtered by user_id that gets written per-request:
  attempts, content_progress, review_state, sessions, reflections.
  These should always read fresh.
- Anything LLM-touching where staleness has tail-risk consequences.

This module is intentionally simple (a dict + a lock). Future
multi-worker uvicorn would need Redis or similar, but for the
single-worker app this is the right shape.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


_LOCK = threading.RLock()
# key -> (value, deadline). deadline is None for cache-forever entries
# (problems, authored content — immutable per deploy) or a monotonic
# timestamp for TTL'd ones (user settings).
_STORE: dict[str, tuple[Any, float | None]] = {}


def get(key: str, *, loader: Callable[[], Any], ttl_s: float | None = None) -> Any:
    """Return the cached value for `key`, or call `loader()` to fill
    it. Thread-safe; the lock is recursive so a loader that calls
    another `get()` won't deadlock.

    `ttl_s` bounds staleness for entries whose writes can happen on
    ANOTHER machine (in-process invalidation can't reach us). None =
    cache until invalidated, the right shape for per-deploy-immutable
    content."""
    with _LOCK:
        if key in _STORE:
            value, deadline = _STORE[key]
            if deadline is None or time.monotonic() < deadline:
                return value
            _STORE.pop(key, None)
        value = loader()
        deadline = time.monotonic() + ttl_s if ttl_s is not None else None
        _STORE[key] = (value, deadline)
        return value


def invalidate(key: str) -> None:
    """Drop a specific cache entry. Idempotent (no-op if absent)."""
    with _LOCK:
        _STORE.pop(key, None)


def invalidate_prefix(prefix: str) -> int:
    """Drop every entry whose key starts with `prefix`. Returns count
    dropped. Useful for "invalidate all settings for any user" style
    bulk operations during admin actions."""
    with _LOCK:
        keys = [k for k in _STORE if k.startswith(prefix)]
        for k in keys:
            _STORE.pop(k, None)
        return len(keys)


def clear_all() -> None:
    """Nuke the entire cache. Test setup uses this; production code
    shouldn't need it."""
    with _LOCK:
        _STORE.clear()


def stats() -> dict[str, int]:
    """Debug helper: how many entries, total approximate size."""
    with _LOCK:
        return {"entries": len(_STORE)}
