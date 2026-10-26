// The list: its header (where it's from, the tiles, the refines and facets,
// Your packages and Your team), each package's row and its cells (version,
// builds, updates, GitHub), and the sources it was worked out from. HTML
// from the store, the state and the filters; app.js draws it (render) and
// handles its controls. Its own state is listView.

import { viewSlug } from './address.js';
import { daysText, daysUntil, shortAge, timeAgo } from './dates.js';
import {
  AGES,
  byMaintainer,
  FILTERS,
  filtering,
  inList,
  inNameSet,
  inPeople,
  inPlatform,
  inSet,
  notHidden,
  PLATFORMS,
  REFINES,
  refined,
  SORTS,
  shownHandle,
} from './filters.js';
import {
  buildFailedBecause,
  communityCheck,
  computeStatus,
  facetCounts,
  failedBecause,
  familyLabel,
  faviconKey,
  inPickedSet,
  midway,
  NAME_STATUSES,
  nameSet,
  neverBuiltOn,
  nothingCompared,
  olderVersionKept,
  onBranch,
  onMaster,
  onPlatform,
  TOP_LEVEL,
  targetVersion,
  unbuiltOn,
  unbuiltWhere,
  updateTitle,
  waitingForChannel,
} from './logic.js';
import { closeHtml, mergeHtml } from './maintainer-view.js';
import { html, raw, safeUrl, setHtml } from './markup.js';
import { isHidden, remember } from './prefs.js';
import { REFINE_WORDS, searchText } from './search.js';
import { buildsWith, failedBuilds, hasFailure, scopeHref, state, teamName } from './state.js';
import { store } from './store.js';
import {
  archivedText,
  BUILD_FAILED,
  bulkShort,
  bulkText,
  FAILED_BECAUSE,
  failingSince,
  fmt,
  GH_ICONS,
  hydraBuildsIt,
  hydraBuildUrl,
  LOOKUP_FAILED,
  longDate,
  notRefreshed,
  ONLY_NIXPKGS_TEXT,
  profileOf,
  stagingWait,
  staleText,
  teamPicker,
  UNSUPPORTED_TEXT,
  UNVERSIONED_TITLE,
} from './ui.js';
import { compareVersions, versionDiff } from './versions.js';
import { isVulnerable, vulnSources, vulnSummary } from './vulns.js';

// Its own state. The visitor's own GitHub handle, for "Your packages" (kept
// in their browser only, nixkeeper-handle), how many packages list them
// once their view is loaded, and whether it's being edited; their team
// (nixkeeper-team), for "Your team", the same. Packages one update moves
// together, folded into one row (foldFamilies): the folds of the list
// drawn (lead's name → its fold), and the names shown behind an open one's
// lead.
export const listView = {
  myHandle: null,
  myCount: null,
  editingHandle: false,
  myTeam: null,
  editingTeam: false,
  folds: new Map(),
  inOpenFold: new Set(),
  // The folds opened (by key, until reload).
  openFolds: new Set(),
};

// Every list some package is on: "maintained" first, as the sync sorts them.
export function allLists() {
  // With every package, the view has only some: the manifest has them all.
  if (store.community)
    return Object.keys(store.manifest.views?.lists || {}).sort((a, b) =>
      a === 'maintained'
        ? -1
        : b === 'maintained'
          ? 1
          : a.localeCompare(b, undefined, { sensitivity: 'base' }),
    );
  const seen = [];
  for (const p of store.packages)
    for (const l of p.lists || []) if (!seen.includes(l)) seen.push(l);
  return seen.sort((a, b) =>
    a === 'maintained' ? -1 : b === 'maintained' ? 1 : a.localeCompare(b),
  );
}

// The systems of a family nixpkgs builds (SYSTEMS in nixkeeper/sources/nixpkgs.py).
export const LINUX_SYSTEMS = ['x86_64-linux', 'aarch64-linux'];

// The sync runs daily; older than this means runs are failing or GitHub has
// paused the schedule (it does after 60 days without commits).
export const STALE_AFTER_HOURS = 48;

// ?team='s teams left out, ?maintainer='s maintainers left out, and none
// (packages without a team) where no maintainer's page has its button:
// each a chip to undo it.
export const teamOutChips = () =>
  html`${state.maintainersLeftOut.map(
    (h) =>
      html`<button type="button" class="plat-filter" data-maintainer-out="${h}" title="Show @${h}'s packages again">not @${h} ✕</button>`,
  )}${state.teamsLeftOut.map(
    (t) =>
      html`<button type="button" class="plat-filter" data-team-out="${t}" title="Show the ${t} team's packages again">not ${t} ✕</button>`,
  )}${
    state.noTeam && !shownHandle()
      ? html`<button type="button" class="plat-filter" data-team-none title="Show packages with a team again">no team ✕</button>`
      : ''
  }`;

// "Failed because" (?updateFailed=): the reasons update attempts failed, each
// with how many of the list's packages it is (as the tiles count: the
// other filters but this one), the commonest first; those with none left
// out, but the one picked.
export function becauseCounts() {
  const base = store.packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && failedBecause(p),
  );
  const counts = {};
  for (const p of base) {
    const why = failedBecause(p);
    counts[why] = (counts[why] || 0) + 1;
  }
  return counts;
}
export function becausePick() {
  const counts = becauseCounts();
  const label = (key) => (key === 'noLog' ? 'build, no log' : FAILED_BECAUSE[key]?.short || key);
  const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
  if (state.becauseFilter && !keys.includes(state.becauseFilter)) keys.push(state.becauseFilter);
  if (!keys.length) return '';
  return html`<label class="refine-age" title="Update failures for one reason, as nixpkgs-update's log says (its last attempt). The counts are of this list, with its other filters">Update failed because <select data-because><option value="">any reason</option>${keys.map(
    (key) =>
      html`<option value="${key}"${state.becauseFilter === key ? raw(' selected') : ''}>${label(key)} (${fmt(counts[key] || 0)})</option>`,
  )}</select></label>`;
}

// "Build failed because" (?buildFailed=): the reasons builds failed on Hydra
// (from their logs, nixkeeper-hydra), each with how many of the list's
// packages have a failed build for it (on the platform picked), the
// commonest first; as becausePick.
export function buildFailedCounts() {
  const base = store.packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && failedBuilds(p).length,
  );
  const counts = {};
  for (const p of base)
    for (const why of buildFailedBecause(p, state.platformFilter))
      counts[why] = (counts[why] || 0) + 1;
  return counts;
}
export function buildFailedPick() {
  const counts = buildFailedCounts();
  // Not before nixkeeper-hydra read any: nothing to pick from.
  if (!Object.keys(counts).some((k) => k !== 'unread') && !state.buildFailedFilter) return '';
  const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
  if (state.buildFailedFilter && !keys.includes(state.buildFailedFilter))
    keys.push(state.buildFailedFilter);
  return html`<label class="refine-age" title="Build failures for one reason, as the build's log on Hydra says. The counts are of this list, with its other filters">Build failed because <select data-build-failed><option value="">any reason</option>${keys.map(
    (key) =>
      html`<option value="${key}"${state.buildFailedFilter === key ? raw(' selected') : ''}>${BUILD_FAILED[key]?.short || key} (${fmt(counts[key] || 0)})</option>`,
  )}</select></label>`;
}

// With Build failures or Failed picked: every failing row's errors at once.
export function errorsPick() {
  if (state.activeFilter !== 'builds' && state.activeFilter !== 'failed') return '';
  return html`<button type="button" class="refine-btn" data-show-errors aria-pressed="${state.showErrors}" title="${state.showErrors ? 'On: click to close them' : 'Open every failing package’s builds under it, with the lines from each log: loaded as they scroll into view'}">Show errors</button>`;
}

// "Newer version": any, known (?newer=yes), none known (?newer=no).
export function newerPick() {
  return html`<label class="refine-age" title="Whether a newer version than nixpkgs' is known: with Build failures, none known means an update won't fix it, the build needs fixing">Newer version <select data-newer><option value="">any</option>${[
    ['yes', 'known'],
    ['no', 'none known'],
  ].map(
    ([key, label]) =>
      html`<option value="${key}"${state.newerFilter === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label>`;
}

// The order: a choice of SORTS, and ↓/↑ reversing it.
export function sortPick() {
  return html`<label class="refine-age" title="The list's order">Sort <select data-sort>${Object.entries(
    SORTS,
  ).map(
    ([key, label]) =>
      html`<option value="${key}"${state.sortMode === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label><button type="button" class="refine-btn sort-dir" data-sort-dir aria-pressed="${state.sortReverse}" aria-label="Reverse the order" title="${state.sortReverse ? 'Reversed: click for the usual order' : 'Reverse the order'}">${state.sortReverse ? '↑' : '↓'}</button>`;
}

// Why "Breaks on staging-next" finds nothing now, when the sync didn't use
// staging-next's evaluation (its sources: "of the cycle merged into
// master..."), or null.
export const stagingNextWhy = () => {
  const s = store.sources?.['branch:staging-next'];
  return s && !s.used && s.why ? s.why : null;
};

// "Open PR": any, with one (?refine=withpr), without (?refine=nopr).
export function prPick() {
  const picked = ['withpr', 'nopr'].find((key) => state.refines.has(key)) || '';
  return html`<label class="refine-age" title="Whether an open PR touches it: for one marked broken, maybe its fix; without one, nobody is on it yet">Open PR <select data-pr-pick><option value="">any</option>${[
    'withpr',
    'nopr',
  ].map(
    (key) =>
      html`<option value="${key}"${picked === key ? raw(' selected') : ''}>${REFINES[key].label}</option>`,
  )}</select></label>`;
}

// The facets' choices with how many each would show: each counted over
// what the list's other filters keep (facetBase), its own left out (the
// sets as with the maintainer and platform picked). The platforms: of
// those, how many are on each (with a platform picked, the tiles' tests
// stay its own: failing on Darwin, how many are on Linux too).
export const BY_SHOWN = 300; // the maintainers offered, the most first

export function facetOptions() {
  const sets = facetCounts(
    filtering.facetBase.filter((p) => byMaintainer(p) && inPlatform(p)),
    (p) => nameSet(p.name),
  );
  const by = facetCounts(
    filtering.facetBase.filter((p) => inNameSet(p) && inPlatform(p)),
    (p) =>
      (p.maintainers || []).length > 1
        ? [...new Set(p.maintainers.map((m) => m.toLowerCase()))]
        : (p.maintainers || []).map((m) => m.toLowerCase()),
  );
  const near = filtering.facetBase.filter((p) => inNameSet(p) && byMaintainer(p));
  const picked = state.platformFilter;
  const platforms = {};
  for (const key of Object.keys(PLATFORMS)) {
    state.platformFilter = key;
    platforms[key] = near.filter(inPlatform).length;
  }
  state.platformFilter = picked;
  return { sets, by: by.slice(0, BY_SHOWN), platforms };
}

// A facet's choice, with its count, selected when it's the one picked.
export const facetOption = (value, label, count, picked) =>
  html`<option value="${value}"${picked === value ? raw(' selected') : ''}>${label} (${fmt(count)})</option>`;

export function refineHtml() {
  const facets = facetOptions();
  // python3Packages (an alias, ?in=): its sets' counts together.
  const setCount = (v) =>
    facets.sets.filter(([s]) => inPickedSet(s, v)).reduce((n, [, c]) => n + c, 0);
  const sets =
    state.inFilter && !facets.sets.some(([s]) => s === state.inFilter)
      ? [...facets.sets, [state.inFilter, 0]]
      : facets.sets;
  return html`<div class="refine" role="group" aria-label="Narrow the list">${Object.entries(
    REFINES,
  )
    .filter(([, r]) => !r.pick)
    .map(
      ([key, r]) =>
        html`<button type="button" class="refine-btn" data-refine="${key}" aria-pressed="${state.refines.has(key)}" title="${r.title}${key === 'stagingnext' && stagingNextWhy() ? `. Now: ${stagingNextWhy()}` : ''}${state.refines.has(key) ? ' (on: click to remove)' : ''}">${r.label}</button>`,
    )}${prPick()}${newerPick()}${sortPick()}${errorsPick()}${
    // On a maintainer's page: ?team=none.
    shownHandle()
      ? html`<button type="button" class="refine-btn" data-no-team aria-pressed="${state.noTeam}" title="Only packages that list this maintainer themselves: leave out those they maintain only as a member of the package's team (meta.teams)">Not via a team</button>`
      : ''
  }<label class="refine-age" title="How long it's been failing or outdated (the kind picked above, if any); or failing builds that never succeeded on Hydra, which have no date">Older than <select data-age><option value="">any age</option>${Object.entries(
    AGES,
  ).map(
    ([key, label]) =>
      html`<option value="${key}"${state.ageFilter === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label>${buildFailedPick()}${becausePick()}<label class="refine-age" title="Only packages available on it, and of their builds the ones there (build failures on Darwin, say). Darwin is macOS, as nixpkgs calls it. Each with how many it would show.">On <select data-platform-pick><option value="">any platform</option>${Object.entries(
    PLATFORMS,
  ).map(([key, p]) =>
    facetOption(key, p.label, facets.platforms[key], state.platformFilter),
  )}</select></label>${
    sets.length > 1 || state.inFilter
      ? html`<label class="refine-age" title="Only one package set, by the attribute's first part (python313Packages, vimPlugins), or the top-level packages. Each with how many it would show.">In <select data-in><option value="">any set</option>${sets.map(
          ([v]) => facetOption(v, v === TOP_LEVEL ? 'top level' : v, setCount(v), state.inFilter),
        )}</select></label>`
      : ''
  }${
    // Not on a maintainer's own page: it's theirs already.
    shownHandle()
      ? ''
      : html`<label class="refine-age" title="Only the packages this maintainer is listed for (meta.maintainers), within this list: type a GitHub handle. The ${fmt(facets.by.length)} with the most here are offered, each with how many.">By <input type="search" class="by-pick" data-by list="byOptions" placeholder="any maintainer" value="${state.byFilter || ''}" autocomplete="off" spellcheck="false"><datalist id="byOptions">${facets.by.map(
          ([h, n]) => html`<option value="${h}">${fmt(n)}</option>`,
        )}</datalist></label>`
  }</div>`;
}

// With every package, the header's tiles (renderScope): these filters, by
// these names, instead of the count chips.
export const TILES = {
  warn: 'Outdated',
  builds: 'Build failures',
  updates: 'Update failures',
  vuln: 'Vulnerable',
  backport: 'Fixes to backport',
  broken: 'Marked broken',
  blocked: 'Blocked',
};

// Where the package's update stands on GitHub, in GitHub's own colors:
// "on master" (merged, purple) while waiting for the channel, else an open
// update PR (green; grey while a draft). A link to the PR when it's known.
export const badge = (cls, text, title, pr) =>
  pr
    ? html` <a class="badge ${cls}" href="${safeUrl(pr.url)}" target="_blank" rel="noopener" title="${title}">${text}</a>`
    : html` <span class="badge ${cls}" title="${title}">${text}</span>`;

// The update's badge: on master when that's all it waits for, else merged
// into staging or staging-next on its way there, else its PR, else the
// branch that has it (haskell-updates), waiting for its merge.
export function prBadge(pkg) {
  if (waitingForChannel(pkg)) return masterBadge(pkg);
  if (pkg.stagingPR) return stagingBadge(pkg);
  if (pkg.openPR) return openPrBadge(pkg);
  return onBranch(pkg) ? branchBadge(pkg) : '';
}

export function branchBadge(pkg) {
  const b = pkg.branch;
  return badge(
    'onmaster',
    `on ${b.name}`,
    `${b.name} already has ${b.version}: waiting for its merge into master (about every two weeks)`,
    b.build ? { url: hydraBuildUrl(b.build) } : null,
  );
}

export function stagingBadge(pkg) {
  const pr = pkg.stagingPR;
  return badge(
    'onmaster',
    `on ${pr.on}`,
    `${pr.on} has ${pr.to}: merged in #${pr.number} (${pr.title}); it ${stagingWait(pr)}. A mass rebuild's way: weeks, not days`,
    pr,
  );
}

export function masterBadge(pkg) {
  const pr = pkg.masterPR;
  return badge(
    'onmaster',
    'on master',
    `master already has ${onMaster(pkg)}: merged${pr ? ` in #${pr.number} (${pr.title})` : ''}, waiting for nixos-unstable to catch up (usually a few days)`,
    pr,
  );
}

export function openPrBadge(pkg) {
  const pr = pkg.openPR;
  if (!pr) return '';
  const behind =
    targetVersion(pkg) && compareVersions(pr.to, targetVersion(pkg)) < 0
      ? ` (the newest is ${targetVersion(pkg)})`
      : '';
  return badge(
    pr.draft ? 'prdraft' : 'propen',
    `PR #${pr.number}`,
    `${pr.draft ? 'Draft update PR' : 'Update PR waiting for review'}: ${pr.title}${behind}`,
    pr,
  );
}

// The versions nixpkgs-update's queue would update a package to: a list
// entry's (summary), or a full row's candidates (one package alone).
export const queuedTo = (pkg) =>
  pkg.queued?.to || [...new Set((pkg.queued?.candidates || []).map(([to]) => to))];

// A robot's head (nixpkgs-update, the bot), in the text's colour.
export const BOT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.6v2"/><circle cx="8" cy="1.8" r="0.9" fill="currentColor" stroke="none"/><rect x="2.75" y="4.6" width="10.5" height="8.4" rx="2.2"/><circle cx="6" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><circle cx="10" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><path d="M1 7.8v2.2M15 7.8v2.2"/></svg>',
);

// A hard hat (Hydra's builders), in the text's colour: a failing build's
// mark in the build cell, as the robot is a failed update's.
export const HAT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 11V9.6a4.8 4.8 0 0 1 9.6 0V11"/><path d="M6.6 5.1v3M9.4 5.1v3"/><rect x="1.5" y="11" width="13" height="2.4" rx="1.2"/></svg>',
);

// The robot in place of a cell's dot (updateCell): red, or "queued" amber
// and "match" green, the queue's colours (queuedState).
export const botMark = (colour) =>
  html`<span class="bot-mark${colour ? ` ${colour}` : ''}" aria-hidden="true">${BOT_ICON}</span>`;

// Whether nixpkgs-update is set to try the package (the update cell's robot):
// { match: to the newest version, its last attempt fine, so its PR should
// follow; title }, or null.
export function queuedState(pkg) {
  const st = computeStatus(pkg);
  const to = queuedTo(pkg);
  if (pkg.openPR || pkg.stagingPR || waitingForChannel(pkg)) return null;
  const target = st === 'warn' ? targetVersion(pkg) : null;
  let match = false;
  let title;
  if (to.length) {
    const newest = Boolean(target && to.includes(target));
    // Its last attempt went wrong: the next may as well.
    const doubtful = pkg.updateFailure || ['cantUpdate', 'skipped'].includes(pkg.update?.outcome);
    // Its last attempt made the PR, or found one or its branch already.
    const made = ['prOpened', 'prExists', 'branchExists'].includes(pkg.update?.outcome);
    match = newest && !doubtful;
    title = `nixpkgs-update is set to update it to ${newest ? `${target}, the newest` : `${to.join(' or ')}${target ? `, not the newest (${target})` : ''}`}${
      doubtful
        ? ", but its last attempt didn't work: the next may not either"
        : made
          ? ': its last attempt already made a PR, or found one (the update panel links it)'
          : newest
            ? ': its PR should follow'
            : ''
    }. When: the update panel`;
  } else if (pkg.queued?.script && st === 'warn') {
    title =
      "nixpkgs-update will run its updateScript, which decides the version: whether it's the newest, its PR will tell. When: the update panel";
  } else {
    return null;
  }
  return { match, title };
}

// "auto update in 4 days": when nixpkgs-update is set to update the package
// to the newest version (the green robot) and the queue says when, the
// update cell's text instead of "—" (nothing reported). Days from its
// expected day (queued.by), as the update panel's "Next attempt" counts.
export function botDueText(pkg) {
  const by = pkg.queued?.by;
  if (!by || !queuedState(pkg)?.match) return null;
  const days = daysUntil(by);
  return days < 1
    ? 'auto update within a day'
    : `auto update in ${days === 1 ? 'a day' : `${days} days`}`;
}

// The version column: the versions on the left, badges on the right (so
// they line up from row to row). Up to date: nixpkgs' version, and what's
// said about it (devel, vulnerable, ...) at the right. Outdated, two lines:
// nixpkgs' version, and under it the newest, in full, with the start they
// share faded so the part that changes stands out ("→" hangs to its left).
// At the right, each line's badges: what's said about nixpkgs' version
// (devel, vulnerable, ...) beside it; the update's (its PR, on master, a
// failing check) beside the newest. Screen readers get the two versions in a
// sentence instead. Both versions are one button: it copies the update's
// title as nixpkgs writes it ("unciv: 4.22.1 -> 4.22.6").
// Whether a line's version and its badges won't fit side by side in the
// version column (its narrowest, about 28 characters of the version's
// font): then the badges go under the versions instead (.vcell.long), or
// they squeezed a long version into a line per few characters
// (linuxKernel.packages.linux_6_6.tbs's 7.2.11-unstable-2025-12-15, beside
// devel and on master, took 8 lines). Badges stack within their column, so
// the widest counts: about 0.95 of a character each, with 1.5 for the
// padding ("only in nixpkgs", 113px, fits beside 2020-01-31 at 1,081px).
export const VERSION_LINE = 28;

export function tooWide(version, badges) {
  const widest = Math.max(
    0,
    ...[...String(badges).matchAll(/class="badge[^"]*"[^>]*>([^<]*)</g)].map(
      (m) => m[1].length * 0.95 + 1.5,
    ),
  );
  return widest > 0 && String(version || '').length + 2 + widest > VERSION_LINE;
}

export function versionCell(pkg, st) {
  if (st === 'missing') return html`<span class="badge missing">not packaged</span>`;
  const now = pkg.nixVersion;
  const stale = notRefreshed(pkg, 'upstream');
  const failing = stale
    ? html`<span class="badge neutral" title="${staleText(stale, "nixkeeper's update check failing")}. ${communityCheck(pkg) ? "It's a community rule: report it to nixkeeper, or give the package a rule of your own." : 'Fix it in package-lists/update-checks.nix.'}">check failing</span>`
    : '';
  const about = html`${pkg.set ? bulkBadge(pkg.set) : ''}${olderVersionKept(pkg) ? html`<span class="badge neutral" title="${keptText(pkg)}">older version</span>` : pkg.unversioned && st === 'neutral' ? html`<span class="badge neutral" title="${UNVERSIONED_TITLE}">not versioned</span>` : st === 'neutral' ? html`<span class="badge neutral"${pkg.nixStatus === 'unsupported' ? html` title="${UNSUPPORTED_TEXT}"` : nothingCompared(pkg) ? html` title="${ONLY_NIXPKGS_TEXT}"` : ''}>${statusLabel(pkg.nixStatus)}</span>` : ''}${pkg.archived ? html`<span class="badge warn" title="${archivedText(pkg)}">archived</span>` : ''}${pkg.dropPR && !pkg.dropPR.proposed ? html`<span class="badge warn" title="An open PR removes it from nixpkgs: #${pkg.dropPR.number} (${pkg.dropPR.title})">being removed</span>` : ''}${pkg.feed?.heldBack && st === 'ok' ? html`<span class="badge neutral" title="nixpkgs pins it to ${pkg.feed.name}: Hackage has ${pkg.feed.heldBack}, which Stackage holds back until its next series">Stackage LTS</span>` : ''}${pkg.devel ? html`<span class="badge devel ${st}">devel</span>` : ''}${vulnBadge(pkg)}${pkg.staleSince ? html`<span class="badge neutral" title="Repology lookup failed on the last run; this is data from ${new Date(pkg.staleSince).toLocaleString()}">not refreshed</span>` : pkg.lookupFailed ? html`<span class="badge neutral" title="${LOOKUP_FAILED}">not looked up</span>` : ''}`;
  if (st !== 'warn')
    return html`<div class="vcell${tooWide(now, html`${about}${failing}`) ? ' long' : ''}"><span class="v-now"><span class="v">${now}</span></span><span class="v-tags top">${about}${failing}</span></div>`;
  const target = targetVersion(pkg);
  const merged = waitingForChannel(pkg);
  const title = updateTitle(pkg);
  // A newer version under the one before it: the start they share faded,
  // the rest in colour, "→" hanging to its left.
  const step = (cls, from, to, colour) => {
    const d = versionDiff(from, to);
    // Outdated, but no newer version known (Repology says outdated without
    // one): say so, rather than a bare "?".
    if (!to)
      return html`<span class="${cls}" aria-hidden="true"><span class="arrow">→</span><span class="unknown">newer version unknown</span></span>`;
    return html`<span class="${cls}" aria-hidden="true" title="${to}"><span class="arrow">→</span><span class="same">${d.same}</span><span class="ref${colour}">${d.to}</span></span>`;
  };
  // Master partway there: its own line, with its badge, between the two.
  const mid = midway(pkg);
  const steps = mid
    ? html`${step('v-mid', pkg.nixVersion, mid, ' merged')}${step('v-next', mid, target, '')}`
    : step('v-next', pkg.nixVersion, target, merged ? ' merged' : '');
  // The update's badge alone (no other badge, master not partway): between
  // the two versions, level with the row's GitHub counts.
  const update = mid ? openPrBadge(pkg) : prBadge(pkg);
  const solo = !mid && String(update) && !String(about) && !String(failing);
  const said = mid
    ? `${now}, on master ${mid}, newest ${target || 'unknown'}`
    : `${now}, newest ${target || 'unknown'}`;
  const long =
    tooWide(now, about) ||
    (mid && tooWide(mid, masterBadge(pkg))) ||
    tooWide(target, html`${update}${failing}`);
  return html`<div class="vcell${mid ? ' three' : ''}${long ? ' long' : ''}">
    <button type="button" class="vcopy" data-copy="${title || ''}" title="Copy “${title || ''}”">
    <span class="v-now"><span class="v" aria-hidden="true">${now}</span><span class="sr-only">${said}</span></span>
    ${steps}
    </button>
    <span class="v-tags top">${about}</span>${mid ? html`<span class="v-tags mid">${masterBadge(pkg)}</span>` : ''}
    <span class="v-tags bottom${solo ? ' solo' : ''}">${update}${failing}</span>
  </div>`;
}

// Where a row's failing builds (on the platform picked, if any) never
// succeeded on Hydra: linux (both its systems), x86_64-linux or
// aarch64-linux, darwin; "" when nowhere.
export function neverWhere(pkg) {
  if (!failedBuilds(pkg).length) return '';
  const systems = neverBuiltOn(pkg, state.platformFilter);
  const linux = systems.filter((s) => s.endsWith('-linux'));
  const shownSystems = linux.length === LINUX_SYSTEMS.length ? ['linux'] : linux;
  if (systems.some((s) => s.endsWith('-darwin'))) shownSystems.push('darwin');
  return shownSystems.join(', ');
}

export function ageTag(pkg, st) {
  // Failing first: how long it's been broken, in the failure's colour. A
  // failing build that never succeeded has no date: "n/a" when nothing
  // else is dated (the build column says where).
  const never = neverWhere(pkg);
  const failing = hasFailure(pkg) && failingSince(pkg);
  if (failing)
    return html`<span class="age failing" title="Failing since ${longDate(failing)}${never ? `; never built on ${never}` : ''}">${shortAge(failing)}</span>`;
  if (never)
    return html`<span class="age failing" title="No date: never built on ${never}">n/a</span>`;
  if (st !== 'warn' || !pkg.outdatedSince) return '';
  return html`<span class="age${waitingForChannel(pkg) ? ' merged' : ''}" title="Outdated since ${longDate(pkg.outdatedSince)}">${shortAge(pkg.outdatedSince)}</span>`;
}

// The row's dot, on hover (the legend popover lists them all).
// Repology's statuses as the page says them, where the code isn't clear
// ("unlisted": with every package, one Repology doesn't know).
export const STATUS_LABEL = { unlisted: 'not on Repology', unique: 'only in nixpkgs' };

// An older version kept beside a newer one (olderVersionKept): which.
export const keptText = (pkg) =>
  pkg.keptBeside
    ? `An older version nixpkgs keeps on purpose: it also has ${pkg.keptBeside.attr} ${pkg.keptBeside.version}`
    : 'An older version nixpkgs keeps on purpose, beside a newer one';

export const statusLabel = (status) => STATUS_LABEL[status] || status;

export const bulkBadge = (set) =>
  html`<span class="badge neutral" title="${bulkText(set)} (${set}): counted on its set's line on the overview">${bulkShort(set)}</span>`;

export const DOT_TITLE = {
  ok: 'Up to date: nixpkgs has the newest version',
  warn: 'Outdated: a newer release is out',
  merged: 'On master: the update is merged, waiting for nixos-unstable',
  missing: 'Not packaged: not in nixpkgs unstable',
  neutral:
    "Can't compare (a rolling or unusual version scheme), or an older version kept on purpose",
};

// Where the data is from: the daily sync's sources as it noted them
// (nixkeeper/sources/about.py), each with when its data is from, or why the
// sync didn't use it (it then asked per package instead). Those read from
// one of nixkeeper's digests are grouped under it (DIGESTS), in this order.
export const DIGESTS = {
  hydra: 'https://github.com/nixkeeper/digest-builds',
  versions: 'https://github.com/nixkeeper/digest-versions',
  updates: 'https://github.com/nixkeeper/digest-update-bot',
  vulnerabilities: 'https://github.com/nixkeeper/digest-vulnerabilities',
  prs: 'https://github.com/nixkeeper/digest-prs',
};

export const hydraEval = (s) =>
  html`evaluation <a class="files-link" href="https://hydra.nixos.org/eval/${s.eval}" target="_blank" rel="noopener">${s.eval}</a>, read ${timeAgo(s.at)}`;

export const SOURCES = [
  {
    key: 'nixpkgs',
    label: 'nixpkgs',
    from: 'https://github.com/NixOS/nixpkgs',
    says: (s) =>
      html`channel at <a class="files-link mono" href="https://github.com/NixOS/nixpkgs/commit/${s.revision}" target="_blank" rel="noopener">${s.revision.slice(0, 7)}</a>`,
  },
  { key: 'github', label: 'GitHub PRs', says: () => 'listed during the sync' },
  {
    // Only noted when lookups failed (Repology down, most likely).
    key: 'repology',
    label: 'Repology lookups',
    says: () => '',
    instead: 'the rest of the sync went on',
  },
  {
    // Hydra's nixpkgs/trunk jobset: master, which the channels follow.
    key: 'hydra',
    digest: 'hydra',
    label: 'master',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/trunk',
    says: hydraEval,
  },
  {
    // Only the jobs that differ from master's (nixkeeper/sources/branches.py),
    // and only while its cycle isn't merged yet.
    key: 'branch:staging-next',
    digest: 'hydra',
    label: 'staging-next',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/staging-next',
    says: (s) => html`${hydraEval(s)}, ${s.jobs?.toLocaleString()} jobs differing from master`,
    instead: 'not shown until its next evaluation',
  },
  {
    key: 'branch:haskell-updates',
    digest: 'hydra',
    label: 'haskell-updates',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/haskell-updates',
    says: hydraEval,
    instead: 'not shown',
  },
  {
    // nixkeeper's own update checks (upstream.py, inferred.py): not a digest
    // nor noted by the sync, but run in it, so from the daily sync's time.
    key: 'nixkeeper',
    digest: 'versions',
    label: 'nixkeeper',
    title: "nixkeeper's own update checks: GitHub tags, release pages, a branch's commits",
    says: (s) => `read ${timeAgo(s.at)}`,
  },
  {
    key: 'versions',
    digest: 'versions',
    label: 'Repology',
    says: (s) => `read ${timeAgo(s.at)}`,
  },
  {
    key: 'releases',
    digest: 'versions',
    label: 'GitHub releases',
    says: (s) => `read ${timeAgo(s.at)}, ${s.packages?.toLocaleString()} packages`,
    instead: 'checked for the lists only',
  },
  {
    key: 'typst',
    digest: 'versions',
    label: 'Typst Universe',
    says: (s) => `read ${timeAgo(s.at)}, ${s.packages?.toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'emacs',
    digest: 'versions',
    label: 'Emacs archives',
    says: (s) =>
      `read ${timeAgo(s.at)}: MELPA ${s.melpa?.toLocaleString()}, MELPA Stable ${s.melpaStable?.toLocaleString()}, NonGNU ${s.nongnu?.toLocaleString()}, GNU ${s.gnu?.toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'stackage',
    digest: 'versions',
    label: 'Stackage LTS',
    says: (s) =>
      `nixpkgs follows ${s.nixpkgs}, ${s.snapshot} is the newest (${s.packages?.toLocaleString()} packages), read ${timeAgo(s.at)}`,
    instead: "Repology's versions used",
  },
  {
    key: 'cran',
    digest: 'versions',
    label: 'CRAN, Bioconductor',
    says: (s) =>
      `read ${timeAgo(s.at)}: CRAN ${s.cran?.toLocaleString()}, Bioconductor ${s.biocVersion} ${((s.bioc || 0) + (s.annotation || 0) + (s.experiment || 0)).toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'updates',
    digest: 'updates',
    label: 'Update attempts',
    says: (s) =>
      `made ${timeAgo(s.at)}${s.pending ? ` · ${s.pending.toLocaleString()} attempts still to read` : ''}`,
  },
  {
    key: 'queue',
    digest: 'updates',
    label: 'Queue',
    says: (s) => `from ${timeAgo(s.at)}, going round every ${s.cycleDays} days`,
  },
  {
    key: 'tracker',
    digest: 'vulnerabilities',
    label: 'NixOS security tracker',
    from: 'https://tracker.security.nixos.org',
    says: (s) =>
      `read ${timeAgo(s.at)}: ${s.suggestions?.toLocaleString()} CVEs, on ${s.packages?.toLocaleString()} packages`,
    instead: "Repology's flag used",
  },
  {
    key: 'osv',
    digest: 'vulnerabilities',
    label: 'OSV',
    from: 'https://osv.dev',
    says: (s) =>
      `read ${timeAgo(s.at)}: ${s.advisories?.toLocaleString()} advisories, on ${s.packages?.toLocaleString()} packages`,
  },
  {
    key: 'prs',
    digest: 'prs',
    label: 'PRs and issues',
    says: (s) =>
      [
        `made ${timeAgo(s.at)}`,
        s.prs != null && `${s.prs.toLocaleString()} open PRs, ${s.issues?.toLocaleString()} issues`,
        s.merged != null && `${s.merged.toLocaleString()} merged since the channel`,
        s.staging != null && `${s.staging.toLocaleString()} merged into staging or staging-next`,
        s.partly && `${s.partly}: listed during the sync`,
      ]
        .filter(Boolean)
        .join(' · '),
    instead: 'listed during the sync',
  },
];

export function sourcesHtml() {
  const when = (iso) =>
    new Date(iso).toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  const noted = (key) =>
    key === 'nixkeeper'
      ? store.sources?.versions && store.checkedAt && { used: true, at: store.checkedAt }
      : store.sources?.[key];
  const row = ({ key, label, from, title, says, instead, digest }) => {
    const s = noted(key);
    const name = from
      ? html`<a class="files-link" href="${from}" target="_blank" rel="noopener">${label}</a>`
      : label;
    return html`<li class="${[s.used ? '' : 'unused', digest ? 'in-digest' : ''].filter(Boolean).join(' ')}"><b${title ? html` title="${title}"` : ''}>${name}</b><span class="src-what"${s.at ? html` title="${when(s.at)}"` : ''}>${
      s.used
        ? says(s)
        : `not used: ${s.why || 'unknown'}${s.at ? `, from ${timeAgo(s.at)}` : ''}, ${instead || 'asked per package instead'}`
    }</span></li>`;
  };
  const shown = SOURCES.filter(({ key }) => noted(key));
  const own = shown.filter((src) => !src.digest).map(row);
  const digests = Object.entries(DIGESTS).map(([digest, url]) => {
    const mine = shown.filter((src) => src.digest === digest);
    return mine.length
      ? html`<li class="src-digest"><a class="files-link" href="${url}" target="_blank" rel="noopener">${url.split('/').pop()}</a></li>${mine.map(row)}`
      : '';
  });
  // nixkeeper.com: every source, and whether each is on time, is the status
  // page's (it was a screenful here, too long for a phone). Elsewhere (an
  // instance of its own, a preview), the list as before: the status page
  // isn't about its runs.
  if (location.hostname === 'nixkeeper.com') {
    const nix = noted('nixpkgs');
    return html`<p class="pop-title">Where the data is from</p>
    <ul>
      <li><b>Last sync</b><span title="${store.checkedAt ? when(store.checkedAt) : ''}">${store.checkedAt ? `${timeAgo(store.checkedAt)}, ${when(store.checkedAt)}` : 'not yet'}</span></li>
      ${nix?.used ? html`<li><b>nixpkgs</b><span>${SOURCES[0].says(nix)}</span></li>` : ''}
    </ul>
    <a class="files-link" href="https://status.nixkeeper.com/" target="_blank" rel="noopener">Every source, and how fresh it is ↗</a>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
  }
  return html`<p class="pop-title">Where the data is from</p>
    <ul>
      <li><b>Last sync</b><span title="${store.checkedAt ? when(store.checkedAt) : ''}">${store.checkedAt ? `${timeAgo(store.checkedAt)}, ${when(store.checkedAt)}` : 'not yet'}</span></li>
      <li><b>Hourly checks</b><span>frequent update checks and update PRs, between syncs</span></li>
      ${own}
      ${digests}
    </ul>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
}

// The tab's icon shows what needs attention among packages (faviconKey).
export function setFavicon(base) {
  const key = faviconKey(base, state.platformFilter);
  const link = document.getElementById('favicon');
  if (link && !link.href.endsWith(`favicon-${key}.svg`)) link.href = `favicon-${key}.svg`;
}

export function renderStats() {
  // Counts follow the platform and list filters, so "outdated" means
  // outdated on Darwin, or on the gaming-team list, while that's selected.
  const base = store.packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && notHidden(p),
  );
  setFavicon(base);
  renderLists();
  // With every package, the counts are the list's tiles (renderScope), and
  // the bar's chip is the way into what needs attention.
  const attention = store.shownView === 'views/attention.json';
  const attentionChip = store.community
    ? html`<button class="stat-btn" data-view="attention" aria-pressed="${attention}"
        title="${attention ? 'Back to the overview' : 'Failing, outdated or vulnerable, worst first'}">
        <b style="color:var(--warn)">${fmt(store.manifest.views?.attention)}</b> needs attention</button>`
    : '';
  const buttons = Object.entries(store.community ? {} : FILTERS).map(([key, f]) => {
    if (['broken', 'builds', 'updates'].includes(key)) return ''; // with every package only
    const count = base.filter((p) => f.test(p) && refined(p, key)).length;
    // "vulnerable", "fixes to backport" and "blocked" only show up when
    // there's some.
    if (['vuln', 'backport', 'blocked'].includes(key) && !count && state.activeFilter !== key)
      return '';
    const pressed = state.activeFilter === key;
    return html`<button class="stat-btn" data-filter="${key}" aria-pressed="${pressed}"
      ${!count && key !== 'all' && !pressed ? raw('disabled') : ''}>
      <b${f.color ? html` style="color:${f.color}"` : ''}>${count}</b> ${key === 'all' && store.community ? 'here' : f.label}</button>`;
  });
  const stale =
    !store.checkedAt ||
    Date.now() - new Date(store.checkedAt).getTime() > STALE_AFTER_HOURS * 3600e3;
  const platformChip = state.platformFilter
    ? html`<button class="plat-filter" data-clear="platform" title="Show all platforms">${PLATFORMS[state.platformFilter].label} only ✕</button>`
    : '';
  // With every package, the list header says which team ("Showing").
  const teamChip =
    state.teamFilter && !store.community
      ? html`<button class="plat-filter" data-clear="team" title="Show every team's packages">team: ${teamName()} ✕</button>`
      : '';
  setHtml(
    document.getElementById('stats'),
    html`${attentionChip}${buttons}${platformChip}${teamChip}${store.community ? '' : teamOutChips()}`,
  );
  // Without every package, the list's narrowing under the counts; with
  // every package, it's in the list's header, under the tiles.
  const refine = document.getElementById('refine');
  refine.hidden = store.community;
  if (store.community) refine.textContent = '';
  else setHtml(refine, refineHtml());
  const checked = document.getElementById('checked');
  checked.classList.toggle('stale', stale);
  // The exact time on hover: "checked 4h ago" is friendly, but vague.
  const exact = store.checkedAt
    ? `Last full sync: ${new Date(store.checkedAt).toLocaleString(undefined, {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      })}.`
    : 'No full sync yet.';
  checked.title = stale
    ? `${exact} The daily sync hasn't updated the data in over 2 days. Check where it runs (on GitHub: the Actions tab).`
    : exact;
  checked.textContent = `checked ${timeAgo(store.checkedAt)}${stale ? ' — sync may be failing' : ''}`;
  setHtml(document.getElementById('sourcesPanel'), sourcesHtml());
}

// Whether the page shown is the visitor's team's (Your team), or their own
// packages (Your packages, isMine).
export const isMyTeam = () =>
  Boolean(listView.myTeam) &&
  store.shownView === `views/team/${viewSlug(listView.myTeam)}.json` &&
  !searchText().trim().startsWith('@');

export const isMine = () =>
  Boolean(listView.myHandle) &&
  searchText().trim().toLowerCase() === `@${listView.myHandle.toLowerCase()}`;

// "Your packages": the visitor's handle (a chip opening their packages,
// ✎ to change it), or a field to give it.
export function mineHtml() {
  if (listView.editingHandle)
    return html`<form class="mine-form" id="mineForm">
      <input id="mineInput" name="handle" placeholder="your GitHub handle" aria-label="Your GitHub handle" autocomplete="off" spellcheck="false" value="${listView.myHandle || ''}">
      <button class="stat-btn" type="submit">Show</button>
    </form>`;
  if (!listView.myHandle)
    return html`<button class="stat-btn" type="button" data-mine-edit title="Give your GitHub handle to find your packages (kept in this browser only)">Your packages…</button>`;
  return html`<button class="stat-btn" type="button" data-mine aria-pressed="${isMine()}"
      title="${isMine() ? 'Back to the overview' : 'The packages that list you as a maintainer'}">${listView.myCount != null ? html`<b>${fmt(listView.myCount)}</b> ` : ''}@${listView.myHandle}</button><button type="button" class="mine-edit" data-mine-edit aria-label="Change your GitHub handle" title="Change your GitHub handle">✎</button>`;
}

// "Your team": the visitor's team (a chip opening its packages, ✎ to change
// it), or a picker to choose it.
export function myTeamHtml() {
  const teams = Object.keys(store.manifest.views?.teams || {}).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' }),
  );
  if (!teams.length) return '';
  if (listView.editingTeam)
    return html`<form class="mine-form" id="teamForm">
      <select id="teamInput" name="team" aria-label="Your team"><option value="">No team</option>${teams.map((t) => html`<option value="${t}"${t === listView.myTeam ? raw(' selected') : ''}>${t}</option>`)}</select>
      <button class="stat-btn" type="submit">Show</button>
    </form>`;
  if (!listView.myTeam || !store.manifest.views.teams[listView.myTeam])
    return html`<button class="stat-btn" type="button" data-team-edit title="Choose your nixpkgs team to find its packages (kept in this browser only)">Your team…</button>`;
  return html`<button class="stat-btn" type="button" data-my-team aria-pressed="${isMyTeam()}"
      title="${isMyTeam() ? 'Back to the overview' : "The team's packages"}"><b>${fmt(store.manifest.views.teams[listView.myTeam])}</b> ${listView.myTeam} team</button><button type="button" class="mine-edit" data-team-edit aria-label="Change your team" title="Change your team">✎</button>`;
}

// The lists from package-lists/, as more filters after the counts (a
// divider between). Hidden when there's only one (or data from before lists
// existed).
export function renderLists() {
  const el = document.getElementById('lists');
  if (store.community) {
    // The visitor's own: their packages and their team. This instance's
    // lists ("maintained", its named lists) mean little to them: not shown,
    // though their addresses (?list=) still work.
    setHtml(el, html`${mineHtml()}${myTeamHtml()}`);
    return;
  }
  const listNames = allLists();
  if (state.listFilter && !listNames.includes(state.listFilter)) listNames.push(state.listFilter); // e.g. a renamed list
  if (listNames.length < 2) {
    el.textContent = '';
    return;
  }
  const base = store.packages.filter((p) => inPlatform(p) && inPeople(p) && refined(p, 'all'));
  const listCount = (name) =>
    store.community
      ? store.manifest.views.lists[name] || 0
      : base.filter((p) => (p.lists || []).includes(name)).length;
  setHtml(
    el,
    html`<span class="lists-label">lists</span>${listNames.map((name) => {
      const pressed = state.listFilter === name;
      const count = listCount(name);
      return html`<button class="stat-btn" type="button" data-list="${name}" aria-pressed="${pressed}"
        title="${pressed ? 'Show every list' : `Show only the ${name} list (shareable: it's in the address)`}">
        <b>${count}</b> ${name}</button>`;
    })}`,
  );
}

// A fold's lead: how many more it stands for, a button showing or folding
// them.
export function foldButton(pkg) {
  const fold = listView.folds.get(pkg.name);
  if (!fold) return '';
  const more = fold.members.length - 1;
  const label = familyLabel(fold.members.map((m) => m.name)) || `${pkg.name} and the like`;
  return html`<button type="button" class="fold-btn" data-fold="${fold.key}" aria-expanded="${fold.open}" title="${fmt(more + 1)} packages one update moves together (${label}): ${fold.open ? 'fold them into one row' : 'show them all'}">${fold.open ? `fold ${fmt(more)}` : `+${fmt(more)} like it`}</button>`;
}

export const CHEVRON = raw(
  '<svg class="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
);

// What a row's dot means, in words: its colour's, or why it's grey when
// only nixpkgs packages it.
export const dotTitle = (pkg, st) =>
  waitingForChannel(pkg)
    ? DOT_TITLE.merged
    : nothingCompared(pkg)
      ? `Not compared: ${ONLY_NIXPKGS_TEXT.charAt(0).toLowerCase()}${ONLY_NIXPKGS_TEXT.slice(1)}`
      : DOT_TITLE[st];

export function rowHtml(pkg, i) {
  const st = computeStatus(pkg);
  return html`<tr class="row${isHidden(pkg) ? ' is-hidden' : ''}${listView.inOpenFold.has(pkg.name) ? ' fold-member' : ''}" tabindex="0" data-i="${i}">
      <td class="c-name"><div class="pkg-name"><span class="who"><span class="status-dot ${waitingForChannel(pkg) ? 'merged' : st}" role="img" aria-label="${dotTitle(pkg, st)}" title="${dotTitle(pkg, st)}"></span><a class="n pkg-link" href="${scopeHref({ pkg: pkg.name })}" tabindex="-1">${breakableName(pkg.name)} ${ageTag(pkg, st)}</a></span>${platformTags(pkg)}${foldButton(pkg)}</div></td>
      <td class="c-ver ver mono">${versionCell(pkg, st)}</td>
      <td class="c-gh${pkg.openPRs || pkg.openIssues ? '' : ' quiet'}">${githubLinks(pkg)}</td>
      <td class="c-build">${buildCell(pkg)}</td>
      <td class="c-update">${updateCell(pkg)}</td>
      <td class="c-chev"><span class="chev" aria-hidden="true">${CHEVRON}</span></td>
    </tr>`;
}

export function listHeaderHtml(loadMerge) {
  const handle = searchText().trim().replace(/^@/, '');
  const path = store.shownView || '';
  // The tiles count the view shown, with the platform, list and team
  // filters, as the count chips do (renderStats).
  const base = store.packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && notHidden(p),
  );
  // Hidden here ("Hide until it changes"), by the same filters.
  const hiddenHere = store.packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && isHidden(p),
  ).length;
  const shownCount = base.filter((p) => refined(p)).length;
  const tiles = Object.entries(TILES).map(([key, label]) => {
    const count = base.filter((p) => FILTERS[key].test(p) && refined(p, key)).length;
    const pressed = state.activeFilter === key;
    return html`<button type="button" class="tile" data-filter="${key}" aria-pressed="${pressed}"
      title="${pressed ? 'Show them all again' : `Show only these (${label.toLowerCase()})`}">
      <span class="tile-label">${label}</span><span class="tile-n" style="color:${FILTERS[key].color}">${fmt(count)}</span></button>`;
  });
  const what = path.startsWith('pkg:')
    ? html`<span class="mono">${path.slice(4)}</span>`
    : path.startsWith('views/maintainer/')
      ? handle === 'none'
        ? 'No maintainer'
        : `@${handle}`
      : path.startsWith('views/team/')
        ? `${teamName()} team`
        : path.startsWith('views/list/')
          ? `${state.listFilter} list`
          : path.startsWith('views/set/')
            ? state.setFilter
            : path.startsWith('views/cause/')
              ? store.causeShown?.title || 'Failing with the same error'
              : path === 'views/broken.json'
                ? 'Marked broken'
                : path === 'views/blocked.json'
                  ? 'Blocked by a dependency'
                  : path === 'views/unbuilt.json'
                    ? 'Not built where listed'
                    : path === 'views/superseded.json'
                      ? 'Update PRs to close'
                      : path === 'views/backport.json'
                        ? 'Fixes to backport'
                        : 'Needs attention';
  return html`<h2 class="sr-only">${what}</h2>
    <div class="scope-view">
      <span class="scope-label">Showing</span>
      <span class="view-chip">${what} · ${fmt(shownCount)}<a class="view-x" href="${scopeHref({})}" data-scope-home aria-label="Back to the overview" title="Back to the overview">✕</a></span>
      ${
        hiddenHere
          ? html`<button type="button" class="hidden-toggle" aria-pressed="${filtering.showHidden}" title="Packages you hid here, in this browser, until what they need attention for changes">${fmt(hiddenHere)} hidden · ${filtering.showHidden ? 'hide them' : 'show them'}</button>`
          : ''
      }<button type="button" class="close-all" title="Close every open package (Esc)" hidden>Close all</button>
      ${path.startsWith('views/cause/') && store.causeShown ? html`<span class="scope-hint cause-line" title="The error line these builds share (paths, numbers and names vary)"><code>${store.causeShown.line}</code></span>` : ''}
      ${
        // Marked broken's neighbour: listed for a platform, never built there.
        path === 'views/broken.json' && store.manifest.views?.unbuilt
          ? html`<a class="scope-hint files-link" href="${scopeHref({ view: 'unbuilt' })}" title="Packages nixpkgs lists for a platform Hydra doesn't build them on: usually a dependency isn't available there">also: ${fmt(store.manifest.views.unbuilt)} not built where listed →</a>`
          : path === 'views/superseded.json'
            ? html`<span class="scope-hint">an open update PR nixpkgs is already past (it has the PR’s version or a newer one): each package’s details link it</span>`
            : path === 'views/unbuilt.json'
              ? html`<span class="scope-hint">listed for a platform Hydra doesn't build them on (struck tags); pick a platform to see its own</span>`
              : ''
      }
      ${
        // "PR to close" on in another list: the whole of nixpkgs' are a view.
        state.refines.has('superseded') &&
        path !== 'views/superseded.json' &&
        store.manifest.views?.superseded
          ? html`<a class="scope-hint files-link" href="${scopeHref({ view: 'superseded' })}" data-card-view="superseded" title="Every package with an open update PR nixpkgs is already past, up to date or not">also: ${fmt(store.manifest.views.superseded)} in all of nixpkgs →</a>`
          : ''
      }
      ${path.startsWith('views/set/') ? html`<span class="scope-hint">${bulkText(state.setFilter)}${profileOf(state.setFilter) ? html` (<a class="files-link" href="${safeUrl(profileOf(state.setFilter).link)}" target="_blank" rel="noopener">in nixpkgs ↗</a>)` : ''}</span>` : ''}
      ${teamPicker('Any team')}${teamOutChips()}
    </div>
    ${mergeHtml(path, handle, loadMerge)}
    ${closeHtml(path, handle)}
    ${
      // One package: its row says it all, the tiles would only count to 1.
      path.startsWith('pkg:') ? '' : html`<div class="tiles">${tiles}</div>${refineHtml()}`
    }`;
}

// The vulnerable badge: "insecure" when nixpkgs' mark is all there is, else
// "vulnerable", coloured by the worst severity known, who says so on hover.
export function vulnBadge(pkg) {
  if (!isVulnerable(pkg)) return '';
  const saidBy = vulnSources(pkg);
  const insecureOnly = saidBy.length === 1 && pkg.markedInsecure?.length;
  const found = vulnSummary(pkg);
  const severity = found?.severity;
  const n = found?.n;
  const title = insecureOnly
    ? `nixpkgs marks it insecure: ${pkg.markedInsecure.join(' · ')}`
    : `Vulnerable, says ${saidBy.join(', ')}${n ? `: ${n} ${n === 1 ? 'CVE or advisory' : 'CVEs or advisories'}` : ''}${severity ? ` (worst: ${severity})` : ''}`;
  return html`<span class="badge vuln${severity ? ` sev-${severity}` : ''}" title="${title}">${insecureOnly ? 'insecure' : 'vulnerable'}</span>`;
}

// quiet: nothing that needs attention, so it's drawn muted, without a dot
// ("none reported" as a dash), and the phone layout leaves it out. Only
// what needs a look keeps its colour.
// mark: in place of the dot (a build's hard hat, the bot's robot), when
// given; marked: what it says that the text doesn't, for screen readers
// ("queued for an update").
export function failureButton(
  kind,
  dot,
  text,
  title,
  stale = null,
  quiet = false,
  mark = null,
  marked = '',
) {
  const calm = quiet && !stale;
  const shown = calm && text === 'none reported' ? html`<span aria-hidden="true">—</span>` : text;
  return html`<button class="failure-btn${dot === 'missing' ? ' failing' : ''}${calm ? ' calm' : ''}" type="button" data-kind="${kind}"${calm ? html` data-quiet aria-label="${kind}: ${text}${marked ? `, ${marked}` : ''}"` : ''} aria-expanded="false" title="${title}">
    ${mark || html`<span class="status-dot ${dot}" aria-hidden="true"></span>`}<span class="cell-label">${kind}:</span>${shown}${marked && !calm ? html`<span class="sr-only">, ${marked}</span>` : ''}${
      stale
        ? html` <span class="stale-tag" title="${staleText(stale, 'Not refreshed')}">not refreshed</span>`
        : ''
    }</button>`;
}

export function buildCell(pkg) {
  if (!pkg.builds) return html`<span class="failure-na" title="Not in nixpkgs">—</span>`;
  const button = (dot, text, quiet = false) =>
    failureButton('build', dot, text, 'Show Hydra builds', notRefreshed(pkg, 'builds'), quiet);
  // Failing, blocked or marked broken: the hard hat in place of the dot, in
  // its colour, as the update column has the robot.
  const hat = (dot, text) =>
    failureButton(
      'build',
      dot,
      text,
      'Show Hydra builds',
      notRefreshed(pkg, 'builds'),
      false,
      html`<span class="bot-mark${dot === 'caution' ? ' queued' : ''}" aria-hidden="true">${HAT_ICON}</span>`,
    );
  // A failed build that never succeeded on Hydra: where, instead (the
  // panel lists the others).
  const never = neverWhere(pkg);
  if (never) return hat('missing', `never: ${never}`);
  if (failedBuilds(pkg).length) {
    // One reason for all of them (their logs, nixkeeper-hydra): only it, as
    // the update column says its own; the column says the rest.
    const [why, ...more] = buildFailedBecause(pkg, state.platformFilter);
    const known = !more.length && why !== 'unread' && BUILD_FAILED[why];
    return hat(
      'missing',
      html`<span class="sr-only">failed: </span>${known ? known.short : 'failure'}`,
    );
  }
  // Known failures: shown, but not counted as failed.
  // Hydra's builds say where; a broken package often has no Hydra job at
  // all, and then only meta.broken does (markedBroken).
  if (buildsWith(pkg, 'broken').length || pkg.markedBroken) return hat('caution', 'marked broken');
  // A dependency's failure stopped it: not its own, so not counted as failed.
  if (buildsWith(pkg, 'dependency').length) return hat('caution', 'blocked');
  if (!hydraBuildsIt(pkg)) return button('neutral', 'not built by Hydra', true);
  return button('ok', 'none reported', true);
}

// nixpkgs-update's latest attempt. `update` is null when the bot never tried
// and missing for packages not in nixpkgs. When the bot is set to update it
// (its queue), the robot is in front, in place of the dot: green when to
// the newest version and its last attempt didn't fail, so its PR should
// follow; amber when it will try but it's unsure (queuedState); its hover
// says which, and the update panel when. Without the queue, a failure's robot is red and "can't
// update"'s gold; the rest have no mark.
export function updateCell(pkg) {
  // A set's, the bot never tried: its set's tooling updates it.
  if (pkg.set && !pkg.update)
    return queuedOrDash(pkg, `${bulkText(pkg.set)}: nixpkgs-update hasn't tried it`);
  if (pkg.update === undefined)
    return html`<span class="failure-na" title="Not in nixpkgs">—</span>`;
  if (pkg.update === null && pkg.unversioned && !pkg.unread?.includes('update'))
    return queuedOrDash(pkg, `${UNVERSIONED_TITLE}: nothing for nixpkgs-update to update`);
  const q = queuedState(pkg);
  const robot = botMark;
  const button = (dot, text, quiet = false, unqueued = null) =>
    failureButton(
      'update',
      dot,
      text,
      `Show the latest nixpkgs-update attempt${q ? `. ${q.title.replace(/\. When: the update panel$/, '')}` : ''}`,
      notRefreshed(pkg, 'update'),
      quiet,
      q ? robot(q.match ? 'match' : 'queued') : unqueued,
      q ? 'queued for an update' : '',
    );
  // Failed: only why ("patch"), the column saying the rest.
  if (pkg.updateFailure) {
    const because = FAILED_BECAUSE[pkg.update?.failedBecause];
    return button(
      'missing',
      html`<span class="sr-only">failed: </span>${because ? because.short : 'failure'}`,
      false,
      robot(''),
    );
  }
  // The bot's last attempt failed, but nixpkgs has moved on since: not a
  // failure anymore, though the next attempt may well break the same way.
  if (pkg.update?.outcome === 'superseded') return button('neutral', 'superseded', true);
  // A newer version the bot has no way to update to: not a failure, but it
  // needs a manual update (or an updateScript).
  if (pkg.update?.outcome === 'cantUpdate')
    return button('caution', "can't update", false, robot('queued'));
  // The bot passes it over on purpose (opted out, GNOME's release cycle, too
  // many rebuilds, ...): not a failure, but it won't update it either.
  if (pkg.update?.outcome === 'skipped') return button('neutral', 'skipped', true);
  // With every package, only the lists' packages' logs are read (with no
  // attempt read before).
  if (pkg.unread?.includes('update') && !pkg.update) return button('neutral', 'not read', true);
  // Nothing reported, and the bot is set to update it: when, in green.
  const due = botDueText(pkg);
  if (due)
    return failureButton(
      'update',
      'ok',
      html`<span class="bot-due">${due}</span>`,
      `${q.title.replace(/\. When: the update panel$/, '')}, expected by ${pkg.queued.by}`,
      notRefreshed(pkg, 'update'),
      false,
      robot('match'),
    );
  if (pkg.update === null) return button('neutral', 'not attempted', true);
  return button('ok', 'none reported', true);
}

// A "—" with nothing to open, saying why on hover; unless the bot is set
// to update it anyway: then the robot and "—", one button opening the
// update panel, as the other cells.
export function queuedOrDash(pkg, why) {
  const q = queuedState(pkg);
  if (!q) return html`<span class="failure-na" title="${why}">—</span>`;
  return failureButton(
    'update',
    'neutral',
    'none reported',
    `${why}. ${q.title.replace(/\. When: the update panel$/, '')}`,
    notRefreshed(pkg, 'update'),
    true,
    botMark(q.match ? 'match' : 'queued'),
    'queued for an update',
  );
}

// From nixpkgs meta.platforms; null means nixpkgs doesn't restrict it.
// Linux and Darwin, and the one Linux system when it's on only one ("Linux
// x86_64": the exception named, the rule not).
export function platformTags(pkg) {
  const pl = pkg.platforms;
  if (pl === undefined) return '';
  // No restriction: "any platform", unless Hydra doesn't build it
  // somewhere, which the chips then say as for a listed platform (fzssh:
  // Linux, not Darwin; 334 such on 2026-10-19).
  const any = pl === null;
  if (any && !unbuiltWhere(pkg).length)
    return html`<span class="plats"><span class="plat any" title="nixpkgs doesn't restrict its platforms">any platform</span></span>`;
  const listed = pl || { linux: true, darwin: true };
  const linux = LINUX_SYSTEMS.filter((s) => onPlatform(pkg, s));
  // Each chip: its platform, and whether Hydra builds it there
  // (unbuiltOn: listed, not built). On both Linux systems with one not
  // built, they split: "Linux x86_64 · aarch64", the latter struck.
  const chips = [];
  if (listed.linux) {
    const built = linux.filter((s) => !unbuiltOn(pkg, s));
    if (linux.length === 2 && built.length === 1) {
      const missing = linux.find((s) => s !== built[0]);
      chips.push([built[0], false], [missing, true, missing.split('-')[0]]);
    } else {
      const key = linux.length === 1 ? linux[0] : 'linux';
      chips.push([key, unbuiltOn(pkg, key)]);
    }
  }
  if (listed.darwin) chips.push(['darwin', unbuiltOn(pkg, 'darwin')]);
  const tags = chips.map(([key, unbuilt, short]) => {
    const p = PLATFORMS[key];
    const where = any
      ? "nixpkgs doesn't restrict its platforms"
      : `Listed for ${p.label} in nixpkgs`;
    const said = unbuilt
      ? `${where}, but Hydra doesn't build it on ${p.label}: no build exists there, usually because a dependency isn't available on ${p.label}`
      : any
        ? `${p.title} (nixpkgs doesn't restrict its platforms)`
        : p.title;
    return html`<button class="plat${unbuilt ? ' unbuilt' : ''}" type="button" data-platform="${key}" aria-pressed="${state.platformFilter === key}"
      title="${said}. ${state.platformFilter === key ? 'Show all platforms' : `Click to show only packages available on ${p.label}`}">${short || p.label}${unbuilt ? html`<span class="sr-only"> (not built by Hydra)</span>` : ''}</button>`;
  });
  // Together, so they wrap as one.
  return tags.length ? html`<span class="plats">${tags}</span>` : '';
}

// Open nixpkgs PRs / issues with the package's attribute name in the title:
// a link to GitHub's search for each kind that has some, with its count.
// None of either: a faint "—", as the other columns say nothing to report
// (two thirds of the attention list had "PRs 0 issues 0", two links to an
// empty search, 2026-10-23). Not counted (an instance whose sync doesn't
// ask GitHub): both, as plain links.
export function githubLinks(pkg) {
  const term = pkg.searchTerm || pkg.name;
  // Packages with none open are counted every few days, not daily
  // (nixkeeper/sources/github.py): when, if it wasn't today.
  const age = pkg.countedAt && daysText(pkg.countedAt);
  const counted = age && age !== 'today' ? ` (counted ${age} ago)` : '';
  // GitHub's icon and the count ("2 open PRs" said); without a count, the
  // word instead.
  // The count is of titles about the package (nixkeeper/sources/
  // github_bulk.py); GitHub's search, linked, matches words, and for a name
  // that's a word (pkg, linux) shows more: the hover says so.
  const link = (kind, path, label, count) => {
    if (count === 0) return '';
    const q = encodeURIComponent(`is:${kind} state:open in:title "${term}"`);
    const more = pkg.searchShowsMore?.includes(kind)
      ? `. GitHub's search shows more: titles with the word ${term} in them, not only its name`
      : '';
    return html`<a class="gh-btn" href="https://github.com/NixOS/nixpkgs/${path}?q=${q}" target="_blank" rel="noopener"
      title="Open nixpkgs ${label} naming ${term} in their title${counted}${more}"${count != null ? html` aria-label="${count} open ${label}"` : ''}>${GH_ICONS[kind]}${count != null ? html`<b>${count}</b>` : label}</a>`;
  };
  if (pkg.openPRs === 0 && pkg.openIssues === 0)
    return html`<span class="failure-na" title="No open nixpkgs PRs or issues naming ${term} in their title${counted}${pkg.searchShowsMore ? `. GitHub's search shows some with the word ${term} in them` : ''}">—</span>`;
  return html`<span class="gh-links">${link('pr', 'pulls', 'PRs', pkg.openPRs)}${link('issue', 'issues', 'issues', pkg.openIssues)}</span>`;
}

// A package's name, able to wrap after each dot (python313Packages. /
// requests) and at its hyphens, as a long one would otherwise widen the
// table past the screen for every row.
export function breakableName(name) {
  return name.split('.').map((part, i) => (i ? html`.<wbr>${part}` : part));
}

// The list's controls, on the page's elements, once: its rows (a panel, a
// copy, a fold, a platform, a page), the counts and tiles, the chips,
// refines and selects that narrow it, Your packages and Your team. page:
// what they need of the page (app.js's pageHooks).
export function wireList(page) {
  // The table's clicks, for every row: a link opens (and nothing else), the
  // versions copy the update's title, a platform filters by it, the build and
  // update cells open their panel, and anywhere else the details.
  document.getElementById('content').addEventListener('click', (e) => {
    // A page link: that page, from its top (a click with a modifier opens it
    // elsewhere, as links do).
    const pageLink = e.target.closest('a.page-btn');
    if (pageLink && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button)) {
      e.preventDefault();
      state.pageNum = Number(pageLink.dataset.page);
      // Back to the table's top, the keyboard on its first row, once drawn.
      page.update({ keepPage: true }).then(() => {
        const content = document.getElementById('content');
        if (content.getBoundingClientRect().top < 0) content.scrollIntoView();
        content.querySelector('tr.row')?.focus({ preventScroll: true });
      });
      return;
    }
    const tr = e.target.closest('tr.row');
    // Its name is a link to it alone (?pkg=): a plain click opens it here,
    // as anywhere on the row; with a modifier, a tab of its own, as links do.
    if (
      tr &&
      e.target.closest('a.pkg-link') &&
      !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button)
    ) {
      e.preventDefault();
      page.toggle(tr, 'info');
      return;
    }
    if (!tr || e.target.closest('a')) return;
    const copy = e.target.closest('.vcopy');
    if (copy) {
      page.copyTitle(copy);
      return;
    }
    const fold = e.target.closest('button.fold-btn');
    if (fold) {
      // Shown or folded again, the keyboard back on the same button.
      const key = fold.dataset.fold;
      if (listView.openFolds.has(key)) listView.openFolds.delete(key);
      else listView.openFolds.add(key);
      page
        .update({ keepPage: true })
        .then(() =>
          [...document.querySelectorAll('button.fold-btn')]
            .find((b) => b.dataset.fold === key)
            ?.focus(),
        );
      return;
    }
    const plat = e.target.closest('button.plat');
    if (plat) {
      // Clicking the active platform again shows all platforms.
      state.platformFilter =
        state.platformFilter === plat.dataset.platform ? null : plat.dataset.platform;
      page.update();
      return;
    }
    // A cell's button or the "queued" badge: its panel; anywhere else, the
    // package's details.
    page.toggle(tr, e.target.closest('[data-kind]')?.dataset.kind || 'info');
  });

  document.getElementById('content').addEventListener('keydown', (e) => {
    if (e.target.matches('tr.row') && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      e.target.click();
    }
  });

  document.getElementById('stats').addEventListener('click', (e) => {
    const clear = e.target.closest('.plat-filter[data-clear]');
    if (clear) {
      if (clear.dataset.clear === 'team') state.teamFilter = null;
      else state.platformFilter = null;
      page.update();
      return;
    }
    const btn = e.target.closest('.stat-btn');
    if (!btn) return;
    if (btn.dataset.view) {
      // With every package: the list, or (pressed) back to the overview.
      page.showView({
        view: btn.getAttribute('aria-pressed') === 'true' ? null : btn.dataset.view,
      });
      return;
    }
    // Clicking the active filter again goes back to showing everything.
    state.activeFilter = btn.dataset.filter === state.activeFilter ? 'all' : btn.dataset.filter;
    page.update();
  });

  // ?team='s left-out teams and none: their chips (teamOutChips) and the
  // maintainer page's "Not via a team".
  document.addEventListener('click', (e) => {
    const out = e.target.closest('button[data-team-out]');
    const person = e.target.closest('button[data-maintainer-out]');
    if (out) state.teamsLeftOut = state.teamsLeftOut.filter((t) => t !== out.dataset.teamOut);
    else if (person)
      state.maintainersLeftOut = state.maintainersLeftOut.filter(
        (h) => h !== person.dataset.maintainerOut,
      );
    else if (e.target.closest('button[data-team-none]')) state.noTeam = false;
    else if (e.target.closest('button[data-no-team]')) state.noTeam = !state.noTeam;
    else return;
    page.update();
  });

  // Show errors: on or off.
  document.addEventListener('click', (e) => {
    if (!e.target.closest('button[data-show-errors]')) return;
    state.showErrors = !state.showErrors;
    page.update({ keepPage: true });
  });

  // ↓/↑: the list's order reversed, or back.
  document.addEventListener('click', (e) => {
    if (!e.target.closest('button[data-sort-dir]')) return;
    state.sortReverse = !state.sortReverse;
    page.update();
  });

  // Narrowing the list (refineHtml), wherever it's drawn.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-refine]');
    if (!btn) return;
    const key = btn.dataset.refine;
    if (state.refines.has(key)) state.refines.delete(key);
    else state.refines.add(key);
    page.update();
  });

  document.addEventListener('change', (e) => {
    if (e.target.matches('select[data-age]')) state.ageFilter = e.target.value || null;
    else if (e.target.matches('select[data-because]')) state.becauseFilter = e.target.value || null;
    else if (e.target.matches('select[data-build-failed]'))
      state.buildFailedFilter = e.target.value || null;
    else if (e.target.matches('select[data-platform-pick]'))
      state.platformFilter = e.target.value || null;
    else if (e.target.matches('select[data-in]')) state.inFilter = e.target.value || null;
    else if (e.target.matches('select[data-sort]')) state.sortMode = e.target.value || 'pressing';
    else if (e.target.matches('select[data-newer]')) state.newerFilter = e.target.value || null;
    else if (e.target.matches('select[data-pr-pick]')) {
      state.refines.delete('withpr');
      state.refines.delete('nopr');
      if (e.target.value) state.refines.add(e.target.value);
    } else if (e.target.matches('select[data-status]')) state.statusFilter = e.target.value || null;
    else if (e.target.matches('select[data-match-team]')) state.matchTeam = e.target.value || null;
    else if (e.target.matches('input[data-by]')) {
      const by = e.target.value.trim().replace(/^@/, '').toLowerCase();
      state.byFilter = /^[\w.-]{1,60}$/.test(by) ? by : null;
    } else if (e.target.matches('select[data-per]')) {
      // The page holding the first row shown before, at the new size.
      const first = (state.pageNum - 1) * state.pageSize;
      state.pageSize = Number(e.target.value);
      state.pageNum = Math.floor(first / state.pageSize) + 1;
      page.update({ keepPage: true });
      return;
    } else return;
    page.update();
  });

  document.getElementById('lists').addEventListener('click', (e) => {
    if (e.target.closest('[data-mine-edit]')) {
      listView.editingHandle = true;
      renderLists();
      document.getElementById('mineInput')?.focus();
      return;
    }
    if (e.target.closest('[data-mine]')) {
      page.showMine(!isMine());
      return;
    }
    if (e.target.closest('[data-team-edit]')) {
      listView.editingTeam = true;
      renderLists();
      document.getElementById('teamInput')?.focus();
      return;
    }
    if (e.target.closest('[data-my-team]')) {
      page.showMyTeam(!isMyTeam());
      return;
    }
    const btn = e.target.closest('.stat-btn[data-list]');
    if (!btn) return;
    // Clicking the active list again shows every list.
    state.listFilter = btn.dataset.list === state.listFilter ? null : btn.dataset.list;
    page.update();
  });

  document.getElementById('lists').addEventListener('submit', (e) => {
    if (e.target.id !== 'teamForm') return;
    e.preventDefault();
    listView.myTeam = e.target.team.value || null;
    listView.editingTeam = false;
    remember('nixkeeper-team', listView.myTeam);
    if (listView.myTeam) page.showMyTeam(true);
    else renderLists();
  });

  document.getElementById('lists').addEventListener('submit', (e) => {
    if (e.target.id !== 'mineForm') return;
    e.preventDefault();
    const handle = e.target.handle.value.trim().replace(/^@/, '');
    listView.myHandle = handle || null;
    listView.myCount = null;
    listView.editingHandle = false;
    remember('nixkeeper-handle', listView.myHandle);
    if (listView.myHandle) {
      page.loadMyCount();
      page.showMine(true);
    } else renderLists();
  });

  document.getElementById('lists').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && e.target.id === 'mineInput') {
      listView.editingHandle = false;
      renderLists();
    }
    if (e.key === 'Escape' && e.target.id === 'teamInput') {
      listView.editingTeam = false;
      renderLists();
    }
  });

  // With every package, the header's tiles: filters, as the count chips are;
  // closing every panel; the rows hidden here shown, or not.
  document.getElementById('scope')?.addEventListener('click', (e) => {
    if (e.target.closest('button.close-all')) {
      page.closeRows(page.openRows());
      return;
    }
    if (e.target.closest('button.hidden-toggle')) {
      filtering.showHidden = !filtering.showHidden;
      page.update({ keepPage: true });
      return;
    }
    const tile = e.target.closest('button.tile');
    if (!tile) return;
    state.activeFilter = tile.dataset.filter === state.activeFilter ? 'all' : tile.dataset.filter;
    page.update();
  });
}

// What the search box's menu offers after each qualifier (search.js's
// suggest), with how many of the list each would keep where the page
// counts them already: the tiles (as renderStats), the platforms, sets
// and maintainers (the facets), the reasons (their picks), the teams. The
// overview lists no packages: its tiles' counts from the manifest, where
// they're the list's too (not blocked or broken: the list's are fewer),
// and, under a name, the matches' (matches: what app.js's matches counted,
// {sets, statuses, by, teams, platforms}, or null), as status: and ofteam:
// everywhere.
const MANIFEST_COUNTS = {
  outdated: 'outdated',
  failed: 'failed',
  builds: 'buildFailures',
  updates: 'updateFailures',
  vulnerable: 'vulnerable',
  backport: 'backport',
};
// Each worked out once, when first asked for (a getter): the menu asks for
// one qualifier's values at a time, and the counts walk every package.
const once = (f) => {
  let done = false;
  let value;
  return () => {
    if (!done) [done, value] = [true, f()];
    return value;
  };
};
const lazily = (makers) =>
  Object.defineProperties(
    {},
    Object.fromEntries(
      Object.entries(makers).map(([k, f]) => [k, { get: once(f), enumerable: true }]),
    ),
  );
export function searchValues(matches = null) {
  const counted = store.packages.length > 0;
  const manifest = store.manifest?.counts || {};
  const base = once(() =>
    store.packages.filter((p) => inPlatform(p) && inList(p) && inPeople(p) && notHidden(p)),
  );
  const facets = once(() => (counted ? facetOptions() : { sets: [], by: [], platforms: {} }));
  const tiles = () =>
    Object.entries(FILTERS)
      .filter(([, f]) => f.param)
      .map(([key, f]) => ({
        value: f.param,
        label: f.label,
        ...(counted
          ? { count: base().filter((p) => f.test(p) && refined(p, key)).length }
          : manifest[MANIFEST_COUNTS[f.param]] != null
            ? { count: manifest[MANIFEST_COUNTS[f.param]] }
            : {}),
      }));
  const refines = Object.entries(REFINE_WORDS).map(([key, word]) => ({
    word,
    label: REFINES[key]?.label || key,
  }));
  const words = (prefix) =>
    refines
      .filter((r) => r.word.startsWith(`${prefix}:`))
      .map((r) => ({ value: r.word.slice(prefix.length + 1), label: r.label }));
  const reasons = (counts, names) =>
    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({ value, label: names(value), count }));
  const teams = once(() =>
    Object.entries(store.manifest?.views?.teams || {})
      .sort(([a], [b]) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
      .map(([value, count]) => ({ value, count })),
  );
  const pairs = (list) => list.map(([value, count]) => ({ value, count }));
  // The matches' own, on the overview (no list to count).
  const fromMatches = !counted && matches;
  return lazily({
    is: () => [...tiles(), ...words('is')],
    '-is': () => words('-is'),
    has: () => [...words('has'), { value: 'newer', label: 'a newer version known' }],
    '-has': () => [...words('-has'), { value: 'newer', label: 'no newer version known' }],
    age: () =>
      Object.entries(AGES).map(([value, label]) => ({ value, label: `older than ${label}` })),
    on: () =>
      Object.entries(PLATFORMS).map(([key, p]) => ({
        value: p.param,
        label: p.label,
        ...(counted
          ? { count: facets().platforms[key] }
          : fromMatches?.platforms[key] != null
            ? { count: fromMatches.platforms[key] }
            : {}),
      })),
    in: () => pairs(fromMatches ? fromMatches.sets : facets().sets),
    by: () => pairs(fromMatches ? fromMatches.by : facets().by),
    team: () => [...teams(), { value: 'none', label: 'not via a team' }],
    '-team': teams,
    build: () =>
      counted
        ? reasons(buildFailedCounts(), (k) => BUILD_FAILED[k]?.short || k)
        : Object.entries(BUILD_FAILED).map(([value, r]) => ({ value, label: r.short })),
    update: () =>
      counted
        ? reasons(becauseCounts(), (k) => FAILED_BECAUSE[k]?.short || k)
        : Object.entries(FAILED_BECAUSE).map(([value, r]) => ({ value, label: r.short })),
    status: () =>
      matches
        ? matches.statuses.map(([value, count]) => ({ value, label: NAME_STATUSES[value], count }))
        : Object.entries(NAME_STATUSES).map(([value, label]) => ({ value, label })),
    ofteam: () => (matches?.teams.length ? pairs(matches.teams) : teams()),
    sort: () => Object.entries(SORTS).map(([value, label]) => ({ value, label })),
    order: () => [{ value: 'reverse', label: 'the other way round' }],
  });
}
