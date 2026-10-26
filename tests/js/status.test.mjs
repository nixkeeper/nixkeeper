// A package's status (page/status.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { faviconKey } from '../../page/palette.js';
import {
  aheadOnMaster,
  attentionPrint,
  attentionRank,
  botWontUpdate,
  buildFailedBecause,
  buildsWith,
  communityCheck,
  computeStatus,
  failedBecause,
  fromMaster,
  hasFailure,
  midway,
  nixkeeperEntry,
  olderThan,
  olderVersionKept,
  onBranch,
  onMaster,
  onPlatform,
  problemSince,
  prPrint,
  sameRelease,
  targetVersion,
  unbuiltOn,
  unbuiltWhere,
  updateTitle,
  vulnFixes,
  waitingForChannel,
} from '../../page/status.js';
import { outdated, pkg } from './helpers.mjs';

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
  test("not the channel's release with a suffix Repology drops", () => {
    // firefox-esr: master 153.5.1esr, Repology 153.5.1; an older version kept
    // beside firefox's 158.0.1, not outdated against it.
    const esr = pkg({
      nixStatus: 'legacy',
      nixVersion: '153.5.1',
      refVersion: '158.0.1',
      master: '153.5.1esr',
      keptBeside: { attr: 'firefox', version: '158.0.1' },
    });
    assert.equal(aheadOnMaster(esr), false);
    assert.equal(computeStatus(esr), 'neutral');
    assert.equal(onMaster({ ...esr, masterPR: { to: '153.5.1esr' } }), null);
    assert.equal(sameRelease('153.5.1esr', '153.5.1'), true);
    assert.equal(sameRelease('1.0rc', '1.0'), false);
    assert.equal(sameRelease('1.0.1', '1.0'), false);
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

describe('nothingCompared', () => {
  test("unique with no other repository and no check of nixkeeper's own: grey", () => {
    const alone = { nixStatus: 'unique', onlyNixpkgs: true };
    assert.equal(computeStatus(alone), 'neutral');
    assert.equal(computeStatus({ ...alone, upstream: { version: '1' } }), 'ok');
    assert.equal(computeStatus({ ...alone, feed: { name: 'CRAN' } }), 'ok');
    assert.equal(computeStatus({ nixStatus: 'unique' }), 'ok');
  });
});

describe('vulnFixes', () => {
  // barman: 3.19.1, the newest 3.20.1, an update PR to it.
  const barman = (over = {}) =>
    outdated({ nixVersion: '3.19.1', refVersion: '3.20.1', openPR: { to: '3.20.1' }, ...over });
  test('what master, the update PR and the newest release fix', () => {
    const vulns = [{ fixedIn: '3.20.1' }, { fixedIn: '3.19.4' }, {}];
    assert.deepEqual(vulnFixes(barman(), vulns), {
      need: '3.20.1',
      named: 2,
      master: null,
      pr: 2,
      newest: 2,
    });
    const behind = barman({ openPR: { to: '3.20.0' }, master: '3.19.5' });
    assert.deepEqual(vulnFixes(behind, vulns), {
      need: '3.20.1',
      named: 2,
      master: 1,
      pr: 1,
      newest: 2,
    });
  });
  test('null when none names a version', () => {
    assert.equal(vulnFixes(barman(), [{}, { id: 'CVE-1' }]), null);
  });
});
