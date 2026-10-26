const pending = new Map();
const worker = new Worker('/static/embed_worker.js', { type: 'module' });
const sessionId = getSessionId();
let modelReady = false;
let activeDevice = '未加载';

const backend = document.querySelector('#backend');
const backendDetail = document.querySelector('#backend-detail');
const dbState = document.querySelector('#db-state');
const progress = document.querySelector('#progress');
const progressText = document.querySelector('#progress-text');
const importStatus = document.querySelector('#import-status');
const localTiming = document.querySelector('#local-timing');
const results = document.querySelector('#results');
const evalOutput = document.querySelector('#eval-output');

function getSessionId() {
  const key = 'track02-session';
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replace(/-/g, '').slice(0, 32);
    sessionStorage.setItem(key, value);
  }
  return value;
}

function setBackend(device, detail) {
  activeDevice = device;
  backend.className = 'badge';
  if (device === 'webgpu') {
    backend.classList.add('webgpu');
    backend.textContent = '当前推理后端：WebGPU';
  } else if (device === 'wasm') {
    backend.classList.add('wasm');
    backend.textContent = '当前推理后端：WASM';
  } else {
    backend.classList.add('error');
    backend.textContent = '当前推理后端：加载失败';
  }
  backendDetail.textContent = detail;
}

worker.onmessage = (event) => {
  const message = event.data || {};
  if (message.type === 'progress') {
    const item = message.event || {};
    if (typeof item.progress === 'number') {
      progress.style.width = `${Math.max(0, Math.min(100, item.progress))}%`;
    }
    progressText.textContent = item.file ? `${item.status || ''} ${item.file}` : (item.status || '');
  } else if (message.type === 'embed-progress') {
    progressText.textContent = `本地编码 ${message.done}/${message.total}`;
    progress.style.width = `${(100 * message.done) / message.total}%`;
  } else if (message.type === 'ready') {
    modelReady = true;
    const fallback = message.fallbackReason ? ` WebGPU 初始化失败，已降级到 WASM。原因：${message.fallbackReason}` : '';
    setBackend(message.device, `模型 ${message.model}，dtype ${message.dtype}（INT8，${message.onnx}）。优先尝试 ${message.preferred}。${message.preferredReason}。${fallback}`);
    for (const id of ['import-corpus', 'time-batch', 'add-doc', 'search', 'eval']) {
      document.querySelector(`#${id}`).disabled = false;
    }
  } else if (message.type === 'embeddings') {
    const waiter = pending.get(message.requestId);
    if (waiter) {
      pending.delete(message.requestId);
      waiter.resolve(message);
    }
  } else if (message.type === 'error') {
    if (message.requestId && pending.has(message.requestId)) {
      const waiter = pending.get(message.requestId);
      pending.delete(message.requestId);
      waiter.reject(new Error(message.message));
    } else {
      modelReady = false;
      setBackend('error', message.message);
    }
  }
};

function embed(texts) {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    worker.postMessage({ type: 'embed', requestId, texts });
  });
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

async function refreshState() {
  const state = await request('/api/state');
  dbState.textContent = `集合 ${state.collection}，${state.count} 条，维度 ${state.dimension}，距离 ${state.distance}，全文 ${state.fulltext_analyzer}。服务端计算 embedding：${state.server_computes_embeddings}。监听 ${state.bind}。会话 ${sessionId}。`;
  return state;
}

function showRows(payload, embedMs) {
  const timing = `查询向量本地编码 ${embedMs == null ? '未使用模型' : `${embedMs.toFixed(1)} ms`}；seekdb hybrid_search ${payload.search_ms.toFixed(1)} ms。`;
  const blocks = payload.rows.length ? payload.rows.map((row, index) => {
    const meta = row.metadata ? JSON.stringify(row.metadata) : '';
    return `<article class="result"><h3>${index + 1}. ${row.id}</h3><p>${escapeHtml(row.document || '')}</p><p class="meta">distance ${row.distance} ${escapeHtml(meta)}</p></article>`;
  }).join('') : '<p>没有命中。</p>';
  results.innerHTML = `<p class="meta">${timing} 融合 rank.rrf。服务端未重新计算向量。</p>${blocks}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}

async function upsertTexts(items) {
  const encoded = await embed(items.map((item) => item.document));
  const payload = {
    items: items.map((item, index) => ({
      id: item.id,
      document: item.document,
      embedding: encoded.vectors[index],
      metadata: {
        title: item.title || item.id,
        source: item.source || 'browser',
        session_id: sessionId,
        embedding_dtype: 'q8',
        embedding_backend: encoded.device,
      },
    })),
  };
  const stored = await request('/api/upsert', payload);
  await refreshState();
  return { encoded, stored };
}

document.querySelector('#load-model').addEventListener('click', () => {
  progressText.textContent = '正在选择 WebGPU 或 WASM 并加载 INT8 模型';
  worker.postMessage({ type: 'init' });
});

document.querySelector('#import-corpus').addEventListener('click', async () => {
  importStatus.textContent = '正在本地编码示例语料';
  try {
    const corpus = await request('/api/corpus');
    const outcome = await upsertTexts(corpus.documents.map((item) => ({ ...item, source: 'demo-corpus' })));
    importStatus.textContent = `已写入 ${outcome.stored.upserted} 条。本地编码 ${outcome.encoded.embedMs.toFixed(1)} ms（${outcome.encoded.device}），refresh_index ${outcome.stored.refresh_ms.toFixed(1)} ms。`;
  } catch (error) {
    importStatus.textContent = error.message;
  }
});

document.querySelector('#add-doc').addEventListener('click', async () => {
  const documentText = document.querySelector('#extra-text').value.trim();
  if (!documentText) {
    importStatus.textContent = '请先输入原文';
    return;
  }
  try {
    const outcome = await upsertTexts([{
      id: `user-${Date.now().toString(36)}`,
      title: '增量文档',
      document: documentText,
      source: 'user',
    }]);
    importStatus.textContent = `增量写入完成。本地编码 ${outcome.encoded.embedMs.toFixed(1)} ms，refresh_index ${outcome.stored.refresh_ms.toFixed(1)} ms。`;
  } catch (error) {
    importStatus.textContent = error.message;
  }
});

document.querySelector('#search').addEventListener('click', async () => {
  const query = document.querySelector('#query').value.trim();
  if (!query) {
    return;
  }
  try {
    const encoded = await embed([query]);
    const body = { query, embedding: encoded.vectors[0], n_results: 5 };
    if (document.querySelector('#session-only').checked) {
      body.session_id = sessionId;
    }
    const payload = await request('/api/search', body);
    showRows(payload, encoded.embedMs);
  } catch (error) {
    results.textContent = error.message;
  }
});

document.querySelector('#probe').addEventListener('click', async () => {
  const embedding = Array(384).fill(0);
  embedding[32] = 1;
  try {
    const payload = await request('/api/search', { query: 'webgpufirst', embedding, n_results: 5 });
    showRows(payload, null);
  } catch (error) {
    results.textContent = error.message;
  }
});

document.querySelector('#reset').addEventListener('click', async () => {
  if (!window.confirm('清空 track02_stepfun_kb？固定向量夹具和已导入文档都会删除。')) {
    return;
  }
  try {
    await request('/api/reset', { confirm: 'reset-track02' });
    await refreshState();
    importStatus.textContent = '集合已清空并重建，embedding function 仍为空。';
  } catch (error) {
    importStatus.textContent = error.message;
  }
});

document.querySelector('#time-batch').addEventListener('click', async () => {
  try {
    const corpus = await request('/api/corpus');
    const texts = corpus.documents.map((item) => item.document);
    const batched = await embed(texts);
    const singleStarted = performance.now();
    for (const text of texts) {
      await embed([text]);
    }
    const singleMs = performance.now() - singleStarted;
    localTiming.textContent = [
      `本次浏览器实测后端：${activeDevice}，dtype q8。`,
      `批大小 8：${batched.embedMs.toFixed(1)} ms / ${texts.length} 条。`,
      `逐条：${singleMs.toFixed(1)} ms / ${texts.length} 条。`,
      '这是当前页面刚刚测到的数字，不是服务器预先写入的 WebGPU 结果。',
    ].join('\n');
  } catch (error) {
    localTiming.textContent = error.message;
  }
});

document.querySelector('#eval').addEventListener('click', async () => {
  try {
    const spec = await request('/api/eval-queries');
    const encoded = await embed(spec.map((item) => item.query));
    const lines = [`后端 ${activeDevice}，INT8。Hit@3 只描述这次浏览器编码后的 seekdb 结果，不是量化前基线。`];
    let hits = 0;
    for (let index = 0; index < spec.length; index += 1) {
      const payload = await request('/api/search', {
        query: spec[index].query,
        embedding: encoded.vectors[index],
        n_results: 3,
      });
      const ids = payload.rows.map((row) => row.id);
      const hit = ids.includes(spec[index].expect_id);
      if (hit) {
        hits += 1;
      }
      lines.push(`${hit ? 'HIT' : 'MISS'} ${spec[index].query} => ${ids.join(', ') || '空'}`);
    }
    lines.push(`Hit@3 ${hits}/${spec.length}。FP32 对照未在无头环境运行，这里也不预填。`);
    evalOutput.textContent = lines.join('\n');
  } catch (error) {
    evalOutput.textContent = error.message;
  }
});

worker.postMessage({ type: 'init' });
refreshState().catch((error) => {
  dbState.textContent = error.message;
});
