import { env, pipeline } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2';

const MODEL_ID = 'Xenova/all-MiniLM-L6-v2';
const DTYPE = 'q8';
const BATCH = 8;

env.allowLocalModels = false;
env.useBrowserCache = true;
if (env.backends && env.backends.onnx && env.backends.onnx.wasm) {
  env.backends.onnx.wasm.numThreads = 1;
}

let extractor = null;
let activeDevice = null;

function post(message) {
  self.postMessage(message);
}

async function preferredDevice() {
  if (!navigator.gpu) {
    return { device: 'wasm', reason: 'navigator.gpu is missing' };
  }
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      return { device: 'wasm', reason: 'requestAdapter returned null' };
    }
    return { device: 'webgpu', reason: 'WebGPU adapter is available' };
  } catch (error) {
    return { device: 'wasm', reason: error && error.message ? error.message : String(error) };
  }
}

async function loadExtractor(device) {
  return pipeline('feature-extraction', MODEL_ID, {
    dtype: DTYPE,
    device,
    progress_callback: (event) => post({ type: 'progress', event }),
  });
}

async function init() {
  const preferred = await preferredDevice();
  let fallbackReason = null;
  let device = preferred.device;
  try {
    extractor = await loadExtractor(device);
  } catch (error) {
    if (device !== 'webgpu') {
      throw error;
    }
    fallbackReason = error && error.message ? error.message : String(error);
    device = 'wasm';
    extractor = await loadExtractor(device);
  }
  activeDevice = device;
  post({
    type: 'ready',
    model: MODEL_ID,
    dtype: DTYPE,
    quantization: 'INT8',
    onnx: 'onnx/model_quantized.onnx',
    device,
    preferred: preferred.device,
    preferredReason: preferred.reason,
    fallbackReason,
    batchSize: BATCH,
  });
}

function asVectors(output, expected) {
  const nested = output.tolist();
  const vectors = nested.length === 384 && typeof nested[0] === 'number' ? [nested] : nested;
  if (vectors.length !== expected || vectors.some((vector) => vector.length !== 384)) {
    throw new Error('model returned an unexpected embedding shape');
  }
  return vectors;
}

async function embed(texts) {
  const started = performance.now();
  const vectors = [];
  for (let offset = 0; offset < texts.length; offset += BATCH) {
    const batch = texts.slice(offset, offset + BATCH);
    const output = await extractor(batch, { pooling: 'mean', normalize: true });
    vectors.push(...asVectors(output, batch.length));
    post({ type: 'embed-progress', done: vectors.length, total: texts.length });
  }
  return { vectors, embedMs: performance.now() - started };
}

self.onmessage = async (event) => {
  const message = event.data || {};
  try {
    if (message.type === 'init') {
      await init();
    } else if (message.type === 'embed') {
      if (!extractor) {
        throw new Error('model is not ready');
      }
      const result = await embed(message.texts || []);
      post({ type: 'embeddings', requestId: message.requestId, ...result, device: activeDevice, dtype: DTYPE });
    } else {
      throw new Error('unknown worker message');
    }
  } catch (error) {
    post({
      type: 'error',
      requestId: message.requestId || null,
      message: error && error.message ? error.message : String(error),
    });
  }
};
