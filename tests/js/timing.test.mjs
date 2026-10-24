// The redraw timer (page/timing.js): off, it does nothing; on, it logs each
// part. Run: node --test tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.location = { search: '' };
const { timer } = await import('../../page/timing.js');

test('off without ?debug=timing: nothing logged', () => {
  const logged = [];
  const t = timer('update', { log: (line) => logged.push(line) });
  t.lap('filter');
  t.done();
  assert.deepEqual(logged, []);
});

test('on: each part, in order, and the whole', () => {
  const logged = [];
  const t = timer('update', { enabled: true, log: (line) => logged.push(line) });
  t.lap('view');
  t.lap('filter');
  t.done();
  assert.equal(logged.length, 1);
  assert.match(logged[0], /^update \d+ ms: view \d+, filter \d+$/);
});
