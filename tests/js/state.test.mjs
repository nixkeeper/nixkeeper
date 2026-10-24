// The page's address and its state (page/state.js): read, then written
// back. Run: node --test tests/js/ (part of `nix flake check`, as
// checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  DEFAULT_PAGE_SIZE,
  known,
  readState,
  scopeHref,
  state,
  writeState,
} from '../../page/state.js';

// The page's tables, as far as the address goes (app.js has their rules).
const KNOWN = {
  FILTERS: { all: {}, builds: { param: 'builds' }, vuln: { param: 'vuln' } },
  SORTS: { pressing: 'most pressing', oldest: 'longest-standing' },
  PLATFORMS: { linux: { param: 'linux' }, darwin: { param: 'darwin', also: 'macos' } },
  REFINES: { withpr: {}, notbroken: {} },
  AGES: { '1y': 'a year' },
};
const read = (query) => readState(new URLSearchParams(query), KNOWN);
const written = (query, params = '') => {
  const { state: st, query: search } = read(query);
  return writeState(st, search, new URLSearchParams(params), KNOWN);
};

describe('readState', () => {
  test('an empty address is the default state', () => {
    const { state: st, query } = read('');
    assert.equal(query, '');
    assert.deepEqual(st, state);
    assert.equal(st.pageSize, DEFAULT_PAGE_SIZE);
  });
  test('each parameter', () => {
    const { state: st, query } = read(
      '?filter=builds&q=wine&sort=oldest&order=reverse&platform=macos&team=gaming&refine=withpr,notbroken&age=1y&buildFailed=compile&in=python313Packages&by=@Alice&newer=no&errors=1&page=3&per=50',
    );
    assert.equal(query, 'wine');
    assert.equal(st.activeFilter, 'builds');
    assert.equal(st.sortMode, 'oldest');
    assert.equal(st.sortReverse, true);
    assert.equal(st.platformFilter, 'darwin'); // ?platform=macos, its other name
    assert.equal(st.teamFilter, 'gaming');
    assert.deepEqual([...st.refines], ['withpr', 'notbroken']);
    assert.equal(st.ageFilter, '1y');
    assert.equal(st.buildFailedFilter, 'compile');
    assert.equal(st.inFilter, 'python313Packages');
    assert.equal(st.byFilter, 'alice');
    assert.equal(st.newerFilter, 'no');
    assert.equal(st.showErrors, true);
    assert.equal(st.pageNum, 3);
    assert.equal(st.pageSize, 50);
  });
  test('unknown values left out', () => {
    const { state: st } = read(
      '?filter=nope&sort=nope&platform=nope&refine=nope&age=9y&per=7&page=-2&cause=xyz',
    );
    assert.deepEqual(st, state);
  });
  test('old addresses still read', () => {
    // ?because= before ?updateFailed= (2026-10-08); refine=direct before
    // ?team=none; ?q=@handle before ?maintainer=.
    assert.equal(read('?because=patch').state.becauseFilter, 'patch');
    assert.equal(read('?refine=direct').state.noTeam, true);
    assert.equal(read('?q=@alice').query, '@alice');
  });
});

describe('writeState', () => {
  test('an address written back as it was read', () => {
    for (const query of [
      '',
      '?filter=builds&platform=darwin',
      '?maintainer=alice',
      '?q=wine&sort=oldest&order=reverse&refine=withpr,notbroken&page=3&per=50',
      '?filter=vuln&team=gaming&age=1y&buildFailed=compile&in=python313Packages&by=alice&newer=no&errors=1',
    ])
      assert.equal(written(query), query);
  });
  test('old names written as the new ones', () => {
    assert.equal(written('?because=patch'), '?updateFailed=patch');
    assert.equal(written('?q=@alice'), '?maintainer=alice');
    assert.equal(written('?refine=direct'), '?team=none');
  });
  test("the address's other parameters kept", () => {
    assert.equal(
      written('?filter=builds', 'owner=me&repo=lists'),
      '?owner=me&repo=lists&filter=builds',
    );
  });
  test('the page asked for, the first left out', () => {
    const { state: st } = read('?page=3');
    assert.equal(writeState(st, '', new URLSearchParams(), KNOWN, 1), '');
    assert.equal(writeState(st, '', new URLSearchParams(), KNOWN, 4), '?page=4');
  });
});

describe('scopeHref', () => {
  test("a view's address: the others' parameters cleared, the data's own kept", () => {
    Object.assign(known, KNOWN);
    globalThis.location = { pathname: '/', search: '?owner=me&filter=vuln&q=wine&page=3&per=50' };
    assert.equal(
      scopeHref({ view: 'attention', filter: 'builds' }),
      '/?owner=me&per=50&view=attention&filter=builds',
    );
    assert.equal(scopeHref({ pkg: 'tgrep' }), '/?owner=me&per=50&pkg=tgrep');
    // A filter with no address of its own (all): none written.
    assert.equal(scopeHref({ filter: 'all' }), '/?owner=me&per=50');
  });
});
