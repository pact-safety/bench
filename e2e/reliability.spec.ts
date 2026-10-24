import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

test("account isolation and persistence integrity on disposable Postgres", () => {
  test.setTimeout(60_000);
  // Reuse the explicitly configured throwaway database. The Python gates
  // reject non-loopback URLs and create only isolated test tables/schemas.
  const databaseUrl = process.env.E2E_DATABASE_URL;
  expect(databaseUrl, "E2E_DATABASE_URL must name the disposable database").toBeTruthy();
  const output = execFileSync(".venv/bin/python", [
    "-m", "pytest", "-q", "-m", "integration",
    "tests/postgres/test_content_account_isolation.py",
    "tests/postgres/test_assessment_account_isolation.py",
    "tests/postgres/test_kb_import_integrity.py",
    "tests/postgres/test_connect_integrity.py",
    "tests/postgres/test_mira_coach_concurrency.py",
    "tests/postgres/test_feedback_promotion_claims.py",
    "tests/postgres/test_track_request_concurrency.py",
    "tests/postgres/test_track_assessment_integrity.py",
  ], {
    encoding: "utf8",
    timeout: 50_000,
    env: {
      ...process.env,
      DATABASE_URL: "",
      E2E_DATABASE_URL: databaseUrl!,
      LIS_NO_DB: "1",
      LIS_SKIP_STARTUP_LOAD: "1",
      SUPABASE_JWT_SECRET: "",
      ANTHROPIC_API_KEY: "",
    },
  });
  expect(output).toContain("passed");
  expect(output).not.toMatch(/\d+ skipped/);
});
