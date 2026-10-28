// The list's header and filter controls: the tiles, the narrowing picks
// (why it failed, what's newer, the sort), the lists and teams to pick from.

import { viewSlug } from './address.js';
import { facetCounts, inPickedSet, nameSet, TOP_LEVEL } from './facets.js';
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
import { closeHtml, mergeHtml } from './maintainer-view.js';
import { html, raw, safeUrl } from './markup.js';
import { isHidden } from './prefs.js';
import { searchText } from './search.js';
import { failedBuilds, listView, scopeHref, state, teamName } from './state.js';
import { buildFailedBecause, failedBecause } from './status.js';
import { store } from './store.js';
import { BUILD_FAILED, bulkText, FAILED_BECAUSE, fmt, profileOf, teamPicker } from './ui.js';

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
function becausePick() {
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
function buildFailedPick() {
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
function errorsPick() {
  if (state.activeFilter !== 'builds' && state.activeFilter !== 'failed') return '';
  return html`<button type="button" class="refine-btn" data-show-errors aria-pressed="${state.showErrors}" title="${state.showErrors ? 'On: click to close them' : 'Open every failing package’s builds under it, with the lines from each log: loaded as they scroll into view'}">Show errors</button>`;
}

// "Newer version": any, known (?newer=yes), none known (?newer=no).
function newerPick() {
  return html`<label class="refine-age" title="Whether a newer version than nixpkgs' is known: with Build failures, none known means an update won't fix it, the build needs fixing">Newer version <select data-newer><option value="">any</option>${[
    ['yes', 'known'],
    ['no', 'none known'],
  ].map(
    ([key, label]) =>
      html`<option value="${key}"${state.newerFilter === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label>`;
}

// The order: a choice of SORTS, and ↓/↑ reversing it.
function sortPick() {
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
const stagingNextWhy = () => {
  const s = store.sources?.['branch:staging-next'];
  return s && !s.used && s.why ? s.why : null;
};

// "Open PR": any, with one (?refine=withpr), without (?refine=nopr).
function prPick() {
  const picked = ['withpr', 'nopr'].find((key) => state.refines.has(key)) || '';
  return html`<label class="refine-age" title="Whether an open PR touches it: for one marked broken, maybe its fix; without one, nobody is on it yet">Open PR <select data-pr-pick><option value="">any</option>${[
    'withpr',
    'nopr',
  ].map(
    (key) =>
      html`<option value="${key}"${picked === key ? raw(' selected') : ''}>${REFINES[key].label}</option>`,
  )}</select></label>`;
}

// "Upstream": any, changed (?refine=upstream), or one kind of change
// (?refine=upstreamgone, ...): what became of its GitHub repository.
const UPSTREAM_PICKS = [
  'upstream',
  'upstreamgone',
  'upstreamarchived',
  'upstreamrenamed',
  'upstreammoved',
];
function upstreamPick() {
  const picked = UPSTREAM_PICKS.find((key) => state.refines.has(key)) || '';
  return html`<label class="refine-age" title="What became of its GitHub repository: gone, archived (no longer worked on), renamed or moved to another owner">Upstream <select data-upstream-pick><option value="">any</option>${UPSTREAM_PICKS.map(
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
    )}${prPick()}${upstreamPick()}${newerPick()}${sortPick()}${errorsPick()}${
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
const TILES = {
  warn: 'Outdated',
  builds: 'Build failures',
  updates: 'Update failures',
  vuln: 'Vulnerable',
  backport: 'Fixes to backport',
  broken: 'Marked broken',
  blocked: 'Blocked',
};

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
                        : path === 'views/upstream.json'
                          ? 'Upstream changed'
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
              : path === 'views/upstream.json'
                ? html`<span class="scope-hint">their GitHub repository is gone, archived, renamed or moved, up to date or not; pick one kind under Upstream</span>`
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

// What the search box's menu offers after each qualifier (search.js's
// suggest), with how many of the list each would keep where the page
// counts them already: the tiles (as renderStats), the platforms, sets
// and maintainers (the facets), the reasons (their picks), the teams. The
// overview lists no packages: its tiles' counts from the manifest, where
// they're the list's too (not blocked or broken: the list's are fewer),
// and, under a name, the matches' (matches: what app.js's matches counted,
// {sets, statuses, by, teams, platforms}, or null), as status: and ofteam:
// everywhere.
export const MANIFEST_COUNTS = {
  outdated: 'outdated',
  failed: 'failed',
  builds: 'buildFailures',
  updates: 'updateFailures',
  vulnerable: 'vulnerable',
  backport: 'backport',
};
