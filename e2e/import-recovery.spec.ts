import {execFileSync} from 'node:child_process';
import {expect, test} from '@playwright/test';

test('vault validation explains retry and re-import preserves distinct folder notes', async ({page}) => {
  const archive = execFileSync('.venv/bin/python', ['-c', `
import io, sys, zipfile
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as archive:
    archive.writestr('vault/Import A/note.md', '# Import A\\nSynthetic import A')
    archive.writestr('vault/Import B/note.md', '# Import B\\nSynthetic import B')
sys.stdout.buffer.write(buf.getvalue())
`]);
  await page.goto('/mira/kb');
  await page.locator('#vault-zip').setInputFiles({name:'invalid.zip', mimeType:'application/zip', buffer:Buffer.from('not an archive')});
  await page.getByRole('button', {name:'Import vault', exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('valid, unencrypted ZIP');
  await page.locator('#vault-zip').setInputFiles({name:'synthetic.zip', mimeType:'application/zip', buffer:archive});
  await page.getByRole('button', {name:'Import vault', exact:true}).click();
  await expect(page.getByRole('status')).toContainText('2 ingested');
  await expect(page.getByRole('status')).toContainText('0 failed');
  await expect(page.locator('.mira-card__meta').filter({hasText:'Import A/note.md'})).toHaveCount(1);
  await expect(page.locator('.mira-card__meta').filter({hasText:'Import B/note.md'})).toHaveCount(1);
  await page.locator('#vault-zip').setInputFiles({name:'synthetic.zip', mimeType:'application/zip', buffer:archive});
  await page.getByRole('button', {name:'Import vault', exact:true}).click();
  await expect(page.getByRole('status')).toContainText('0 ingested');
  await expect(page.getByRole('status')).toContainText('2 unchanged');
});
