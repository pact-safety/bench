-- Signal: the evidence half of readiness.
--
-- readiness.py already answers "can I do the work" (JD-weighted axis
-- gaps in hours). This answers the other half a selection process
-- actually reads: "can anyone TELL that I can do the work" — and what
-- happened when I applied.
--
-- Motivating report (cohort thread, 2026-08-21): an applicant with 14
-- rejections, several at final stage, wrote "most of these send
-- recommendations on how to improve; lately they're recommending
-- things I've already done." Another: applicants get one bit of
-- information, accept or reject, months later. Neither the evidence
-- they've built nor the outcomes they've collected is anywhere a
-- person can look at it.
--
-- `opportunities` and `opportunity_events` deliberately match the
-- column spec in BEN-148 so that issue's agent-written brief, job
-- scan and SECURITY DEFINER writer land as pure additions rather
-- than a schema fight. What BEN-148 additionally specifies and this
-- migration does NOT create: brief_runs, the agent write path.
--
-- Criteria themselves are authored FILES (content/criteria/*.md),
-- not rows — same call as tracks. Only user data lives here.

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    -- Slug of a content/criteria/*.md file. Not an FK: criteria are
    -- files, and a retired criterion must not delete someone's work.
    criterion    TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    -- What this artifact demonstrates, in the user's own words. The
    -- act of writing it is half the value: an artifact you cannot
    -- describe in one sentence is usually the weak version.
    claim_md     TEXT,
    -- Self-assessed against the criterion's "strong looks like" list.
    strength     TEXT NOT NULL DEFAULT 'unrated'
                 CHECK (strength IN ('unrated', 'weak', 'partial', 'strong')),
    occurred_on  DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_artifacts_user
    ON evidence_artifacts (user_id, criterion);

ALTER TABLE evidence_artifacts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS evidence_artifacts_owner_only ON evidence_artifacts;
CREATE POLICY evidence_artifacts_owner_only ON evidence_artifacts
    FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());


-- Column list per BEN-148. `location` is NOT NULL by the operator's
-- standing rule that every role and fellowship listing carries one.
CREATE TABLE IF NOT EXISTS opportunities (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL
                 CHECK (kind IN ('fellowship','grant','job','program','workshop')),
    org          TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    location     TEXT NOT NULL DEFAULT 'unspecified',
    deadline     DATE,
    stage        TEXT NOT NULL DEFAULT 'watching'
                 CHECK (stage IN ('watching','selected','drafting','submitted',
                                  'interview','decision','closed')),
    outcome      TEXT,
    -- Feedback received, verbatim. The thread's sharpest complaint is
    -- that this is the one artifact of a rejection worth keeping and
    -- nobody keeps it.
    feedback_md  TEXT,
    source       TEXT NOT NULL DEFAULT 'manual'
                 CHECK (source IN ('scan','manual','agent')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opportunities_user_stage
    ON opportunities (user_id, stage);

ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS opportunities_owner_only ON opportunities;
CREATE POLICY opportunities_owner_only ON opportunities
    FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());


-- State lives in events, not description rewrites (BEN-148 rule 8).
CREATE TABLE IF NOT EXISTS opportunity_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind            TEXT NOT NULL,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_opportunity_events_opp
    ON opportunity_events (opportunity_id, at DESC);

ALTER TABLE opportunity_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS opportunity_events_owner_only ON opportunity_events;
CREATE POLICY opportunity_events_owner_only ON opportunity_events
    FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
