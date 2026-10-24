-- Add calibration_json to reflections (GH #193 — predicted-vs-actual
-- capture for the Calibration prompt that #191 introduced into the
-- Hamming reflect rotation).
--
-- Pre-migration, the Calibration prompt's predicted/actual/gap inputs
-- were captured as free-text in the reflection body. PR #204 adds a
-- structured Path A capture (Moore & Healy 2008 prediction-vs-outcome)
-- with three optional inputs that persist as JSONB so the /aim
-- scatter plot can render predicted-vs-actual over time without
-- LLM parsing the prose.
--
-- Schema:
--   { "predicted_score": 0-100, "actual_score": 0-100,
--     "prompt_type": "calibration", "gap_text": "..." }
--
-- Backward-compatible: existing reflections have NULL calibration_json;
-- the /aim section hides itself when no reflection has the field set.

ALTER TABLE reflections
    ADD COLUMN IF NOT EXISTS calibration_json JSONB;
