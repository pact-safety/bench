-- Per-attempt initiative tagging (approved 2026-05-25; see
-- docs/proposals/per-attempt-initiative-tagging.md).
--
-- /focus today attributes ALL bench-resident activity to EVERY initiative
-- whose `bench.surface == '/'`. So an attempt on a capstone-related
-- problem shows up under "Bench Product Development" AND "MSCS Sycophancy
-- Capstone" with the same count. That heuristic was the right thing in
-- single-tenant alpha when 99% of activity was on one initiative — but
-- once the operator starts working across ≥3 initiatives in a week, the
-- dashboard becomes structurally inaccurate.
--
-- Migration 011 adds `initiative_slug TEXT` to the four primary activity
-- tables. NULL = "unassigned" (the legacy state). Write paths land in
-- PR #2 of this sequence and default the slug to settings.active_initiative;
-- read path lands in PR #3 and switches /focus from bench.surface to
-- exact-slug attribution.
--
-- No foreign key: initiatives live in markdown files under
-- content/initiatives/, not the DB. Validation happens at the write
-- layer (the route handler checks the slug against
-- initiatives_service.load_initiatives()).
--
-- Indexes are (user_id, initiative_slug, recency) so /focus's per-row
-- "give me this user's last 7d of activity on slug X" query is a
-- single index seek. PG's index-only-scan on this shape costs ~O(log N)
-- regardless of total row count.

ALTER TABLE attempts          ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE reflections       ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE content_progress  ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE writings          ADD COLUMN IF NOT EXISTS initiative_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_attempts_user_initiative_started
    ON attempts (user_id, initiative_slug, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_reflections_user_initiative_generated
    ON reflections (user_id, initiative_slug, generated_at DESC);

-- content_progress has no "started_at" — checked_at is the only time
-- column and it's nullable. Compound on (user_id, initiative_slug) is
-- enough; the per-row recency comes from the row's own checked_at.
CREATE INDEX IF NOT EXISTS idx_content_progress_user_initiative
    ON content_progress (user_id, initiative_slug);

CREATE INDEX IF NOT EXISTS idx_writings_user_initiative_updated
    ON writings (user_id, initiative_slug, updated_at DESC);
