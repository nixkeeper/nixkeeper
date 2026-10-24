// The overview (page/overview.js): its pieces of HTML and text from the
// data. Run: node --test tests/js/ (part of `nix flake check`, as
// checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  botCause,
  creditName,
  creditText,
  familyLink,
  platformSplit,
  sparkline,
  trendSpan,
} from '../../page/overview.js';
import { store } from '../../page/store.js';

globalThis.location = { pathname: '/', search: '' };

describe('the cards', () => {
  test('build failures split by platform, when the data has it', () => {
    assert.equal(String(platformSplit(null)), '');
    assert.match(
      String(platformSplit({ linux: 873, darwin: 770, 'x86_64-linux': 600 })),
      /Linux 873 · Darwin 770/,
    );
  });
  test('a trend: its days, and a line through its points', () => {
    const points = [
      { day: '2026-10-20', failing: 10 },
      { day: '2026-10-22', failing: 30 },
      { day: '2026-10-24', failing: 20 },
    ];
    assert.equal(trendSpan(points), 5);
    store.trendEvents = [];
    const svg = String(sparkline(points, 'failing', 'var(--danger)'));
    // Lowest at the bottom (y 20), highest at the top (y 2).
    assert.match(svg, /,20\.0/);
    assert.match(svg, /,2\.0/);
  });
});

describe('what was fixed', () => {
  test('credited to a person, not a bot', () => {
    assert.equal(creditName({ author: 'r-ryantm', mergedBy: 'alice' }), 'alice');
    assert.equal(
      creditText({ pr: 575734, author: 'drupol', mergedBy: 'drupol', likely: true }),
      'Likely fixed by #575734, opened by @drupol, merged by @drupol',
    );
  });
});

describe('links', () => {
  test("a family by its search, a package by its page's address", () => {
    assert.equal(
      String(familyLink('cups-brother', { label: 'cups-brother-*' })),
      'href="?q=cups-brother-"',
    );
    assert.match(String(familyLink('tgrep', null)), /href="\/\?pkg=tgrep" data-scope-pkg="tgrep"/);
  });
  test('an update failure without a log, said so', () => {
    assert.equal(botCause('noLog'), 'build, no log');
  });
});
