// A maintainer's or team's page (page/maintainer-view.js): You can merge
// these, Can be closed, the page of every maintainer. Run: node --test
// tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

globalThis.location = { pathname: '/', search: '', href: 'https://nixkeeper.test/' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { closeHtml, maintainerItem, maintainerView, mergeHtml } = await import(
  '../../page/maintainer-view.js'
);
const { store } = await import('../../page/store.js');

// The visible text of some HTML, its tags removed until none is left.
const text = (markup) => {
  let out = String(markup);
  for (let was = null; was !== out; ) {
    was = out;
    out = out.replace(/<[^>]*>/g, '');
  }
  return out.replace(/&#39;/g, "'").replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim();
};

describe('You can merge these', () => {
  const pr = (n, author, who) => ({
    number: n,
    title: `pkg${n}: 1 -> 2`,
    author,
    who,
    packages: [`pkg${n}`],
    created: '2026-10-20T00:00:00Z',
  });
  test('only on a maintainer or team page, loading the PRs first', () => {
    let asked = 0;
    store.mergeList = null;
    assert.equal(String(mergeHtml('views/attention.json', null, () => asked++)), '');
    assert.equal(String(mergeHtml('views/maintainer/alice.json', 'alice', () => asked++)), '');
    assert.equal(asked, 1);
  });
  test('their own PR first, then the others they can merge, the first few', () => {
    store.mergeList = [
      pr(1, 'bob', ['alice']),
      pr(2, 'alice', ['alice']),
      pr(3, 'carol', ['dave']),
    ];
    const said = text(mergeHtml('views/maintainer/alice.json', 'alice', () => {}));
    assert.match(said, /You can merge these 2 PRs/);
    assert.ok(said.indexOf('pkg2: 1 -> 2') < said.indexOf('pkg1: 1 -> 2'));
    assert.doesNotMatch(said, /pkg3/);
    assert.match(said, /your own PR/);
    assert.equal(maintainerView.mergeAll, false);
  });
});

describe('Can be closed', () => {
  test("a maintainer's packages' PRs nixpkgs is past, init ones too", () => {
    store.packages = [
      {
        name: 'macshot',
        supersededPRs: [
          {
            number: 506894,
            title: 'macshot: init at 4.0.4',
            author: 'Myzel394',
            created: '2026-04-05T08:23:13Z',
            now: '4.1.2',
            init: true,
          },
        ],
      },
    ];
    const said = text(closeHtml('views/maintainer/gaetanlepage.json', 'GaetanLepage'));
    assert.match(said, /This init PR can be closed nixpkgs has the package they add now/);
    assert.match(said, /nixpkgs has it now \(4\.1\.2\), added another way/);
    assert.equal(String(closeHtml('views/attention.json', null)), '');
  });
});

describe('the page of every maintainer', () => {
  test('a maintainer, linked to their page, with their counts', () => {
    const item = String(maintainerItem(['alice', 12, 3, 0]));
    assert.match(item, /href="\/\?maintainer=alice" data-maintainer="alice">@alice/);
    assert.match(text(item), /@alice12 packages · 3 outdated/);
  });
});
