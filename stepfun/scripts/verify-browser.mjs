import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import os from 'node:os';
import assert from 'node:assert/strict';

const base = process.env.APP_URL || 'http://127.0.0.1:8010';
const corpus = JSON.parse(await readFile('data/corpus.json', 'utf8'));
const qrels = JSON.parse(await readFile('data/qrels.json', 'utf8'));
const executablePath = process.env.EDGE_PATH || (process.platform === 'win32' ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(180000);
const errors = [], requests = [];
page.on('pageerror', error => errors.push(String(error)));
page.on('request', request => requests.push({ method: request.method(), url: request.url() }));
const evidence = { timestamp: new Date().toISOString(), cpu: os.cpus()[0]?.model, logicalCpus: os.cpus().length, totalMemoryBytes: os.totalmem(), platform: `${os.platform()} ${os.release()}`, node: process.version, browser: browser.version(), corpusDocuments: corpus.length, queryCount: Object.keys(qrels).length, dataset: 'Hand-authored English mini benchmark; not a general retrieval benchmark', configs: [], checks: {}, errors, requests };
await mkdir('evidence', { recursive: true });
async function save() { await writeFile('evidence/browser-results.json', JSON.stringify(evidence, null, 2) + '\n'); }
async function api(route, body) {
  return page.evaluate(async ({ route, body }) => {
    const response = await fetch(route, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, data: await response.json() };
  }, { route, body });
}
async function embed(texts, dtype, device, batchSize) {
  return page.evaluate(async options => {
    const app = await import('/app.js');
    return app.embed(options.texts, options.dtype, options.device, options.batchSize);
  }, { texts, dtype, device, batchSize });
}
function quality(ids, relevant) {
  const recall = ids.filter(id => relevant.includes(id)).length / relevant.length;
  const dcg = ids.reduce((sum, id, index) => sum + (relevant.includes(id) ? 1 / Math.log2(index + 2) : 0), 0);
  const ideal = relevant.slice(0, 5).reduce((sum, _, index) => sum + 1 / Math.log2(index + 2), 0);
  return { recallAt5: recall, ndcgAt5: dcg / ideal };
}
try {
  await page.goto(base, { waitUntil: 'networkidle' });
  evidence.health = (await api('/api/health')).data;
  evidence.model = (await api('/api/config')).data.manifest;
  evidence.navigator = await page.evaluate(() => ({ userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, deviceMemory: navigator.deviceMemory, crossOriginIsolated, gpu: Boolean(navigator.gpu) }));
  assert.equal(evidence.health.inference, 'browser-only');
  const stamp = Date.now().toString(36);
  for (const config of [
    { dtype: 'fp32', device: 'wasm', batchSize: 1 },
    { dtype: 'fp32', device: 'wasm', batchSize: 8 },
    { dtype: 'q8', device: 'wasm', batchSize: 1 },
    { dtype: 'q8', device: 'wasm', batchSize: 8 },
    { dtype: 'fp32', device: 'webgpu', batchSize: 8 },
    { dtype: 'q8', device: 'webgpu', batchSize: 8 },
  ]) {
    const collection = `bench_${stamp}_${evidence.configs.length}`;
    const result = { ...config, collection, runs: [] };
    evidence.configs.push(result);
    console.log('CONFIG', config);
    for (let repeat = 0; repeat < 4; repeat++) {
      const inference = await embed(corpus.map(item => item.text), config.dtype, config.device, config.batchSize);
      assert.equal(inference.vectors.length, corpus.length);
      assert.equal(inference.vectors[0].length, 384);
      const write = await api('/api/import', { collection, dtype: config.dtype, refreshPolicy: 'batch', documents: corpus.map((item, index) => ({ ...item, embedding: inference.vectors[index] })) });
      assert.equal(write.status, 200, JSON.stringify(write));
      assert.equal(write.data.count, corpus.length);
      const run = { repeat, firstInConfig: repeat === 0, inference: { ...inference, vectors: undefined, resources: repeat === 0 ? inference.resources : undefined }, write: write.data, queries: [] };
      result.runs.push(run);
      for (const [query, relevant] of Object.entries(qrels)) {
        const measurement = await page.evaluate(async options => {
          const started = performance.now();
          const app = await import('/app.js');
          const queryInference = await app.embed([options.query], options.dtype, options.device, 1);
          const response = await fetch('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ collection: options.collection, dtype: options.dtype, query: options.query, embedding: queryInference.vectors[0], topK: 5 }) });
          const result = await response.json();
          if (!response.ok) throw new Error(JSON.stringify(result));
          const renderStarted = performance.now();
          const container = document.querySelector('#results');
          container.replaceChildren(...result.results.map(item => { const article = document.createElement('article'); article.textContent = item.text; return article; }));
          return { ids: result.results.map(item => item.id), embeddingMs: queryInference.inferenceMs, loadMs: queryInference.loadMs, databaseMs: result.databaseMs, renderMs: performance.now() - renderStarted, endToEndMs: performance.now() - started };
        }, { query, collection, dtype: config.dtype, device: config.device });
        run.queries.push({ query, relevant, ...measurement, ...quality(measurement.ids, relevant) });
      }
      await save();
    }
  }
  const reference = evidence.configs.find(config => config.dtype === 'fp32' && config.device === 'wasm' && config.batchSize === 8);
  const meanQuality = config => {
    const queries = config.runs.filter(run => !run.firstInConfig).flatMap(run => run.queries);
    return { recallAt5: queries.reduce((sum, query) => sum + query.recallAt5, 0) / queries.length, ndcgAt5: queries.reduce((sum, query) => sum + query.ndcgAt5, 0) / queries.length };
  };
  const baseline = meanQuality(reference);
  evidence.qualityGate = { maximumAbsoluteDrop: 0.05, baseline, comparisons: evidence.configs.filter(config => config.dtype === 'q8').map(config => ({ requested: config.device, actual: config.runs[0].inference.device, batchSize: config.batchSize, ...meanQuality(config) })) };
  for (const comparison of evidence.qualityGate.comparisons) {
    assert.ok(comparison.recallAt5 >= baseline.recallAt5 - 0.05);
    assert.ok(comparison.ndcgAt5 >= baseline.ndcgAt5 - 0.05);
  }
  evidence.checks.quantizationQualityGate = true;
  const dtype = 'q8', collection = `state_${stamp}`;
  const vectorResult = await embed(['A new document about zebras.'], dtype, 'wasm', 1);
  const doc = { id: 'zebra', title: '<img src=x onerror="window.xss=1">', text: '<script>window.xss=1</script> A new document about zebras.', embedding: vectorResult.vectors[0] };
  const first = await api('/api/import', { collection, dtype, documents: [doc] });
  const second = await api('/api/import', { collection, dtype, documents: [doc] });
  assert.equal(first.data.count, 1); assert.equal(second.data.count, 1);
  evidence.checks.idempotentUpsert = true;
  const extraInference = await embed(['An incremental document about penguins.'], dtype, 'wasm', 1);
  const extra = { id: 'penguin', title: 'incremental', text: 'An incremental document about penguins.', embedding: extraInference.vectors[0] };
  const increment = await api('/api/import', { collection, dtype, documents: [extra] });
  assert.equal(increment.data.count, 2);
  const found = await api('/api/search', { collection, dtype, query: 'penguins', embedding: extra.embedding, topK: 2 });
  assert.equal(found.data.results[0].id, 'penguin');
  evidence.checks.incrementalVisibility = true;
  const isolated = await api('/api/import', { collection: `${collection}_other`, dtype, documents: [{ ...doc, id: 'only-other' }] });
  assert.equal(isolated.data.count, 1);
  const isolationSearch = await api('/api/search', { collection: `${collection}_other`, dtype, query: 'penguins', embedding: extra.embedding, topK: 5 });
  assert.deepEqual(isolationSearch.data.results.map(item => item.id), ['only-other']);
  evidence.checks.collectionIsolation = true;
  const precisionSearch = await api('/api/search', { collection, dtype: 'fp32', query: 'zebra', embedding: doc.embedding });
  assert.equal(precisionSearch.status, 404);
  evidence.checks.precisionIsolation = true;
  await page.fill('#collection', collection); await page.locator('#collection').dispatchEvent('change');
  await page.selectOption('#dtype', dtype); await page.selectOption('#device', 'wasm');
  await page.fill('#query', 'zebras'); await page.click('#search');
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'));
  assert.equal(await page.evaluate(() => window.xss), undefined);
  assert.ok((await page.locator('#results').textContent()).includes('<script>'));
  evidence.checks.xssEscaped = true;
  await page.screenshot({ path: 'evidence/ui-wasm.png', fullPage: true });
  await page.reload({ waitUntil: 'networkidle' });
  assert.equal(await page.locator('#collection').inputValue(), collection);
  assert.equal(await page.locator('#dtype').inputValue(), dtype);
  await page.fill('#query', 'penguins'); await page.click('#search');
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'));
  assert.ok((await page.locator('#results').textContent()).includes('penguins'));
  evidence.checks.pageReload = true;
  const uiCollection = `ui_${stamp}`;
  await page.fill('#collection', uiCollection); await page.locator('#collection').dispatchEvent('change');
  const uploadText = corpus.slice(0, 3).map(item => `# ${item.title}\n${item.text}`).join('\n\n');
  await page.locator('#file').setInputFiles({ name: '真实导入.md', mimeType: 'text/markdown', buffer: Buffer.from(uploadText) });
  for (let repeat = 0; repeat < 2; repeat++) {
    await page.click('#import');
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('导入完成'));
    const collections = (await api('/api/collections')).data.collections;
    assert.equal(collections.find(item => item.name === `stepfun_${uiCollection}_${dtype}`).count, 3);
  }
  await page.fill('#query', 'How does INT8 affect model size?'); await page.click('#search');
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'));
  assert.ok((await page.locator('#results').textContent()).includes('INT8'));
  await page.screenshot({ path: 'evidence/ui-full-flow.png', fullPage: true });
  evidence.checks.fileUploadUiAndStableUnicodeIds = true;
  evidence.ui = { collection: uiCollection, dtype, importedChunks: 3, importRepeats: 2, metrics: JSON.parse(await page.locator('#metrics').textContent()) };
  await page.selectOption('#dtype', 'fp32'); await page.selectOption('#device', 'webgpu');
  const gpuCollection = evidence.configs.find(config => config.dtype === 'fp32' && config.device === 'webgpu').collection;
  await page.fill('#collection', gpuCollection); await page.locator('#collection').dispatchEvent('change');
  await page.click('#search');
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'));
  evidence.gpuUi = { status: await page.locator('#status').textContent(), metrics: JSON.parse(await page.locator('#metrics').textContent()) };
  await page.screenshot({ path: 'evidence/ui-webgpu.png', fullPage: true });
  const denied = await fetch(`${base}/api/health`, { headers: { Origin: 'https://untrusted.invalid' } });
  assert.equal(denied.status, 403);
  const nullBody = await api('/api/import', null);
  assert.ok([404, 405].includes(nullBody.status));
  const malformed = await page.evaluate(async () => {
    const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'null' });
    return response.status;
  });
  assert.equal(malformed, 400);
  evidence.checks.originAndMalformedPayload = true;
  const refreshVectors = await embed(corpus.map(item => item.text), dtype, 'wasm', 8);
  for (const policy of ['each', 'batch']) {
    evidence.refreshComparison ??= [];
    for (let repeat = 0; repeat < 3; repeat++) {
      const response = await api('/api/import', { collection: `refresh_${stamp}_${policy}`, dtype, refreshPolicy: policy, writeBatchSize: 1, documents: corpus.map((item, index) => ({ ...item, embedding: refreshVectors.vectors[index] })) });
      assert.equal(response.status, 200);
      evidence.refreshComparison.push({ policy, repeat, ...response.data, note: 'Identical real browser corpus vectors reused across policies to isolate DB write/refresh strategy; no embedding optimization claimed here' });
    }
  }
  const invalid = await api('/api/import', { collection: 'invalid', dtype, documents: [{ ...doc, embedding: [1] }] });
  assert.equal(invalid.status, 400);
  evidence.checks.invalidVectorRejected = true;
  const external = requests.filter(item => !item.url.startsWith(base));
  assert.equal(external.length, 0, JSON.stringify(external));
  assert.equal(errors.length, 0, JSON.stringify(errors));
  evidence.checks.noExternalNetwork = true;
  const disabledGpuBrowser = await chromium.launch({ headless: true, executablePath, args: ['--disable-gpu', '--disable-webgpu'] });
  try {
    const fallbackPage = await disabledGpuBrowser.newPage({ viewport: { width: 1280, height: 1000 } });
    await fallbackPage.goto(base, { waitUntil: 'networkidle' });
    await fallbackPage.fill('#collection', collection);
    await fallbackPage.selectOption('#dtype', dtype);
    await fallbackPage.selectOption('#device', 'webgpu');
    await fallbackPage.fill('#query', 'penguins'); await fallbackPage.click('#search');
    await fallbackPage.waitForFunction(() => document.querySelector('#status').textContent.startsWith('检索完成'), null, { timeout: 180000 });
    evidence.forcedFallback = { status: await fallbackPage.locator('#status').textContent(), metrics: JSON.parse(await fallbackPage.locator('#metrics').textContent()), args: ['--disable-gpu', '--disable-webgpu'] };
    assert.equal(evidence.forcedFallback.metrics.browserBackend, 'wasm');
    assert.ok(evidence.forcedFallback.metrics.fallback);
    assert.ok((await fallbackPage.locator('#results').textContent()).includes('penguins'));
    await fallbackPage.screenshot({ path: 'evidence/ui-auto-fallback.png', fullPage: true });
    evidence.checks.automaticFallback = true;
  } finally { await disabledGpuBrowser.close(); }
  evidence.persistence = { collection, dtype, query: 'penguins', expectedId: 'penguin' };
  evidence.success = true;
  await save();
  console.log('PASS', evidence.checks);
} catch (error) { evidence.success = false; evidence.failure = String(error.stack || error); await save(); throw error; }
finally { await browser.close(); }
