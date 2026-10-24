# Proposal: migrate chat_outcomes to a dedicated table

**Status:** approved (operator 2026-05-25) — ship 1st in the per-attempt-tagging / news-feed / chat-outcomes triple

**Resolved decisions:**
1. `next_actions` stored as `TEXT` string (matches current MCP behavior; no tool-signature change)
2. `log_chat_outcome` MCP tool: signature unchanged (string `next_actions`)
3. UI: no edit, no delete (append-only; matches original spec)
4. Provenance: keep the `manual` value reserved even though no manual entry form exists today
5. `latest_per_initiative` returns all initiatives (no pre-limit)

**Author:** Claude (under operator delegation)

**Date:** 2026-05-25

**Predecessor:** BEN-82 (PR #250 shipped /decisions backed by `user_settings.chat_outcomes` JSON). PR #243 (BEN-81 MCP scaffold) noted the dedicated-table cutover as a follow-up.

## Problem

Chat outcomes — entries the MCP server's `log_chat_outcome` tool writes — currently live in `user_settings.chat_outcomes` (a JSON array, self-capped at 200 entries).

This works for single-tenant alpha but has real ceilings:

1. **No durable indexing.** Every read of `/decisions` deserializes the full JSON array, walks all 200 entries, filters/sorts in Python. Fine at N=200. Not fine at N=2000.
2. **No SQL queryability.** `/focus`'s "last decided per initiative" lookup does the same full-walk on every page load. The lookup table is computed correctly but the work is O(initiatives × entries).
3. **No proper schema constraints.** A future bug in `log_chat_outcome` could write malformed entries; the read path tolerates them by skipping, but the storage layer has no schema check.
4. **No clean foreign-key relationship** between outcomes and initiatives. The slug is a string today; validating it against the loaded initiatives is read-time work.
5. **The 200-entry cap silently loses history.** The MCP cap is "good enough for v1" but if the operator wants a full chat-outcome timeline at year+1, the cap will already have eaten some entries.

The BEN-82 issue spec called for a real `journal_entries` table from day one. PR #250 shipped against JSON storage to avoid the CODEOWNERS migration handoff. This proposal closes that loop.

## Proposed design

### Schema

Migration 009 (or whatever the next sequential number is — check `migrations_pg/` at write time):

```sql
CREATE TABLE IF NOT EXISTS chat_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    initiative_slug TEXT NOT NULL,
    decisions       TEXT NOT NULL DEFAULT '',
    next_actions    TEXT NOT NULL DEFAULT '',
    chat_url        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Provenance: was this written by the MCP server, the future
    -- "manual" entry form, or imported from a backfill?
    source          TEXT NOT NULL DEFAULT 'mcp'
                       CHECK (source IN ('mcp', 'manual', 'backfill'))
);

CREATE INDEX idx_chat_outcomes_user_initiative_created
    ON chat_outcomes (user_id, initiative_slug, created_at DESC);
CREATE INDEX idx_chat_outcomes_user_created
    ON chat_outcomes (user_id, created_at DESC);

-- Defensive: at least one of decisions/next_actions must be populated.
ALTER TABLE chat_outcomes
    ADD CONSTRAINT chat_outcomes_has_content
    CHECK (length(trim(decisions)) > 0 OR length(trim(next_actions)) > 0);
```

`initiative_slug` is TEXT not FK because initiatives are markdown files, not a DB table. Validation is the route's responsibility.

A few schema differences from BEN-82's original spec:

- **`next_actions: TEXT` not `JSONB`.** The original spec called for an array; the MCP scaffold treats it as a single string. Keeping the simpler shape avoids a write-time decision about how to parse "Do X then Y" — if/when checklist rendering matters, a `next_actions_items: JSONB` column can land later as a parallel field.
- **No RLS policies in this migration.** The bench's existing tables don't use RLS — security is enforced at the FastAPI route + middleware layer via `user_id` matching. Consistent with the rest of the codebase.

### Repo + service

New `app/repositories/chat_outcomes_repository.py`:

```python
class ChatOutcomesRepository:
    def insert(self, entry: ChatOutcome) -> str: ...    # returns uuid
    def get(self, entry_id: str, *, user_id: str) -> ChatOutcome | None: ...
    def list_for_user(
        self, user_id: str, *,
        initiative_slug: str | None = None,
        limit: int = 50,
    ) -> list[ChatOutcome]: ...
    def initiatives_with_counts(self, user_id: str) -> list[tuple[str, int]]: ...
    def latest_per_initiative(self, user_id: str) -> dict[str, ChatOutcome]: ...
```

The methods mirror the current `app/services/journal.py` API one-for-one, so the cutover at the call site is mechanical.

### Cutover

Three call sites move from `user_settings.chat_outcomes` to the new repo:

1. **MCP write path** (`app/mcp_server.py:_record_chat_outcome_to_settings`) — becomes `_record_chat_outcome_to_db` calling `chat_outcomes_repo.insert(...)`.
2. **/decisions read path** (`app/services/journal.py`) — keep the module name (operator-facing concept is "journal"), swap internals to call the repo.
3. **/focus "last decided" lookup** (`app/services/focus.py:_latest_decision_by_initiative`) — swap to `chat_outcomes_repo.latest_per_initiative(uid)`, which is now a single indexed query.

### Backfill

A one-shot script `scripts/backfill_chat_outcomes.py`:

1. For each user with `settings.chat_outcomes` containing entries: deserialize, validate, insert into `chat_outcomes` with `source='backfill'`.
2. Idempotent: dedup on (user_id, created_at, initiative_slug, decisions) so re-running doesn't duplicate.
3. After successful backfill, optionally clear `settings.chat_outcomes` (or leave for one release as a parachute).

Single-tenant means the backfill is < 200 entries. ~1s of work.

### Removal of the JSON storage

Two-step:

1. **PR A**: ship the table, repo, service swap. JSON storage stays as a parachute; backfill script run; reads now hit the DB. Verify in production for ≥1 day.
2. **PR B** (a week later): remove the JSON storage entirely. MCP server stops writing to settings; the `chat_outcomes` key in user_settings becomes dead.

This sequencing means rollback is one config flag away during the verify window.

## Open decisions (operator input needed)

1. **JSONB or TEXT for next_actions?**
   - **TEXT (recommend):** matches current MCP behavior. Single string. Operator can paste a checklist as markdown; rendering treats it as prose.
   - **JSONB array:** matches the BEN-82 original spec. Lets `/decisions/{id}` render real checkboxes. Worth doing if the operator wants to USE next-actions as actionable.

2. **Should the MCP `log_chat_outcome` tool accept `next_actions` as an array?**
   - If JSONB: yes; the tool signature changes.
   - If TEXT: no; current `str` signature stays.
   - Operator decision tied to (1).

3. **Edit / delete in the UI?**
   - **None (recommend, per original spec):** append-only log. Mistakes get a follow-up entry.
   - **Delete only:** matches `/writings` delete pattern. Doesn't break the spec spirit.
   - **Full edit:** rejected; turns the log into a draft surface.

4. **Provenance enum: include `manual` even though there's no manual entry form yet?**
   - **Recommend yes.** Lets future "I want to add a non-chat entry" forms ship without a schema change. Free.

5. **Should the new repo's `latest_per_initiative` return only the most recent N initiatives, or all?**
   - **All (recommend).** With an indexed `(user_id, initiative_slug, created_at DESC)`, the query is one scan; no point pre-limiting at the repo layer. /focus consumes selectively.

## Scope estimate

| File | Purpose |
|---|---|
| `migrations_pg/009_chat_outcomes.sql` | CODEOWNERS, operator-authored |
| `app/models.py` | `@dataclass class ChatOutcome` |
| `app/repositories/chat_outcomes_repository.py` | new |
| `app/main.py` | wire repo into app startup (one line) |
| `app/services/journal.py` | swap internals, keep API stable for /decisions consumers |
| `app/services/focus.py` | swap `_latest_decision_by_initiative` to repo call |
| `app/mcp_server.py` | swap `_record_chat_outcome_to_settings` to repo call; rename helper |
| `scripts/backfill_chat_outcomes.py` | one-shot |
| `tests/unit/test_chat_outcomes_repository.py` | new |
| `tests/unit/test_journal.py` | update mocks: patch repo instead of settings dict |
| `tests/unit/test_focus.py` | same: patch repo for the `_latest_decision_by_initiative` call |
| `tests/unit/test_mcp_server.py` | same: patch repo for `log_chat_outcome` |

**~10-12 files, ~500-700 lines, 2 PRs (A: ship + verify, B: remove JSON parachute).** Migration is the only CODEOWNERS-blocked piece.

## Why now / why later

**Why now:** the BEN-82 follow-up (/focus "last decided") and the MCP server both depend on JSON-walking the chat_outcomes list on every read. Each is currently O(N entries × M consumers) per request. Indexed table query is O(1) per consumer. Performance ceiling is real even if not yet hit.

**Why later:** at the operator's actual usage rate, the 200-entry cap is months away. The JSON approach works fine today. Doing this now is "we'd rather have it right" engineering, not solving a felt problem.

**Trigger to ship:** when the operator notices `/focus` getting slow OR when chat outcome count exceeds ~150 (visible ceiling pressure).

## Acceptance criteria

- Migration 009 applied; table + indexes + check constraint visible in psql
- Repo unit-tested against a mock conn (matches credentials_repo / writings_repo test pattern)
- MCP `log_chat_outcome` writes to the new table; existing tool clients unaffected
- `/decisions` and `/decisions/{id}` render exactly as before — pure refactor at the read layer
- `/focus` "last decided" same — pure refactor at the lookup layer
- Backfill script run on operator's data; entry count in `chat_outcomes` table matches `user_settings.chat_outcomes` array length
- After ≥1 day of dual-storage verification, PR B removes the JSON path

## Alternatives considered

- **Use the existing `feedback` table or `reflections` table**: rejected. Different semantics; would muddle row meaning.
- **Store as Postgres array column, not separate table**: rejected. Doesn't solve the indexing/query problem; just changes the deserialization layer.
- **Keep JSON storage but add an index on user_settings**: rejected. JSONB GIN indexes work for membership checks but not "latest per initiative" ordering. Would still walk the array client-side.
- **External event store / append log**: rejected. Single-tenant alpha doesn't need event sourcing complexity.
