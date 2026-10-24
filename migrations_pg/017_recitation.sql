-- 017_recitation.sql — BEN-135 recitation loop.
--
-- Per-concept successive-relearning state rides on the user's content_progress
-- row (like initiative_slug / favorited_bool already do). recitation_state is a
-- JSONB map: { "<concept>": {"interval_days": int, "due_at": iso,
-- "misses": int, "last_recited": iso} }. A missed concept resets to +1 day;
-- a held concept advances +1 → +7 → +30.
--
-- Also folds in the pinned_at column that BEN-133 added ONLY to the dead
-- migrations/ dir — confirmed absent from the applied (prod) schema, so
-- content_repository.set_pinned() has been writing to a column that doesn't
-- exist. Additive + idempotent, so re-apply is a no-op and this restores
-- pinning without a separate migration.
ALTER TABLE content_progress
  ADD COLUMN IF NOT EXISTS pinned_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recitation_state JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS last_recited_at  TIMESTAMPTZ;
