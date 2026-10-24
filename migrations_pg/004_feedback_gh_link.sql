-- Feedback ↔ GitHub Issues link (LIS-301).
--
-- The `feedback` table already has a local triage workflow
-- (status = open / backlog / archived / dismissed). This migration
-- adds *promotion* state: when the operator decides an item is real
-- work, the row gets stamped with the GitHub Issue URL that tracks it.
-- The local status stays meaningful (you might promote an item AND
-- archive it because it's now tracked on GitHub, or keep it open while
-- the issue is being actively worked) — the two are orthogonal.
--
-- Promotion happens two ways:
--   1. Auto: operator (LIS_ADMIN_USER_IDS) submits feedback → create
--      a GH issue immediately. `promoted_by` = operator's user_id,
--      `promoted_at` = NOW().
--   2. Manual: any allowlisted user submitted feedback → operator
--      clicks "Promote →" in the inbox. Same stamping.
--
-- `promoted_by` deliberately has NO foreign key. Supabase's auth.users
-- lives in a different schema and we don't want a delete-cascade
-- relationship across schemas. Treat it as a soft reference; the
-- repository never joins on it.

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS gh_issue_url    TEXT,
    ADD COLUMN IF NOT EXISTS gh_issue_number INTEGER,
    ADD COLUMN IF NOT EXISTS promoted_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS promoted_by     UUID;

-- The admin inbox's most common query is "show me unpromoted open
-- items, newest first" — a partial index keeps that fast even as the
-- table grows.
CREATE INDEX IF NOT EXISTS idx_feedback_unpromoted_open
    ON feedback (created_at DESC)
    WHERE gh_issue_url IS NULL AND status = 'open';

-- "Find this feedback's GH issue" — used when the operator clicks
-- through to GitHub from the inbox.
CREATE INDEX IF NOT EXISTS idx_feedback_gh_issue_number
    ON feedback (gh_issue_number)
    WHERE gh_issue_number IS NOT NULL;
