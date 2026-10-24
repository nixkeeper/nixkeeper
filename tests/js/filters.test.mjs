// What the list keeps (page/filters.js): the tiles' filters, the refines,
// the platforms, and the list worked out and put in order. Run: node --test
// tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

const search = { value: '' };
globalThis.document = { getElementById: () => search };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { currentFiltered, FILTERS, filtering, inList, inPlatform, sortedList } = await import(
  '../../page/filters.js'
);
const { readState, state } = await import('../../page/state.js');
const { KNOWN } = await import('../../page/filters.js');
const { store } = await import('../../page/store.js');

// A package: up to date, or outdated, or failing to build on a system.
const pkg = (name, fields = {}) => ({ name, nixStatus: 'newest', ...fields });
const outdated = (name, fields = {}) =>
  pkg(name, { nixStatus: 'outdated', nixVersion: '1.0', refVersion: '1.1', ...fields });
const failing = (name, system, fields = {}) =>
  pkg(name, { builds: [{ system, status: 'failed', build: 1 }], ...fields });

// The state an address says, as the page reads it.
const at = (query) => {
  Object.assign(state, readState(new URLSearchParams(query), KNOWN).state);
  search.value = '';
};
beforeEach(() => at(''));

describe("the tiles' filters", () => {
  test('outdated and build failures', () => {
    assert.equal(FILTERS.warn.test(outdated('a')), true);
    assert.equal(FILTERS.warn.test(pkg('b')), false);
    assert.equal(FILTERS.builds.test(failing('c', 'x86_64-linux')), true);
    assert.equal(FILTERS.builds.test(pkg('d')), false);
  });
  test('build failures on the platform picked', () => {
    at('?platform=darwin');
    assert.equal(FILTERS.builds.test(failing('c', 'x86_64-linux')), false);
    assert.equal(FILTERS.builds.test(failing('c', 'aarch64-darwin')), true);
  });
});

describe('what a list keeps', () => {
  test('a list from package-lists/, by its name', () => {
    at('?list=gaming-team');
    assert.equal(inList(pkg('a', { lists: ['gaming-team'] })), true);
    assert.equal(inList(pkg('b', { lists: ['maintained'] })), false);
  });
  test('a platform: the packages available there', () => {
    at('?platform=linux');
    assert.equal(inPlatform(pkg('a', { platforms: { linux: true } })), true);
    assert.equal(inPlatform(pkg('b', { platforms: { darwin: true } })), false);
  });
});

describe('the list worked out', () => {
  test("the tile's packages, what the facets count over kept", () => {
    store.packages = [outdated('b'), pkg('a'), outdated('c')];
    at('?filter=outdated&sort=az');
    assert.deepEqual(
      currentFiltered().map((p) => p.name),
      ['b', 'c'],
    );
    assert.deepEqual(
      filtering.facetBase.map((p) => p.name),
      ['b', 'c'],
    );
  });
  test('by name, either way', () => {
    at('?sort=az');
    const list = [pkg('a'), pkg('b')];
    assert.deepEqual(
      sortedList(list, -1).map((p) => p.name),
      ['b', 'a'],
    );
  });
});
