-- Add pregenerated flag to reflections (GH #229 — Saturday-morning
-- pre-generation of the weekly Reflect set).
--
-- Pre-migration, every reflection row was created on-demand when the
-- operator clicked "Generate this week's reflection," which paid the
-- 3-5s LLM round-trip every Saturday (down from 15-25s after PR #223's
-- Haiku + prompt-cache + max_tokens cuts, but still a visible wait).
--
-- PR #229 ships a 7am Saturday cron that pre-generates the week's
-- prompts in the background. The Saturday home view surfaces the
-- pregenerated reflection if one exists; clicking "Open" is then
-- instantaneous instead of a 3-5s wait. The `pregenerated` flag
-- distinguishes cron-generated rows from operator-triggered rows so
-- the UI can label them and so the cron can skip users whose row for
-- the current period already exists.
--
-- Backward-compatible: existing reflections default to pregenerated =
-- FALSE. The flag is non-null with a default; no data migration needed.

ALTER TABLE reflections
    ADD COLUMN IF NOT EXISTS pregenerated BOOLEAN NOT NULL DEFAULT FALSE;
