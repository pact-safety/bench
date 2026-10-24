import {expect, test} from '@playwright/test';

test.skip('Mira retries share a saved note while conflicting drafts survive', async ({page}) => {
  await page.goto('/mira?new=1&problem=warmest-reading');
  const form = await page.locator('form[action="/mira/coach"]').evaluate(node =>
    Object.fromEntries(new FormData(node as HTMLFormElement)) as Record<string, string>);
  form.message = 'Synthetic retry: I will state a prediction first.';
  const results = await Promise.all([
    page.request.post('/mira/coach', {form, maxRedirects: 0}),
    page.request.post('/mira/coach', {form, maxRedirects: 0}),
  ]);
  expect(results.map(r => r.status())).toEqual([303, 303]);
  const sessionUrl = results[0].headers().location;
  expect(results[1].headers().location).toBe(sessionUrl);
  await page.goto(sessionUrl);
  await expect(page.locator('.mira-msg__body--plain')).toHaveCount(1);
  await expect(page.locator('[name="stage"]')).toHaveValue('attempt');
  const conflict = await page.request.post('/mira/coach', {
    form: {...form, message: 'Synthetic conflicting draft to preserve.'}, maxRedirects: 0,
  });
  expect(conflict.status()).toBe(409);
  expect(await conflict.text()).toContain('Synthetic conflicting draft to preserve.');
  await page.reload();
  await expect(page.locator('.mira-msg__body--plain')).toHaveCount(1);
});

test('completed assessment distinguishes unmeasured axes from numeric scores', async ({page}) => {
  test.setTimeout(60_000);
  const started = await page.request.post('/onboarding/start', {maxRedirects: 0});
  expect(started.status()).toBe(303);
  await page.goto(started.headers().location);
  for (let step = 0; step < 10 && !page.url().endsWith('/result'); step++) {
    const form = page.locator('form[action$="/answer"]');
    const values = await form.evaluate(node => {
      const data = new FormData(node as HTMLFormElement);
      const option = node.querySelector<HTMLInputElement>('input[type="radio"]');
      if (option) data.set(option.name, option.value);
      return Object.fromEntries(data) as Record<string, string>;
    });
    const action = await form.getAttribute('action');
    const response = await page.request.post(action!, {form: values});
    expect(response.status()).toBe(200);
    await page.goto(response.url());
  }
  await expect(page).toHaveURL(/\/assess\/\d+\/result$/);
  // The chart groups related axes; each group has measured evidence even
  // though these three individual axes were not covered by the question pool.
  await expect(page.locator('.assess-result > p').filter({hasText: 'Not assessed:'})).toHaveText(
    'Not assessed: AI safety fundamentals, Mechanistic interpretability, AGI strategy & governance.',
  );
  await expect(page.getByText('10 of 13 axes assessed.', {exact: false})).toBeVisible();
  await expect(page.getByText('retake the assessment to record a new snapshot.', {exact: false})).toBeVisible();
});
