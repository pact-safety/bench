import {expect, test} from '@playwright/test';

for (const width of [390, 1280]) {
  test(`feedback triage stays usable at ${width}px with accessibility preferences`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await page.emulateMedia({reducedMotion: 'reduce'});
    const body = `Synthetic inbox layout ${width} ${Date.now()}`;
    const response = await page.request.post('/feedback', {form: {
      url: '/content/track-ml4good-' + 'abcdef0123456789'.repeat(4), body,
    }});
    expect(response.ok()).toBeTruthy();
    await page.goto('/feedback/inbox');
    await page.evaluate(() => {
      for (const name of ['data-larger-text', 'data-high-contrast', 'data-reduce-motion']) {
        document.documentElement.setAttribute(name, '1');
      }
    });
    const item = page.locator('.fb-item').filter({hasText: body});
    await expect(item).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const note = item.getByLabel('Reason to defer (optional)');
    await note.fill('Synthetic review note');
    await note.focus();
    expect(await note.evaluate(el => getComputedStyle(el).boxShadow)).not.toBe('none');
    await page.keyboard.press('Tab');
    await expect(item.getByRole('button', {name: '→ backlog', exact: true})).toBeFocused();
    await Promise.all([page.waitForNavigation(), page.keyboard.press('Enter')]);
    await page.goto('/feedback/inbox?status=backlog');
    const deferred = page.locator('.fb-item').filter({hasText: body});
    await expect(deferred).toContainText('Synthetic review note');
    await deferred.getByLabel('Resolution note (optional)').fill('Reviewed in fixture');
    await deferred.getByRole('button', {name: 'close (done)', exact: true}).click();
    await page.goto('/feedback/inbox?status=closed');
    const closed = page.locator('.fb-item').filter({hasText: body});
    await expect(closed).toContainText('Reviewed in fixture');
    await closed.getByRole('button', {name: 'reopen', exact: true}).click();
    await page.goto('/feedback/inbox');
    await expect(page.locator('.fb-item').filter({hasText: body})).toBeVisible();
  });
}
