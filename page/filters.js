// What the list keeps: the tiles' filters (FILTERS), the refines and ages
// that narrow any list, the sorts and platforms, the tests a package
// passes (in a list, a set, a team, a maintainer's page...), and the list
// worked out with them (currentFiltered) and put in order (sortedList).
// The state says which are picked; app.js draws the list.

import { VIEWS } from './address.js';
import { inPickedSet, nameSet } from './facets.js';
import { maintainersKeep, matchesSearch, searchHandle, teamsKeep } from './people.js';
import { isHidden } from './prefs.js';
import { searchText } from './search.js';
import { attentionRank, buildsWith, failedBuilds, hasFailure, known, state } from './state.js';
import {
  botWontUpdate,
  buildFailedBecause,
  computeStatus,
  failedBecause,
  NEVER_BUILT,
  olderThan,
  onBranch,
  onPlatform,
  problemSince,
  targetVersion,
  unbuiltOn,
  unbuiltWhere,
  waitingForChannel,
} from './status.js';
import { store } from './store.js';
import { failingSince } from './ui.js';
import { versionGap } from './versions.js';
import { isVulnerable, severityRank } from './vulns.js';

// Its own state: what every filter but the facets kept, the last time the
// list was worked out (facetBase: the facets count over it, with no second
// pass), and whether rows hidden here are shown, greyed (showHidden).
export const filtering = { facetBase: [], showHidden: false };

export const inSet = (pkg) => !state.setFilter || pkg.set === state.setFilter;

// ?in=: one package set, by the attribute's first part (logic.js nameSet:
// python313Packages, vimPlugins, top-level); ?by=: one maintainer's
// packages within the list shown (a handle, lowercase). Counted, with the
// platforms, over the list's other filters (facetOptions).
export const inNameSet = (pkg) => !state.inFilter || inPickedSet(nameSet(pkg.name), state.inFilter);

export const byMaintainer = (pkg) =>
  !state.byFilter || (pkg.maintainers || []).some((m) => m.toLowerCase() === state.byFilter);

// What every filter but the facets kept, last time the list was worked out
// (currentFiltered): the facets count over it, with no second pass.
// The list's order (?sort=, SORTS key; the first, most pressing, is the
// default) and whether it's reversed (?order=reverse).
export const SORTS = {
  pressing: 'most pressing',
  oldest: 'longest-standing',
  newest: 'newest',
  gap: 'biggest version gap',
  az: 'name A–Z',
};

// null, or a list from package-lists/ ("maintained", "gaming-team", ...):
// ?list=gaming-team is a page of just that list's packages, to share.
export const inList = (pkg) => !state.listFilter || (pkg.lists || []).includes(state.listFilter);

// What the address keeps by people: its teams, and maintainers left out.
export const inPeople = (pkg) =>
  teamsKeep(
    pkg,
    { include: state.teamFilter, leftOut: state.teamsLeftOut, none: state.noTeam },
    shownHandle(),
  ) && maintainersKeep(pkg, state.maintainersLeftOut);

// The platform filter's choices, families and the systems nixpkgs builds
// ("any platform" counts as all: onPlatform), in nixpkgs' words
// (lib.platforms.darwin, aarch64-linux), other names on hover. `also`:
// another address that still picks it (?platform=macos, from before 0.14.0).
export const PLATFORMS = {
  linux: {
    label: 'Linux',
    param: 'linux',
    title: 'Linux: x86_64-linux (amd64) and aarch64-linux (arm64)',
  },
  'x86_64-linux': {
    label: 'Linux x86_64',
    param: 'x86_64-linux',
    title: 'Linux on x86_64 (amd64) only: not on aarch64-linux',
  },
  'aarch64-linux': {
    label: 'Linux aarch64',
    param: 'aarch64-linux',
    title: 'Linux on aarch64 (arm64) only: not on x86_64-linux',
  },
  darwin: {
    label: 'Darwin',
    param: 'darwin',
    also: 'macos',
    title: 'Darwin (macOS): aarch64-darwin (Apple silicon)',
  },
};

// Available on the platform picked: listed for it, and built there by Hydra
// when Hydra builds it at all (unbuiltOn); listed but not built counts only
// with "Not built where listed" on, or in its view, which find exactly
// those.
export function inPlatform(pkg) {
  if (!state.platformFilter) return true;
  if (!onPlatform(pkg, state.platformFilter)) return false;
  // Not built where listed (?view=unbuilt): a platform picked keeps those
  // not built there (Darwin: the Darwin ones), as the refine does.
  if (store.shownView === VIEWS.unbuilt) return unbuiltOn(pkg, state.platformFilter);
  return state.refines.has('unbuilt') || !unbuiltOn(pkg, state.platformFilter);
}

// `param` is how each filter appears in the page address (?filter=outdated).
export const FILTERS = {
  all: { label: 'tracked', test: () => true },
  warn: {
    label: 'outdated',
    param: 'outdated',
    color: 'var(--warn)',
    test: (p) => computeStatus(p) === 'warn',
  },
  failed: { label: 'failed', param: 'failed', color: 'var(--danger)', test: (p) => hasFailure(p) },
  // With every package only, the two kinds of failing apart (tiles, cards).
  builds: {
    label: 'build failures',
    param: 'builds',
    color: 'var(--danger)',
    test: (p) => failedBuilds(p).length > 0,
  },
  updates: {
    label: 'update failures',
    param: 'updates',
    color: 'var(--caution)',
    test: (p) => Boolean(p.updateFailure),
  },
  vuln: {
    label: 'flagged vulnerable',
    param: 'vulnerable',
    color: 'var(--danger)',
    // Repology's flag, or nixpkgs marking it insecure.
    test: isVulnerable,
  },
  // A CVE fixed on unstable, the newest release still affected
  // (nixkeeper-vulnerabilities): not in Vulnerable's count, unstable having
  // the fix.
  backport: {
    label: 'fixes to backport',
    param: 'backport',
    color: 'var(--danger)',
    test: (p) => (p.backport || []).length > 0,
  },
  // A build Hydra didn't try, as a dependency failed (nixkeeper-hydra says
  // which): not failing itself, so in no other count.
  blocked: {
    label: 'blocked',
    param: 'blocked',
    color: 'var(--caution)',
    test: (p) => buildsWith(p, 'dependency').length > 0,
  },
  // With every package only (tiles of the header, renderScope).
  broken: {
    label: 'marked broken',
    param: 'broken',
    color: 'var(--caution)',
    test: (p) => p.markedBroken || buildsWith(p, 'broken').length > 0,
  },
};

// What narrows any list, together with its other filters: each is left
// out or kept whatever the tile (?refine=); "older than" (?age=) goes by
// how long the tile's kind of problem has lasted (any, with none picked).
export const REFINES = {
  unmaintained: {
    label: 'Without maintainer',
    title: 'Only packages with no maintainer in nixpkgs',
    test: (p) => !(p.maintainers || []).length,
  },
  notbroken: {
    label: 'Not marked broken',
    title: "Leave out what nixpkgs marks broken: failures nobody's marked yet",
    test: (p) => !FILTERS.broken.test(p),
  },
  // Its update merged somewhere, on its way: master (waiting for
  // nixos-unstable), staging or staging-next, a branch like haskell-updates.
  notonmaster: {
    label: 'Not merged yet',
    title:
      'Leave out outdated packages whose update is already merged: on master (waiting for nixos-unstable), into staging or staging-next, or a branch like haskell-updates',
    test: (p) => !waitingForChannel(p) && !p.stagingPR && !onBranch(p),
  },
  // A forecast (branches.apply_staging_next_breaks): builds on master,
  // fails its own build on staging-next at the same version.
  stagingnext: {
    label: 'Breaks on staging-next',
    title:
      'Only packages that build on master but fail their own build on staging-next, at the same version: unless fixed, they fail on master when staging-next is merged into it',
    test: (p) => Boolean(p.stagingNextBreaks),
  },
  // Something open on GitHub about it: for a broken package, maybe its fix.
  // Picked in the "Open PR" select (pick: 'pr'), not a chip: one or the
  // other.
  withpr: {
    label: 'with one',
    pick: 'pr',
    title:
      'Only packages an open PR touches: for one marked broken, maybe its fix (or moot: a person checks)',
    test: (p) => (p.openPRs || 0) > 0,
  },
  nopr: {
    label: 'without',
    pick: 'pr',
    title: 'Only packages no open PR touches: nobody is on it yet',
    test: (p) => !((p.openPRs || 0) > 0),
  },
  // Listed for a platform Hydra doesn't build it on (unbuiltWhere): a
  // dependency missing there, or meta.platforms promising too much. With a
  // platform picked, that platform's only.
  unbuilt: {
    label: 'Not built where listed',
    title:
      "Only packages nixpkgs lists for a platform Hydra doesn't build them on (no build exists there): usually a dependency isn't available there, or meta.platforms promises too much",
    test: (p) =>
      state.platformFilter
        ? onPlatform(p, state.platformFilter) && unbuiltOn(p, state.platformFilter)
        : unbuiltWhere(p).length > 0,
  },
  // Where a person is needed: nixpkgs-update won't open the PR.
  // An open update PR nixpkgs is already past (prs_digest.mark_superseded).
  superseded: {
    label: 'PR to close',
    title:
      'Only packages with an open PR nixpkgs is already past: an update PR to its version or an older one, or an init PR for a package it has now, so the PR can be closed',
    test: (p) => (p.supersededPRs || []).length > 0,
  },
  nobot: {
    label: "Bot won't update it",
    title:
      "Only outdated packages nixpkgs-update won't update by itself: it can't, it skips them on purpose, or it has never tried and they aren't in its queue. No update PR open or merged yet",
    test: (p) => botWontUpdate(p, Boolean(store.sources?.queue?.used)),
  },
};

export const AGES = {
  '1m': 'a month',
  '6m': '6 months',
  '1y': 'a year',
  '2y': '2 years',
  '3y': '3 years',
  [NEVER_BUILT]: 'never built',
};

// What the address can name, for state.js's readState and writeState.
export const KNOWN = { FILTERS, SORTS, PLATFORMS, REFINES, AGES };
Object.assign(known, KNOWN);

// kind: whose age counts (a FILTERS key): the list's, or a count's own.
export const refined = (p, kind = state.activeFilter) =>
  [...state.refines].every((key) => REFINES[key].test(p)) &&
  (!state.newerFilter || (state.newerFilter === 'yes') === (computeStatus(p) === 'warn')) &&
  (!state.becauseFilter || failedBecause(p) === state.becauseFilter) &&
  (!state.buildFailedFilter ||
    buildFailedBecause(p, state.platformFilter).includes(state.buildFailedFilter)) &&
  olderThan(p, state.ageFilter, kind, Date.now(), state.platformFilter);

// The maintainer whose page this is (@handle in the search), or null.
export const shownHandle = () => searchHandle(searchText());

export const notHidden = (pkg) => filtering.showHidden || !isHidden(pkg);

// What every filter but the facets (set, maintainer, platform) keeps.
export const passesOthers = (p, q) =>
  inList(p) &&
  inPeople(p) &&
  inSet(p) &&
  notHidden(p) &&
  refined(p) &&
  FILTERS[state.activeFilter].test(p) &&
  matchesSearch(p, q);

export function currentFiltered() {
  const q = searchText();
  filtering.facetBase = store.packages.filter((p) => passesOthers(p, q));
  const list = filtering.facetBase.filter((p) => inPlatform(p) && inNameSet(p) && byMaintainer(p));
  return sortedList(list, state.sortReverse ? -1 : 1);
}

// The list in the order picked (sortMode), reversed with dir -1; those with
// nothing to sort by (no date, no newer version) last either way. Each
// package's key worked out once, not at every comparison: sorting every
// package compares about 170,000 pairs, and on a mid-range phone working
// them out each time took half a second (Lighthouse, 2026-10-07). ISO dates
// in UTC compare correctly as plain strings; undated ones last ("~").
export function sortedList(list, dir = 1) {
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // The data arrives sorted by name, and Array.sort is stable.
  if (state.sortMode === 'az') return dir > 0 ? list : [...list].reverse();
  if (state.sortMode === 'oldest' || state.sortMode === 'newest') {
    // How long its problem has lasted (the tile's kind, when one is picked).
    const keyed = list.map((p) => ({ p, since: problemSince(p, state.activeFilter) || '' }));
    const order = state.sortMode === 'oldest' ? dir : -dir;
    keyed.sort((a, b) =>
      !a.since || !b.since ? !a.since - !b.since : order * cmp(a.since, b.since),
    );
    return keyed.map((k) => k.p);
  }
  if (state.sortMode === 'gap') {
    // The biggest update first (versionGap); numbering changes, then none
    // (no newer version known), last either way.
    const keyed = list.map((p) => ({
      p,
      gap: computeStatus(p) === 'warn' ? versionGap(p.nixVersion, targetVersion(p)) : null,
    }));
    keyed.sort((a, b) =>
      !a.gap || !b.gap
        ? !a.gap - !b.gap
        : a.gap.scheme - b.gap.scheme ||
          dir * (a.gap.level - b.gap.level || b.gap.step - a.gap.step),
    );
    return keyed.map((k) => k.p);
  }
  // Most pressing. The vulnerable ones: worst severity first (in the order
  // they had).
  if (state.activeFilter === 'vuln') {
    const ranked = list.map((p) => ({ p, rank: severityRank(p) }));
    ranked.sort((a, b) => dir * (a.rank - b.rank));
    return ranked.map((k) => k.p);
  }
  // Worst first, then longest first.
  const keyed = list.map((p) => {
    const rank = attentionRank(p);
    const since = rank === 1 ? p.outdatedSince : rank === 0 ? failingSince(p) : null;
    return { p, rank, since: since || '~' };
  });
  keyed.sort((a, b) => dir * (a.rank - b.rank || (a.rank <= 1 ? cmp(a.since, b.since) : 0)));
  return keyed.map((k) => k.p);
}
