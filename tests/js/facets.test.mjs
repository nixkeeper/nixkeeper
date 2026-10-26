// The names index's facets (page/facets.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  crc32,
  decodeFacets,
  facetCounts,
  familyLabel,
  foldFamilies,
  inPickedSet,
  matchFacets,
  nameSet,
  shardOf,
} from '../../page/facets.js';

describe('shards', () => {
  // The same as Python's zlib.crc32 (nixkeeper/naming.py), or a panel
  // would look for a package in the wrong shard.
  test('crc32 matches zlib', () => {
    assert.equal(crc32(''), 0);
    assert.equal(crc32('wesnoth'), 3265293464);
    assert.equal(crc32('python3.13-ï'), 2328554205); // UTF-8 bytes
  });
  test('shardOf', () => {
    assert.equal(shardOf('pkg0', 4), 1);
    assert.equal(shardOf('wesnoth', 1), 0);
  });
});

describe('foldFamilies', () => {
  const pkg = (name, extra = {}) => ({
    name,
    family: 'f1',
    nixStatus: 'outdated',
    refVersion: '3.1.218',
    ...extra,
  });
  test('three or more alike are one row, the first; open shows them after it', () => {
    const list = [pkg('sdk-a'), pkg('other', { family: null }), pkg('sdk-b'), pkg('sdk-c')];
    const { list: out, folds, inOpen } = foldFamilies(list);
    assert.deepEqual(
      out.map((p) => p.name),
      ['sdk-a', 'other'],
    );
    const fold = folds.get('sdk-a');
    assert.equal(fold.members.length, 3);
    assert.equal(fold.open, false);
    assert.equal(inOpen.size, 0);
    const opened = foldFamilies(list, () => '', new Set([fold.key]));
    assert.deepEqual(
      opened.list.map((p) => p.name),
      ['sdk-a', 'sdk-b', 'sdk-c', 'other'],
    );
    assert.deepEqual([...opened.inOpen], ['sdk-b', 'sdk-c']);
  });
  test('not when fewer, or unlike in status, target or key', () => {
    assert.equal(foldFamilies([pkg('a'), pkg('b')]).list.length, 2);
    const list = [
      pkg('a'),
      pkg('b'),
      pkg('c', { refVersion: '3.1.219' }),
      pkg('d', { nixStatus: 'newest' }),
    ];
    assert.equal(foldFamilies(list).list.length, 4);
    // a, b and c alike but for the key (the dot): c is its own.
    const three = [pkg('a'), pkg('b'), pkg('c', { bad: true })];
    assert.equal(foldFamilies(three, (p) => (p.bad ? 'bad' : 'ok')).list.length, 3);
    assert.equal(foldFamilies(three).list.length, 1);
  });
});

describe('familyLabel', () => {
  test('the shared end, else the common start and a star', () => {
    assert.equal(
      familyLabel(['linuxPackages.mbp2018-bridge-drv', 'linuxPackages_6_1.mbp2018-bridge-drv']),
      'mbp2018-bridge-drv',
    );
    assert.equal(
      familyLabel(['python313Packages.huaweicloudsdkaad', 'python313Packages.huaweicloudsdkcce']),
      'python313Packages.huaweicloudsdk*',
    );
    assert.equal(familyLabel(['abc', 'xyz']), null);
  });
});

describe('nameSet', () => {
  test("the attribute's first part, or top-level", () => {
    assert.equal(nameSet('python313Packages.requests'), 'python313Packages');
    assert.equal(nameSet('vimPlugins.nvim-treesitter-parsers.lua'), 'vimPlugins');
    assert.equal(nameSet('ripgrep'), 'top-level');
  });
});

describe('facetCounts', () => {
  test('the most first, ties by name; several values each counted', () => {
    const list = [
      { maintainers: ['b', 'a'] },
      { maintainers: ['a'] },
      { maintainers: [] },
      { maintainers: ['C'] },
    ];
    assert.deepEqual(
      facetCounts(list, (p) => p.maintainers),
      [
        ['a', 2],
        ['b', 1],
        ['C', 1],
      ],
    );
    assert.deepEqual(
      facetCounts([{ n: 'x' }, { n: null }], (p) => p.n),
      [['x', 1]],
    );
  });
});

describe('matchFacets', () => {
  const matches = [
    ['ripgrep', 'u'],
    ['ripgrep-all', 'o'],
    ['emacsPackages.ripgrep', 'fv'],
    ['vimPlugins.blink-ripgrep-nvim', 'u'],
  ];
  test('counts each facet with the other picked', () => {
    const all = matchFacets(matches);
    assert.equal(all.kept.length, 4);
    assert.deepEqual(all.sets, [
      ['top-level', 2],
      ['emacsPackages', 1],
      ['vimPlugins', 1],
    ]);
    assert.deepEqual(all.statuses, [
      ['failing', 1],
      ['outdated', 1],
      ['uptodate', 2],
      ['vulnerable', 1],
    ]);
    const upToDate = matchFacets(matches, { status: 'uptodate' });
    assert.deepEqual(
      upToDate.kept.map(([n]) => n),
      ['ripgrep', 'vimPlugins.blink-ripgrep-nvim'],
    );
    assert.deepEqual(upToDate.sets, [
      ['top-level', 1],
      ['vimPlugins', 1],
    ]);
    const top = matchFacets(matches, { set: 'top-level', status: 'vulnerable' });
    assert.equal(top.kept.length, 0);
    assert.deepEqual(top.statuses, [
      ['outdated', 1],
      ['uptodate', 1],
    ]);
  });
});

describe('decodeFacets and matchFacets with facets', () => {
  const names = [
    ['ripgrep', 'u'],
    ['ripgrep-all', 'o'],
    ['emacsPackages.ripgrep', 'fv'],
  ];
  const facets = decodeFacets({
    handles: ['Iedame', 'someone'],
    teams: ['Gaming'],
    rows: [[7, [0], [0]], 1, [4, [1]]],
  });
  test('decoded beside names, handles lowercase', () => {
    assert.deepEqual(facets[0], { bits: 7, handles: ['iedame'], teams: ['Gaming'] });
    assert.deepEqual(facets[1], { bits: 1, handles: [], teams: [] });
  });
  const of = (e) => facets[names.indexOf(e)];
  test('by, team and platform, each counted with the others', () => {
    const all = matchFacets(names, {}, of);
    assert.deepEqual(all.by, [
      ['iedame', 1],
      ['someone', 1],
    ]);
    assert.deepEqual(all.teams, [['Gaming', 1]]);
    assert.deepEqual(all.platforms, { linux: 2, 'x86_64-linux': 2, 'aarch64-linux': 1, darwin: 2 });
    const darwin = matchFacets(names, { platform: 'darwin' }, of);
    assert.deepEqual(
      darwin.kept.map(([n]) => n),
      ['ripgrep', 'emacsPackages.ripgrep'],
    );
    assert.deepEqual(darwin.platforms.darwin, 2); // its own left out
    const mine = matchFacets(names, { by: 'iedame', platform: 'darwin' }, of);
    assert.deepEqual(
      mine.kept.map(([n]) => n),
      ['ripgrep'],
    );
    assert.deepEqual(mine.sets, [['top-level', 1]]);
  });
  test('while facets.json loads, its filters keep everything', () => {
    assert.equal(matchFacets(names, { by: 'iedame' }).kept.length, 3);
  });
});

describe('inPickedSet', () => {
  test('python3Packages picks any python3xPackages', () => {
    assert.equal(inPickedSet('python313Packages', 'python3Packages'), true);
    assert.equal(inPickedSet('python314Packages', 'python3Packages'), true);
    assert.equal(inPickedSet('python313Packages', 'python313Packages'), true);
    assert.equal(inPickedSet('python313Packages', 'perl5Packages'), false);
    assert.equal(inPickedSet('pythonPackages', 'python3Packages'), false);
  });
});
