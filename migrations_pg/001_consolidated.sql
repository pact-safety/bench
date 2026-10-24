-- Consolidated Postgres schema for Li's Bench.
--
-- COLUMN-FOR-COLUMN MIRROR of the SQLite schema under `migrations/`,
-- translating SQLite types to Postgres-native ones. The mirror is
-- intentional: it lets the Phase 2 data-export script use the same
-- column names on both sides (no rename mapping needed), and keeps
-- the app's existing data layer compatible until Phase 4's refactor.
--
-- Type translation rules:
--   INTEGER (boolean *_bool)            → BOOLEAN
--   INTEGER PRIMARY KEY [AUTOINCREMENT] → BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
--   INTEGER (FK / numeric)              → BIGINT
--   TEXT (JSON-as-text *_json)          → JSONB
--   TEXT (ISO timestamp)                → TIMESTAMPTZ
--   TEXT (ISO date e.g. authored_date)  → DATE
--   REAL                                → REAL
--   datetime('now') default             → NOW()
--   user_id INTEGER FK to users(id)     → UUID FK to public.users(id)
--                                          (the one principled break;
--                                           supports Supabase Auth)

-- ============================================================
-- Users (1:1 with auth.users; trigger auto-creates on signup)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.users (
    id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email           CITEXT,
    is_test         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settings_json   JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    INSERT INTO public.users (id, email)
    VALUES (NEW.id, NEW.email)
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();


-- ============================================================
-- Problems (authored markdown, loaded at startup)
-- ============================================================

CREATE TABLE IF NOT EXISTS problems (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug                        TEXT NOT NULL UNIQUE,
    title                       TEXT NOT NULL,
    difficulty                  TEXT NOT NULL CHECK (difficulty IN ('easy','medium','hard')),
    time_bucket                 INTEGER NOT NULL CHECK (time_bucket IN (5,10,30,60)),
    problem_type                TEXT NOT NULL,
    is_warmup                   BOOLEAN NOT NULL DEFAULT FALSE,
    structural_tags_json        JSONB NOT NULL DEFAULT '[]'::jsonb,
    domain_tags_json            JSONB NOT NULL DEFAULT '[]'::jsonb,
    competency_tags_json        JSONB NOT NULL DEFAULT '[]'::jsonb,
    jd_signal_tags_json         JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_md                  TEXT NOT NULL,
    starter_code_python         TEXT,
    starter_code_rust           TEXT,
    reference_solution_python   TEXT,
    reference_solution_rust     TEXT,
    key_insight                 TEXT,
    pitfalls_md                 TEXT,
    test_code_python            TEXT,
    rust_crate_dir              TEXT,
    source_provenance           TEXT,
    original_bool               BOOLEAN NOT NULL DEFAULT TRUE,
    authored_by                 TEXT,
    authored_date               TEXT,
    version_int                 INTEGER NOT NULL DEFAULT 1,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    em_mode                     TEXT NOT NULL DEFAULT 'full',
    em_prompts_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    references_json             JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_problems_is_warmup ON problems(is_warmup);
CREATE INDEX IF NOT EXISTS idx_problems_type ON problems(problem_type);


-- ============================================================
-- Attempts
-- ============================================================

CREATE TABLE IF NOT EXISTS attempts (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    problem_id                      BIGINT NOT NULL REFERENCES problems(id),
    problem_version                 INTEGER NOT NULL,
    started_at                      TIMESTAMPTZ NOT NULL,
    ended_at                        TIMESTAMPTZ,
    language_used                   TEXT NOT NULL CHECK (language_used IN ('python','rust')),
    final_code                      TEXT,
    solved_without_lookup_bool      BOOLEAN,
    confidence_1_to_5               INTEGER CHECK (confidence_1_to_5 BETWEEN 1 AND 5),
    time_to_first_edit_seconds      INTEGER,
    edit_count                      INTEGER NOT NULL DEFAULT 0,
    looked_at_solution_bool         BOOLEAN NOT NULL DEFAULT FALSE,
    looked_at_pitfalls_bool         BOOLEAN NOT NULL DEFAULT FALSE,
    test_passed_bool                BOOLEAN,
    test_output                     TEXT,
    notes_md                        TEXT,
    explore_notes                   TEXT,
    brainstorm_notes                TEXT,
    plan_notes                      TEXT,
    verify_notes                    TEXT,
    time_per_phase_json             JSONB,
    interview_mode_bool             BOOLEAN NOT NULL DEFAULT FALSE,
    hints_used_json                 JSONB
);

CREATE INDEX IF NOT EXISTS idx_attempts_user_problem ON attempts(user_id, problem_id);
CREATE INDEX IF NOT EXISTS idx_attempts_started ON attempts(started_at);
CREATE INDEX IF NOT EXISTS idx_attempts_user_started ON attempts(user_id, started_at DESC);


-- ============================================================
-- Review state (scheduler memory per (user, problem))
-- ============================================================

CREATE TABLE IF NOT EXISTS review_state (
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    problem_id          BIGINT NOT NULL REFERENCES problems(id),
    last_attempt_id     BIGINT REFERENCES attempts(id),
    last_due_score      REAL NOT NULL DEFAULT 0,
    next_due_at         TIMESTAMPTZ,
    lapses              INTEGER NOT NULL DEFAULT 0,
    ease_factor         REAL,
    PRIMARY KEY (user_id, problem_id)
);


-- ============================================================
-- Sessions (a daily working slate)
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                 UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at                TIMESTAMPTZ,
    strategy_name           TEXT NOT NULL,
    time_limit_seconds      INTEGER,
    problems_json           JSONB NOT NULL
);


-- ============================================================
-- Problem revisions
-- ============================================================

CREATE TABLE IF NOT EXISTS problem_revisions (
    problem_id      BIGINT NOT NULL REFERENCES problems(id),
    version_int     INTEGER NOT NULL,
    diff_md         TEXT,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (problem_id, version_int)
);


-- ============================================================
-- Adaptive assessment
-- ============================================================

CREATE TABLE IF NOT EXISTS assessment_runs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    final_scores_json   JSONB
);

CREATE TABLE IF NOT EXISTS assessment_responses (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              BIGINT NOT NULL REFERENCES assessment_runs(id) ON DELETE CASCADE,
    question_id         TEXT NOT NULL,
    answer_index        INTEGER NOT NULL,
    axis_scores_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    answered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assessment_runs_user ON assessment_runs(user_id);


-- ============================================================
-- Content items + progress
-- ============================================================

CREATE TABLE IF NOT EXISTS content_items (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug                TEXT NOT NULL UNIQUE,
    kind                TEXT NOT NULL CHECK (kind IN ('reading','video','podcast','exercise')),
    title               TEXT NOT NULL,
    source              TEXT,
    url                 TEXT,
    duration_min        INTEGER,
    axes_json           JSONB NOT NULL DEFAULT '[]'::jsonb,
    prerequisites_json  JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_md          TEXT,
    authored_by         TEXT,
    authored_date       TEXT,
    version_int         INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_kind         TEXT NOT NULL DEFAULT 'authored' CHECK (source_kind IN ('authored','user')),
    created_by_user_id  UUID REFERENCES public.users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_content_items_kind ON content_items(kind);
CREATE INDEX IF NOT EXISTS idx_content_items_source_kind ON content_items(source_kind);

CREATE TABLE IF NOT EXISTS content_progress (
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    content_id          BIGINT NOT NULL REFERENCES content_items(id),
    status              TEXT NOT NULL DEFAULT 'unread' CHECK (status IN ('unread','in_progress','completed')),
    checked_at          TIMESTAMPTZ,
    notes_md            TEXT,
    favorited_bool      BOOLEAN NOT NULL DEFAULT FALSE,
    rating_1_to_5       INTEGER CHECK (rating_1_to_5 BETWEEN 1 AND 5),
    PRIMARY KEY (user_id, content_id)
);


-- ============================================================
-- Credentials (three-table split mirrors SQLite)
-- ============================================================

CREATE TABLE IF NOT EXISTS credential_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status_text     TEXT
);

CREATE INDEX IF NOT EXISTS idx_credential_runs_user ON credential_runs(user_id);

CREATE TABLE IF NOT EXISTS credential_files (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES credential_runs(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    byte_size       INTEGER NOT NULL,
    sha256          TEXT,
    extracted_text  TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credential_files_run ON credential_files(run_id);

CREATE TABLE IF NOT EXISTS credential_assessments (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                      BIGINT NOT NULL REFERENCES credential_runs(id) ON DELETE CASCADE,
    inferred_axis_scores_json   JSONB NOT NULL,
    summary_md                  TEXT,
    rationale_json              JSONB,
    method                      TEXT NOT NULL,
    model_used                  TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credential_assessments_run ON credential_assessments(run_id);


-- ============================================================
-- Attempt reviews
-- ============================================================

CREATE TABLE IF NOT EXISTS attempt_reviews (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt_id          BIGINT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    method              TEXT NOT NULL,
    model_used          TEXT,
    summary_md          TEXT,
    per_phase_json      JSONB,
    overall_score       REAL,
    error_text          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rubric_signals_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_attempt_reviews_attempt ON attempt_reviews(attempt_id);


-- ============================================================
-- Job descriptions
-- ============================================================

CREATE TABLE IF NOT EXISTS jds (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    org             TEXT,
    source_text     TEXT NOT NULL,
    parsed_json     JSONB,
    parsed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jds_user ON jds(user_id);


-- ============================================================
-- Feedback inbox
-- ============================================================

CREATE TABLE IF NOT EXISTS feedback (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    url                 TEXT NOT NULL,
    page_title          TEXT,
    theme               TEXT,
    viewport_width      INTEGER,
    body                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open','backlog','archived','dismissed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,
    processing_notes    TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status, created_at);


-- ============================================================
-- Writings
-- ============================================================

CREATE TABLE IF NOT EXISTS writings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title               TEXT NOT NULL DEFAULT '',
    body_md             TEXT NOT NULL DEFAULT '',
    source_refs_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
    status              TEXT NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft','published','archived')),
    word_count          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_writings_user_status ON writings(user_id, status);


-- ============================================================
-- Reflections (Hamming mode)
-- ============================================================

CREATE TABLE IF NOT EXISTS reflections (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                 UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    period_start            TIMESTAMPTZ NOT NULL,
    period_end              TIMESTAMPTZ NOT NULL,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prompts_json            JSONB NOT NULL,
    response_md             TEXT,
    response_updated_at     TIMESTAMPTZ,
    summary_md              TEXT,
    method                  TEXT NOT NULL DEFAULT 'fallback',
    model_used              TEXT
);

CREATE INDEX IF NOT EXISTS idx_reflections_user_date ON reflections(user_id, generated_at);


-- ============================================================
-- Reserved tables (notes / sources placeholder)
-- ============================================================

CREATE TABLE IF NOT EXISTS sources (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url                 TEXT,
    title               TEXT,
    source_type         TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_md          TEXT,
    authors_json        JSONB,
    published_date      TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    source_id                   BIGINT REFERENCES sources(id),
    problem_id                  BIGINT REFERENCES problems(id),
    content_md                  TEXT NOT NULL,
    tags_json                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    post_readiness_1_to_5       INTEGER CHECK (post_readiness_1_to_5 BETWEEN 1 AND 5),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
