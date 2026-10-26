// The list's rows and cells (page/row.js), and where the data is from
// (page/sources.js), as HTML. Run:
// node --test tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { buildCell, githubLinks, rowHtml, versionCell } from '../../page/row.js';
import { sourcesHtml } from '../../page/sources.js';
import { store } from '../../page/store.js';

// No browser: what's read of one at call time (a row's links read the page's
// address), not when the modules load.
globalThis.location = { pathname: '/', search: '', href: 'https://nixkeeper.test/' };

// The visible text of some HTML, its tags removed until none is left.
const text = (markup) => {
  let out = String(markup);
  for (let was = null; was !== out; ) {
    was = out;
    out = out.replace(/<[^>]*>/g, '');
  }
  return out.replace(/&#39;/g, "'").replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim();
};

store.checkedAt = '2026-10-24T09:00:00Z';
const tgrep = {
  name: 'tgrep',
  nixStatus: 'outdated',
  nixVersion: '1.1.0',
  refVersion: '1.2.4',
  platforms: { linux: true, darwin: true },
  builds: [
    { attr: 'tgrep', system: 'x86_64-linux', status: 'failed', build: 1, failedBecause: 'tests' },
    { attr: 'tgrep', system: 'aarch64-darwin', status: 'ok', build: 2 },
  ],
  openPRs: 2,
  openIssues: 0,
  searchTerm: 'tgrep',
};

describe('a row', () => {
  test('its name, versions and builds, at its place in the list', () => {
    const row = String(rowHtml(tgrep, 7));
    assert.match(row, /data-i="7"/);
    assert.match(text(row), /tgrep/);
    assert.match(text(row), /1\.1\.0/);
  });
  test("the version cell: nixpkgs' and the newest", () => {
    const said = text(versionCell(tgrep, 'warn'));
    assert.match(said, /1\.1\.0/);
    assert.match(said, /1\.2\.4/);
  });
  test('the build cell says why it fails', () => {
    assert.match(text(buildCell(tgrep)), /tests/);
  });
  test('GitHub: only the counts above 0', () => {
    const said = text(githubLinks(tgrep));
    assert.match(said, /2/);
    assert.equal(text(githubLinks({ ...tgrep, openPRs: 0 })), '—');
  });
});

describe('where the data is from', () => {
  test('on nixkeeper.com, the status page for every source; elsewhere, the list', () => {
    store.sources = { nixpkgs: { used: true, revision: '02c087f' }, versions: { used: true } };
    globalThis.location.hostname = 'nixkeeper.com';
    const there = String(sourcesHtml());
    assert.match(there, /href="https:\/\/status\.nixkeeper\.com\/"/);
    globalThis.location.hostname = 'example.org';
    const elsewhere = String(sourcesHtml());
    assert.doesNotMatch(elsewhere, /status\.nixkeeper\.com/);
    assert.ok(elsewhere.length > there.length);
  });
});
