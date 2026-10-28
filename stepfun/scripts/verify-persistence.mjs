import { chromium } from 'playwright';
import { readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const base = process.env.APP_URL || 'http://127.0.0.1:8010';
const prior = JSON.parse(await readFile('evidence/browser-results.json', 'utf8'));
const target = prior.persistence;
assert.ok(target, 'Run verify-browser.mjs first, then restart the application server');
const executablePath = process.env.EDGE_PATH || (process.platform === 'win32' ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
try {
  const page = await browser.newPage();
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.fill('#collection', target.collection);
  await page.selectOption('#dtype', target.dtype);
  await page.selectOption('#device', 'wasm');
  await page.fill('#query', target.query);
  await page.click('#search');
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'), null, { timeout: 180000 });
  assert.ok((await page.locator('#results').textContent()).includes(target.query));
  const output = { timestamp: new Date().toISOString(), target, success: true, status: await page.locator('#status').textContent(), metrics: JSON.parse(await page.locator('#metrics').textContent()), note: 'Fresh browser after application server restart; existing seekdb data queried with newly computed browser embedding. Database process itself was not restarted.' };
  await writeFile('evidence/persistence.json', JSON.stringify(output, null, 2) + '\n');
  await page.screenshot({ path: 'evidence/ui-after-restart.png', fullPage: true });
  console.log('PASS application restart persistence');
} finally { await browser.close(); }
