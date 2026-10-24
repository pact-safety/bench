-- Bench v2.1 KB: per-user vaults ride the existing MIRA KB tables.
--
-- kb_documents was designed for the shared safety-eval canon (spec §8);
-- v2.1 adds user-owned documents (Obsidian vault notes) to the SAME
-- table rather than a parallel one, so retrieval (rag.hybrid_search)
-- fuses canon + vault in one query. `user_id IS NULL` = shared canon,
-- readable in any user's retrieval; non-NULL = that user's private
-- vault, retrieved only for them (enforced in the repository query —
-- RLS on these tables is deny-all for PostgREST roles, and the app
-- connection scopes by user_id).
--
-- No FK to public.users: account deletion sweeps kb_documents via the
-- generic table loop (added to _DELETE_ACCOUNT_TABLES_ORDER), and
-- kb_chunks cascades from kb_documents. Vault notes carry synthetic
-- source_urls (vault://<user_id>/<note path>) which satisfy the
-- existing global UNIQUE constraint.

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS user_id UUID;

CREATE INDEX IF NOT EXISTS idx_kb_documents_user
    ON kb_documents (user_id)
    WHERE user_id IS NOT NULL;

-- Sparse-retrieval support: the tsvector column is generated; this is
-- the GIN index the ts_rank query needs to stay sub-linear as vaults
-- grow. (The canon seeding never shipped, so this index is new work,
-- not drift.)
CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv
    ON kb_chunks USING GIN (content_tsv);
