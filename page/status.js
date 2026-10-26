// A package's status from its data alone: outdated, failing, waiting for
// the channel, how urgent, and since when. Where a rule depends on the
// selected platform, it takes it as an argument (null for all platforms).

import { AGE_DAYS, DAY } from './dates.js';
import { compareVersions } from './versions.js';
import { isVulnerable, vulnSummary } from './vulns.js';

// Whether pkg is available on key: a family ("linux", "darwin") or a system
// ("x86_64-linux"). "any platform" (no restriction in nixpkgs) counts as all.
// platforms.systems, when there, says which systems of a family it's on
// (available_on in nixkeeper/sources/nixpkgs.py); without it, all of them.
export function onPlatform(pkg, key) {
  const pl = pkg.platforms;
  if (pl === null) return true;
  const family = key.split('-').pop();
  if (!pl?.[family]) return false;
  return key === family || !pl.systems || pl.systems.includes(key);
}

// A build is on platform: its system, or any system of that family.
const onSystem = (system, platform) =>
  platform.includes('-') ? system === platform : system.endsWith(`-${platform}`);

// Listed for key (a family or a system) but not built there by Hydra: none
// of its builds there exists ("notBuilt": no job, usually as a dependency
// isn't available there, so the job fails to evaluate and Hydra drops it),
// while Hydra builds it elsewhere (not a package Hydra skips altogether:
// unfree, or kept off it). 1,659 Darwin listings on 2026-10-19, juce's and
// driftnet's among them.
export function unbuiltOn(pkg, key) {
  const here = (pkg.builds || []).filter((b) => onSystem(b.system, key));
  return (
    here.length > 0 &&
    here.every((b) => b.status === 'notBuilt') &&
    (pkg.builds || []).some((b) => !onSystem(b.system, key) && b.status !== 'notBuilt')
  );
}

// What a package needs attention for, as one string: hidden ("Hide until
// it changes") while it stays the same. Its status, the version it's
// outdated against, each failing build (system and status), the update
// bot's outcome and why it failed, its counted CVEs, and nixpkgs' broken
// mark: any of them changing (1.3 out after 1.2 was hidden, a new failing
// system, a new CVE) brings it back. A vulnerable package's has the sync's
// time too (checkedAt): a CVE comes back at the next sync, never hidden
// for long.
export function attentionPrint(pkg, checkedAt = '') {
  const failing = (pkg.builds || [])
    .filter((b) => b.status === 'failed' || b.status === 'dependency')
    .map((b) => `${b.system}:${b.status}`)
    .sort();
  return JSON.stringify([
    computeStatus(pkg),
    pkg.refVersion || '',
    failing,
    pkg.updateFailure ? [pkg.update?.outcome || '', pkg.update?.failedBecause || ''] : [],
    // The list's entry has vuln, the full row vulnerabilities: the same
    // count either way (vulnSummary), so a panel's hide matches the list.
    vulnSummary(pkg)?.n || (pkg.nixVulnerable ? 1 : 0),
    Boolean(pkg.markedBroken),
    isVulnerable(pkg) ? checkedAt || '' : '',
  ]);
}

// What a PR of "You can merge these" is, as one string: hidden there
// ("Hide") while it stays the same. Its title, which the update bot
// rewrites when it pushes a newer version ("foo: 1.2 -> 1.4"), and whether
// it's for a vulnerable package. Not upstream moving on ("behind"): a PR
// held back on purpose stays hidden through new releases.
export function prPrint(pr) {
  return JSON.stringify([pr.title, Boolean(pr.vulnerable)]);
}

// The systems pkg is listed for but not built on (unbuiltOn), each Linux
// system apart, Darwin as one: [] when Hydra builds it everywhere listed.
export function unbuiltWhere(pkg) {
  return ['x86_64-linux', 'aarch64-linux', 'darwin'].filter(
    (key) => onPlatform(pkg, key) && unbuiltOn(pkg, key),
  );
}

// Follows Repology's statuses, but "legacy" (an older version nixpkgs keeps
// beside a newer one under another attribute: tracy_0_11 beside tracy) isn't
// outdated by itself: only by a newer release in its own series (an update
// check), or, for a devel variant (a beta), a newer devel version elsewhere
// (config.KEPT in nixkeeper). Whether a row is a devel variant comes
// separately from pkg.devel and only shades its "devel" badge.
// Repology's "unique" with nothing to compare: no repository outside
// nixpkgs has it, and no update check or feed of nixkeeper's own knows its
// releases (python313Packages.pbar2): not up to date, not compared
// (datastore.nothing_compared).
export const nothingCompared = (pkg) =>
  pkg.nixStatus === 'unique' && Boolean(pkg.onlyNixpkgs) && !pkg.upstream && !pkg.feed;

export function computeStatus(pkg) {
  if (pkg.nixStatus === 'missing') return 'missing';
  if (pkg.nixStatus === 'outdated') return 'warn';
  if (
    pkg.nixStatus === 'legacy' &&
    pkg.devel &&
    pkg.refVersion &&
    pkg.nixVersion &&
    compareVersions(pkg.refVersion, pkg.nixVersion) > 0
  )
    return 'warn';
  // nixkeeper's own update check found a release Repology hasn't seen.
  if (pkg.upstream?.newer) return 'warn';
  // Or master already has a newer version than the channel.
  if (aheadOnMaster(pkg)) return 'warn';
  if (nothingCompared(pkg)) return 'neutral';
  if (pkg.nixStatus === 'newest' || pkg.nixStatus === 'unique' || pkg.nixStatus === 'devel')
    return 'ok';
  return 'neutral';
}

// An older version nixpkgs keeps on purpose beside a newer one (Repology's
// "legacy"), and nothing newer in its own series: shown as such, not as
// outdated. pkg.keptBeside names the newer one, when the data has it.
export function olderVersionKept(pkg) {
  return pkg.nixStatus === 'legacy' && computeStatus(pkg) !== 'warn';
}

// Hydra builds with a status, on the selected platform only while one is.
export function buildsWith(pkg, status, platform = null) {
  return (pkg.builds || []).filter(
    (b) => b.status === status && (!platform || onSystem(b.system, platform)),
  );
}

// Everything shown in red: not found in nixpkgs, or a build or update
// failure reported.
export function hasFailure(pkg, platform = null) {
  return (
    computeStatus(pkg) === 'missing' ||
    buildsWith(pkg, 'failed', platform).length > 0 ||
    Boolean(pkg.updateFailure)
  );
}

// The version master has, when ahead of the channel: Hydra's build there, or
// what an update PR merged into master brings (before Hydra has built it),
// whichever is higher (on_master in nixkeeper/changes.py).
export function onMaster(pkg) {
  const versions = [pkg.master, pkg.masterPR?.to].filter(
    (v) => v && !sameRelease(v, pkg.nixVersion),
  );
  return versions.sort(compareVersions).pop() || null;
}

// Outdated, but master already has the target version (or newer): the update
// is merged and waits for nixos-unstable, usually a few days (see
// waiting_for_channel in nixkeeper/changes.py).
export function waitingForChannel(pkg) {
  return (
    computeStatus(pkg) === 'warn' &&
    Boolean(onMaster(pkg)) &&
    compareVersions(targetVersion(pkg) || '', onMaster(pkg)) <= 0
  );
}

// Outdated, and nixpkgs-update won't update it by itself, so it takes
// someone: the bot can't (none of its ways apply), passes it over on
// purpose (skipped), or has never tried it and isn't about to (not in its
// queue; queueRead: whether the data has the queue at all). Not while an
// update PR is open or merged (someone is on it), nor where the bot's
// attempts aren't known (generated sets, not read yet, not in nixpkgs).
export function botWontUpdate(pkg, queueRead = true) {
  if (computeStatus(pkg) !== 'warn' || pkg.pending || pkg.update === undefined) return false;
  if (pkg.openPR || waitingForChannel(pkg)) return false;
  const outcome = pkg.update?.outcome;
  if (outcome === 'cantUpdate' || outcome === 'skipped') return true;
  return pkg.update === null && !pkg.unread?.includes('update') && !(queueRead && pkg.queued);
}

// Outdated, but the branch that updates its set before master
// (haskell-updates: pkg.branch) already has the target version or newer:
// waiting for the branch's merge into master (on_branch in
// nixkeeper/changes.py).
export function onBranch(pkg) {
  return (
    computeStatus(pkg) === 'warn' &&
    Boolean(pkg.branch?.version) &&
    compareVersions(targetVersion(pkg) || '', pkg.branch.version) <= 0
  );
}

// Whether version is the channel's release with a suffix Repology leaves
// out of nixpkgs' version (firefox-esr's 153.5.1esr is 153.5.1 there), not
// a newer one; a pre-release's suffix isn't that (same_release in
// nixkeeper/changes.py).
export function sameRelease(version, channel) {
  if (!version || !channel || !version.startsWith(channel)) return false;
  const rest = version.slice(channel.length);
  return (
    /^[A-Za-z]+$/.test(rest) && !/^(a|b|c|alpha|beta|rc|pre|preview|dev|snapshot)$/i.test(rest)
  );
}

// Hydra's build of master is newer than the channel's version: there's a
// newer release, whatever Repology and the update checks know
// (ahead_on_master in nixkeeper/changes.py). Not the channel's release
// with a suffix Repology drops (sameRelease).
export function aheadOnMaster(pkg) {
  return (
    Boolean(pkg.master && pkg.nixVersion) &&
    compareVersions(pkg.master, pkg.nixVersion) > 0 &&
    !sameRelease(pkg.master, pkg.nixVersion)
  );
}

// Whether the version to update to is master's, newer than anything
// Repology or an update check knows (count_master in nixkeeper/changes.py;
// data from before that rule only has master, not refFromMaster).
export function fromMaster(pkg) {
  return (
    aheadOnMaster(pkg) &&
    (Boolean(pkg.refFromMaster) ||
      !pkg.refVersion ||
      compareVersions(pkg.master, pkg.refVersion) > 0)
  );
}

// Whether the package's update check is a community rule
// (community/update-checks.nix): its result says so, or its failure does.
export function communityCheck(pkg) {
  return Boolean(
    pkg.upstream?.community || pkg.notRefreshed?.upstream?.reason?.startsWith('community rule'),
  );
}

// nixkeeper's own entry among the repositories a package is compared
// against, first: its update check's version (your rule, a community rule,
// or worked out from nixpkgs' source), "ahead" when it counts as newer than
// nixpkgs', as a repository's newest version is. kind and where (the tags,
// the page) say where it came from. null without a result.
export function nixkeeperEntry(pkg) {
  const up = pkg.upstream;
  if (!up?.version) return null;
  return {
    repo: 'nixkeeper',
    version: up.version,
    ahead: Boolean(up.newer),
    kind: up.community
      ? 'A community update check'
      : up.inferred
        ? "Worked out from nixpkgs' source"
        : 'Your update check',
    where: up.label || (up.repo ? `${up.repo} tags` : ''),
  };
}

// The version an update would bring.
export function targetVersion(pkg) {
  return fromMaster(pkg) ? pkg.master : pkg.refVersion;
}

// What fixes a package's CVEs, from the versions their ranges say fix them
// (fixedIn, fixed_in in nixkeeper/sources/vulnerabilities_digest.py): the
// version that fixes all of those (need), how many name one, and how many
// master, the open update PR and the newest release each fix. null when
// none names one.
export function vulnFixes(pkg, vulns) {
  const named = vulns.filter((v) => v.fixedIn);
  if (!named.length) return null;
  const fixes = (version) =>
    version ? named.filter((v) => compareVersions(version, v.fixedIn) >= 0).length : null;
  return {
    need: named
      .map((v) => v.fixedIn)
      .sort(compareVersions)
      .pop(),
    named: named.length,
    master: fixes(onMaster(pkg)),
    pr: fixes(pkg.openPR?.to),
    newest: fixes(targetVersion(pkg)),
  };
}

// Default order: failed, then outdated (longest outdated first), then
// outdated but already fixed on master, then the rest; otherwise
// alphabetical (the index arrives sorted by name and Array.sort is stable).
export function attentionRank(pkg, platform = null) {
  if (hasFailure(pkg, platform)) return 0;
  if (waitingForChannel(pkg)) return 1.5;
  if (computeStatus(pkg) === 'warn') return 1;
  return 2;
}

// Why a package's latest update attempt failed (its "update.failedBecause",
// read from the bot's log): "other" when none was recognised; null when its
// attempt didn't fail. ?updateFailed= narrows a list to one.
export function failedBecause(pkg) {
  if (!pkg.updateFailure) return null;
  return pkg.update?.failedBecause || 'other';
}

// Why a package's failed builds failed (on platform, when given), each
// once: nixkeeper-hydra's reasons, from their logs ("unread" while a log
// isn't read yet). ?buildFailed= narrows a list to one. Empty when no build
// failed.
export function buildFailedBecause(pkg, platform = null) {
  return [...new Set(buildsWith(pkg, 'failed', platform).map((b) => b.failedBecause || 'unread'))];
}
export const NEVER_BUILT = 'never';

// Since when a row has had the problem kind names (the list's filter):
// failing (its builds or update attempts, the earlier; or builds or updates
// alone), outdated, or for any other, the earliest of them; null when it has
// none of them.
export function problemSince(pkg, kind) {
  const failing = [pkg.failingSince, pkg.updateFailingSince];
  const dates =
    kind === 'failed'
      ? failing
      : kind === 'builds'
        ? [pkg.failingSince]
        : kind === 'updates'
          ? [pkg.updateFailingSince]
          : kind === 'warn'
            ? [pkg.outdatedSince]
            : [...failing, pkg.outdatedSince];
  return dates.filter(Boolean).sort()[0] || null;
}

// The systems where a row's failing builds never succeeded on Hydra
// (neverBuiltOn), only those on platform when one is picked.
export const neverBuiltOn = (pkg, platform = null) =>
  (pkg.neverBuiltOn || []).filter((system) => !platform || onSystem(system, platform));

// Whether a row has had that problem for longer than age (an AGE_DAYS key;
// NEVER_BUILT: a failing build of it never succeeded, on platform if one is
// picked, for any kind of problem but outdated and update failures; any
// other: no limit, so every row is).
export function olderThan(pkg, age, kind, now = Date.now(), platform = null) {
  if (age === NEVER_BUILT)
    return neverBuiltOn(pkg, platform).length > 0 && kind !== 'warn' && kind !== 'updates';
  if (!AGE_DAYS[age]) return true;
  const since = problemSince(pkg, kind);
  return Boolean(since) && now - new Date(since).getTime() > AGE_DAYS[age] * DAY;
}

// An update's title as nixpkgs writes it, for commits and PRs:
// "unciv: 4.22.1 -> 4.22.6". Only for an outdated package with a known
// newest version; null otherwise.
// Starting from master's version when master is partway there (the next
// update goes on from it): "google-chrome: 154.0.8037.92 -> 154.0.8037.97".
export function updateTitle(pkg) {
  const target = targetVersion(pkg);
  const from = midway(pkg) || pkg.nixVersion;
  return computeStatus(pkg) === 'warn' && from && target
    ? `${pkg.name}: ${from} -> ${target}`
    : null;
}

// Master's version when it's partway between the channel and the newest: an
// update merged (waiting for the channel), and a newer one after it. Null
// otherwise (nothing on master, or master already has the newest).
export function midway(pkg) {
  const master = onMaster(pkg);
  const target = targetVersion(pkg);
  return computeStatus(pkg) === 'warn' &&
    master &&
    target &&
    pkg.nixVersion &&
    compareVersions(master, pkg.nixVersion) > 0 &&
    compareVersions(master, target) < 0
    ? master
    : null;
}
