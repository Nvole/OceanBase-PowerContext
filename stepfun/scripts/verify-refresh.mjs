import { chromium } from 'playwright';
import { readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const corpus = JSON.parse(await readFile('data/corpus.json', 'utf8'));
const executablePath = process.env.EDGE_PATH || (process.platform === 'win32' ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
try {
  const page = await browser.newPage();
  await page.goto(process.env.APP_URL || 'http://127.0.0.1:8010', { waitUntil: 'networkidle' });
  const runs = await page.evaluate(async corpus => {
    const app = await import('/app.js');
    const embedding = await app.embed(corpus.map(item => item.text), 'q8', 'wasm', 1);
    const documents = corpus.map((item, index) => ({ ...item, embedding: embedding.vectors[index] }));
    const result = [];
    const stamp = Date.now().toString(36);
    for (let repeat = 0; repeat < 4; repeat++) {
      for (const policy of ['each', 'batch']) {
        const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ collection: `control_${stamp}`, dtype: 'q8', refreshPolicy: policy, writeBatchSize: 1, documents }) });
        const data = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(data));
        result.push({ repeat, warmup: repeat === 0, policy, ...data });
      }
    }
    return result;
  }, corpus);
  for (const run of runs) {
    assert.equal(run.count, corpus.length);
    assert.equal(run.writeBatchSize, 1);
    assert.equal(run.refreshCalls, run.policy === 'each' ? corpus.length : 1);
  }
  await writeFile('evidence/refresh-results.json', JSON.stringify({ timestamp: new Date().toISOString(), note: 'Same browser-generated vectors, same collection, same per-document write size, alternating policies; first pair is warmup, next three pairs are measured. Only refresh frequency differs.', runs }, null, 2) + '\n');
  console.log('PASS controlled refresh strategy comparison');
} finally { await browser.close(); }
