// Island E2E happy paths (FRONTEND-1c) — the real app, real Postgres,
// real hydration. Covers the three islands shipped so far.
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" }); // shared single-user settings

test("first problem tip preserves solve and dismissal form ownership", async ({ page }) => {
  await page.goto("/problem/paired-eval-position-debias");
  await expect(page.locator(".ob-bubble")).toBeVisible();
  const ownership = await page.evaluate(() => {
    const solve = document.querySelector<HTMLFormElement>("#solve-form")!;
    const run = document.querySelector<HTMLButtonElement>("#run-tests-btn")!;
    const advance = document.querySelector<HTMLButtonElement>(".ob-bubble__next")!;
    const dismiss = advance.form;
    return {
      runOwner: run.form?.id,
      codeOwner: document.querySelector<HTMLTextAreaElement>("#code")?.form?.id,
      solveFields: Array.from(solve.elements).map((field) => field.getAttribute("name")),
      dismissOwner: dismiss?.id,
      dismissAction: dismiss?.getAttribute("action"),
      dismissFields: dismiss ? Object.fromEntries(new FormData(dismiss, advance)) : {},
    };
  });
  expect(ownership.runOwner).toBe("solve-form");
  expect(ownership.codeOwner).toBe("solve-form");
  expect(ownership.solveFields).toContain("code");
  expect(ownership.solveFields).not.toContain("tip");
  expect(ownership.dismissOwner).toBe("ob-bubble-form-seen");
  expect(ownership.dismissAction).toBe("/settings/bubbles");
  expect(ownership.dismissFields).toEqual({
    surface: "problem", tip: "phase_rail", action: "seen",
    next: "/problem/paired-eval-position-debias",
  });
});

test("theme-preview island: live preview + server persistence", async ({
  page,
}) => {
  // Start from the dark default.
  await page.request.post("/settings/theme", { form: { theme: "" } });
  await page.goto("/settings");
  await expect(page.locator("html")).not.toHaveAttribute("data-theme");

  // Island hydrated over the fallback select.
  const island = page.locator('[data-island="theme-preview"]');
  await expect(island).toHaveAttribute("data-hydrated", "1");

  // Live preview: selecting HTC applies the theme immediately, no save.
  await island.locator("select").selectOption("hyperbolic");
  await expect(page.locator("html")).toHaveAttribute(
    "data-theme",
    "hyperbolic",
  );
  await expect(page.getByText("previewing — Save to keep it")).toBeVisible();

  // Commit through the server form; persisted across a fresh load.
  await page.getByRole("button", { name: "Save theme" }).click();
  await page.goto("/settings");
  await expect(page.locator("html")).toHaveAttribute(
    "data-theme",
    "hyperbolic",
  );
});

test("glass-slider island: live var tuning + persistence", async ({
  page,
}) => {
  await page.goto("/settings"); // hyperbolic persisted by the prior test
  const island = page.locator('[data-island="glass-slider"]');
  await expect(island).toHaveAttribute("data-hydrated", "1");

  // Drag to 100: the inline vars update live…
  const slider = island.locator('input[type="range"]');
  await slider.fill("100");
  await expect
    .poll(async () =>
      page.evaluate(() =>
        document.documentElement.style.getPropertyValue("--glass-alpha"),
      ),
    )
    .toBe("0.85");

  // …and the level persists: fresh load paints the same values
  // server-side (base.html inline style).
  await expect
    .poll(async () => {
      const r = await page.request.get("/settings");
      return (await r.text()).includes("--glass-alpha: 0.85");
    })
    .toBe(true);
});

test("mcq-flow island: select → commit → advance", async ({ page }) => {
  await page.goto("/onboarding");
  // Start an assessment run (the onboarding form posts to /onboarding/start).
  await page.request
    .post("/onboarding/start")
    .then(async (r) => page.goto(r.url()));

  const island = page.locator('[data-island="mcq-flow"]');
  await expect(island).toHaveAttribute("data-hydrated", "1");
  await expect(page.getByText("Question 1 of up to")).toBeVisible();

  // Commit is disabled until an option is picked.
  const commit = page.getByRole("button", { name: "Commit answer" });
  await expect(commit).toBeDisabled();

  await island.getByRole("radio").first().check();
  await expect(commit).toBeEnabled();
  await commit.click();
  // 4a reveal beat: the axis-signal panel appears after the locked-in
  // beat, then auto-advances (~1.6s) to the next question.
  await expect(page.getByText("Answer locked — this feeds")).toBeVisible();

  // The reveal auto-advance submits the real form; we land on question 2.
  await expect(page.getByText("Question 2 of up to")).toBeVisible({
    timeout: 10_000,
  });
});

test.skip("Mira coaching: preserve a draft, save reflection, return to practice", async ({
  page,
}) => {
  // Exercise the real persistence path without an answer-generating provider.
  await page.goto("/mira?new=1&problem=warmest-reading");
  await expect(page.getByText("Text coaching preview", { exact: false })).toBeVisible();
  await expect(page.locator('[data-island="mira-chat"]')).toHaveCount(0);
  const thinking = page.getByLabel("Your thinking", { exact: true });
  const frame = "I want to predict the result before running the example.";
  await thinking.fill(frame);
  await page.reload();
  await expect(thinking).toHaveValue(frame);
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Describe your attempt", exact: true })).toBeVisible();
  await expect(thinking).toHaveValue("");

  await thinking.fill("I wrote a small case and a prediction on paper.");
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Choose a check", exact: true })).toBeVisible();
  await thinking.fill("I will compare the observed result against my prediction.");
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reflect and continue", exact: true })).toBeVisible();
  await thinking.fill("I need to check my assumptions before scaling up.");
  await page.getByRole("button", { name: "Save reflection", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reflection saved", exact: true })).toBeVisible();
  await expect(page.getByText(frame, { exact: true })).toBeVisible();
  await expect(page.getByText("Coaching has not marked the exercise complete.", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "Return to practice →", exact: true }).click();
  await expect(page).toHaveURL(/\/problem\/warmest-reading$/);
});

test("compose-editor island: bundled CodeMirror replaces the textarea", async ({
  page,
}) => {
  await page.goto("/problem/warmest-reading");
  const island = page.locator('[data-island="compose-editor"]');
  await expect(island).toHaveAttribute("data-hydrated", "1");
  await expect(island.locator(".cm-content")).toBeVisible();
  // The form field stays; the editor hides it and syncs on submit.
  await expect(page.locator("#code")).toBeHidden();
  // Starter code made it into the editor.
  await expect(island.locator(".cm-content")).toContainText("def warmest_reading");
});
