-- Add user_tests_code to attempts (GH #111 — user-written tests as
-- part of the practice workflow). Pre-migration, attempts persisted
-- the submitted solution + grading metadata; the user couldn't write
-- tests of their own. PR #117 added a "Your tests" tab to the problem
-- page and wired it through the runner so each submission's outcome
-- splits into hidden-passed vs user-passed flags. This migration adds
-- the storage column.
--
-- After this migration:
--   * `attempts.user_tests_code` persists whatever the user typed in
--     the "Your tests" textarea at submit time.
--   * The repo's _row_to_attempt path now actually reads it instead of
--     hitting the defensive `getattr(row, 'user_tests_code', None)`
--     fallback that PR #117 included for pre-migration safety.
--   * Future attempts surface the user's prior tests on attempt
--     re-entry so they can iterate on their test design.
--
-- The PR #117 repo code already handles the pre-migration state
-- gracefully (the INSERT has a retry-without-column path; the read
-- path uses getattr). So this migration is purely additive — running
-- it AFTER the deploy lands is safe; running it BEFORE the deploy is
-- safe; both orderings work.

ALTER TABLE attempts
    ADD COLUMN IF NOT EXISTS user_tests_code TEXT;
