// How the page reads its data (page/data.js), with fetch, the address and
// the document stood in for. Run: node --test tests/js/ (part of `nix flake
// check`, as checks.page).

import assert from 'node:assert/strict';
import { test } from 'node:test';

// The data's files, by URL, and what was asked for.
const files = new Map();
const asked = [];
globalThis.location = {
  href: 'https://nixkeeper.test/',
  origin: 'https://nixkeeper.test',
  search: '?data=/data',
};
globalThis.document = { querySelector: () => null };
globalThis.fetch = async (url, options) => {
  asked.push(url);
  assert.equal(options.cache, 'no-store');
  const body = files.get(url);
  if (body instanceof Error) throw body;
  return body === undefined
    ? { ok: false, status: 404 }
    : body === 500
      ? { ok: false, status: 500 }
      : { ok: true, status: 200, json: async () => structuredClone(body) };
};

const { dataUrl, fullRowOf, locateData, readJson } = await import('../../page/data.js');
const at = (path) => `https://nixkeeper.test/data/${path}`;

test('the data where ?data= says, on the same site', async () => {
  assert.equal(await locateData(), 'https://nixkeeper.test/data/');
  assert.equal(dataUrl('views/merge.json'), at('views/merge.json'));
});

test('a file as JSON, or its stand-in', async () => {
  files.set(at('index.json'), { format: 2 });
  assert.deepEqual(await readJson('index.json'), { format: 2 });
  // Optional: any failure gives the stand-in.
  files.set(at('history.json'), 500);
  assert.deepEqual(await readJson('history.json', { otherwise: { points: [] } }), { points: [] });
  assert.equal(await readJson('facets.json', { otherwise: null }), null);
  // A view: only a missing one is empty; another failure throws.
  assert.deepEqual(await readJson('views/team/none.json', { missing: { packages: [] } }), {
    packages: [],
  });
  files.set(at('views/attention.json'), 500);
  await assert.rejects(readJson('views/attention.json', { missing: { packages: [] } }), /500/);
  await assert.rejects(readJson('summary.json'), /404/);
});

test("a package's full row, its shard loaded once", async () => {
  // Shard 0 of 1: every name.
  files.set(at('rows/0.json'), { packages: [{ name: 'tgrep', nixVersion: '1.1.0' }] });
  const before = asked.length;
  const stamped = (row) => ({ ...row, stamped: true });
  const row = await fullRowOf('tgrep', 1, stamped);
  assert.deepEqual(row, { name: 'tgrep', nixVersion: '1.1.0', stamped: true });
  // The same row again, without asking again.
  assert.equal(await fullRowOf('tgrep', 1, stamped), row);
  assert.equal(await fullRowOf('gone', 1, stamped), null);
  assert.equal(asked.length - before, 1);
});

test('a shard that failed is asked for again', async () => {
  files.set(at('rows/1.json'), new Error('offline'));
  // shardOf('atuin', 2) === 1 (crc32 % 2).
  assert.equal(await fullRowOf('atuin', 2), null);
  files.set(at('rows/1.json'), { packages: [{ name: 'atuin' }] });
  assert.deepEqual(await fullRowOf('atuin', 2), { name: 'atuin' });
});
