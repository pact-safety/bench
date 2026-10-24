-- Enable Row-Level Security on all bench tables + add owner-only
-- policies for user-scoped data.
--
-- Why: Supabase's database advisor flags every table without RLS
-- enabled. The bench's runtime accesses Postgres via psycopg using the
-- `postgres` role (which has BYPASSRLS), so RLS does NOT change what
-- the running app sees. But RLS is defense-in-depth against:
--   1. Direct PostgREST API access using anon / authenticated JWT roles
--   2. Future code that uses Supabase JS client instead of psycopg
--   3. Compromised anon key + curious script kid
--
-- Posture: for user-scoped tables, a single policy that resolves
-- `user_id = auth.uid()` for ALL operations. JWT roles see only their
-- own rows. The bench's psycopg connection bypasses these entirely.
--
-- Global tables (problems, content_items, problem_revisions, sources):
-- RLS enabled with NO policies. JWT roles see nothing (default-deny).
-- The bench's curation writes go through the postgres role's
-- BYPASSRLS, so the running app is unaffected. Future client-side
-- reads (if any) would need an explicit SELECT policy added.
--
-- access_requests: special case. Anyone can submit (sign-up form,
-- pre-auth). Reads are admin-only. Policy: anon INSERT allowed; no
-- SELECT/UPDATE/DELETE policy → JWT roles can't read submissions.
-- Operator reads via service-role bypass.
--
-- Idempotent: ENABLE ROW LEVEL SECURITY is safe to run multiple times
-- (it's a no-op when already enabled). CREATE POLICY uses
-- `DROP POLICY IF EXISTS` first so re-running the migration replaces
-- any prior version without error.


-- ============================================================
-- Helper: re-create each policy idempotently.
-- ============================================================
--
-- We can't use CREATE POLICY IF NOT EXISTS (Postgres doesn't have it),
-- so each block does DROP POLICY IF EXISTS first.


-- ============================================================
-- public.users — id IS the user's auth.uid() (PK = auth.users(id))
-- ============================================================

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_owner_only ON public.users;
CREATE POLICY users_owner_only ON public.users
    FOR ALL
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());


-- ============================================================
-- User-scoped tables (single user_id column)
-- ============================================================

-- Defines a per-table owner-only policy. PL/pgSQL DO block so we can
-- enable RLS + create policy in a loop and keep the migration short.

DO $$
DECLARE
    t TEXT;
    tables TEXT[] := ARRAY[
        'attempts',
        'assessment_runs',
        'review_state',
        'sessions',
        'content_progress',
        'credential_runs',
        'jds',
        'feedback',
        'writings',
        'reflections',
        'notes',
        'chat_outcomes'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I_owner_only ON %I', t, t);
        EXECUTE format(
            'CREATE POLICY %I_owner_only ON %I
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())',
            t, t
        );
    END LOOP;
END $$;


-- ============================================================
-- Indirect-user tables — scoped via a parent row's user_id
-- ============================================================
-- Subquery against the parent table. Slightly slower than a direct
-- user_id column but the JWT path isn't hot — production uses the
-- BYPASSRLS postgres role.

-- assessment_responses → assessment_runs.user_id
ALTER TABLE assessment_responses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS assessment_responses_owner_only ON assessment_responses;
CREATE POLICY assessment_responses_owner_only ON assessment_responses
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM assessment_runs ar
             WHERE ar.id = assessment_responses.run_id
               AND ar.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM assessment_runs ar
             WHERE ar.id = assessment_responses.run_id
               AND ar.user_id = auth.uid()
        )
    );

-- attempt_reviews → attempts.user_id
ALTER TABLE attempt_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS attempt_reviews_owner_only ON attempt_reviews;
CREATE POLICY attempt_reviews_owner_only ON attempt_reviews
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM attempts a
             WHERE a.id = attempt_reviews.attempt_id
               AND a.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM attempts a
             WHERE a.id = attempt_reviews.attempt_id
               AND a.user_id = auth.uid()
        )
    );

-- credential_files → credential_runs.user_id
ALTER TABLE credential_files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS credential_files_owner_only ON credential_files;
CREATE POLICY credential_files_owner_only ON credential_files
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM credential_runs cr
             WHERE cr.id = credential_files.run_id
               AND cr.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM credential_runs cr
             WHERE cr.id = credential_files.run_id
               AND cr.user_id = auth.uid()
        )
    );

-- credential_assessments → credential_runs.user_id
ALTER TABLE credential_assessments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS credential_assessments_owner_only ON credential_assessments;
CREATE POLICY credential_assessments_owner_only ON credential_assessments
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM credential_runs cr
             WHERE cr.id = credential_assessments.run_id
               AND cr.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM credential_runs cr
             WHERE cr.id = credential_assessments.run_id
               AND cr.user_id = auth.uid()
        )
    );


-- ============================================================
-- Global (curated by operator, read-may-be-public-eventually)
-- ============================================================
-- RLS enabled with NO policy = JWT roles see nothing. Bench's
-- BYPASSRLS connection still has full access. If/when a future
-- client-side read is wanted (e.g., the /public/dashboard or the
-- public-corpus mirror), add a per-table SELECT policy here.

ALTER TABLE problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE problem_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- access_requests — pre-auth signups
-- ============================================================
-- Anyone (anon JWT role) can INSERT a request; no SELECT for JWT
-- roles means only the bench (via BYPASSRLS) reads them. This is the
-- right shape for a signup form behind a public landing page.

ALTER TABLE access_requests ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS access_requests_anon_insert ON access_requests;
CREATE POLICY access_requests_anon_insert ON access_requests
    FOR INSERT
    TO anon, authenticated
    WITH CHECK (true);

-- No SELECT/UPDATE/DELETE policies → JWT roles can't read submissions.
-- Service role + the bench's postgres connection bypass and can read.
