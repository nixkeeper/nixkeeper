// The page's addresses and links (page/address.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  githubRepo,
  homeHref,
  pageLinks,
  viewPath,
  viewSlug,
  withRunStamps,
  withSlash,
} from '../../page/address.js';
import { nameMatches } from '../../page/people.js';

describe('the way home (the lockup)', () => {
  test('drops every filter, the search, the page and the open package', () => {
    assert.equal(
      homeHref('/', '?filter=outdated&q=@iedame&team=-Gaming&sort=az&page=3&per=200&pkg=wesnoth'),
      '/',
    );
    assert.equal(homeHref('/', ''), '/');
  });
  test('keeps where the data lives', () => {
    assert.equal(
      homeHref('/nixkeeper/', '?owner=someone&repo=their-keeper&view=attention&q=x'),
      '/nixkeeper/?owner=someone&repo=their-keeper',
    );
    assert.equal(homeHref('/', '?data=%2Ftest%2F&filter=failed'), '/?data=%2Ftest%2F');
  });
  test('stays on the page it was opened at', () => {
    assert.equal(homeHref('/nixkeeper/index.html', '?view=backport'), '/nixkeeper/index.html');
  });
});

describe('where the data is', () => {
  const at = (url) => {
    const u = new URL(url);
    return [u.searchParams, u];
  };
  test('a GitHub Pages project site names its repository', () => {
    assert.equal(
      githubRepo(...at('https://nixkeeper.github.io/nixkeeper/')),
      'nixkeeper/nixkeeper',
    );
    assert.equal(
      githubRepo(...at('https://nixkeeper.github.io/nixkeeper/index.html')),
      'nixkeeper/nixkeeper',
    );
  });
  test('?owner=&repo= names another one', () => {
    assert.equal(
      githubRepo(...at('https://nixkeeper.github.io/nixkeeper/?owner=someone&repo=their-keeper')),
      'someone/their-keeper',
    );
  });
  test('only names GitHub allows', () => {
    for (const [owner, repo] of [
      ['a"b', 'x'],
      ['someone', '../../evil'],
      ['someone', '..'],
      ['-someone', 'x'],
      ['some/one', 'x'],
      ['someone', 'a b'],
      ['someone', '<script>'],
    ]) {
      const q = new URLSearchParams({ owner, repo });
      assert.equal(
        githubRepo(...at(`https://nixkeeper.github.io/nixkeeper/?${q}`)),
        null,
        `${owner}/${repo}`,
      );
    }
    assert.equal(githubRepo(...at('https://nixkeeper.github.io/%3Cscript%3E/')), null);
    assert.equal(
      githubRepo(...at('https://nixkeeper.github.io/nixkeeper/?owner=a-b&repo=c.d_e-f')),
      'a-b/c.d_e-f',
    );
  });
  test('anywhere else, no repository', () => {
    assert.equal(githubRepo(...at('http://127.0.0.1:8765/')), null);
    assert.equal(githubRepo(...at('https://nixkeeper.github.io/')), null);
    assert.equal(githubRepo(...at('https://example.org/nixkeeper/')), null);
  });
  test('withSlash', () => {
    assert.equal(withSlash('https://x/data'), 'https://x/data/');
    assert.equal(withSlash('https://x/data/'), 'https://x/data/');
  });
});

describe('pageLinks', () => {
  test('few pages: all of them', () => {
    assert.deepEqual(pageLinks(1, 1), [1]);
    assert.deepEqual(pageLinks(2, 2), [1, 2]);
    assert.deepEqual(pageLinks(1, 6), [1, 2, 3, 4, 5, 6]);
  });
  test('gaps around the current page', () => {
    assert.deepEqual(pageLinks(1, 20), [1, 2, 3, null, 20]);
    assert.deepEqual(pageLinks(10, 20), [1, null, 8, 9, 10, 11, 12, null, 20]);
    assert.deepEqual(pageLinks(20, 20), [1, null, 18, 19, 20]);
  });
  test('a gap of one page shows the page', () => {
    assert.deepEqual(pageLinks(5, 20), [1, 2, 3, 4, 5, 6, 7, null, 20]);
  });
});

describe('withRunStamps', () => {
  const RUN = '2026-10-05T06:00:00+00:00';
  test('puts back the dates left out', () => {
    const row = withRunStamps(
      {
        builds: [{ status: 'ok' }, { status: 'ok', checkedAt: '2026-10-03' }],
        upstream: { version: '2' },
        openPRs: 0,
      },
      RUN,
    );
    assert.deepEqual(
      row.builds.map((b) => b.checkedAt),
      [RUN, '2026-10-03'],
    );
    assert.equal(row.upstream.checkedAt, RUN);
    assert.equal(row.countedAt, RUN);
  });
  test('adds nothing where nothing was', () => {
    assert.deepEqual(withRunStamps({ name: 'a' }, RUN), { name: 'a' });
    assert.deepEqual(withRunStamps({ name: 'a' }, null), { name: 'a' });
  });
});

describe('views (every package)', () => {
  test('viewSlug as naming.slug', () => {
    assert.equal(viewSlug('Security review'), 'security-review');
    assert.equal(viewSlug('Qt-KDE'), 'qt-kde');
    assert.equal(viewSlug('gaming-team'), 'gaming-team');
  });
  test('viewPath: the narrowest the address asks for', () => {
    assert.equal(viewPath(), 'overview');
    assert.equal(viewPath({ query: 'firefox' }), 'overview');
    assert.equal(viewPath({ view: 'attention' }), 'views/attention.json');
    assert.equal(viewPath({ view: 'maintainers' }), 'maintainers');
    assert.equal(viewPath({ view: 'maintainers', query: 'fg' }), 'maintainers'); // narrows it
    assert.equal(viewPath({ view: 'broken' }), 'views/broken.json');
    assert.equal(viewPath({ view: 'nonsense' }), 'overview');
    assert.equal(viewPath({ query: '@Iedame', team: 'Gaming' }), 'views/maintainer/iedame.json');
    assert.equal(viewPath({ query: '@none' }), 'views/maintainer/none.json');
    assert.equal(viewPath({ query: '@' }), 'overview');
    assert.equal(
      viewPath({ team: 'Security review', list: 'x' }),
      'views/team/security-review.json',
    );
    assert.equal(viewPath({ list: 'gaming-team' }), 'views/list/gaming-team.json');
    assert.equal(viewPath({ set: 'rPackages' }), 'views/set/rPackages.json');
    assert.equal(viewPath({ pkg: 'zlib', query: '@x' }), 'pkg:zlib');
  });
  test('nameMatches leaves out the view shown', () => {
    const names = [
      ['firefox', 'u'],
      ['firefox-esr', 'o'],
      ['thunderbird', 'u'],
    ];
    assert.deepEqual(nameMatches(names, 'FIRE', new Set(['firefox'])), {
      found: [['firefox-esr', 'o']],
      total: 1,
    });
    assert.deepEqual(nameMatches(names, '@fire', new Set()), { found: [], total: 0 });
    assert.equal(nameMatches(names, 'f', new Set(), 1).found.length, 1);
  });
  test('nameMatches: the closest first', () => {
    const names = [
      ['emacsPackages.helm-firefox', 'u'],
      ['firefox-esr', 'u'],
      ['librewolf-firefox', 'u'],
      ['firefox', 'u'],
      ['python3Packages.firefox', 'u'],
    ];
    assert.deepEqual(
      nameMatches(names, 'firefox', new Set()).found.map(([n]) => n),
      [
        'firefox',
        'firefox-esr',
        'librewolf-firefox',
        'emacsPackages.helm-firefox',
        'python3Packages.firefox',
      ],
    );
  });
});
