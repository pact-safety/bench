-- MIRA: KB (RAG) + mentor session/memory + cross-feature agenda/evals tables.
-- Spec §7.4. Renumbered from the spec's 004 (004 was already taken by
-- 004_feedback_gh_link.sql); 014 is the next free number in this repo.
--
-- IF NOT EXISTS throughout: the runner (app/db.py:apply_migrations) tracks
-- applied files by filename so this normally runs once, but the guards make
-- it safe to re-apply against a DB that already has the side-effects without
-- a schema_migrations row — the exact drift class that bit prod pre-2026-05-27.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_url TEXT UNIQUE NOT NULL,
  source_kind TEXT NOT NULL,  -- 'paper'|'org_blog'|'curriculum'|'job_profile'|'doc'|'forum_post'
  title TEXT NOT NULL,
  authors TEXT[],
  published_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ DEFAULT now(),
  content_md TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  meta JSONB DEFAULT '{}'::jsonb,
  priority SMALLINT DEFAULT 5
);

CREATE TABLE IF NOT EXISTS kb_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES kb_documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  section_path TEXT,
  content TEXT NOT NULL,
  content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  embedding vector(1536),
  token_count INT,
  meta JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_idx ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS kb_chunks_tsv_idx ON kb_chunks USING GIN (content_tsv);

CREATE TABLE IF NOT EXISTS mira_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  started_at TIMESTAMPTZ DEFAULT now(),
  ended_at TIMESTAMPTZ,
  modality TEXT NOT NULL CHECK (modality IN ('chat','voice')),
  title TEXT,
  meta JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS mira_turns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES mira_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  content TEXT NOT NULL,
  tool_calls JSONB,
  citations JSONB,
  provider_used TEXT,
  latency_ms JSONB,
  interrupted BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mira_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('goal','fact','preference','context')),
  content TEXT NOT NULL,
  source_turn_id UUID REFERENCES mira_turns(id),
  superseded_by UUID REFERENCES mira_memory(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  meta JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS mira_memory_active_idx
  ON mira_memory (user_id, category)
  WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS research_agenda (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('question','experiment','writing','deadline')),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','active','parked','done','abandoned')),
  why TEXT,
  notes_md TEXT,
  linked_doc_ids UUID[],
  due_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS proposed_evals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  hypothesis TEXT NOT NULL,
  model_under_test TEXT,
  method_md TEXT,
  scoring_md TEXT,
  status TEXT DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT now(),
  meta JSONB DEFAULT '{}'::jsonb
);
