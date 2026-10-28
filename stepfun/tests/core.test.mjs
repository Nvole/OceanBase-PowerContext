import test from 'node:test';
import assert from 'node:assert/strict';
import { collectionName, documents, queryInput, vector, createQueue } from '../lib/core.mjs';

const unit = Array.from({ length: 384 }, (_, index) => index === 0 ? 1 : 0);

test('validates normalized vectors and collection names', () => {
  assert.deepEqual(vector(unit), unit);
  assert.equal(collectionName('demo', 'q8'), 'stepfun_demo_q8');
  assert.throws(() => collectionName('Bad', 'q8'));
  assert.throws(() => vector([1, 2]));
});

test('validates documents and query payloads', () => {
  const docs = documents([{ id: 'a:0', title: 'A', text: 'safe text', embedding: unit }]);
  assert.equal(docs[0].id, 'a:0');
  assert.equal(queryInput({ query: 'hello', embedding: unit, topK: 5 }).topK, 5);
  assert.throws(() => documents([{ id: 'a:0', text: 'x', embedding: unit }, { id: 'a:0', text: 'y', embedding: unit }]));
  assert.throws(() => documents([null]), /Expected document object/);
});

test('serial queue preserves order after a rejected action', async () => {
  const queue = createQueue();
  const order = [];
  await assert.rejects(queue(async () => { order.push('first'); throw new Error('expected'); }));
  await queue(async () => order.push('second'));
  assert.deepEqual(order, ['first', 'second']);
});
