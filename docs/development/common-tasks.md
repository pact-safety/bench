# Common dev tasks

Cheat-sheet for the things you'll do most often.

## Reset your local data

`/settings/reset` in the running app. Or directly:

```sql
DELETE FROM attempts            WHERE user_id = '<your-uuid>';
DELETE FROM content_progress    WHERE user_id = '<your-uuid>';
DELETE FROM assessment_runs     WHERE user_id = '<your-uuid>';
DELETE FROM reflections         WHERE user_id = '<your-uuid>';
-- … keep jds / writings / feedback / credentials
UPDATE users SET settings_json = settings_json - 'onboarding_skipped'
WHERE id = '<your-uuid>';
```

## Inspect the feedback inbox

```bash
# Replace <digest> with the full SHA-256 hex digest of your UTF-8 user ID.
cat "data/feedback/users/<digest>/inbox.md"
cat "data/feedback/users/<digest>/archive.md"
```

Each user's mirror is regenerated separately after feedback actions. The old
`data/feedback/inbox.md` and `archive.md` files, if present, are legacy snapshots
and are no longer updated or automatically removed.

Or the web UI: `/feedback/inbox` (filter by status: open / backlog / closed).

## Test a single Claude call without booting the app

```python
# python
from anthropic import Anthropic
from app.services import hints, review, voices

# Hints with a real Problem
from app.repositories.problem_repository import ProblemRepository
from app.db import conn
p = ProblemRepository(conn).get_by_slug("softmax-temperature")
print(hints.get_hint(p, "explore", "shapes: x is (B, V)", code=None, count_so_far=0))

# Review with a voice
# (need an Attempt object; load one or use the sample_attempt fixture in tests)
```

## Re-run only one test file

```bash
.venv/bin/pytest tests/unit/test_voices.py -v
```

## Tail the logs

```bash
.venv/bin/uvicorn app.main:app --port 8765 --log-level debug
```

Sentry sends events on uncaught exceptions (`SENTRY_DSN` in `.env.local`). Set it blank to disable.

## Force-reload content (skip the content-hash cache)

```bash
LIS_FORCE_RELOAD=1 .venv/bin/uvicorn app.main:app --port 8765
```

## Skip the startup content loader (for tests)

```bash
LIS_SKIP_STARTUP_LOAD=1 .venv/bin/pytest
```

Already set in `tests/conftest.py` for all unit tests.

## Switch active JD

```python
# In settings_json:
settings["active_jd_id"] = <jd_id>
```

Or via the UI: `/jds/<id> → Activate`.

## Cache invalidation

The in-process cache (`app/cache.py`) lives on the running process. Repository writes invalidate by prefix (e.g., `content_items:*` after a new item). To wipe manually in dev:

```python
from app import cache
cache.clear_all()
```

## Where each LLM model is set

Each service reads its model from an env var with a default:

| Service | Env var | Default model |
|---|---|---|
| Review | `ANTHROPIC_MODEL` | `claude-sonnet-4-5` |
| Hints | `ANTHROPIC_HINT_MODEL` | `claude-haiku-4-5-20251001` |
| External capture parse | `ANTHROPIC_PARSE_MODEL` | `claude-haiku-4-5` |
| Hamming (reflect) | `ANTHROPIC_HAMMING_MODEL` | falls back to `ANTHROPIC_MODEL` |

Override in `.env.local` to test against a different model.

## See also

- [Setup](setup.md)
- [Adding things](contributing.md)
