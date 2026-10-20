// The page's rules (page/logic.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import {
  aheadOnMaster,
  attentionPrint,
  attentionRank,
  botWontUpdate,
  buildFailedBecause,
  buildsWith,
  communityCheck,
  comparedRepos,
  compareVersions,
  computeStatus,
  crc32,
  cvePieces,
  dayPosition,
  daysText,
  daysUntil,
  escapeHtml,
  failedBecause,
  familyLabel,
  faviconKey,
  foldFamilies,
  fromMaster,
  githubRepo,
  hasFailure,
  homeHref,
  html,
  isVulnerable,
  maintainerMatches,
  maintainersKeep,
  maintainersParam,
  maintainsDirectly,
  matchesSearch,
  midway,
  nameMatches,
  nixkeeperEntry,
  olderThan,
  olderVersionKept,
  onBranch,
  onHost,
  onMaster,
  onPlatform,
  pageLinks,
  parseMaintainers,
  parseTeams,
  problemSince,
  prPrint,
  raw,
  safeUrl,
  searchHandle,
  severityRank,
  shardOf,
  shortAge,
  targetVersion,
  teamsKeep,
  teamsParam,
  themeFor,
  timeAgo,
  trendChange,
  unbuiltOn,
  unbuiltWhere,
  updateTitle,
  versionDiff,
  viewPath,
  viewSlug,
  vulnSources,
  vulnSummary,
  waitingForChannel,
  weekChange,
  withRunStamps,
  withSlash,
} from '../../page/logic.js';

const NOW = Date.parse('2026-10-01T12:00:00Z');
const daysAgo = (n) => new Date(NOW - n * 86400e3).toISOString();

// A package as index.json has it, up to date unless overridden.
const pkg = (fields = {}) => ({ name: 'p', nixStatus: 'newest', ...fields });
const outdated = (fields = {}) =>
  pkg({ nixStatus: 'outdated', nixVersion: '1.0', refVersion: '1.1', ...fields });

describe('attentionPrint', () => {
  const juce = (fields = {}) =>
    outdated({ name: 'juce', nixVersion: '8.0.12', refVersion: '9.0.4', ...fields });
  test('the same while nothing changes', () => {
    assert.equal(attentionPrint(juce(), 'a'), attentionPrint(juce(), 'b'));
  });
  test('a newer version, a new failing build, an update failure, broken', () => {
    const before = attentionPrint(juce());
    assert.notEqual(attentionPrint(juce({ refVersion: '9.0.5' })), before);
    assert.notEqual(
      attentionPrint(juce({ builds: [{ system: 'aarch64-darwin', status: 'failed' }] })),
      before,
    );
    assert.notEqual(
      attentionPrint(
        juce({ updateFailure: true, update: { outcome: 'failed', failedBecause: 'patch' } }),
      ),
      before,
    );
    assert.notEqual(attentionPrint(juce({ markedBroken: true })), before);
    // An ok build isn't attention: no change.
    assert.equal(
      attentionPrint(juce({ builds: [{ system: 'x86_64-linux', status: 'ok' }] })),
      before,
    );
  });
  test('the same from the list entry and the full row', () => {
    const entry = juce({ vuln: { n: 1, by: ['tracker'] } });
    const row = juce({
      vulnerabilities: [{ id: 'CVE-1', verdict: 'affected', source: 'tracker' }],
    });
    assert.equal(attentionPrint(entry, 's'), attentionPrint(row, 's'));
  });
  test('vulnerable: back at the next sync', () => {
    const vuln = juce({ vuln: { n: 1, by: ['tracker'] } });
    assert.equal(attentionPrint(vuln, 'sync1'), attentionPrint(vuln, 'sync1'));
    assert.notEqual(attentionPrint(vuln, 'sync1'), attentionPrint(vuln, 'sync2'));
  });
});

describe('prPrint', () => {
  const pr = (fields = {}) => ({ number: 1, title: 'foo: 1.2 -> 1.3', ...fields });
  test('the same while nothing that matters changes', () => {
    assert.equal(prPrint(pr()), prPrint(pr({ behind: '1.5', approvedBy: ['x'] })));
  });
  test('a newer version in its title, or a CVE, brings it back', () => {
    assert.notEqual(prPrint(pr()), prPrint(pr({ title: 'foo: 1.2 -> 1.4' })));
    assert.notEqual(prPrint(pr()), prPrint(pr({ vulnerable: true })));
  });
});

describe('computeStatus', () => {
  test("follows Repology's statuses", () => {
    assert.equal(computeStatus(pkg()), 'ok');
    assert.equal(computeStatus(pkg({ nixStatus: 'unique' })), 'ok');
    assert.equal(computeStatus(pkg({ nixStatus: 'devel' })), 'ok');
    assert.equal(computeStatus(pkg({ nixStatus: 'outdated' })), 'warn');
    assert.equal(computeStatus(pkg({ nixStatus: 'missing' })), 'missing');
    assert.equal(computeStatus(pkg({ nixStatus: 'rolling' })), 'neutral');
  });
  test('an older version kept (legacy) is not outdated by itself', () => {
    const kept = pkg({ nixStatus: 'legacy', nixVersion: '0.11.1', refVersion: '0.14.1' });
    assert.equal(computeStatus(kept), 'neutral');
    assert.equal(olderVersionKept(kept), true);
    // A newer release in its own series makes it outdated.
    const behind = { ...kept, upstream: { newer: true, version: '0.11.2' } };
    assert.equal(computeStatus(behind), 'warn');
    assert.equal(olderVersionKept(behind), false);
  });
  test('a devel variant (legacy) behind newer devel versions is outdated', () => {
    const beta = pkg({
      nixStatus: 'legacy',
      devel: true,
      nixVersion: '1.0b1',
      refVersion: '1.1b2',
    });
    assert.equal(computeStatus(beta), 'warn');
    assert.equal(computeStatus({ ...beta, refVersion: '0.9' }), 'neutral');
  });
  test("an update check's newer release makes it outdated", () => {
    assert.equal(computeStatus(pkg({ upstream: { newer: true } })), 'warn');
    assert.equal(computeStatus(pkg({ nixStatus: 'rolling', upstream: { newer: true } })), 'warn');
  });
  test('missing wins over an update check', () => {
    assert.equal(
      computeStatus(pkg({ nixStatus: 'missing', upstream: { newer: true } })),
      'missing',
    );
  });
});

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

describe("botWontUpdate: outdated, and nixpkgs-update won't update it", () => {
  test("it can't, or passes it over on purpose", () => {
    assert.equal(botWontUpdate(outdated({ update: { outcome: 'cantUpdate' } })), true);
    assert.equal(botWontUpdate(outdated({ update: { outcome: 'skipped' } })), true);
  });
  test("never tried, and not in its queue (unless there's no queue)", () => {
    assert.equal(botWontUpdate(outdated({ update: null })), true);
    assert.equal(botWontUpdate(outdated({ update: null, queued: { to: ['1.1'] } })), false);
    assert.equal(botWontUpdate(outdated({ update: null, queued: { to: ['1.1'] } }), false), true);
  });
  test('it will, or might: a failure, a PR it made, nothing to update', () => {
    for (const outcome of ['failed', 'prOpened', 'noChange', 'superseded', 'other']) {
      assert.equal(botWontUpdate(outdated({ update: { outcome } })), false, outcome);
    }
  });
  test("not when someone's on it, or the bot's attempts aren't known", () => {
    const cant = { update: { outcome: 'cantUpdate' } };
    assert.equal(botWontUpdate(outdated({ ...cant, openPR: { number: 1 } })), false);
    assert.equal(botWontUpdate(outdated({ ...cant, master: '1.1' })), false);
    assert.equal(botWontUpdate(outdated({ update: null, pending: true })), false);
    assert.equal(botWontUpdate(outdated({ update: null, unread: ['update'] })), false);
    assert.equal(botWontUpdate(outdated()), false); // not in nixpkgs
  });
  test('only outdated packages', () => {
    assert.equal(botWontUpdate(pkg({ update: { outcome: 'cantUpdate' } })), false);
  });
});

describe('onBranch: updated on haskell-updates, waiting for its merge', () => {
  const branch = (version) => ({ name: 'haskell-updates', version });
  test('the target version there, or newer', () => {
    assert.equal(onBranch(outdated({ branch: branch('1.1') })), true);
    assert.equal(onBranch(outdated({ branch: branch('1.2') })), true);
  });
  test('not when the branch is behind, or nothing is outdated', () => {
    assert.equal(onBranch(outdated({ branch: branch('1.0') })), false);
    assert.equal(onBranch(outdated()), false);
    assert.equal(onBranch(pkg({ branch: branch('9.9') })), false);
  });
});

describe('onMaster and waitingForChannel', () => {
  test("master's version: the higher of Hydra's and a merged PR's", () => {
    assert.equal(onMaster(pkg()), null);
    assert.equal(onMaster(pkg({ master: '1.1' })), '1.1');
    assert.equal(onMaster(pkg({ master: '1.1', masterPR: { to: '1.2' } })), '1.2');
    assert.equal(onMaster(pkg({ master: '1.3', masterPR: { to: '1.2' } })), '1.3');
  });
  test('waiting once master has the newest version or newer', () => {
    assert.equal(waitingForChannel(outdated({ master: '1.1' })), true);
    assert.equal(waitingForChannel(outdated({ masterPR: { to: '1.2' } })), true);
  });
  test('not waiting when master is still behind', () => {
    assert.equal(waitingForChannel(outdated({ master: '1.0.5' })), false);
    assert.equal(waitingForChannel(outdated()), false);
  });
  test('only outdated packages wait', () => {
    assert.equal(waitingForChannel(pkg({ master: '9.9' })), false);
  });
});

describe('master ahead of the channel', () => {
  // wesnoth-devel: Repology knows 1.19.24 (the channel's), master has 1.19.28.
  const wesnoth = (fields = {}) =>
    pkg({
      nixStatus: 'devel',
      nixVersion: '1.19.24',
      refVersion: '1.19.24',
      master: '1.19.28',
      ...fields,
    });

  test('counts as outdated, and waits for the channel', () => {
    assert.equal(aheadOnMaster(wesnoth()), true);
    assert.equal(computeStatus(wesnoth()), 'warn');
    assert.equal(waitingForChannel(wesnoth()), true);
  });
  test("master's version is the one to update to", () => {
    // As the sync now writes it, and as older data has it.
    const synced = wesnoth({ refVersion: '1.19.28', refFromMaster: true });
    for (const p of [synced, wesnoth()]) {
      assert.equal(fromMaster(p), true);
      assert.equal(targetVersion(p), '1.19.28');
    }
  });
  test('a newer known release stays the target, still to do', () => {
    // unciv: master has 4.22.5, but 4.22.6 is out.
    const unciv = outdated({ nixVersion: '4.22.1', refVersion: '4.22.6', master: '4.22.5' });
    assert.equal(fromMaster(unciv), false);
    assert.equal(targetVersion(unciv), '4.22.6');
    assert.equal(waitingForChannel(unciv), false);
  });
  test('not when master matches the channel, or there is no master', () => {
    assert.equal(aheadOnMaster(wesnoth({ master: '1.19.24' })), false);
    assert.equal(computeStatus(wesnoth({ master: '1.19.24' })), 'ok');
    assert.equal(aheadOnMaster(pkg({ nixVersion: '1.0' })), false);
  });
  test("isn't a new release to act on in the tab icon", () => {
    assert.equal(faviconKey([wesnoth()]), 'ok');
  });
});

describe('communityCheck', () => {
  test("a community rule's result, or its failure", () => {
    assert.equal(communityCheck(pkg({ upstream: { version: '2', community: true } })), true);
    const failing = {
      upstream: { since: 'x', reason: 'community rule refused: url must be https://' },
    };
    assert.equal(communityCheck(pkg({ notRefreshed: failing })), true);
  });
  test('your own rule', () => {
    assert.equal(communityCheck(pkg({ upstream: { version: '2' } })), false);
    const failing = { upstream: { since: 'x', reason: 'nothing matches' } };
    assert.equal(communityCheck(pkg({ notRefreshed: failing })), false);
    assert.equal(communityCheck(pkg()), false);
  });
});

describe('matchesSearch', () => {
  const heroic = pkg({
    name: 'heroic',
    attrs: ['heroic', 'heroic-unwrapped'],
    maintainers: ['TomaSajt', 'iedame'],
  });
  test('names, projects and attributes contain the text', () => {
    assert.equal(matchesSearch(heroic, ' Unwrapped '), true);
    assert.equal(matchesSearch(heroic, ''), true);
    assert.equal(matchesSearch(heroic, 'tomas'), false); // handles only with @
  });
  test('@handle: the whole handle, in any case', () => {
    assert.equal(matchesSearch(heroic, '@tomasajt'), true);
    assert.equal(matchesSearch(heroic, '@TomaS'), false);
    assert.equal(matchesSearch(heroic, '@'), true); // still typing
    assert.equal(matchesSearch(pkg(), '@iedame'), false); // not synced yet
  });
  test('@none: no maintainer, not unknown', () => {
    assert.equal(matchesSearch(pkg({ maintainers: [] }), '@none'), true);
    assert.equal(matchesSearch(heroic, '@none'), false);
    assert.equal(matchesSearch(pkg(), '@none'), false);
  });
});

describe('nixkeeperEntry', () => {
  test("its update check's version, ahead when newer", () => {
    const up = { version: '0.48.0', newer: true, inferred: true, repo: 'o/r' };
    assert.deepEqual(nixkeeperEntry(pkg({ upstream: up })), {
      repo: 'nixkeeper',
      version: '0.48.0',
      ahead: true,
      kind: "Worked out from nixpkgs' source",
      where: 'o/r tags',
    });
    const page = { version: '16.0', newer: false, community: true, label: 'www.barebones.com' };
    const entry = nixkeeperEntry(pkg({ upstream: page }));
    assert.equal(entry.ahead, false);
    assert.equal(entry.kind, 'A community update check');
    assert.equal(entry.where, 'www.barebones.com');
    assert.equal(nixkeeperEntry(pkg({ upstream: { version: '2' } })).kind, 'Your update check');
  });
  test('none without a result', () => {
    assert.equal(nixkeeperEntry(pkg()), null);
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

describe('failures and platforms', () => {
  const builds = [
    { system: 'x86_64-linux', status: 'failed' },
    { system: 'aarch64-darwin', status: 'succeeded' },
    { system: 'aarch64-linux', status: 'broken' },
  ];
  test('builds with a status, on the selected platform', () => {
    assert.equal(buildsWith(pkg({ builds }), 'failed').length, 1);
    assert.equal(buildsWith(pkg({ builds }), 'failed', 'linux').length, 1);
    assert.equal(buildsWith(pkg({ builds }), 'failed', 'darwin').length, 0);
    assert.equal(buildsWith(pkg({ builds }), 'broken', 'linux').length, 1);
    assert.deepEqual(buildsWith(pkg(), 'failed'), []);
  });
  test('a failed build counts only on its platform', () => {
    assert.equal(hasFailure(pkg({ builds })), true);
    assert.equal(hasFailure(pkg({ builds }), 'linux'), true);
    assert.equal(hasFailure(pkg({ builds }), 'darwin'), false);
  });
  test('marked broken is not a failure', () => {
    assert.equal(hasFailure(pkg({ builds: [builds[2]] })), false);
  });
  test('an update failure or missing from nixpkgs is a failure', () => {
    assert.equal(hasFailure(pkg({ updateFailure: { version: '1.1' } })), true);
    assert.equal(hasFailure(pkg({ updateFailure: { version: '1.1' } }), 'darwin'), true);
    assert.equal(hasFailure(pkg({ nixStatus: 'missing' })), true);
    assert.equal(hasFailure(pkg()), false);
  });
  test('listed but not built there', () => {
    const built = (system) => ({ system, status: 'ok' });
    const none = (system) => ({ system, status: 'notBuilt' });
    const both = { linux: true, darwin: true };
    // juce: built on Linux, no Darwin build.
    const juce = pkg({
      platforms: both,
      builds: [built('x86_64-linux'), built('aarch64-linux'), none('aarch64-darwin')],
    });
    assert.equal(unbuiltOn(juce, 'darwin'), true);
    assert.equal(unbuiltOn(juce, 'linux'), false);
    assert.deepEqual(unbuiltWhere(juce), ['darwin']);
    // One Linux system missing: that one, not the family.
    const arm = pkg({
      platforms: { linux: true, darwin: false },
      builds: [built('x86_64-linux'), none('aarch64-linux')],
    });
    assert.equal(unbuiltOn(arm, 'aarch64-linux'), true);
    assert.equal(unbuiltOn(arm, 'linux'), false);
    assert.deepEqual(unbuiltWhere(arm), ['aarch64-linux']);
    // Hydra builds it nowhere (unfree, kept off it): not this.
    const unfree = pkg({
      platforms: both,
      builds: [none('x86_64-linux'), none('aarch64-linux'), none('aarch64-darwin')],
    });
    assert.deepEqual(unbuiltWhere(unfree), []);
    // Not listed there: not this either.
    const linuxOnly = pkg({
      platforms: { linux: true, darwin: false },
      builds: [built('x86_64-linux'), none('aarch64-darwin')],
    });
    assert.deepEqual(unbuiltWhere(linuxOnly), []);
  });
  test('"any platform" counts as both', () => {
    assert.equal(onPlatform(pkg({ platforms: null }), 'linux'), true);
    assert.equal(onPlatform(pkg({ platforms: null }), 'darwin'), true);
    assert.equal(onPlatform(pkg({ platforms: { linux: true } }), 'darwin'), false);
    assert.equal(onPlatform(pkg({ platforms: { linux: true } }), 'linux'), true);
  });
  test('by system', () => {
    const both = pkg({ platforms: { linux: true, darwin: true } });
    assert.equal(onPlatform(both, 'aarch64-linux'), true); // no systems: all of each
    const x86 = pkg({ platforms: { linux: true, darwin: false, systems: ['x86_64-linux'] } });
    assert.equal(onPlatform(x86, 'linux'), true);
    assert.equal(onPlatform(x86, 'x86_64-linux'), true);
    assert.equal(onPlatform(x86, 'aarch64-linux'), false);
    assert.equal(onPlatform(x86, 'darwin'), false);
    assert.equal(onPlatform(pkg({ platforms: null }), 'aarch64-linux'), true);
    assert.equal(buildsWith(pkg({ builds }), 'failed', 'x86_64-linux').length, 1);
    assert.equal(buildsWith(pkg({ builds }), 'failed', 'aarch64-linux').length, 0);
    assert.equal(buildsWith(pkg({ builds }), 'broken', 'aarch64-linux').length, 1);
    assert.equal(hasFailure(pkg({ builds }), 'aarch64-linux'), false);
  });
});

describe('attentionRank', () => {
  test('failed, outdated, waiting for the channel, then the rest', () => {
    const order = [
      pkg({ name: 'fine' }),
      outdated({ name: 'waiting', master: '1.1' }),
      outdated({ name: 'outdated' }),
      pkg({ name: 'failed', updateFailure: {} }),
    ].sort((a, b) => attentionRank(a) - attentionRank(b));
    assert.deepEqual(
      order.map((p) => p.name),
      ['failed', 'outdated', 'waiting', 'fine'],
    );
  });
  test('a failure elsewhere ranks with the rest while a platform is selected', () => {
    const failsOnLinux = pkg({ builds: [{ system: 'x86_64-linux', status: 'failed' }] });
    assert.equal(attentionRank(failsOnLinux), 0);
    assert.equal(attentionRank(failsOnLinux, 'darwin'), 2);
  });
});

describe('faviconKey', () => {
  test('all good', () => {
    assert.equal(faviconKey([]), 'ok');
    assert.equal(faviconKey([pkg(), pkg({ nixStatus: 'rolling' })]), 'ok');
  });
  test('each signal lights its own chevron, in r, f, v order', () => {
    assert.equal(faviconKey([outdated()]), 'r');
    assert.equal(faviconKey([pkg({ updateFailure: {} })]), 'f');
    assert.equal(faviconKey([pkg({ nixVulnerable: true })]), 'v');
    assert.equal(
      faviconKey([pkg({ nixVulnerable: true }), pkg({ updateFailure: {} }), outdated()]),
      'rfv',
    );
    assert.equal(faviconKey([outdated({ nixVulnerable: true })]), 'rv');
  });
  test('marked insecure by nixpkgs lights the vulnerable one too', () => {
    assert.equal(faviconKey([pkg({ markedInsecure: ['CVE-2020-25031'] })]), 'v');
  });
  test("an update already on master isn't a new release to act on", () => {
    assert.equal(faviconKey([outdated({ master: '1.1' })]), 'ok');
  });
  test('failures follow the platform filter', () => {
    const failsOnLinux = pkg({ builds: [{ system: 'x86_64-linux', status: 'failed' }] });
    assert.equal(faviconKey([failsOnLinux]), 'f');
    assert.equal(faviconKey([failsOnLinux], 'darwin'), 'ok');
  });
});

describe('ages', () => {
  test('shortAge: one unit, rounded down', () => {
    assert.equal(shortAge(daysAgo(0.5), NOW), '<1 d');
    assert.equal(shortAge(daysAgo(1), NOW), '1 d');
    assert.equal(shortAge(daysAgo(6), NOW), '6 d');
    assert.equal(shortAge(daysAgo(7), NOW), '1 w');
    assert.equal(shortAge(daysAgo(29), NOW), '4 w');
    assert.equal(shortAge(daysAgo(30), NOW), '1 m');
    assert.equal(shortAge(daysAgo(364), NOW), '11 m');
    assert.equal(shortAge(daysAgo(365), NOW), '1 y');
    assert.equal(shortAge(daysAgo(800), NOW), '2 y');
  });
  test('daysText', () => {
    assert.equal(daysText(daysAgo(0.2), NOW), 'today');
    assert.equal(daysText(daysAgo(1), NOW), '1 day');
    assert.equal(daysText(daysAgo(12), NOW), '12 days');
  });
  test('daysUntil', () => {
    // NOW is 2026-10-01 at noon UTC.
    assert.equal(daysUntil('2026-10-01', NOW), 0);
    assert.equal(daysUntil('2026-10-02', NOW), 1);
    assert.equal(daysUntil('2026-10-12', NOW), 11);
    assert.equal(daysUntil('2026-09-28', NOW), 0); // past: due now
  });
  test('onHost', () => {
    assert.equal(onHost('https://github.com/yairm210/Unciv/releases', 'github.com'), true);
    assert.equal(onHost('https://API.GitHub.com/repos/x', 'github.com'), true);
    // The name elsewhere in the address isn't the host.
    assert.equal(onHost('https://example.org/?github.com', 'github.com'), false);
    assert.equal(onHost('https://github.com.example.org/', 'github.com'), false);
    assert.equal(onHost('https://notgithub.com/', 'github.com'), false);
    assert.equal(onHost('not a url', 'github.com'), false);
    assert.equal(onHost('', 'repology.org'), false);
  });
  test('timeAgo', () => {
    assert.equal(timeAgo(null, NOW), 'never');
    assert.equal(timeAgo(new Date(NOW - 30e3).toISOString(), NOW), 'just now');
    assert.equal(timeAgo(new Date(NOW - 5 * 60e3).toISOString(), NOW), '5m ago');
    assert.equal(timeAgo(new Date(NOW - 4 * 3600e3).toISOString(), NOW), '4h ago');
    assert.equal(timeAgo(daysAgo(3), NOW), '3d ago');
  });
});

describe('links and markup from data', () => {
  test('escapeHtml', () => {
    assert.equal(
      escapeHtml(`<a href="x">'&'</a>`),
      '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;',
    );
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(42), '42');
  });
  test('only web addresses are links', () => {
    assert.equal(
      safeUrl('https://github.com/NixOS/nixpkgs/pull/1'),
      'https://github.com/NixOS/nixpkgs/pull/1',
    );
    assert.equal(safeUrl('http://example.org/'), 'http://example.org/');
    assert.equal(safeUrl('javascript:alert(1)'), '');
    assert.equal(safeUrl('JavaScript:alert(1)'), '');
    assert.equal(safeUrl('data:text/html,<script>'), '');
    assert.equal(safeUrl('not a url'), '');
    assert.equal(safeUrl(undefined), '');
  });
  test('html escapes everything put in it', () => {
    const title = `<img src=x onerror="alert(1)">'&'`;
    assert.equal(
      String(html`<b title="${title}">${title}</b>`),
      '<b title="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;&#39;">' +
        '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;&#39;</b>',
    );
    // Links: safeUrl, then escaped like the rest.
    assert.equal(
      String(html`<a href="${safeUrl('https://example.org/?a="b"&c')}">`),
      '<a href="https://example.org/?a=&quot;b&quot;&amp;c">',
    );
  });
  test('html keeps markup made with html or raw', () => {
    const name = '<i>x</i>';
    const inner = html`<i>${name}</i>`;
    assert.equal(String(html`<b>${inner}</b>`), '<b><i>&lt;i&gt;x&lt;/i&gt;</i></b>');
    assert.equal(String(html`${raw('<br>')}`), '<br>');
  });
  test('html joins arrays, and leaves out null and undefined only', () => {
    assert.equal(String(html`${['<a>', html`<b>`]}`), '&lt;a&gt;<b>');
    assert.equal(String(html`${null}${undefined}|${0}|${false}`), '|0|false');
  });
});

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

describe('themeFor', () => {
  test('nothing chosen: classic, following the system', () => {
    assert.deepEqual(themeFor(), { palette: 'classic', mode: 'auto' });
    assert.deepEqual(themeFor({ palette: null, mode: null }, null), {
      palette: 'classic',
      mode: 'auto',
    });
  });
  test("the page's default, when the visitor hasn't chosen", () => {
    assert.deepEqual(themeFor({}, 'catppuccin'), { palette: 'catppuccin', mode: 'auto' });
  });
  test("the visitor's choice wins over the page's default", () => {
    assert.deepEqual(themeFor({ palette: 'classic', mode: 'dark' }, 'catppuccin'), {
      palette: 'classic',
      mode: 'dark',
    });
  });
  test('unknown values count as not set', () => {
    assert.deepEqual(themeFor({ palette: 'solarized', mode: 'dim' }, 'catppuccin'), {
      palette: 'catppuccin',
      mode: 'auto',
    });
    assert.deepEqual(themeFor({}, 'nord'), { palette: 'classic', mode: 'auto' });
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

describe('updateTitle', () => {
  test("an outdated package: nixpkgs' title for the update", () => {
    assert.equal(
      updateTitle(outdated({ name: 'unciv', nixVersion: '4.22.1', refVersion: '4.22.6' })),
      'unciv: 4.22.1 -> 4.22.6',
    );
  });
  test('none when up to date, or without a newest version', () => {
    assert.equal(updateTitle(pkg({ nixVersion: '1.0' })), null);
    assert.equal(updateTitle(outdated({ refVersion: undefined })), null);
  });
});

describe('midway', () => {
  test("master between the channel and the newest: master's version", () => {
    const pkg = outdated({ nixVersion: '1.0', refVersion: '1.2', masterPR: { to: '1.1' } });
    assert.equal(midway(pkg), '1.1');
    assert.equal(updateTitle({ ...pkg, name: 'p' }), 'p: 1.1 -> 1.2');
  });
  test('none when master already has the newest, or has nothing new', () => {
    assert.equal(
      midway(outdated({ nixVersion: '1.0', refVersion: '1.1', masterPR: { to: '1.1' } })),
      null,
    );
    assert.equal(midway(outdated({ nixVersion: '1.0', refVersion: '1.1' })), null);
    assert.equal(midway(pkg({ nixVersion: '1.1', masterPR: { to: '1.1' } })), null);
  });
});

describe('shards', () => {
  // The same as Python's zlib.crc32 (nixkeeper/datastore.py), or a panel
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
  test('viewSlug as datastore.slug', () => {
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

describe('weekChange', () => {
  const day = (d, failed) => ({ day: d, failed });
  test('against the newest point a week or more before', () => {
    const points = [day('2026-09-25', 100), day('2026-09-28', 110), day('2026-10-05', 150)];
    assert.equal(weekChange(points, 'failed'), 40);
  });
  test('null without a week of points', () => {
    assert.equal(weekChange([day('2026-10-01', 1), day('2026-10-05', 2)], 'failed'), null);
    assert.equal(weekChange([], 'failed'), null);
  });
});

describe('problemSince and olderThan', () => {
  const now = Date.parse('2026-10-06T00:00:00Z');
  const pkg = {
    failingSince: '2026-09-20T00:00:00Z',
    updateFailingSince: '2026-03-01T00:00:00Z',
    outdatedSince: '2025-06-01T00:00:00Z',
  };
  test("the list's kind of problem, or the earliest", () => {
    assert.equal(problemSince(pkg, 'failed'), '2026-03-01T00:00:00Z'); // the earlier failing
    assert.equal(problemSince(pkg, 'warn'), '2025-06-01T00:00:00Z');
    assert.equal(problemSince(pkg, 'all'), '2025-06-01T00:00:00Z');
    assert.equal(problemSince(pkg, 'builds'), '2026-09-20T00:00:00Z'); // builds alone
    assert.equal(problemSince(pkg, 'updates'), '2026-03-01T00:00:00Z'); // updates alone
    assert.equal(problemSince({}, 'all'), null);
  });
  test('older than a month, 6 months, a year', () => {
    assert.equal(olderThan(pkg, '6m', 'failed', now), true); // since March
    assert.equal(olderThan(pkg, '1y', 'failed', now), false);
    assert.equal(olderThan(pkg, '1y', 'warn', now), true); // since June 2025
    assert.equal(olderThan({ failingSince: '2026-09-20T00:00:00Z' }, '1m', 'failed', now), false);
  });
  test('2 and 3 years; never built (where), which has no date', () => {
    const old = { failingSince: '2023-12-01T00:00:00Z' };
    assert.equal(olderThan(old, '2y', 'builds', now), true);
    assert.equal(olderThan(old, '3y', 'builds', now), false);
    const never = { neverBuiltOn: ['aarch64-darwin'] };
    assert.equal(olderThan(never, 'never', 'builds', now), true);
    assert.equal(olderThan(never, 'never', 'all', now), true);
    assert.equal(olderThan(never, 'never', 'warn', now), false); // not a build's
    assert.equal(olderThan(never, '3y', 'builds', now), false); // no date
    assert.equal(olderThan(old, 'never', 'builds', now), false); // built once
    // With a platform picked, only where it never built.
    assert.equal(olderThan(never, 'never', 'builds', now, 'darwin'), true);
    assert.equal(olderThan(never, 'never', 'builds', now, 'linux'), false);
    assert.equal(olderThan(never, 'never', 'builds', now, 'aarch64-linux'), false);
  });
  test('no problem: never older; no age picked: every row', () => {
    assert.equal(olderThan({}, '1m', 'all', now), false);
    assert.equal(olderThan({}, null, 'all', now), true);
    assert.equal(olderThan({}, 'bogus', 'all', now), true);
  });
});

describe('maintainerMatches', () => {
  const list = [
    ['Fgaz', 81, 23, 7],
    ['fgazbot', 2, 0, 0],
    ['afgazer', 1, 0, 0],
    ['iedame', 27, 4, 0],
  ];
  test('the handle, then those starting with it, then by handle; any case, @ or not', () => {
    assert.deepEqual(
      maintainerMatches(list, '@fgaz').found.map(([h]) => h),
      ['Fgaz', 'fgazbot', 'afgazer'],
    );
    assert.equal(maintainerMatches(list, 'FGAZ').total, 3);
  });
  test('at most limit, and how many there are', () => {
    assert.deepEqual(maintainerMatches(list, 'a', 2), {
      found: [list[2], list[0]],
      total: 4,
    });
    assert.deepEqual(maintainerMatches(list, '@'), { found: [], total: 0 });
  });
});

describe('trendChange and dayPosition', () => {
  const day = (d, failed) => ({ day: d, failed });
  test('a week once there is one, else since the first point', () => {
    const week = [day('2026-09-25', 100), day('2026-10-05', 150)];
    assert.deepEqual(trendChange(week, 'failed'), { change: 50, since: null });
    const two = [day('2026-10-05', 2127), day('2026-10-06', 2195)];
    assert.deepEqual(trendChange(two, 'failed'), { change: 68, since: '2026-10-05' });
    assert.equal(trendChange([day('2026-10-06', 1)], 'failed'), null);
  });
  test('by date, missing days keeping their room; null outside', () => {
    const points = [day('2026-10-01', 0), day('2026-10-02', 0), day('2026-10-05', 0)];
    assert.equal(dayPosition(points, '2026-10-01'), 0);
    assert.equal(dayPosition(points, '2026-10-02'), 25);
    assert.equal(dayPosition(points, '2026-10-05'), 100);
    assert.equal(dayPosition(points, '2026-09-28'), null);
    assert.equal(dayPosition([day('2026-10-01', 0)], '2026-10-01'), null);
  });
});

describe('isVulnerable and cvePieces', () => {
  test("Repology's flag or nixpkgs' mark", () => {
    assert.equal(isVulnerable({ nixVulnerable: true }), true);
    assert.equal(isVulnerable({ markedInsecure: ['EOL'] }), true);
    assert.equal(isVulnerable({ markedInsecure: [] }), false);
    assert.equal(isVulnerable({}), false);
  });
  test('the CVE ids in a reason, apart to link', () => {
    assert.deepEqual(cvePieces('CVE-2018-19655'), [{ cve: 'CVE-2018-19655' }]);
    assert.deepEqual(cvePieces('CVE-2026-34400: SQL injection, fixed in 9.1.0'), [
      { cve: 'CVE-2026-34400' },
      { text: ': SQL injection, fixed in 9.1.0' },
    ]);
    assert.deepEqual(cvePieces('Uses Electron 39, EOL'), [{ text: 'Uses Electron 39, EOL' }]);
  });
});

describe('searchHandle and maintainsDirectly', () => {
  test('the maintainer a search names', () => {
    assert.equal(searchHandle(' @L0b0 '), 'l0b0');
    assert.equal(searchHandle('@'), null);
    assert.equal(searchHandle('@none'), null);
    assert.equal(searchHandle('gdal'), null);
  });
  test('listed directly, not only as a team member', () => {
    const gdal = { maintainers: ['tviti', 'l0b0'], nonTeamMaintainers: ['tviti'] };
    assert.equal(maintainsDirectly(gdal, 'tviti'), true);
    assert.equal(maintainsDirectly(gdal, 'l0b0'), false);
    // No nonTeamMaintainers: every maintainer is a direct one.
    assert.equal(maintainsDirectly({ maintainers: ['L0b0'] }, 'l0b0'), true);
  });
});

describe('?team=: one team, teams left out, none', () => {
  test('read and written back', () => {
    const t = parseTeams('Gaming, -Geospatial,-Steam,none,-Geospatial');
    assert.deepEqual(t, { include: 'Gaming', leftOut: ['Geospatial', 'Steam'], none: true });
    assert.equal(teamsParam(t), 'Gaming,-Geospatial,-Steam,none');
    assert.deepEqual(parseTeams(null), { include: null, leftOut: [], none: false });
    assert.equal(teamsParam(parseTeams('')), '');
    assert.deepEqual(parseTeams('-').leftOut, []); // a lone "-" names nothing
  });
  const gdal = {
    teams: ['Geospatial'],
    maintainers: ['tviti', 'l0b0'],
    nonTeamMaintainers: ['tviti'],
  };
  const game = { teams: ['Gaming'], maintainers: ['l0b0'] };
  const own = { maintainers: ['l0b0'] };
  const keep = (value, handle = null) =>
    [gdal, game, own].filter((p) => teamsKeep(p, parseTeams(value), handle)).length;
  test('a team left out, any case', () => {
    assert.equal(keep('-geospatial'), 2);
    assert.equal(keep('-Geospatial,-Gaming'), 1);
  });
  test("none: a maintainer's own packages, or packages without a team", () => {
    assert.equal(keep('none', 'l0b0'), 2); // game (direct) and own
    assert.equal(keep('none', 'tviti'), 1); // gdal
    assert.equal(keep('none'), 1); // own: no team
  });
  test('one team, as before', () => {
    assert.equal(keep('Gaming'), 1);
    assert.equal(keep(''), 3);
  });
});

describe('?maintainer=: one page, maintainers left out', () => {
  test('read and written back', () => {
    const m = parseMaintainers('l0b0,-iedame, -@Someone,-iedame');
    assert.deepEqual(m, { handle: 'l0b0', leftOut: ['iedame', 'someone'] });
    assert.equal(maintainersParam(m), 'l0b0,-iedame,-someone');
    assert.deepEqual(parseMaintainers('-iedame'), { handle: null, leftOut: ['iedame'] });
    assert.deepEqual(parseMaintainers('@l0b0'), { handle: 'l0b0', leftOut: [] });
    assert.equal(maintainersParam(parseMaintainers(null)), '');
  });
  test('their packages left out, directly or through a team', () => {
    const freedink = { maintainers: ['iedame', 'l0b0'], nonTeamMaintainers: ['iedame'] };
    assert.equal(maintainersKeep(freedink, ['iedame']), false);
    assert.equal(maintainersKeep(freedink, ['l0b0']), false); // via Gaming: still theirs
    assert.equal(maintainersKeep(freedink, ['someone']), true);
    assert.equal(maintainersKeep({}, ['iedame']), true);
    assert.equal(maintainersKeep(freedink, []), true);
  });
});

describe("nixkeeper-vulnerabilities' verdict", () => {
  test("the sync's, when there is one", () => {
    // null: the digest had entries, none counted, nor Repology nor nixpkgs.
    assert.equal(isVulnerable({ vuln: null, nixVulnerable: false }), false);
    assert.equal(isVulnerable({ vuln: { n: 1, by: ['tracker'] } }), true);
    // No "vuln" (data from before, or nothing on it): as before.
    assert.equal(isVulnerable({ nixVulnerable: true }), true);
  });
  test("from a full row's vulnerabilities, as the sync's summary", () => {
    const row = {
      nixVulnerable: true,
      vulnerabilities: [
        { verdict: 'fixed', source: 'tracker', severity: 'critical' },
        { verdict: 'osv', source: 'osv', severity: 'moderate' },
        { verdict: 'affected', source: 'tracker', severity: 'high' },
      ],
    };
    assert.deepEqual(vulnSummary(row), {
      n: 2,
      severity: 'high',
      by: ['osv', 'tracker', 'repology'],
    });
    assert.equal(isVulnerable(row), true);
    const none = { vulnerabilities: [{ verdict: 'fixed', source: 'tracker' }] };
    assert.equal(vulnSummary(none), null);
    assert.equal(isVulnerable(none), false);
  });
  test('worst severity first, unknown last', () => {
    const order = [{}, { vuln: { severity: 'low' } }, { vuln: { severity: 'critical' } }].map((p) =>
      severityRank(p),
    );
    assert.deepEqual(order, [5, 4, 0]);
  });
  test('who says so', () => {
    assert.deepEqual(vulnSources({ vuln: { by: ['tracker', 'repology'] } }), [
      'the NixOS security tracker',
      'Repology',
    ]);
    assert.deepEqual(vulnSources({ nixVulnerable: true, markedInsecure: ['x'] }), [
      'nixpkgs (marked insecure)',
      'Repology',
    ]);
  });
});

describe('buildFailedBecause', () => {
  const pkg = {
    builds: [
      { status: 'failed', system: 'x86_64-linux', failedBecause: 'cmake4' },
      { status: 'failed', system: 'aarch64-linux', failedBecause: 'cmake4' },
      { status: 'failed', system: 'aarch64-darwin' },
      { status: 'ok', system: 'x86_64-linux', failedBecause: 'tests' },
    ],
  };
  test("each failed build's reason once, unread while its log isn't read", () => {
    assert.deepEqual(buildFailedBecause(pkg), ['cmake4', 'unread']);
  });
  test('on the platform picked', () => {
    assert.deepEqual(buildFailedBecause(pkg, 'linux'), ['cmake4']);
    assert.deepEqual(buildFailedBecause(pkg, 'darwin'), ['unread']);
  });
  test('none without a failed build', () => {
    assert.deepEqual(
      buildFailedBecause({ builds: [{ status: 'ok', system: 'x86_64-linux' }] }),
      [],
    );
  });
});

describe('failedBecause', () => {
  test("the reason the bot's last attempt failed, other when unknown", () => {
    assert.equal(
      failedBecause({ updateFailure: true, update: { failedBecause: 'patch' } }),
      'patch',
    );
    assert.equal(failedBecause({ updateFailure: true, update: { outcome: 'failed' } }), 'other');
    // Not failing: no reason, whatever an older attempt said.
    assert.equal(failedBecause({ update: { failedBecause: 'patch' } }), null);
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
