// A package panel's sections (page/panel.js), as HTML from a package. Run:
// node --test tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { buildLine, githubSection, groupedBuilds, vulnSection } from '../../page/panel.js';

// Markup without its tags, removed until none is left (a single pass would
// leave one behind in "<sp<b>an>": CodeQL's incomplete sanitization).
const untagged = (markup) => {
  let out = String(markup).replace(/<span class="sr-only">[^<]*<\/span>/g, '');
  for (let was = null; was !== out; ) {
    was = out;
    out = out.replace(/<[^>]*>/g, '');
  }
  return out;
};

// The visible text of some HTML, spaces collapsed: what a reader sees.
const text = (markup) =>
  untagged(markup)
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();

describe('vulnSection', () => {
  // barman, 2026-10-23: one CVE, its fix in 3.20.1, an update PR to it.
  const barman = {
    name: 'barman',
    nixVersion: '3.19.1',
    refVersion: '3.20.1',
    nixStatus: 'outdated',
    openPR: {
      number: 564426,
      to: '3.20.1',
      url: 'https://github.com/NixOS/nixpkgs/pull/564426',
      facts: { vulnerable: true },
    },
    vulnerabilities: [
      { id: 'CVE-2026-93853', verdict: 'affected', severity: 'high', fixedIn: '3.20.1' },
    ],
  };
  test('fixed in, and whether the update PR fixes it', () => {
    const said = text(vulnSection(barman));
    assert.match(said, /CVE-2026-93853 high/);
    assert.match(said, /fixed in 3\.20\.1/);
    assert.match(said, /#564426 ↗ updates it to 3\.20\.1, which fixes it; review it first/);
  });
  test('patched by an open PR', () => {
    const said = text(
      vulnSection({
        ...barman,
        openPR: null,
        vulnerabilities: [
          {
            ...barman.vulnerabilities[0],
            prs: [{ number: 578074, title: 'x', base: 'release-26.05' }],
          },
        ],
      }),
    );
    assert.match(said, /patched by #578074 ↗ \(into release-26\.05\)/);
  });
  test('nothing without vulnerabilities', () => {
    assert.equal(String(vulnSection({ name: 'p' })), '');
  });
});

describe('buildLine', () => {
  // tgrep, 2026-10-23: last built at 1.1.0, failing at 1.2.4 since #575734.
  const failed = {
    attr: 'tgrep',
    system: 'x86_64-linux',
    status: 'failed',
    build: 1,
    version: '1.2.4',
    lastSuccess: '2026-10-22T15:30:00Z',
    lastSuccessVersion: '1.1.0',
  };
  const tgrep = {
    name: 'tgrep',
    builds: [failed],
    buildCausePR: {
      number: 575734,
      title: 'tgrep: 1.1.0 -> 1.2.4',
      url: 'https://github.com/NixOS/nixpkgs/pull/575734',
    },
  };
  test('the update it has failed since', () => {
    const said = text(buildLine(tgrep, failed));
    assert.match(said, /at 1\.2\.4, since its update \(#575734 ↗\)/);
    assert.match(said, /last built at 1\.1\.0/);
  });
  test('a search for the update PR when it is not known', () => {
    const line = String(buildLine({ ...tgrep, buildCausePR: undefined }, failed));
    assert.match(text(line), /since its update \(its PR ↗\)/);
    assert.match(line, /pulls\?q=is%3Apr%20is%3Amerged/);
  });
  test('a blocking package linked only when the page can open it', () => {
    const blocked = { ...failed, status: 'dependency', blockedBy: [{ name: 'libfoo', row: true }] };
    assert.doesNotMatch(String(buildLine(tgrep, blocked)), /data-scope-pkg/);
    assert.match(
      String(buildLine(tgrep, blocked, undefined, (name) => `/?pkg=${name}`)),
      /href="\/\?pkg=libfoo" data-scope-pkg="libfoo"/,
    );
  });
  test('builds failing alike grouped, their lines shown once', () => {
    const other = {
      ...failed,
      system: 'aarch64-linux',
      failedBecause: 'tests',
      failedExcerpt: 'error',
    };
    const groups = groupedBuilds([
      { ...failed, failedBecause: 'tests', failedExcerpt: 'error' },
      other,
    ]);
    assert.deepEqual(
      groups.map(([, alike]) => alike),
      [
        { n: 2, shows: false },
        { n: 2, shows: true },
      ],
    );
  });
});

describe('githubSection', () => {
  test('the update that broke the build, and the likely fix', () => {
    // atuin, 2026-10-23.
    const said = text(
      githubSection({
        name: 'atuin',
        buildCausePR: {
          number: 576384,
          title: 'atuin: 18.23.0 -> 18.24.1',
          url: 'https://github.com/NixOS/nixpkgs/pull/576384',
        },
        buildFixPR: {
          number: 577449,
          title: 'atuin: 18.24.1 -> 18.24.2',
          url: 'https://github.com/NixOS/nixpkgs/pull/577449',
        },
      }),
    );
    assert.match(said, /#576384 ↗ atuin: 18\.23\.0 -> 18\.24\.1 likely broke the build/);
    assert.match(said, /#577449 ↗ atuin: 18\.24\.1 -> 18\.24\.2 likely fix/);
  });
});
