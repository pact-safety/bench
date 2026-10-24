// Playwright E2E tier (FRONTEND-1c).
//
// Runs the REAL app (uvicorn, LIS_LOCAL_MODE) against a THROWAWAY
// Postgres. E2E_DATABASE_URL is mandatory and deliberately distinct
// from DATABASE_URL: the suite writes freely (themes, assessment runs),
// so it must be impossible to point it at a real database by accident
// or by .env.local leakage.
//
// Bring-up (local):
//   docker run -d --name bench-e2e -p 54329:5432 \
//     -e POSTGRES_PASSWORD=e2e pgvector/pgvector:pg16
//   psql postgresql://postgres:e2e@127.0.0.1:54329/postgres \
//     -f scripts/e2e_bootstrap.sql
//   E2E_DATABASE_URL=postgresql://postgres:e2e@127.0.0.1:54329/postgres npm run e2e
import { defineConfig } from "@playwright/test";

const dbUrl = process.env.E2E_DATABASE_URL;
if (!dbUrl) {
  throw new Error(
    "E2E_DATABASE_URL is required (a THROWAWAY database — the suite " +
      "writes). Refusing to fall back to DATABASE_URL/.env.local.",
  );
}

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://127.0.0.1:8877",
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      ".venv/bin/uvicorn app.main:app --port 8877 || uvicorn app.main:app --port 8877",
    url: "http://127.0.0.1:8877/__health",
    stdout: "pipe",
    stderr: "pipe",
    timeout: 60_000,
    env: {
      DATABASE_URL: dbUrl,
      LIS_LOCAL_MODE: "1",
      // Explicitly blank the Supabase interlock + noise sources so a
      // developer's .env.local can't leak into the E2E server process.
      SUPABASE_JWT_SECRET: "",
      SENTRY_DSN: "",
      ANTHROPIC_API_KEY: "",
    },
  },
});
