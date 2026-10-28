const state = { worker: null, sequence: 0, pending: new Map(), lastVectors: null };
const $ = selector => document.querySelector(selector);

function setStatus(message, kind = '') {
  const node = $('#status');
  node.textContent = message;
  node.dataset.kind = kind;
}

function escapeText(value) { return String(value ?? ''); }

function worker() {
  if (state.worker) return state.worker;
  state.worker = new Worker('/embedding.worker.js', { type: 'module' });
  state.worker.onmessage = event => {
    const message = event.data;
    const pending = state.pending.get(message.id);
    if (!pending) return;
    if (message.type === 'progress' || message.type === 'batch') {
      pending.progress?.(message);
    } else if (message.type === 'done') {
      state.pending.delete(message.id);
      pending.resolve(message);
    } else if (message.type === 'error') {
      state.pending.delete(message.id);
      pending.reject(new Error(message.message));
    }
  };
  return state.worker;
}

export function embed(texts, dtype, device, batchSize, progress) {
  const id = ++state.sequence;
  return new Promise((resolve, reject) => {
    state.pending.set(id, { resolve, reject, progress });
    worker().postMessage({ id, texts, dtype, device, batchSize });
  });
}

function splitText(text, title) {
  const normalized = text.replace(/\r\n?/g, '\n').trim();
  const paragraphs = normalized.split(/\n\s*\n/).map(item => item.trim()).filter(Boolean);
  const chunks = [];
  for (const paragraph of paragraphs.length ? paragraphs : [normalized]) {
    for (let offset = 0; offset < paragraph.length; offset += 700) {
      const chunk = paragraph.slice(offset, offset + 900).trim();
      if (chunk) chunks.push({ title, text: chunk });
    }
  }
  return chunks;
}

async function readInput() {
  const file = $('#file').files[0];
  if (file) {
    if (file.size > 1024 * 1024 || !/\.(txt|md)$/i.test(file.name)) throw new Error('仅支持 1MB 以内的 .txt/.md 文件');
    return { title: file.name, text: await file.text() };
  }
  return { title: $('#title').value.trim() || 'manual', text: $('#text').value };
}

async function importDocuments() {
  const started = performance.now();
  const input = await readInput();
  if (!input.text.trim()) throw new Error('请先选择 .txt/.md 文件或粘贴文本');
  const dtype = $('#dtype').value;
  const device = $('#device').value;
  const batchSize = Number($('#batchSize').value);
  const collection = $('#collection').value.trim();
  const chunks = splitText(input.text, input.title);
  if (chunks.length > 200) throw new Error('单次最多导入 200 个块，请分批导入');
  setStatus(`正在本地向量化 ${chunks.length} 个文本块…`);
  const embedded = await embed(chunks.map(item => item.text), dtype, device, batchSize, message => {
    if (message.completed) setStatus(`本地向量化 ${message.completed}/${message.total}…`);
  });
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input.title));
  const sourceId = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
  const docs = chunks.map((item, index) => ({ id: `${sourceId}:${index}`, title: item.title, text: item.text, embedding: embedded.vectors[index] }));
  const writeStart = performance.now();
  const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ collection, dtype, refreshPolicy: $('#refreshPolicy').value, documents: docs }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '导入失败');
  state.lastVectors = { dtype, device: embedded.device, fallback: embedded.fallback, loadMs: embedded.loadMs, inferenceMs: embedded.inferenceMs, requestMs: performance.now() - writeStart, endToEndMs: performance.now() - started, count: docs.length };
  $('#metrics').textContent = JSON.stringify({ ...state.lastVectors, accepted: result.accepted, dbWriteMs: result.writeMs, refreshMs: result.refreshMs, totalMs: result.totalMs }, null, 2);
  setStatus(`导入完成：${result.accepted} 个块，backend=${embedded.device}${embedded.fallback ? `；自动降级：${embedded.fallback}` : ''}`, 'ok');
  await refreshCollections();
}

async function search() {
  const started = performance.now();
  const query = $('#query').value.trim();
  if (!query) throw new Error('请输入查询');
  const dtype = $('#dtype').value;
  const embedded = await embed([query], dtype, $('#device').value, 1, () => {});
  const response = await fetch('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ collection: $('#collection').value.trim(), dtype, query, embedding: embedded.vectors[0], topK: Number($('#topK').value) }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '检索失败');
  $('#results').replaceChildren(...result.results.map((item, index) => {
    const article = document.createElement('article');
    const heading = document.createElement('h3');
    heading.textContent = `${index + 1}. ${escapeText(item.metadata?.title || item.id)}  score=${Number(item.score ?? 0).toFixed(5)}`;
    const body = document.createElement('p');
    body.textContent = escapeText(item.text);
    article.append(heading, body);
    return article;
  }));
  $('#metrics').textContent = JSON.stringify({ queryLoadMs: embedded.loadMs, queryEmbeddingMs: embedded.inferenceMs, browserBackend: embedded.device, fallback: embedded.fallback, dbMs: result.databaseMs, endToEndMs: performance.now() - started }, null, 2);
  setStatus(`检索完成：${result.results.length} 条，backend=${embedded.device}${embedded.fallback ? `；自动降级：${embedded.fallback}` : ''}`, 'ok');
}

async function refreshCollections() {
  const response = await fetch('/api/collections');
  const result = await response.json();
  $('#collections').textContent = JSON.stringify(result.collections, null, 2);
}

async function loadCorpus() {
  const response = await fetch('/data/corpus.json');
  const corpus = await response.json();
  $('#title').value = 'fixed-corpus.md';
  $('#text').value = corpus.map(item => `# ${item.title}\n${item.text}`).join('\n\n');
  setStatus(`已载入固定语料 ${corpus.length} 条，可直接导入`);
}

for (const selector of ['#collection', '#dtype', '#device', '#batchSize', '#refreshPolicy']) {
  const saved = localStorage.getItem(selector);
  if (saved) $(selector).value = saved;
  $(selector).addEventListener('change', () => { localStorage.setItem(selector, $(selector).value); $('#results').replaceChildren(); setStatus('配置已切换，请在当前集合/精度下导入或查询'); });
}
for (const [selector, handler] of [['#import', importDocuments], ['#search', search], ['#loadCorpus', loadCorpus], ['#refresh', refreshCollections]]) {
  $(selector).addEventListener('click', async () => {
    const controls = [...document.querySelectorAll('button,input,select,textarea')];
    controls.forEach(control => { control.disabled = true; });
    try { await handler(); } catch (error) { setStatus(error.message, 'error'); }
    finally { controls.forEach(control => { control.disabled = false; }); }
  });
}
refreshCollections().catch(() => {});
