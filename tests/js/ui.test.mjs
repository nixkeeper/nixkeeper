// The small pieces of text the page shares (page/ui.js). Run:
// node --test tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { forgeName, upstreamKind, upstreamRepoLabel, upstreamRepoText } from '../../page/ui.js';

describe('upstream repository', () => {
  test('renamed: the same owner, another name', () => {
    const u = { repo: 'emilazy/autopen', movedTo: 'emilazy/boot-security-tools' };
    assert.equal(upstreamRepoLabel(u), 'upstream renamed');
    assert.match(upstreamRepoText(u), /^Its repository on GitHub was renamed: /);
  });

  test('moved: another owner, with or without another name', () => {
    const owner = { repo: 'jdx/aube', movedTo: 'aubepkg/aube' };
    assert.equal(upstreamRepoLabel(owner), 'upstream moved');
    assert.match(upstreamRepoText(owner), /moved to another owner: /);
    const both = { repo: 'coq/coq', movedTo: 'rocq-prover/rocq' };
    assert.equal(upstreamRepoLabel(both), 'upstream moved');
    assert.match(upstreamRepoText(both), /moved to another owner and renamed: /);
  });

  test("an owner's case only isn't another owner", () => {
    const u = { repo: 'Feromond/budget_tracker_tui', movedTo: 'feromond/budget-tracker-tui' };
    assert.equal(upstreamRepoLabel(u), 'upstream renamed');
  });

  test('on GitLab and Codeberg: the owner past the host, the forge named', () => {
    // GitLab's projects nest in groups: the owner is the top group.
    const nested = {
      forge: 'gitlab',
      repo: 'gitlab.com/cubocore/coreapps/a',
      movedTo: 'gitlab.com/cubocore/apps/a',
    };
    assert.equal(upstreamKind(nested), 'renamed');
    const moved = {
      forge: 'gitlab',
      repo: 'gitlab.com/warsaw/public',
      movedTo: 'gitlab.com/flufl/public',
    };
    assert.equal(upstreamKind(moved), 'moved');
    assert.match(
      upstreamRepoText(moved),
      /^Its repository on GitLab was moved to another owner: .* which GitLab now redirects/,
    );
    const fdo = { forge: 'gitlab', repo: 'gitlab.freedesktop.org/libevdev/evtest', archived: true };
    assert.equal(forgeName(fdo), 'gitlab.freedesktop.org');
    assert.match(
      upstreamRepoText(fdo),
      /^Its repository, gitlab\.freedesktop\.org\/libevdev\/evtest, is archived/,
    );
    const gone = { forge: 'forgejo', repo: 'codeberg.org/o/r', gone: true };
    assert.match(
      upstreamRepoText(gone),
      /^Its repository, codeberg\.org\/o\/r, is gone: Codeberg doesn't know it/,
    );
    assert.equal(forgeName({ repo: 'o/r' }), 'GitHub');
  });

  test('archived or gone come first', () => {
    const archived = { repo: 'uw-labs/bloomrpc', archived: true, movedTo: 'bloomrpc/bloomrpc' };
    assert.equal(upstreamRepoLabel(archived), 'upstream archived');
    assert.match(upstreamRepoText(archived), /It was also moved to another owner: /);
    assert.equal(upstreamRepoLabel({ repo: 'x/y', gone: true }), 'upstream gone');
  });
});
