-- Bench v2.1 slice 6: per-user Linear integration.
--
-- "Operate like a lab": research-agenda items push into the USER'S
-- own Linear workspace as issues, and their state reads back onto the
-- agenda. The API key lives in Supabase Vault (same pattern as
-- user_llm_configs); this table carries only the vault secret id and
-- the chosen team. RLS enabled, no policies — deny-all for PostgREST
-- roles, app connection owner-scopes every query.

CREATE TABLE IF NOT EXISTS user_linear_configs (
    user_id          UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    vault_secret_id  UUID,
    team_id          TEXT,
    team_name        TEXT,
    -- Viewer display name from key verification; shown in settings so
    -- the user can confirm which Linear account is connected.
    account_label    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_linear_configs ENABLE ROW LEVEL SECURITY;

-- Where an agenda item landed in Linear. TEXT ids (Linear's are
-- uuids, but opaque strings age better across API versions); the
-- identifier ("BEN-12") is what the UI shows.
ALTER TABLE research_agenda ADD COLUMN IF NOT EXISTS linear_issue_id TEXT;
ALTER TABLE research_agenda ADD COLUMN IF NOT EXISTS linear_issue_identifier TEXT;
ALTER TABLE research_agenda ADD COLUMN IF NOT EXISTS linear_issue_url TEXT;
