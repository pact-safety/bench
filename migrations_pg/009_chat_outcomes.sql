-- Add chat_outcomes table (GH #211 / BEN-81 follow-up; see
-- docs/proposals/chat-outcomes-table.md).
--
-- Pre-migration, chat outcomes (the structured "what I decided in this
-- chat" log written by the MCP server's log_chat_outcome tool) lived
-- in user_settings.chat_outcomes as a JSON array self-capped at 200
-- entries. That worked for single-tenant alpha but:
--
-- 1. Every read of /decisions and every /focus "last decided" lookup
--    deserialized the full JSON array and walked all entries in Python.
-- 2. No durable indexing → no SQL queryability for per-initiative
--    queries.
-- 3. No schema constraints → a future write-path bug could persist
--    malformed entries; defensive parsing tolerates but doesn't prevent.
-- 4. The 200-entry cap silently lost history.
--
-- Migration 009 moves chat outcomes to a dedicated table with proper
-- indexes + a content check constraint. The cutover ships in two PRs:
-- PR A (this migration + repo + service swap) keeps JSON writes as a
-- parachute; PR B (≥1 day later) removes the JSON path. Both surfaces
-- (/decisions and /focus "last decided") refactor at the read layer
-- only; no UX changes.
--
-- next_actions is TEXT not JSONB per operator decision (2026-05-25) —
-- matches current MCP behavior, no log_chat_outcome tool-signature
-- change required.

CREATE TABLE IF NOT EXISTS chat_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    initiative_slug TEXT NOT NULL,
    decisions       TEXT NOT NULL DEFAULT '',
    next_actions    TEXT NOT NULL DEFAULT '',
    chat_url        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Provenance: where did this entry come from? Reserved for future
    -- manual-entry forms even though only 'mcp' is written today.
    source          TEXT NOT NULL DEFAULT 'mcp'
                       CHECK (source IN ('mcp', 'manual', 'backfill'))
);

-- Per-initiative queries on /focus "last decided" lookup hit this index.
CREATE INDEX IF NOT EXISTS idx_chat_outcomes_user_initiative_created
    ON chat_outcomes (user_id, initiative_slug, created_at DESC);

-- /decisions chronological feed across all initiatives.
CREATE INDEX IF NOT EXISTS idx_chat_outcomes_user_created
    ON chat_outcomes (user_id, created_at DESC);

-- Defensive: at least one of decisions or next_actions must be
-- populated. The MCP tool enforces this at the write boundary; the
-- check constraint catches any future bug where a write path
-- regresses on that invariant.
ALTER TABLE chat_outcomes
    DROP CONSTRAINT IF EXISTS chat_outcomes_has_content;
ALTER TABLE chat_outcomes
    ADD CONSTRAINT chat_outcomes_has_content
    CHECK (length(trim(decisions)) > 0 OR length(trim(next_actions)) > 0);
