export const DIMENSION = 384;
export const MODEL = 'Xenova/all-MiniLM-L6-v2';
export function bad(message, status = 400) { return Object.assign(new Error(message), { status }); }
export function collectionName(name, dtype) {
  if (!/^[a-z][a-z0-9_]{0,31}$/.test(name ?? '')) throw bad('Invalid collection: use 1-32 lowercase letters, digits or underscore');
  if (!['fp32', 'q8'].includes(dtype)) throw bad('dtype must be fp32 or q8');
  return `stepfun_${name}_${dtype}`;
}
export function vector(value) {
  if (!Array.isArray(value) || value.length !== DIMENSION || !value.every(Number.isFinite)) throw bad('Expected 384 finite numbers');
  const norm = Math.sqrt(value.reduce((sum, item) => sum + item * item, 0));
  if (Math.abs(norm - 1) > 0.02) throw bad('Vector must be L2 normalized');
  return value;
}
export function documents(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 200) throw bad('Expected 1-200 chunks');
  const seen = new Set();
  return value.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw bad('Expected document object');
    if (typeof item.text !== 'string' || !item.text.trim() || item.text.length > 12000) throw bad('Invalid document length');
    if (typeof item.id !== 'string' || !/^[a-zA-Z0-9_.:-]{1,128}$/.test(item.id) || seen.has(item.id)) throw bad('Invalid or duplicate document ID');
    seen.add(item.id);
    return { id: item.id, text: item.text, title: String(item.title ?? item.id).slice(0, 160), embedding: vector(item.embedding) };
  });
}
export function queryInput(body) {
  if (typeof body.query !== 'string' || !body.query.trim() || body.query.length > 2000) throw bad('Invalid query');
  const topK = body.topK ?? 5;
  if (!Number.isInteger(topK) || topK < 1 || topK > 20) throw bad('topK must be 1-20');
  return { query: body.query, embedding: vector(body.embedding), topK };
}
export function createQueue() {
  let pending = Promise.resolve();
  return action => { const result = pending.then(action); pending = result.catch(() => {}); return result; };
}
