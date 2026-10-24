-- 016_evals_conditions.sql — 6d: give proposed_evals the design's condition
-- table + falsifier so /mira/evals renders the A/B/C framing grid, not just a
-- hypothesis line.
--
-- Additive and idempotent (ADD COLUMN IF NOT EXISTS): re-applying is a no-op,
-- so a re-run can't brick boot the way a non-idempotent DDL could. `conditions`
-- holds the design's framing table as [{"label": "...", "framing": "..."}];
-- `falsifier` is the explicit "what would kill this hypothesis" line. The
-- presentational bits (short title, Inspect path) ride the existing `meta`
-- jsonb, so they need no columns of their own.
ALTER TABLE proposed_evals
  ADD COLUMN IF NOT EXISTS falsifier  TEXT,
  ADD COLUMN IF NOT EXISTS conditions JSONB NOT NULL DEFAULT '[]'::jsonb;
