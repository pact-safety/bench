-- Interview-mode v1 — per-phase budgets + cutoff tracking.
--
-- v1 of the interview-mode rebuild (docs/proposals/interview-mode-v2.md).
-- This migration adds two columns to the attempts table so the bench
-- can:
--   1. Snapshot which phase budgets were in effect when the operator
--      took the attempt. Storing the budgets per-row (vs. re-deriving
--      from the problem TOML) makes the historical record stable when
--      the problem's budgets later change.
--   2. Mark sessions that were force-ended by the hard cutoff so the
--      calibration data can distinguish "operator wrapped up normally"
--      from "ran out of time."
--
-- v3+ will use `interview_mode_preference` (silent / nudges /
-- live_coach) to track which coach style was active. Adding the column
-- now means v1's read path doesn't need a schema-bump when v3 lands.

ALTER TABLE attempts
    ADD COLUMN IF NOT EXISTS phase_budgets_json JSONB,
    ADD COLUMN IF NOT EXISTS cutoff_bool BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS interview_mode_preference TEXT;
