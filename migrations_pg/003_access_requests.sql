-- Access requests: people who hit /request-access asking the operator
-- to add them to the allowlist. Single source of truth for "who's
-- asked"; operator approves by adding their email to
-- LIS_ALLOWED_EMAILS and flipping `status` here for audit.
--
-- No FK to auth.users because most submitters don't have an account
-- (or have a *blocked* one). `email` is captured verbatim and used
-- as the soft dedupe key for "have we already seen this person?"

CREATE TABLE IF NOT EXISTS access_requests (
    id              BIGSERIAL PRIMARY KEY,
    -- Submitter-provided. Email is required; everything else is best-effort.
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    github_handle   TEXT,
    -- Free-text: "what brings you here". Capped client-side to keep
    -- abuse small; bigger blob protections live at the request layer.
    note            TEXT,
    -- Capture for spam triage. Not displayed publicly.
    ip              TEXT,
    user_agent      TEXT,
    -- Workflow: 'pending' on insert, 'granted' when the operator
    -- promotes them, 'declined' otherwise. No enum — adding states
    -- later is cheaper as a varchar.
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    processed_note  TEXT
);

-- The operator's typical query is "show me the new ones, latest first".
CREATE INDEX IF NOT EXISTS idx_access_requests_status_created
    ON access_requests (status, created_at DESC);

-- Soft duplicate guard: same email within ~30s = spam burst. We don't
-- enforce uniqueness (people legitimately re-submit after fixing typos),
-- but the route checks for an existing pending row before inserting.
CREATE INDEX IF NOT EXISTS idx_access_requests_email
    ON access_requests (lower(email));
