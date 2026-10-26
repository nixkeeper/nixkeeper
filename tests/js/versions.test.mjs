// Comparing versions (page/versions.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { comparedRepos, compareVersions, versionDiff, versionGap } from '../../page/versions.js';

describe('compareVersions', () => {
  test('numbers as numbers', () => {
    assert.equal(compareVersions('1.10', '1.9'), 1);
    assert.equal(compareVersions('1.9', '1.10'), -1);
    assert.equal(compareVersions('2.4.3', '2.4.3'), 0);
  });
  test('a letter part sorts before a number', () => {
    assert.equal(compareVersions('1.0rc1', '1.0.1'), -1);
    assert.equal(compareVersions('1.0.1', '1.0rc1'), 1);
  });
  test('a longer version is newer', () => {
    assert.equal(compareVersions('1.0', '1.0.1'), -1);
    assert.equal(compareVersions('1.0.1', '1.0'), 1);
  });
  test('unstable dates compare by date', () => {
    assert.equal(compareVersions('0-unstable-2026-08-22', '0-unstable-2026-09-01'), -1);
  });
  test("nixpkgs' unstable snapshots come after their version", () => {
    assert.equal(compareVersions('1.2-unstable-2025-05-01', '1.2'), 1);
    assert.equal(compareVersions('1.3', '1.2-unstable-2025-05-01'), 1);
    assert.equal(compareVersions('0-unstable-2022-07-13', '0'), 1);
    assert.equal(compareVersions('0.37-unstable-2026-06-03', '0.37'), 1);
    assert.equal(compareVersions('0.0.1', '0-unstable-2023-04-26'), 1);
    assert.equal(compareVersions('0.0.1', 'unstable-2023-04-26'), 1);
    assert.equal(compareVersions('unstable-2023-04-26', '0-unstable-2023-04-26'), 0);
  });
  test('a pre-release before its release; a trailing zero changes nothing', () => {
    assert.equal(compareVersions('1.0rc1', '1.0'), -1);
    assert.equal(compareVersions('2.0.0-beta.1', '2.0.0'), -1);
    assert.equal(compareVersions('1', '1.0'), 0);
    assert.equal(compareVersions('1.0RC1', '1.0rc1'), 0);
  });
  // Repology's test suite (tests/data/version-comparison-tests.txt, CC0):
  // its plain cases, as tests/test_versions.py reads them.
  test("Repology's version comparison test suite", () => {
    const text = readFileSync(
      new URL('../data/version-comparison-tests.txt', import.meta.url),
      'utf8',
    );
    let section = '';
    let count = 0;
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      if (line.startsWith('[')) {
        section = line;
        continue;
      }
      const m = /^"(.*)" ([a-z]*)([<=>])([a-z]*) "(.*)"$/.exec(line);
      if (!m || m[2] || m[4]) continue;
      const got = ['<', '=', '>'][compareVersions(m[1], m[5]) + 1];
      assert.equal(got, m[3], `${section} ${m[1]} ${m[3]} ${m[5]}`);
      count++;
    }
    assert.ok(count > 150);
  });
});

describe('versionDiff', () => {
  test('by whole parts', () => {
    assert.deepEqual(versionDiff('1.19.24', '1.19.28'), { same: '1.19.', from: '24', to: '28' });
    assert.deepEqual(versionDiff('1.9', '1.10'), { same: '1.', from: '9', to: '10' });
    assert.deepEqual(versionDiff('154.0.8037.57', '154.0.8037.92'), {
      same: '154.0.8037.',
      from: '57',
      to: '92',
    });
  });
  test('an unstable version: the date', () => {
    assert.deepEqual(versionDiff('5.1.0-b2-unstable-2022-11-14', '5.1.0-b2-unstable-2026-08-22'), {
      same: '5.1.0-b2-unstable-',
      from: '2022-11-14',
      to: '2026-08-22',
    });
  });
  test('nothing shared, or only something added', () => {
    assert.deepEqual(versionDiff('2.8', '3.0'), { same: '', from: '2.8', to: '3.0' });
    assert.deepEqual(versionDiff('1.2', '1.2.1'), { same: '1.2', from: '', to: '.1' });
  });
  test('a missing version', () => {
    assert.deepEqual(versionDiff('1.0', undefined), { same: '', from: '1.0', to: '' });
  });
});

describe('comparedRepos', () => {
  const e = (repo, version, status = 'outdated') => ({ repo, version, status });
  test('newest version first, ties by repository', () => {
    const sorted = comparedRepos([
      e('debian', '1.3.5'),
      e('homebrew', '1.3.8', 'newest'),
      e('aur', '1.3.8', 'newest'),
      e('fedora', '1.3.10'),
    ]);
    assert.deepEqual(
      sorted.map((x) => x.repo),
      ['fedora', 'aur', 'homebrew', 'debian'],
    );
  });
  test('one entry per repository, its newest', () => {
    const sorted = comparedRepos([
      e('alpine_edge', '1.3.7'),
      e('alpine_edge', '1.3.8', 'newest'),
      e('debian', '1.3.5'),
    ]);
    assert.deepEqual(
      sorted.map((x) => `${x.repo} ${x.version}`),
      ['alpine_edge 1.3.8', 'debian 1.3.5'],
    );
  });
  test("versions that don't compare go last", () => {
    const sorted = comparedRepos([e('gentoo', '9999', 'rolling'), e('aur', '1.0', 'newest')]);
    assert.deepEqual(
      sorted.map((x) => x.repo),
      ['aur', 'gentoo'],
    );
  });
  test("doesn't change its input", () => {
    const entries = [e('a', '1'), e('b', '2')];
    comparedRepos(entries);
    assert.equal(entries[0].repo, 'a');
  });
});

describe('versionGap', () => {
  test('a major update before a minor, a minor before a patch, bigger steps first', () => {
    assert.deepEqual(versionGap('2.8.2', '3.2.4'), { level: 0, step: 0.5, scheme: false });
    assert.deepEqual(versionGap('5.0.0', '5.0.1'), { level: 2, step: 1, scheme: false });
    assert.deepEqual(versionGap('1.2.0', '1.9.0'), { level: 1, step: 3.5, scheme: false });
    assert.deepEqual(versionGap('1.0', '1.0-rc2'), { level: 2, step: 1, scheme: false });
    assert.equal(versionGap('1.0', '1.0'), null);
    assert.equal(versionGap('1.0', null), null);
  });
  test('relative steps: a build number moves less than a major version', () => {
    assert.ok(versionGap('10798', '11832').step < versionGap('2.0', '3.0').step);
  });
  test('a numbering change has no size; dates count in years', () => {
    assert.equal(versionGap('2026-10', '202610050438').scheme, true);
    assert.equal(versionGap('0-unstable-2021-04-19', '2021041900').scheme, true);
    assert.equal(versionGap('9', '10').scheme, false); // a digit more is fine
    assert.equal(versionGap('20261009101206', '20261021011254').step, 0);
    assert.equal(versionGap('20060219', '20221026').step, 16);
  });
});
