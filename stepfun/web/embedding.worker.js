import { env, pipeline } from '@huggingface/transformers';

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = '/models/';
env.backends.onnx.wasm.wasmPaths = '/vendor/ort/';
env.backends.onnx.wasm.numThreads = 4;

let active = null;
let pending = Promise.resolve();
let q8GpuRejected = null;
let calibration = null;

function post(id, type, payload = {}) { self.postMessage({ id, type, ...payload }); }

async function gpuInfo() {
  if (!navigator.gpu) return { available: false, reason: 'navigator.gpu unavailable' };
  try {
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
    if (!adapter) return { available: false, reason: 'No WebGPU adapter' };
    const info = adapter.info || await adapter.requestAdapterInfo?.() || {};
    return { available: true, vendor: info.vendor, architecture: info.architecture, device: info.device, description: info.description, software: adapter.isFallbackAdapter ?? info.isFallbackAdapter ?? false };
  } catch (error) { return { available: false, reason: String(error.message || error) }; }
}

async function getExtractor(dtype, device, id) {
  const key = `${dtype}:${device}`;
  if (active?.key === key) return { ...active, cached: true };
  if (active) { await active.extractor.dispose(); active = null; }
  const extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
    device, dtype, progress_callback: progress => post(id, 'progress', { progress }),
  });
  active = { key, extractor, device };
  if (dtype === 'q8' && device === 'webgpu') {
    const probes = ['A small cat rests on a blue chair.', 'Database vector search and full text retrieval.', 'Quantized model inference runs in a browser.'];
    const wasm = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', { device: 'wasm', dtype, progress_callback: progress => post(id, 'progress', { progress }) });
    try {
      const gpuVectors = await encode(extractor, probes, 1, id);
      const wasmVectors = await encode(wasm, probes, 1, id);
      const cosines = gpuVectors.map((row, index) => row.reduce((sum, value, offset) => sum + value * wasmVectors[index][offset], 0));
      calibration = { probes, cosines, threshold: 0.99, passed: cosines.every(value => Number.isFinite(value) && value >= 0.99), scope: 'Same q8 model, WebGPU vs WASM; independent fixed probes, not relevance labels' };
      if (!calibration.passed) {
        q8GpuRejected = `INT8 WebGPU numeric self-check failed (minimum cosine=${Math.min(...cosines).toFixed(5)} < 0.99); using WASM`;
        await extractor.dispose();
        active = { key: `${dtype}:wasm`, extractor: wasm, device: 'wasm' };
      } else { await wasm.dispose(); }
    } catch (error) {
      await wasm.dispose();
      throw error;
    }
  }
  return { ...active, cached: false };
}

async function encode(extractor, texts, batchSize, id) {
  const vectors = [];
  for (let offset = 0; offset < texts.length; offset += batchSize) {
    const batch = texts.slice(offset, offset + batchSize);
    const output = await extractor(batch, { pooling: 'mean', normalize: true });
    for (const row of output.tolist()) {
      const norm = Math.sqrt(row.reduce((sum, value) => sum + value * value, 0));
      vectors.push(row.map(value => value / norm));
    }
    post(id, 'batch', { completed: Math.min(offset + batch.length, texts.length), total: texts.length });
  }
  return vectors;
}

async function handle({ id, texts, dtype = 'fp32', device = 'webgpu', batchSize = 8 }) {
  try {
    if (!Array.isArray(texts) || !texts.length || !texts.every(text => typeof text === 'string') || !['fp32', 'q8'].includes(dtype) || !['webgpu', 'wasm'].includes(device) || !Number.isInteger(batchSize) || batchSize < 1 || batchSize > 32) throw new Error('Invalid embedding options');
    const started = performance.now();
    const gpu = device === 'webgpu' ? await gpuInfo() : { available: false, reason: 'WASM explicitly selected' };
    const requested = device === 'webgpu' && gpu.available && !(dtype === 'q8' && q8GpuRejected) ? 'webgpu' : 'wasm';
    let fallback = device === 'webgpu' && !gpu.available ? gpu.reason : null;
    if (device === 'webgpu' && dtype === 'q8' && q8GpuRejected) fallback = q8GpuRejected;
    let loaded;
    try { loaded = await getExtractor(dtype, requested, id); }
    catch (error) {
      if (requested === 'wasm') throw error;
      fallback = `WebGPU initialization failed: ${String(error.message || error)}`;
      loaded = await getExtractor(dtype, 'wasm', id);
    }
    const loadMs = performance.now() - started;
    if (device === 'webgpu' && dtype === 'q8' && q8GpuRejected) fallback = q8GpuRejected;
    const inferenceStarted = performance.now();
    let vectors;
    try { vectors = await encode(loaded.extractor, texts, batchSize, id); }
    catch (error) {
      if (loaded.device === 'wasm') throw error;
      fallback = `WebGPU execution failed: ${String(error.message || error)}`;
      loaded = await getExtractor(dtype, 'wasm', id);
      vectors = await encode(loaded.extractor, texts, batchSize, id);
    }
    post(id, 'done', { vectors, dtype, device: loaded.device, gpu, calibration: dtype === 'q8' && device === 'webgpu' ? calibration : null, fallback, cached: loaded.cached, loadMs, inferenceMs: performance.now() - inferenceStarted, totalMs: performance.now() - started, resources: performance.getEntriesByType('resource').map(item => ({ name: item.name, duration: item.duration, transferSize: item.transferSize })) });
  } catch (error) { post(id, 'error', { message: String(error.stack || error) }); }
}

self.onmessage = event => { pending = pending.then(() => handle(event.data)); };
