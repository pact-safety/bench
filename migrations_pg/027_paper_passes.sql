-- 027_paper_passes.sql — Ng's multi-pass paper reading.
--
-- Rides on the existing content_progress row, exactly like
-- recitation_state (017) and pinned_at: per-(user, content) reading
-- state as JSONB rather than a fifth progress table.
--
--   {"pass": 2,
--    "passes": {"1": "<iso>", "2": "<iso>"},
--    "answers": {"content.aim": "...", "methods.evidence": "..."},
--    "verdict": "relevant" | "park" | "drop",
--    "verdict_at": "<iso>"}
--
-- Deliberately NOT a score. The recitation grader (BEN-135) states the
-- constraint as product law: no score, no percentage, no "N of M" —
-- a discouraging grader is worse than none. Passes are a record of
-- what you read, not a mark out of four.
--
-- Additive + idempotent; re-apply is a no-op.

ALTER TABLE content_progress
  ADD COLUMN IF NOT EXISTS paper_state JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN content_progress.paper_state IS
  'Ng multi-pass reading state: furthest pass, per-pass timestamps, '
  'guiding-question answers, and the relevance verdict. Never a score.';
