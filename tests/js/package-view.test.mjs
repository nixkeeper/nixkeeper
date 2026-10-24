// A package's panel (page/package-view.js): the parts that are HTML from a
// package (filling the panel itself needs a page). Run: node --test
// tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { hideButton, queueHtml, stagingNextBlockedNote } from '../../page/package-view.js';
import { store } from '../../page/store.js';

// The visible text of some HTML, its tags removed until none is left.
const text = (markup) => {
  let out = String(markup);
  for (let was = null; was !== out; ) {
    was = out;
    out = out.replace(/<[^>]*>/g, '');
  }
  return out.replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim();
};

describe('hideButton', () => {
  test('only with something to hide, or hidden already', () => {
    assert.equal(String(hideButton(false, false)), '');
    assert.equal(text(hideButton(false, true)), 'Hide until it changes');
    assert.equal(text(hideButton(true, false)), 'Show it again');
  });
});

describe('stagingNextBlockedNote', () => {
  // A build stopped on staging-next by a failing dependency, one nixkeeper
  // has a row for (linked) and one it hasn't.
  const pkg = {
    stagingNextBlockedBy: {
      eval: 1830329,
      builds: [{ system: 'x86_64-linux', by: [{ name: 'libfoo', row: true }, { name: 'source' }] }],
    },
  };
  test("the blockers, a package linked by the page's address for it", () => {
    const [note] = stagingNextBlockedNote(pkg, (name) => `/?pkg=${name}`);
    assert.match(String(note), /href="\/\?pkg=libfoo" data-scope-pkg="libfoo">libfoo<\/a>/);
    assert.doesNotMatch(String(note), /pkg=source/);
    assert.match(
      text(note),
      /its build \(x86_64-linux\) is stopped by libfoo, source, failing there/,
    );
  });
  test('nothing for a package not stopped there', () => {
    assert.deepEqual(
      stagingNextBlockedNote({}, () => ''),
      [],
    );
  });
});

describe('queueHtml', () => {
  test("only when the bot's queue is read", () => {
    store.sources = null;
    assert.equal(String(queueHtml({ name: 'p' })), '');
    store.sources = { queue: { used: true } };
    assert.match(text(queueHtml({ name: 'p' })), /Not in nixpkgs-update's queue ↗/);
    store.sources = null;
  });
});
