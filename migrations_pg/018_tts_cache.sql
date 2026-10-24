-- 018_tts_cache.sql — BEN-135 audio-out cache.
--
-- Rendered TTS audio for a content item, cached so a chapter is synthesised
-- once, not on every page view (real Groq cost + latency). One row per audio
-- chunk (a book chapter is many TTS calls).
--
-- OWNER-ONLY by construction: every row carries user_id and the serve route
-- filters WHERE user_id = <requester>, so audio for content the operator owns
-- (possibly commercial books) is never reachable by another user, never
-- anonymously, and never via a public bucket. cache_key is
-- sha256(content_id:version:voice:chunk_ix) — the (content, version, voice)
-- identity from the brief — scoped per user via the composite PK.
CREATE TABLE IF NOT EXISTS tts_cache (
    user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    cache_key   TEXT NOT NULL,
    content_id  BIGINT NOT NULL,
    chunk_ix    INTEGER NOT NULL DEFAULT 0,
    voice       TEXT NOT NULL,
    mime        TEXT NOT NULL,
    audio       BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_tts_cache_lookup
    ON tts_cache (user_id, content_id, chunk_ix);
