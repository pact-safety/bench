import {expect, test} from '@playwright/test';

// Uses only the required throwaway E2E database. Failed requests are intercepted.
test('writing publish keeps unsaved title/body across failure and explicit recovery', async ({page}) => {
  const created = await page.request.post('/writings');
  const url = created.url();
  await page.goto(url);
  await page.locator('input[name="title"]').fill('Synthetic recovery title');
  await page.locator('#writing-body').fill('Synthetic unsaved body');
  await page.route('**/writings/*/status', route => route.fulfill({status:503, body:'Synthetic save failure'}));
  await page.getByRole('button', {name:'Mark published'}).click();
  await expect(page.getByText('Synthetic save failure')).toBeVisible();
  await page.goto(url);
  const recovery = page.locator('[data-autosave-recovery]');
  await expect(recovery).toHaveCount(2);
  // Restoring removes that panel, so resolve the next remaining panel each time.
  for (let remaining = 2; remaining > 0; remaining--) {
    const panel = recovery.first();
    await panel.locator('summary').click();
    await panel.getByRole('button', {name:'Use recovery copy'}).click();
  }
  await expect(page.locator('input[name="title"]')).toHaveValue('Synthetic recovery title');
  await expect(page.locator('#writing-body')).toHaveValue('Synthetic unsaved body');
  await page.unroute('**/writings/*/status');
  await page.getByRole('button', {name:'Mark published'}).click();
  await expect(page.locator('.writing__head-meta .badge')).toHaveText('published');
  await page.reload();
  await expect(page.locator('input[name="title"]')).toHaveValue('Synthetic recovery title');
  await expect(page.locator('#writing-body')).toHaveValue('Synthetic unsaved body');
  await expect(page.locator('[data-autosave-recovery]')).toHaveCount(0);
});

test('CodeMirror edits persist immediately and recover explicitly after reload', async ({page}) => {
  await page.goto('/problem/warmest-reading');
  const editor = page.locator('.cm-content');
  await expect(editor).toBeVisible();
  await editor.fill('# synthetic unsaved code');
  await expect(page.locator('#code')).toHaveValue('# synthetic unsaved code');
  await expect.poll(() => page.evaluate(() => {
    const field = document.querySelector<HTMLTextAreaElement>('#code')!;
    const key = 'lisbench.autosave:v2:' + JSON.stringify([document.body.dataset.autosaveUser, location.pathname, field.form!.id, field.name]);
    return localStorage.getItem(key);
  })).toBe('# synthetic unsaved code');
  await page.reload();
  await expect(editor).toBeVisible();
  const recovery = page.locator('[data-autosave-recovery]').filter({has:page.getByText('Unsaved code recovery copy available', {exact:true})});
  await recovery.locator('summary').click();
  await recovery.getByRole('button', {name:'Use recovery copy'}).click();
  await expect(editor).toContainText('# synthetic unsaved code');
});

test('deadline sends a complete snapshot and retries identical text after a failed request', async ({page}) => {
  await page.clock.install();
  const payloads: URLSearchParams[] = [];
  await page.route('**/submit/*', async route => {
    payloads.push(new URLSearchParams(route.request().postData() || ''));
    await route.fulfill({status:503, body:'Synthetic cutoff failure'});
  });
  page.on('dialog', dialog => dialog.accept());
  await page.route('**/problem/paired-eval-position-debias?mode=interview', async route => {
    const response = await route.fetch();
    // Keep real form markup/JS while shortening only this synthetic deadline.
    const body = (await response.text()).replace(/var TOTAL = \d+ \* 60;/, 'var TOTAL = 60;');
    await route.fulfill({response, body});
  });
  await page.goto('/problem/paired-eval-position-debias?mode=interview');
  const editor = page.locator('.cm-content');
  await expect(editor).toBeVisible();
  const bypass = page.locator('#plan-gate-bypass');
  if (await bypass.isVisible()) await bypass.click();
  await editor.fill('# synthetic partial code');
  await page.locator('textarea[name="notes_md"]').evaluate((field: HTMLTextAreaElement) => {
    field.value = 'Synthetic cutoff notes';
    field.dispatchEvent(new Event('input', {bubbles:true}));
  });
  await page.clock.runFor(65_000);
  await expect(page.locator('[data-cutoff-retry]')).toBeVisible();
  expect(payloads[0].get('code')).toBe('# synthetic partial code');
  expect(payloads[0].get('notes_md')).toBe('Synthetic cutoff notes');
  expect(payloads[0].get('cutoff_bool')).toBe('1');
  expect(payloads[0].has('time_per_phase_json')).toBe(true);
  await expect(page.locator('[data-cutoff-copy]')).toContainText('# synthetic partial code');
  await page.locator('[data-cutoff-retry]').click();
  await expect.poll(() => payloads.length).toBe(2);
  expect(payloads[1].toString()).toBe(payloads[0].toString());
});
