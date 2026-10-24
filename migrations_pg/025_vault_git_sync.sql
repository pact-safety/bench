-- Bench v2.1 slice 5: git-repo vault sync.
--
-- Most Obsidian vaults are already git repos. Instead of re-exporting
-- a zip after every writing session, the user connects the repo once;
-- the bench pulls the GitHub tarball on demand and nightly (cron
-- behind single_flight) and feeds the same ingest pipeline as the zip
-- path. The read token lives in Supabase Vault (same custody as BYO
-- LLM keys and Linear tokens); this table carries only the secret id
-- and the sync target. RLS enabled, no policies — deny-all for
-- PostgREST roles.

CREATE TABLE IF NOT EXISTS user_vault_syncs (
    user_id          UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    -- "owner/name" form, normalized by the repository layer.
    repo             TEXT NOT NULL,
    -- Empty string = the repo's default branch (GitHub resolves it).
    branch           TEXT NOT NULL DEFAULT '',
    -- Optional folder inside the repo when the vault isn't at root.
    subdir           TEXT NOT NULL DEFAULT '',
    -- NULL for public repos — a token is only needed for private ones.
    vault_secret_id  UUID,
    last_synced_at   TIMESTAMPTZ,
    -- Short human-readable outcome ("ingested 12, unchanged 180"),
    -- shown on /mira/kb. Never contains token material.
    last_result      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_vault_syncs ENABLE ROW LEVEL SECURITY;
