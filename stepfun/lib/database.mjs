import { SeekdbClient, Schema, FulltextIndexConfig, VectorIndexConfig } from 'seekdb';
import { collectionName, createQueue, DIMENSION, bad, MODEL } from './core.mjs';
export async function connectDatabase() {
  const database = process.env.SEEKDB_DATABASE ?? 'stepfun_kb';
  if (!/^stepfun_[a-z0-9_]+$/.test(database)) throw bad('Only a dedicated stepfun_ database is permitted', 500);
  const config = { host: process.env.SEEKDB_HOST ?? '127.0.0.1', port: Number(process.env.SEEKDB_PORT ?? 2881), user: process.env.SEEKDB_USER ?? 'root', password: process.env.SEEKDB_PASSWORD ?? '', queryTimeout: 60000 };
  const admin = new SeekdbClient({ ...config, database: 'information_schema' });
  try { await admin.execute(`CREATE DATABASE IF NOT EXISTS \`${database}\``); } finally { await admin.close(); }
  const client = new SeekdbClient({ ...config, database });
  const serial = createQueue();
  const version = await client.execute('SELECT VERSION() AS version');
  const cache = new Map();
  async function get(name, dtype, create = false) {
    const physical = collectionName(name, dtype);
    if (cache.has(physical)) return cache.get(physical);
    let collection;
    if (await client.hasCollection(physical)) collection = await client.getCollection({ name: physical, embeddingFunction: null });
    else if (create) collection = await client.createCollection({ name: physical, schema: new Schema({ fulltextIndex: new FulltextIndexConfig('space'), vectorIndex: new VectorIndexConfig({ hnsw: { dimension: DIMENSION, distance: 'cosine' }, embeddingFunction: null }) }), embeddingFunction: null });
    else throw bad('Import documents into this collection/precision first', 404);
    cache.set(physical, collection);
    return collection;
  }
  return {
    database, version: version?.[0]?.version,
    list: () => serial(async () => {
      const collections = await client.listCollections({ withEmbeddingFunction: false });
      return Promise.all(collections.filter(item => item.name.startsWith('stepfun_')).map(async item => ({ name: item.name, count: Number(await item.count()) })));
    }),
    ingest: (name, dtype, docs, refreshPolicy, writeBatchSize = 32) => serial(async () => {
      const collection = await get(name, dtype, true);
      const started = performance.now();
      let writeMs = 0, refreshMs = 0;
      const batchSize = writeBatchSize;
      for (let offset = 0; offset < docs.length; offset += batchSize) {
        const batch = docs.slice(offset, offset + batchSize);
        const beforeWrite = performance.now();
        await collection.upsert({ ids: batch.map(doc => doc.id), documents: batch.map(doc => doc.text), embeddings: batch.map(doc => doc.embedding), metadatas: batch.map(doc => ({ title: doc.title, model: MODEL, dtype })) });
        writeMs += performance.now() - beforeWrite;
        if (refreshPolicy === 'each') { const before = performance.now(); await collection.refresh_index(); refreshMs += performance.now() - before; }
      }
      if (refreshPolicy !== 'each') { const before = performance.now(); await collection.refresh_index(); refreshMs += performance.now() - before; }
      return { accepted: docs.length, count: Number(await collection.count()), writeMs, refreshMs, totalMs: performance.now() - started, refreshPolicy, writeBatchSize, refreshCalls: refreshPolicy === 'each' ? Math.ceil(docs.length / batchSize) : 1 };
    }),
    search: (name, dtype, input) => serial(async () => {
      const collection = await get(name, dtype);
      const started = performance.now();
      const result = await collection.hybridSearch({ query: { whereDocument: { $contains: input.query } }, knn: { queryEmbeddings: [input.embedding], nResults: Math.max(20, input.topK) }, rank: { rrf: { rankConstant: 60, rankWindowSize: 50 } }, nResults: input.topK, include: ['documents', 'metadatas', 'distances'] });
      return { databaseMs: performance.now() - started, engine: 'seekdb.hybridSearch / DBMS_HYBRID_SEARCH / server-side RRF', results: (result.ids?.[0] ?? []).map((id, index) => ({ id, text: result.documents?.[0]?.[index], metadata: result.metadatas?.[0]?.[index], score: result.distances?.[0]?.[index] })) };
    }),
    close: () => serial(() => client.close()),
  };
}
