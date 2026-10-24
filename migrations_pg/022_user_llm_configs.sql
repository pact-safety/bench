-- BYO LLM provider (Bench v2 launch week): alpha users can route the
-- AI features (hints, review, reflect, JD parse, ...) through their
-- own key instead of the operator's, either straight to Anthropic or
-- via an OmniRoute-style Anthropic-compatible gateway.
--
-- KEY MATERIAL IS NEVER STORED IN THIS TABLE. The key lives in
-- Supabase Vault (encrypted at rest, excluded from logical backups'
-- plaintext); this row only carries the vault secret id plus display
-- metadata. `key_hint` is the last 4 characters, for the settings UI.
--
-- RLS enabled with NO policies — deny-all for the PostgREST JWT
-- roles, same shape as allowlist_entries; only the bench's own
-- connection reads it, and only at LLM-call time (never cached).

CREATE TABLE IF NOT EXISTS user_llm_configs (
    user_id          UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    -- 'bench' (operator key + daily cap) | 'anthropic' | 'omniroute'
    provider         TEXT NOT NULL DEFAULT 'bench',
    vault_secret_id  UUID,
    -- Anthropic-compatible gateway origin; required for 'omniroute',
    -- NULL for 'anthropic' (SDK default) and 'bench'.
    base_url         TEXT,
    key_hint         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE user_llm_configs ENABLE ROW LEVEL SECURITY;
