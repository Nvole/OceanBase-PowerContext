import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bad, collectionName, documents, queryInput, MODEL, DIMENSION } from './lib/core.mjs';
import { connectDatabase } from './lib/database.mjs';
const root = path.dirname(fileURLToPath(import.meta.url));
const db = await connectDatabase();
const host = process.env.HOST ?? '127.0.0.1';
if (!['127.0.0.1', 'localhost', '::1'].includes(host)) throw new Error('Local-only demo: do not expose this unauthenticated server publicly');
const port = Number(process.env.PORT ?? 8010), base = `http://${host}:${port}`;
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json', '.css': 'text/css; charset=utf-8', '.wasm': 'application/wasm', '.onnx': 'application/octet-stream' };
function json(response, status, value) { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); response.end(JSON.stringify(value)); }
async function body(request) {
  const chunks = []; let size = 0;
  for await (const chunk of request) { size += chunk.length; if (size > 8 * 1024 * 1024) throw bad('Payload exceeds 8MB', 413); chunks.push(chunk); }
  let value;
  try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw bad('Invalid JSON'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw bad('Expected JSON object');
  return value;
}
const server = http.createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
  response.setHeader('Cross-Origin-Opener-Policy', 'same-origin'); response.setHeader('Cross-Origin-Embedder-Policy', 'require-corp'); response.setHeader('Referrer-Policy', 'no-referrer');
  try {
    if (request.headers.host !== new URL(base).host) throw bad('Host mismatch', 403);
    if (request.headers.origin && request.headers.origin !== base) throw bad('Cross-site request rejected', 403);
    const url = new URL(request.url, base);
    if (url.pathname === '/favicon.ico') { response.writeHead(204); return response.end(); }
    if (url.pathname === '/api/health') return json(response, 200, { status: 'ok', database: db.database, version: db.version, inference: 'browser-only', model: MODEL, dimension: DIMENSION });
    if (url.pathname === '/api/config') return json(response, 200, { model: MODEL, dimension: DIMENSION, manifest: JSON.parse(await readFile(path.join(root, 'models', 'manifest.json'), 'utf8')) });
    if (url.pathname === '/api/collections' && request.method === 'GET') return json(response, 200, { collections: await db.list() });
    if (url.pathname === '/api/import' && request.method === 'POST') {
      const input = await body(request); collectionName(input.collection, input.dtype);
      if (!['batch', 'each'].includes(input.refreshPolicy ?? 'batch')) throw bad('Invalid refresh policy');
      const writeBatchSize = input.writeBatchSize ?? 32;
      if (!Number.isInteger(writeBatchSize) || writeBatchSize < 1 || writeBatchSize > 32) throw bad('writeBatchSize must be 1-32');
      return json(response, 200, await db.ingest(input.collection, input.dtype, documents(input.documents), input.refreshPolicy ?? 'batch', writeBatchSize));
    }
    if (url.pathname === '/api/search' && request.method === 'POST') { const input = await body(request); collectionName(input.collection, input.dtype); return json(response, 200, await db.search(input.collection, input.dtype, queryInput(input))); }
    if (url.pathname.startsWith('/api/')) throw bad('API not found', 404);
    if (!['GET', 'HEAD'].includes(request.method)) throw bad('Method not allowed', 405);
    const decoded = decodeURIComponent(url.pathname);
    let directory = path.join(root, 'dist'), relative = decoded === '/' ? 'index.html' : decoded.slice(1);
    if (decoded.startsWith('/models/')) { directory = path.join(root, 'models'); relative = decoded.slice(8); }
    if (decoded === '/data/corpus.json') { directory = path.join(root, 'data'); relative = 'corpus.json'; }
    const filename = path.resolve(directory, relative);
    if (!filename.startsWith(`${directory}${path.sep}`)) throw bad('Invalid path', 403);
    const info = await stat(filename).catch(() => { throw bad('File missing: build app and download models first', 404); });
    if (!info.isFile()) throw bad('File missing', 404);
    response.writeHead(200, { 'Content-Type': mime[path.extname(filename)] ?? 'application/octet-stream', 'Content-Length': info.size, 'Cache-Control': decoded.startsWith('/models/') || decoded.startsWith('/vendor/') ? 'public, max-age=31536000, immutable' : 'no-cache' });
    if (request.method === 'HEAD') return response.end();
    createReadStream(filename).on('error', () => response.destroy()).pipe(response);
  } catch (error) {
    const status = error.status ?? 500;
    if (status >= 500) console.error('Request failed:', error.code ?? error.name, String(error.message).replaceAll(process.env.SEEKDB_PASSWORD || '\u0000', '[redacted]'));
    if (!response.headersSent) json(response, status, { error: status >= 500 ? 'Database/runtime error; check local server log' : error.message }); else response.destroy();
  }
});
server.listen(port, host, () => console.log(`StepFun: ${base}; database=${db.database}; no server embedding`));
async function shutdown() { server.close(); await db.close(); process.exit(0); }
process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown);
