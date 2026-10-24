-- E2E bootstrap for a PLAIN Postgres (FRONTEND-1c).
--
-- The app's migrations assume a Supabase database: `citext` is
-- preinstalled and the `auth.users` table exists (public.users FKs it,
-- and migration 001 installs a trigger on it). This file stubs exactly
-- that surface so `migrations_pg/` applies cleanly on a vanilla
-- pgvector/pgvector image — used by the Playwright E2E tier and equally
-- valid for plain-Postgres self-hosting.
--
-- Run BEFORE the app's first boot:  psql "$DATABASE_URL" -f scripts/e2e_bootstrap.sql

CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS auth;

-- Minimal mirror of the Supabase auth.users columns the app's schema
-- touches (id via FK, email via the signup trigger).
CREATE TABLE IF NOT EXISTS auth.users (
    id    UUID PRIMARY KEY,
    email TEXT
);

-- Supabase's RLS helper, referenced by policy DDL in the migrations.
-- The app connects as the table owner (RLS doesn't bind), so a NULL
-- stub is behaviorally inert here — it only needs to exist for the
-- CREATE POLICY statements to parse.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE AS 'SELECT NULL::uuid';

-- Supabase's standard roles, referenced by GRANT/POLICY DDL in the
-- migrations. NOLOGIN — they exist only so the statements parse.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
END $$;

-- Seed the LIS_LOCAL_MODE fixed user so settings writes persist. The
-- public.users row is created by migration 001's signup trigger when it
-- exists; insert both sides idempotently so ordering doesn't matter.
INSERT INTO auth.users (id, email)
VALUES ('00000000-0000-4000-8000-000000000001', 'local@localhost')
ON CONFLICT (id) DO NOTHING;
