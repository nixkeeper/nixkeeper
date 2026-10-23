import {
  attentionPrint,
  botWontUpdate,
  buildFailedBecause,
  buildsWith as buildsOn,
  communityCheck,
  comparedRepos,
  compareVersions,
  computeStatus,
  cvePieces,
  dayPosition,
  daysText,
  daysUntil,
  decodeFacets,
  facetCounts,
  failedBecause,
  hasFailure as failureOn,
  familyLabel,
  faviconKey,
  foldFamilies,
  fromMaster,
  homeHref,
  html,
  inPickedSet,
  isVulnerable,
  maintainerMatches,
  maintainersKeep,
  maintainersParam,
  matchesSearch,
  matchFacets,
  midway,
  NAME_DOTS,
  NAME_STATUSES,
  NEVER_BUILT,
  nameMatches,
  nameSet,
  neverBuiltOn,
  nixkeeperEntry,
  nothingCompared,
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
  attentionRank as rankOn,
  raw,
  githubRepo as repoFrom,
  safeUrl,
  searchHandle,
  severityRank,
  shardOf,
  shortAge,
  TOP_LEVEL,
  targetVersion,
  teamsKeep,
  teamsParam,
  themeFor,
  timeAgo,
  trendChange,
  unbuiltOn,
  unbuiltWhere,
  updateTitle,
  VIEWS,
  VULN_COUNTED,
  versionDiff,
  versionGap,
  viewPath,
  viewSlug,
  vulnSources,
  vulnSummary,
  waitingForChannel,
  withRunStamps,
  withSlash,
} from './logic.js';

const NIX_REPO = 'nix_unstable';

const githubRepo = (params) => repoFrom(params, location);

// Where the data (index.json, summary.json, the shards) lives, as a URL
// ending in "/". First of:
//   1. ?data=<url> in the address: for testing; same site only, so a link
//      can't point someone's page at data from elsewhere
//   2. <meta name="nixkeeper-data" content="<url>"> in index.html: a host
//      that keeps the data somewhere else sets it
//   3. data/ next to the page, when one server serves both (self-hosting)
//   4. on a GitHub Pages project site (https://<owner>.github.io/<repo>/),
//      the repo's data branch; ?owner=...&repo=... names another repo
async function findDataBase() {
  const params = new URLSearchParams(location.search);
  const asked = params.get('data');
  if (asked) {
    const url = new URL(asked, location.href);
    if (url.origin === location.origin) return withSlash(url.href);
  }
  const meta = document.querySelector('meta[name="nixkeeper-data"]')?.content;
  if (meta) return withSlash(new URL(meta, location.href).href);
  try {
    const res = await fetch('data/index.json', { method: 'HEAD', cache: 'no-store' });
    if (res.ok) return new URL('data/', location.href).href;
  } catch {
    // not served here: try GitHub
  }
  const repo = githubRepo(params);
  return repo ? `https://raw.githubusercontent.com/${repo}/data/data/` : null;
}

// The footer links to nixkeeper itself; a copy of it on GitHub Pages (its
// own package lists) also links to those lists.
const UPSTREAM = 'nixkeeper/nixkeeper';
function addListsLink() {
  const repo = githubRepo(new URLSearchParams(location.search));
  if (!repo || repo === UPSTREAM) return;
  const a = document.createElement('a');
  a.className = 'files-link';
  a.href = `https://github.com/${repo}/tree/HEAD/package-lists`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = "this page's package lists ↗";
  document.getElementById('about')?.prepend(a);
}
addListsLink();
// The lockup goes back to the overview, with no filters (a page load: every
// filter, search and open panel starts over).
document.getElementById('homeLink').href = homeHref(location.pathname, location.search);

let dataBase = null; // set by loadIndex
const dataUrl = (path) => new URL(path, dataBase).href;
// The data (docs/data.md, format 2): the list from summary.json (a short
// entry per package), each package's full row from its shard
// (rows/<n>.json, of shardCount), loaded when a panel opens.
let shardCount = 1;
// With every package (a community instance: index.json's allPackages), the
// page shows one view of the data at a time (viewPath): `packages` is that
// view's, `manifest` index.json, with the counts of all of nixpkgs.
let community = false;
// The line by the logo on an instance of its own lists (index.html's is
// for every package).
const OWN_TAG = 'health of your nixpkgs packages';
let manifest = null;
let sources = null; // the daily sync's sources (index.json's "sources")
let shownView = null; // the path of the view in `packages`
let wantedView = null; // the one being loaded (the newest asked for wins)
let names = null; // the name index (names.json), once loaded: [[name, status, set?]]
let namesLoading = null;
// facets.json, decoded (decodeFacets): each names entry's maintainers,
// teams and platforms, by its position there (nameIndex), once loaded for
// a search's filters. Null if it doesn't line up with names (a sync
// between the two loads): the search then filters without them.
let facetIndex = null;
let facetsLoading = null;
let nameIndex = null;
const facetsOf = (entry) => facetIndex[nameIndex.get(entry)];
// ?pkg=: one package alone (with every package); ?set=: a generated set;
// ?view=: a list by name (attention, broken).
let pkgParam = null;
// The ?pkg= its details were opened for, once: a link to a package opens
// them, and closing them keeps them closed while it's shown.
let pkgOpenedFor = null;
let viewParam = null;
let trendPoints = null; // history.json's points, once loaded (the overview's trends)
let trendEvents = []; // and what marks them (staging-next merges, nixkeeper updates)
let historyLoading = false;
let setFilter = null;
const inSet = (pkg) => !setFilter || pkg.set === setFilter;
// ?cause=: a group of failed builds sharing an error (views/cause/<key>.json,
// nixkeeper's causes.py), and what its view file says of it.
let causeFilter = null;
let causeShown = null;
const shardCache = new Map(); // n -> Promise of Map(name -> full row)
let packages = [];
let checkedAt = null;
let activeFilter = 'all'; // 'all' | 'warn' | 'failed' | 'vuln'
// Narrowing any list further, with everything else (?refine=, REFINES keys
// comma-separated, and ?age=, an AGES key).
let refines = new Set();
let ageFilter = null;
// ?updateFailed=: update failures for one reason (a FAILED_BECAUSE key, or
// other).
let becauseFilter = null;
// ?buildFailed=: build failures for one reason (a BUILD_FAILED key).
let buildFailedFilter = null;
// ?newer=: whether a newer version is known ("yes": outdated, merged or
// not; "no": not outdated), with any tile: build failures an update won't
// fix (?filter=builds&newer=no), say.
let newerFilter = null;
// ?errors=1: with Build failures (or Failed), every failing row's build
// panel open under it, loaded as it scrolls into view (watchErrors).
let showErrors = false;
const errorsHere = () => showErrors && (activeFilter === 'builds' || activeFilter === 'failed');
// ?in=: one package set, by the attribute's first part (logic.js nameSet:
// python313Packages, vimPlugins, top-level); ?by=: one maintainer's
// packages within the list shown (a handle, lowercase). Counted, with the
// platforms, over the list's other filters (facetOptions).
let inFilter = null;
let byFilter = null;
const inNameSet = (pkg) => !inFilter || inPickedSet(nameSet(pkg.name), inFilter);
const byMaintainer = (pkg) =>
  !byFilter || (pkg.maintainers || []).some((m) => m.toLowerCase() === byFilter);
// ?status=: the search's matches in all of nixpkgs of one status (a
// NAME_STATUSES key: what the name index's letter says). How many of them
// are shown, more on asking (moreMatchesHtml), from MATCHES_SHOWN again
// with another search or filter (matchQuery: what was asked).
let statusFilter = null;
// ?ofteam=: the matches of one team (its name as nixpkgs writes it); the
// maintainer (?by=) and platform (?platform=) ones are the list's own.
let matchTeam = null;
const MATCHES_SHOWN = 50;
const MATCHES_MORE = 200;
let matchLimit = MATCHES_SHOWN;
let matchQuery = '';
// What every filter but the facets kept, last time the list was worked out
// (currentFiltered): the facets count over it, with no second pass.
let facetBase = [];
// The list's order (?sort=, SORTS key; the first, most pressing, is the
// default) and whether it's reversed (?order=reverse).
const SORTS = {
  pressing: 'most pressing',
  oldest: 'longest-standing',
  newest: 'newest',
  gap: 'biggest version gap',
  az: 'name A–Z',
};
let sortMode = 'pressing';
let sortReverse = false;
// The table shows pageSize rows at a time: drawing stays fast whatever the
// data's size, and the page keeps working with Ctrl+F and screen readers
// (no virtual scrolling). ?page= in the address, past the first; ?per= for
// another of PAGE_SIZES (only those: a huge one would draw every package at
// once), also picked under the table.
const PAGE_SIZES = [50, 100, 200, 500, 1000];
const DEFAULT_PAGE_SIZE = 200;
let pageSize = DEFAULT_PAGE_SIZE;
// Of those, drawn first, with the counts and tiles: more than a screen's
// worth; the rest follow a moment later (update).
const FIRST_ROWS = 50;
let pageNum = 1;
let platformFilter = null; // null | 'linux' | 'darwin', combined with activeFilter
// The rules that follow the platform filter (logic.js), on the selected one.
const hasFailure = (pkg) => failureOn(pkg, platformFilter);
const buildsWith = (pkg, status) => buildsOn(pkg, status, platformFilter);
const failedBuilds = (pkg) => buildsWith(pkg, 'failed');
const attentionRank = (pkg) => rankOn(pkg, platformFilter);
// null, or a list from package-lists/ ("maintained", "gaming-team", ...):
// ?list=gaming-team is a page of just that list's packages, to share.
let listFilter = null;
const inList = (pkg) => !listFilter || (pkg.lists || []).includes(listFilter);
// null, or a nixpkgs team (meta.teams, by its short name; any case):
// ?team=gaming is a page of the team's packages here.
let teamFilter = null;
// ?team= besides one team: teams left out (-Geospatial), and none (not
// through a team: logic.js parseTeams).
let teamsLeftOut = [];
let noTeam = false;
// ?maintainer='s handles left out (-iedame), lowercase.
let maintainersLeftOut = [];
const isTeam = (name) => name.toLowerCase() === teamFilter.toLowerCase();
// What the address keeps by people: its teams, and maintainers left out.
const inPeople = (pkg) =>
  teamsKeep(pkg, { include: teamFilter, leftOut: teamsLeftOut, none: noTeam }, shownHandle()) &&
  maintainersKeep(pkg, maintainersLeftOut);
// The team's name as nixpkgs writes it ("Qt-KDE"), or as the address has it.
const teamName = () => packages.flatMap((p) => p.teams || []).find(isTeam) || teamFilter;
// Every list some package is on: "maintained" first, as the sync sorts them.
function allLists() {
  // With every package, the view has only some: the manifest has them all.
  if (community)
    return Object.keys(manifest.views?.lists || {}).sort((a, b) =>
      a === 'maintained'
        ? -1
        : b === 'maintained'
          ? 1
          : a.localeCompare(b, undefined, { sensitivity: 'base' }),
    );
  const seen = [];
  for (const p of packages) for (const l of p.lists || []) if (!seen.includes(l)) seen.push(l);
  return seen.sort((a, b) =>
    a === 'maintained' ? -1 : b === 'maintained' ? 1 : a.localeCompare(b),
  );
}

// The platform filter's choices, families and the systems nixpkgs builds
// ("any platform" counts as all: onPlatform), in nixpkgs' words
// (lib.platforms.darwin, aarch64-linux), other names on hover. `also`:
// another address that still picks it (?platform=macos, from before 0.14.0).
const PLATFORMS = {
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
// The systems of a family nixpkgs builds (SYSTEMS in nixkeeper/sources/nixpkgs.py).
const LINUX_SYSTEMS = ['x86_64-linux', 'aarch64-linux'];
// Available on the platform picked: listed for it, and built there by Hydra
// when Hydra builds it at all (unbuiltOn); listed but not built counts only
// with "Not built where listed" on, or in its view, which find exactly
// those.
function inPlatform(pkg) {
  if (!platformFilter) return true;
  if (!onPlatform(pkg, platformFilter)) return false;
  // Not built where listed (?view=unbuilt): a platform picked keeps those
  // not built there (Darwin: the Darwin ones), as the refine does.
  if (shownView === VIEWS.unbuilt) return unbuiltOn(pkg, platformFilter);
  return refines.has('unbuilt') || !unbuiltOn(pkg, platformFilter);
}
// The sync runs daily; older than this means runs are failing or GitHub has
// paused the schedule (it does after 60 days without commits).
const STALE_AFTER_HOURS = 48;

// `param` is how each filter appears in the page address (?filter=outdated).
const FILTERS = {
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
const REFINES = {
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
      platformFilter
        ? onPlatform(p, platformFilter) && unbuiltOn(p, platformFilter)
        : unbuiltWhere(p).length > 0,
  },
  // Where a person is needed: nixpkgs-update won't open the PR.
  // An open update PR nixpkgs is already past (prs_digest.mark_superseded).
  superseded: {
    label: 'PR to close',
    title:
      'Only packages with an open update PR nixpkgs is already past: it has the PR’s version or a newer one, so the PR can be closed',
    test: (p) => (p.supersededPRs || []).length > 0,
  },
  nobot: {
    label: "Bot won't update it",
    title:
      "Only outdated packages nixpkgs-update won't update by itself: it can't, it skips them on purpose, or it has never tried and they aren't in its queue. No update PR open or merged yet",
    test: (p) => botWontUpdate(p, Boolean(sources?.queue?.used)),
  },
};
const AGES = {
  '1m': 'a month',
  '6m': '6 months',
  '1y': 'a year',
  '2y': '2 years',
  '3y': '3 years',
  [NEVER_BUILT]: 'never built',
};
// kind: whose age counts (a FILTERS key): the list's, or a count's own.
const refined = (p, kind = activeFilter) =>
  [...refines].every((key) => REFINES[key].test(p)) &&
  (!newerFilter || (newerFilter === 'yes') === (computeStatus(p) === 'warn')) &&
  (!becauseFilter || failedBecause(p) === becauseFilter) &&
  (!buildFailedFilter || buildFailedBecause(p, platformFilter).includes(buildFailedFilter)) &&
  olderThan(p, ageFilter, kind, Date.now(), platformFilter);

// The maintainer whose page this is (@handle in the search), or null.
const shownHandle = () => searchHandle(document.getElementById('search').value);

// ?team='s teams left out, ?maintainer='s maintainers left out, and none
// (packages without a team) where no maintainer's page has its button:
// each a chip to undo it.
const teamOutChips = () =>
  html`${maintainersLeftOut.map(
    (h) =>
      html`<button type="button" class="plat-filter" data-maintainer-out="${h}" title="Show @${h}'s packages again">not @${h} ✕</button>`,
  )}${teamsLeftOut.map(
    (t) =>
      html`<button type="button" class="plat-filter" data-team-out="${t}" title="Show the ${t} team's packages again">not ${t} ✕</button>`,
  )}${
    noTeam && !shownHandle()
      ? html`<button type="button" class="plat-filter" data-team-none title="Show packages with a team again">no team ✕</button>`
      : ''
  }`;

// "Failed because" (?updateFailed=): the reasons update attempts failed, each
// with how many of the list's packages it is (as the tiles count: the
// other filters but this one), the commonest first; those with none left
// out, but the one picked.
function becausePick() {
  const base = packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && failedBecause(p),
  );
  const counts = {};
  for (const p of base) {
    const why = failedBecause(p);
    counts[why] = (counts[why] || 0) + 1;
  }
  const label = (key) => (key === 'noLog' ? 'build, no log' : FAILED_BECAUSE[key]?.short || key);
  const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
  if (becauseFilter && !keys.includes(becauseFilter)) keys.push(becauseFilter);
  if (!keys.length) return '';
  return html`<label class="refine-age" title="Update failures for one reason, as nixpkgs-update's log says (its last attempt). The counts are of this list, with its other filters">Update failed because <select data-because><option value="">any reason</option>${keys.map(
    (key) =>
      html`<option value="${key}"${becauseFilter === key ? raw(' selected') : ''}>${label(key)} (${fmt(counts[key] || 0)})</option>`,
  )}</select></label>`;
}

// "Build failed because" (?buildFailed=): the reasons builds failed on Hydra
// (from their logs, nixkeeper-hydra), each with how many of the list's
// packages have a failed build for it (on the platform picked), the
// commonest first; as becausePick.
function buildFailedPick() {
  const base = packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && failedBuilds(p).length,
  );
  const counts = {};
  for (const p of base)
    for (const why of buildFailedBecause(p, platformFilter)) counts[why] = (counts[why] || 0) + 1;
  // Not before nixkeeper-hydra read any: nothing to pick from.
  if (!Object.keys(counts).some((k) => k !== 'unread') && !buildFailedFilter) return '';
  const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
  if (buildFailedFilter && !keys.includes(buildFailedFilter)) keys.push(buildFailedFilter);
  return html`<label class="refine-age" title="Build failures for one reason, as the build's log on Hydra says. The counts are of this list, with its other filters">Build failed because <select data-build-failed><option value="">any reason</option>${keys.map(
    (key) =>
      html`<option value="${key}"${buildFailedFilter === key ? raw(' selected') : ''}>${BUILD_FAILED[key]?.short || key} (${fmt(counts[key] || 0)})</option>`,
  )}</select></label>`;
}

// With Build failures or Failed picked: every failing row's errors at once.
function errorsPick() {
  if (activeFilter !== 'builds' && activeFilter !== 'failed') return '';
  return html`<button type="button" class="refine-btn" data-show-errors aria-pressed="${showErrors}" title="${showErrors ? 'On: click to close them' : 'Open every failing package’s builds under it, with the lines from each log: loaded as they scroll into view'}">Show errors</button>`;
}

// "Newer version": any, known (?newer=yes), none known (?newer=no).
function newerPick() {
  return html`<label class="refine-age" title="Whether a newer version than nixpkgs' is known: with Build failures, none known means an update won't fix it, the build needs fixing">Newer version <select data-newer><option value="">any</option>${[
    ['yes', 'known'],
    ['no', 'none known'],
  ].map(
    ([key, label]) =>
      html`<option value="${key}"${newerFilter === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label>`;
}

// The order: a choice of SORTS, and ↓/↑ reversing it.
function sortPick() {
  return html`<label class="refine-age" title="The list's order">Sort <select data-sort>${Object.entries(
    SORTS,
  ).map(
    ([key, label]) =>
      html`<option value="${key}"${sortMode === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label><button type="button" class="refine-btn sort-dir" data-sort-dir aria-pressed="${sortReverse}" aria-label="Reverse the order" title="${sortReverse ? 'Reversed: click for the usual order' : 'Reverse the order'}">${sortReverse ? '↑' : '↓'}</button>`;
}

// Why "Breaks on staging-next" finds nothing now, when the sync didn't use
// staging-next's evaluation (its sources: "of the cycle merged into
// master..."), or null.
const stagingNextWhy = () => {
  const s = sources?.['branch:staging-next'];
  return s && !s.used && s.why ? s.why : null;
};

// "Open PR": any, with one (?refine=withpr), without (?refine=nopr).
function prPick() {
  const picked = ['withpr', 'nopr'].find((key) => refines.has(key)) || '';
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
const BY_SHOWN = 300; // the maintainers offered, the most first
function facetOptions() {
  const sets = facetCounts(
    facetBase.filter((p) => byMaintainer(p) && inPlatform(p)),
    (p) => nameSet(p.name),
  );
  const by = facetCounts(
    facetBase.filter((p) => inNameSet(p) && inPlatform(p)),
    (p) =>
      (p.maintainers || []).length > 1
        ? [...new Set(p.maintainers.map((m) => m.toLowerCase()))]
        : (p.maintainers || []).map((m) => m.toLowerCase()),
  );
  const near = facetBase.filter((p) => inNameSet(p) && byMaintainer(p));
  const picked = platformFilter;
  const platforms = {};
  for (const key of Object.keys(PLATFORMS)) {
    platformFilter = key;
    platforms[key] = near.filter(inPlatform).length;
  }
  platformFilter = picked;
  return { sets, by: by.slice(0, BY_SHOWN), platforms };
}

// A facet's choice, with its count, selected when it's the one picked.
const facetOption = (value, label, count, picked) =>
  html`<option value="${value}"${picked === value ? raw(' selected') : ''}>${label} (${fmt(count)})</option>`;

function refineHtml() {
  const facets = facetOptions();
  // python3Packages (an alias, ?in=): its sets' counts together.
  const setCount = (v) =>
    facets.sets.filter(([s]) => inPickedSet(s, v)).reduce((n, [, c]) => n + c, 0);
  const sets =
    inFilter && !facets.sets.some(([s]) => s === inFilter)
      ? [...facets.sets, [inFilter, 0]]
      : facets.sets;
  return html`<div class="refine" role="group" aria-label="Narrow the list">${Object.entries(
    REFINES,
  )
    .filter(([, r]) => !r.pick)
    .map(
      ([key, r]) =>
        html`<button type="button" class="refine-btn" data-refine="${key}" aria-pressed="${refines.has(key)}" title="${r.title}${key === 'stagingnext' && stagingNextWhy() ? `. Now: ${stagingNextWhy()}` : ''}${refines.has(key) ? ' (on: click to remove)' : ''}">${r.label}</button>`,
    )}${prPick()}${newerPick()}${sortPick()}${errorsPick()}${
    // On a maintainer's page: ?team=none.
    shownHandle()
      ? html`<button type="button" class="refine-btn" data-no-team aria-pressed="${noTeam}" title="Only packages that list this maintainer themselves: leave out those they maintain only as a member of the package's team (meta.teams)">Not via a team</button>`
      : ''
  }<label class="refine-age" title="How long it's been failing or outdated (the kind picked above, if any); or failing builds that never succeeded on Hydra, which have no date">Older than <select data-age><option value="">any age</option>${Object.entries(
    AGES,
  ).map(
    ([key, label]) =>
      html`<option value="${key}"${ageFilter === key ? raw(' selected') : ''}>${label}</option>`,
  )}</select></label>${buildFailedPick()}${becausePick()}<label class="refine-age" title="Only packages available on it, and of their builds the ones there (build failures on Darwin, say). Darwin is macOS, as nixpkgs calls it. Each with how many it would show.">On <select data-platform-pick><option value="">any platform</option>${Object.entries(
    PLATFORMS,
  ).map(([key, p]) =>
    facetOption(key, p.label, facets.platforms[key], platformFilter),
  )}</select></label>${
    sets.length > 1 || inFilter
      ? html`<label class="refine-age" title="Only one package set, by the attribute's first part (python313Packages, vimPlugins), or the top-level packages. Each with how many it would show.">In <select data-in><option value="">any set</option>${sets.map(
          ([v]) => facetOption(v, v === TOP_LEVEL ? 'top level' : v, setCount(v), inFilter),
        )}</select></label>`
      : ''
  }${
    // Not on a maintainer's own page: it's theirs already.
    shownHandle()
      ? ''
      : html`<label class="refine-age" title="Only the packages this maintainer is listed for (meta.maintainers), within this list: type a GitHub handle. The ${fmt(facets.by.length)} with the most here are offered, each with how many.">By <input type="search" class="by-pick" data-by list="byOptions" placeholder="any maintainer" value="${byFilter || ''}" autocomplete="off" spellcheck="false"><datalist id="byOptions">${facets.by.map(
          ([h, n]) => html`<option value="${h}">${fmt(n)}</option>`,
        )}</datalist></label>`
  }</div>`;
}

// The overview's build failures by where they fail (the manifest's
// buildFailuresOn): Linux and Darwin, each Hydra system on hover. Not with
// data from before.
function platformSplit(on) {
  if (!on || on.linux == null) return '';
  const systems = Object.entries(on)
    .filter(([k]) => k.includes('-'))
    .map(([k, n]) => `${k} ${fmt(n)}`)
    .join(', ');
  return html`<span class="card-sub" title="Packages whose own build fails there: ${systems}. A package failing on both Linux systems counts once for Linux; on Linux and Darwin (macOS), once for each. Narrow the list by platform under its tiles.">Linux ${fmt(on.linux)} · Darwin ${fmt(on.darwin || 0)}</span>`;
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

// Where the package's update stands on GitHub, in GitHub's own colors:
// "on master" (merged, purple) while waiting for the channel, else an open
// update PR (green; grey while a draft). A link to the PR when it's known.
const badge = (cls, text, title, pr) =>
  pr
    ? html` <a class="badge ${cls}" href="${safeUrl(pr.url)}" target="_blank" rel="noopener" title="${title}">${text}</a>`
    : html` <span class="badge ${cls}" title="${title}">${text}</span>`;

// The update's badge: on master when that's all it waits for, else merged
// into staging or staging-next on its way there, else its PR, else the
// branch that has it (haskell-updates), waiting for its merge.
function prBadge(pkg) {
  if (waitingForChannel(pkg)) return masterBadge(pkg);
  if (pkg.stagingPR) return stagingBadge(pkg);
  if (pkg.openPR) return openPrBadge(pkg);
  return onBranch(pkg) ? branchBadge(pkg) : '';
}

const hydraBuildUrl = (build) => `https://hydra.nixos.org/build/${encodeURIComponent(build)}`;

function branchBadge(pkg) {
  const b = pkg.branch;
  return badge(
    'onmaster',
    `on ${b.name}`,
    `${b.name} already has ${b.version}: waiting for its merge into master (about every two weeks)`,
    b.build ? { url: hydraBuildUrl(b.build) } : null,
  );
}

// What a branch updating its set before master (haskell-updates) has, in
// the panel: its version, how its build went, and what that means here.
const BRANCH_BUILD = {
  ok: 'builds',
  failed: 'fails to build',
  dependency: "doesn't build: a dependency fails",
  unfinished: "didn't finish building",
  queued: "isn't built yet",
};
function branchNote(pkg) {
  const b = pkg.branch;
  if (!b) return '';
  const failing = failedBuilds(pkg).length > 0;
  if (b.version === pkg.nixVersion && b.status === 'ok' && !failing) return '';
  const after = onBranch(pkg)
    ? b.status === 'ok'
      ? ': the update waits for its merge into master, about every two weeks.'
      : ', so the update may wait for a fix before the branch merges.'
    : failing && b.status === 'ok'
      ? ': fixed there, once the branch merges into master.'
      : failing
        ? ': failing there too.'
        : b.status === 'failed' || b.status === 'dependency'
          ? ': it breaks when the branch merges into master, unless fixed first.'
          : '.';
  return html`<div class="master-note"><span class="mono">${b.name}</span> has <span class="mono">${b.version}</span>, which ${BRANCH_BUILD[b.status] || b.status} there (<a class="files-link" href="${safeUrl(hydraBuildUrl(b.build))}" target="_blank" rel="noopener">build ↗</a>)${after}</div>`;
}

// Where an update merged into staging or staging-next is, and what it waits
// for: staging-next's merge into master (about every two to three weeks),
// or before that, the next staging-next.
function stagingWait(pr) {
  return pr.on === 'staging-next'
    ? `reaches master when staging-next is merged into it${pr.cycle ? ` (#${pr.cycle.n}, open since ${shortDay(pr.cycle.cut.slice(0, 10))})` : ''}`
    : 'goes to staging-next when the next one is cut from staging, then to master with it';
}

function stagingBadge(pkg) {
  const pr = pkg.stagingPR;
  return badge(
    'onmaster',
    `on ${pr.on}`,
    `${pr.on} has ${pr.to}: merged in #${pr.number} (${pr.title}); it ${stagingWait(pr)}. A mass rebuild's way: weeks, not days`,
    pr,
  );
}

// How an update on staging-next builds there, from Hydra's newest
// evaluation of it (branches.apply_staging_next): built everywhere, failing
// where (each failure's build linked), not built yet, or not in that
// evaluation yet. Said with the evaluation's day: it's a day or two old.
const STAGING_BUILD = {
  failed: 'fails to build',
  dependency: 'fails: a dependency fails',
};
function stagingBuilds(pr) {
  if (!pr.eval) return '';
  const when = pr.eval.evaluatedAt ? ` of ${shortDay(pr.eval.evaluatedAt.slice(0, 10))}` : '';
  const evalLink = html`<a class="files-link" href="https://hydra.nixos.org/eval/${pr.eval.eval}" target="_blank" rel="noopener">Hydra's evaluation${when} ↗</a>`;
  if (!pr.inEval) return html` It isn't in ${evalLink} yet.`;
  const builds = pr.builds || [];
  // staging-next past this PR's version: what it builds is that one.
  const it = pr.evalVersion
    ? html`staging-next has a newer version, <span class="mono">${pr.evalVersion}</span>, which`
    : 'it';
  const failing = builds.filter((b) => STAGING_BUILD[b.status]);
  if (failing.length)
    return html` In ${evalLink}, ${it} ${failing.map(
      (b, i) =>
        html`${i ? (i === failing.length - 1 ? ' and ' : ', ') : ''}${STAGING_BUILD[b.status]} on ${b.system} (<a class="files-link" href="${safeUrl(hydraBuildUrl(b.build))}" target="_blank" rel="noopener">build ↗</a>)`,
    )}.`;
  const waiting = builds.filter((b) => b.status !== 'ok');
  if (waiting.length)
    return html` In ${evalLink}, ${it} isn't built yet on ${waiting.map((b) => b.system).join(', ')}.`;
  return html` In ${evalLink}, ${it} builds${builds.length > 1 ? ' on every platform' : ''}.`;
}

// What staging-next breaks: this package, building on master, fails its own
// build there (each platform's build linked), as of Hydra's newest
// evaluation of it.
function stagingNextBreaksNote(pkg) {
  const b = pkg.stagingNextBreaks;
  if (!b) return '';
  const when = b.evaluatedAt ? ` of ${shortDay(b.evaluatedAt.slice(0, 10))}` : '';
  const evalLink = html`<a class="files-link" href="https://hydra.nixos.org/eval/${b.eval}" target="_blank" rel="noopener">Hydra's evaluation${when} ↗</a>`;
  const systems = [...new Set(b.builds.map((x) => x.system))];
  const builds = b.builds.map(
    (x, i) =>
      html`${i ? ', ' : ''}<a class="files-link" href="${safeUrl(hydraBuildUrl(x.build))}" target="_blank" rel="noopener">${b.builds.length > systems.length ? `${x.attr} on ` : ''}${x.system} ↗</a>`,
  );
  const merge = b.cycle
    ? html` (<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${b.cycle.n}" target="_blank" rel="noopener">#${b.cycle.n} ↗</a>)`
    : '';
  return html`<div class="master-note">⚠ Breaks on <span class="mono">staging-next</span>: in ${evalLink}, it fails to build there (${builds}), at the same version master builds fine. Unless fixed, it fails on master when staging-next is merged into it${merge}; a fix may already be on staging.</div>`;
}

// On staging-next, this package stops others (a failing dependency there),
// or is stopped there by one, as of Hydra's newest evaluation of it.
function stagingNextBlockedNote(pkg) {
  const notes = [];
  const evalOf = (x) =>
    html`<a class="files-link" href="https://hydra.nixos.org/eval/${x.eval}" target="_blank" rel="noopener">Hydra's evaluation${x.evaluatedAt ? ` of ${shortDay(x.evaluatedAt.slice(0, 10))}` : ''} ↗</a>`;
  const blocks = pkg.stagingNextBlocks;
  if (blocks)
    notes.push(
      html`<div class="master-note">⚠ On <span class="mono">staging-next</span>, its failure stops ${fmt(blocks.packages)} other ${blocks.packages === 1 ? "package's" : "packages'"} builds (${fmt(blocks.builds)} ${blocks.builds === 1 ? 'build' : 'builds'}, in ${evalOf(blocks)}) that build on master: fixing it there unblocks them before staging-next is merged.</div>`,
    );
  const blocked = pkg.stagingNextBlockedBy;
  if (blocked) {
    const by = [...new Map(blocked.builds.flatMap((b) => b.by).map((x) => [x.name, x])).values()];
    const names = by.map(
      (x, i) =>
        html`${i ? ', ' : ''}${x.row ? html`<a class="files-link mono" href="${scopeHref({ pkg: x.name })}" data-scope-pkg="${x.name}">${x.name}</a>` : html`<span class="mono">${x.name}</span>`}`,
    );
    const systems = [...new Set(blocked.builds.map((b) => b.system))].join(', ');
    notes.push(
      html`<div class="master-note">On <span class="mono">staging-next</span>, its build (${systems}) is stopped by ${names}, failing there, in ${evalOf(blocked)}; it builds on master. Unless that's fixed, it's stopped on master too when staging-next is merged.</div>`,
    );
  }
  return notes;
}

function stagingNote(pkg) {
  const pr = pkg.stagingPR;
  if (!pr) return '';
  return html`<div class="master-note"><span class="mono">${pr.on}</span> already has <span class="mono">${pr.to}</span> (merged in <a class="files-link" href="${safeUrl(pr.url)}" target="_blank" rel="noopener">#${pr.number} ↗</a>${pr.merged ? ` on ${longDate(pr.merged)}` : ''}): it ${stagingWait(pr)}.${stagingBuilds(pr)}</div>`;
}

function masterBadge(pkg) {
  const pr = pkg.masterPR;
  return badge(
    'onmaster',
    'on master',
    `master already has ${onMaster(pkg)}: merged${pr ? ` in #${pr.number} (${pr.title})` : ''}, waiting for nixos-unstable to catch up (usually a few days)`,
    pr,
  );
}

function openPrBadge(pkg) {
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
const queuedTo = (pkg) =>
  pkg.queued?.to || [...new Set((pkg.queued?.candidates || []).map(([to]) => to))];

// A robot's head (nixpkgs-update, the bot), in the text's colour.
const BOT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.6v2"/><circle cx="8" cy="1.8" r="0.9" fill="currentColor" stroke="none"/><rect x="2.75" y="4.6" width="10.5" height="8.4" rx="2.2"/><circle cx="6" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><circle cx="10" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><path d="M1 7.8v2.2M15 7.8v2.2"/></svg>',
);

// A hard hat (Hydra's builders), in the text's colour: a failing build's
// mark in the build cell, as the robot is a failed update's.
const HAT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 11V9.6a4.8 4.8 0 0 1 9.6 0V11"/><path d="M6.6 5.1v3M9.4 5.1v3"/><rect x="1.5" y="11" width="13" height="2.4" rx="1.2"/></svg>',
);

// GitHub's own icons (Octicons, (c) GitHub, MIT licence), 14px, in the
// text's colour: an open PR, a draft, a merged one, an open issue. In the
// list's GitHub cell and before each PR and issue in a package's details.
const octicon = (d) =>
  raw(
    `<svg class="gh-icon" viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">${d
      .map((p) => `<path d="${p}"/>`)
      .join('')}</svg>`,
  );
const GH_ICONS = {
  pr: octicon([
    'M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z',
  ]),
  draft: octicon([
    'M3.25 1A2.25 2.25 0 0 1 4 5.372v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.251 2.251 0 0 1 3.25 1Zm9.5 14a2.25 2.25 0 1 1 0-4.5 2.25 2.25 0 0 1 0 4.5ZM2.5 3.25a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0ZM3.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm9.5 0a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM14 7.5a1.25 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Zm0-4.25a1.25 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Z',
  ]),
  merged: octicon([
    'M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z',
  ]),
  issue: octicon([
    'M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z',
    'M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z',
  ]),
};

// The robot in place of a cell's dot (updateCell): red, or "queued" amber
// and "match" green, the queue's colours (queuedState).
const botMark = (colour) =>
  html`<span class="bot-mark${colour ? ` ${colour}` : ''}" aria-hidden="true">${BOT_ICON}</span>`;

// Whether nixpkgs-update is set to try the package (the update cell's robot):
// { match: to the newest version, its last attempt fine, so its PR should
// follow; title }, or null.
function queuedState(pkg) {
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
function botDueText(pkg) {
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
const VERSION_LINE = 28;
function tooWide(version, badges) {
  const widest = Math.max(
    0,
    ...[...String(badges).matchAll(/class="badge[^"]*"[^>]*>([^<]*)</g)].map(
      (m) => m[1].length * 0.95 + 1.5,
    ),
  );
  return widest > 0 && String(version || '').length + 2 + widest > VERSION_LINE;
}

function versionCell(pkg, st) {
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

// How long an outdated package has been outdated, after its name: orange,
// or violet when the update is merged and waiting for the channel.
// Since when a row's builds or update attempts have been failing: the
// earlier of the two (failingSince, updateFailingSince), or null.
const failingSince = (pkg) =>
  [pkg.failingSince, pkg.updateFailingSince].filter(Boolean).sort()[0] || null;

// Where a row's failing builds (on the platform picked, if any) never
// succeeded on Hydra: linux (both its systems), x86_64-linux or
// aarch64-linux, darwin; "" when nowhere.
function neverWhere(pkg) {
  if (!failedBuilds(pkg).length) return '';
  const systems = neverBuiltOn(pkg, platformFilter);
  const linux = systems.filter((s) => s.endsWith('-linux'));
  const names = linux.length === LINUX_SYSTEMS.length ? ['linux'] : linux;
  if (systems.some((s) => s.endsWith('-darwin'))) names.push('darwin');
  return names.join(', ');
}

function ageTag(pkg, st) {
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

// Copies an update's title, and says so on the button for a moment. The
// clipboard API needs a secure page (https, or localhost); elsewhere (a
// self-hosted page over plain http) the older way.
async function copyTitle(btn) {
  const text = btn.dataset.copy;
  if (!text) return;
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch {
    const area = Object.assign(document.createElement('textarea'), { value: text });
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    ok = document.execCommand('copy');
    area.remove();
  }
  btn.dataset.copied = ok ? 'Copied' : "Couldn't copy";
  announce(ok ? `Copied ${text}` : "Couldn't copy");
  clearTimeout(btn.copiedTimer);
  btn.copiedTimer = setTimeout(() => delete btn.dataset.copied, 1500);
}

// Filter, search and sort live in the page address, so a view survives a
// reload and can be bookmarked or shared. Other parameters (owner, repo) are
// left alone.
function readViewFromUrl() {
  const params = new URLSearchParams(location.search);
  activeFilter =
    Object.keys(FILTERS).find(
      (k) => FILTERS[k].param && FILTERS[k].param === params.get('filter'),
    ) || 'all';
  // A maintainer's page: ?maintainer=handle (the search shows @handle);
  // ?q=@handle, as it was first written, opens it too and becomes that.
  // -handle in it: their packages left out, on any list.
  const maintainers = parseMaintainers(params.get('maintainer'));
  maintainersLeftOut = maintainers.leftOut;
  document.getElementById('search').value = maintainers.handle
    ? `@${maintainers.handle}`
    : params.get('q') || '';
  sortMode = SORTS[params.get('sort')] ? params.get('sort') : 'pressing';
  sortReverse = params.get('order') === 'reverse';
  platformFilter =
    Object.keys(PLATFORMS).find((k) =>
      [PLATFORMS[k].param, PLATFORMS[k].also].includes(params.get('platform')),
    ) || null;
  // Any name: which lists exist is only known once the data has loaded.
  listFilter = params.get('list') || null;
  const teams = parseTeams(params.get('team'));
  teamFilter = teams.include;
  teamsLeftOut = teams.leftOut;
  noTeam = teams.none;
  setFilter = params.get('set') || null;
  causeFilter = /^[0-9a-f]{10}$/.test(params.get('cause') || '') ? params.get('cause') : null;
  pkgParam = params.get('pkg') || null;
  viewParam = params.get('view') || null;
  const refineKeys = (params.get('refine') || '').split(',');
  // refine=direct: ?team=none, as it was first called.
  if (refineKeys.includes('direct')) noTeam = true;
  refines = new Set(refineKeys.filter((key) => REFINES[key]));
  ageFilter = AGES[params.get('age')] ? params.get('age') : null;
  // Any reason the data may have (checked by the list, not here). ?because=
  // is its name from before ?buildFailed= came (2026-10-08), still read.
  const updateFailed = params.get('updateFailed') ?? params.get('because') ?? '';
  becauseFilter = /^[A-Za-z]{1,30}$/.test(updateFailed) ? updateFailed : null;
  const buildFailed = params.get('buildFailed') || '';
  buildFailedFilter = /^[A-Za-z]{1,30}$/.test(buildFailed) ? buildFailed : null;
  const inSetParam = params.get('in') || '';
  inFilter = /^[\w.+-]{1,100}$/.test(inSetParam) ? inSetParam : null;
  const by = (params.get('by') || '').replace(/^@/, '').toLowerCase();
  byFilter = /^[\w.-]{1,60}$/.test(by) ? by : null;
  statusFilter = NAME_STATUSES[params.get('status')] ? params.get('status') : null;
  newerFilter = ['yes', 'no'].includes(params.get('newer')) ? params.get('newer') : null;
  showErrors = params.get('errors') === '1';
  const ofTeam = params.get('ofteam') || '';
  matchTeam = /^[\w .+-]{1,60}$/.test(ofTeam) ? ofTeam : null;
  pageNum = Math.max(1, Number.parseInt(params.get('page'), 10) || 1);
  const per = Number(params.get('per'));
  pageSize = PAGE_SIZES.includes(per) ? per : DEFAULT_PAGE_SIZE;
}

// The address for the current view, on page `page`.
function viewQuery(page = pageNum) {
  const params = new URLSearchParams(location.search);
  const q = document.getElementById('search').value.trim();
  const set = (k, v) => (v ? params.set(k, v) : params.delete(k));
  set('filter', FILTERS[activeFilter].param);
  // @handle in the search: ?maintainer=handle; anything else: ?q=.
  const handle = q.startsWith('@') && q.length > 1 ? q.slice(1) : '';
  set('maintainer', maintainersParam({ handle, leftOut: maintainersLeftOut }));
  set('q', handle ? '' : q);
  set('sort', sortMode === 'pressing' ? '' : sortMode);
  set('order', sortReverse ? 'reverse' : '');
  set('platform', platformFilter && PLATFORMS[platformFilter].param);
  set('list', listFilter);
  set('team', teamsParam({ include: teamFilter, leftOut: teamsLeftOut, none: noTeam }));
  set('set', setFilter);
  set('cause', causeFilter);
  set('pkg', pkgParam);
  set('view', viewParam);
  set('refine', [...refines].join(','));
  set('age', ageFilter);
  set('buildFailed', buildFailedFilter);
  set('updateFailed', becauseFilter);
  set('in', inFilter);
  set('by', byFilter);
  set('status', statusFilter);
  set('newer', newerFilter);
  set('errors', showErrors ? '1' : '');
  set('ofteam', matchTeam);
  params.delete('because'); // the old name, written as the new one
  set('page', page > 1 ? page : '');
  set('per', pageSize !== DEFAULT_PAGE_SIZE ? pageSize : '');
  // "@" and "," are fine in a query: ?q=@ and ?refine=a,b read better in
  // a shared link.
  const query = params.toString().replaceAll('%40', '@').replaceAll('%2C', ',');
  return location.pathname + (query ? `?${query}` : '');
}
function writeViewToUrl() {
  // replaceState, not pushState: typing a search shouldn't fill the history.
  history.replaceState(null, '', viewQuery() + location.hash);
}

// The Theme menu. theme.js applied the saved choice before the page drew;
// this keeps it, and the page's default from the data, in the browser
// (localStorage: nothing is sent anywhere) and applies changes.
const SITE_PALETTE = `nixkeeper-site-palette:${location.pathname}`;
const stored = (key) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked: nothing is remembered
  }
};
const store = (key, value) => {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // storage blocked: it lasts until the page is left
  }
};

// "Hide until it changes": in this browser only (localStorage), each hidden
// package by name with what it needed attention for then (attentionPrint).
// Back as soon as that differs; "Show hidden" shows them all, greyed.
const HIDDEN_KEY = 'nixkeeper-hidden';
const hiddenPrints = (() => {
  try {
    return JSON.parse(stored(HIDDEN_KEY) || '{}') || {};
  } catch {
    return {};
  }
})();
let showHidden = false;
// Entries that no longer match (it changed, or left the data) dropped, once
// a view's packages are in: what's hidden only ever matches now.
function pruneHidden(list) {
  let changed = false;
  for (const pkg of list) {
    if (pkg.name in hiddenPrints && !isHidden(pkg)) {
      delete hiddenPrints[pkg.name];
      changed = true;
    }
  }
  if (changed)
    store(HIDDEN_KEY, Object.keys(hiddenPrints).length ? JSON.stringify(hiddenPrints) : '');
}
const isHidden = (pkg) => hiddenPrints[pkg.name] === attentionPrint(pkg, checkedAt);
const notHidden = (pkg) => showHidden || !isHidden(pkg);
function setHidden(pkg, hide) {
  if (hide) hiddenPrints[pkg.name] = attentionPrint(pkg, checkedAt);
  else delete hiddenPrints[pkg.name];
  store(HIDDEN_KEY, Object.keys(hiddenPrints).length ? JSON.stringify(hiddenPrints) : '');
  announce(hide ? `${pkg.name} hidden until it changes` : `${pkg.name} shown again`);
  update({ keepPage: true });
}

// "You can merge these"'s Hide, as the packages': in this browser only,
// each hidden PR by number with what it was then (prPrint), back as soon as
// that differs. Entries for PRs no longer in the list are dropped once it's
// in (loadMerge).
const HIDDEN_PRS_KEY = 'nixkeeper-hidden-prs';
const hiddenPrPrints = (() => {
  try {
    return JSON.parse(stored(HIDDEN_PRS_KEY) || '{}') || {};
  } catch {
    return {};
  }
})();
let showHiddenPrs = false;
const isPrHidden = (pr) => hiddenPrPrints[pr.number] === prPrint(pr);
function saveHiddenPrs() {
  store(HIDDEN_PRS_KEY, Object.keys(hiddenPrPrints).length ? JSON.stringify(hiddenPrPrints) : '');
}
function setPrHidden(number, hide) {
  const pr = (mergeList || []).find((p) => p.number === number);
  if (!pr) return;
  if (hide) hiddenPrPrints[number] = prPrint(pr);
  else delete hiddenPrPrints[number];
  saveHiddenPrs();
  announce(hide ? `#${number} hidden until it changes` : `#${number} shown again`);
  renderScope();
}

function applyTheme() {
  const { palette, mode } = themeFor(
    { palette: stored('nixkeeper-palette'), mode: stored('nixkeeper-mode') },
    stored(SITE_PALETTE),
  );
  const root = document.documentElement;
  root.dataset.palette = palette;
  if (mode === 'auto') delete root.dataset.mode;
  else root.dataset.mode = mode;
  for (const input of document.querySelectorAll('#themePanel input')) {
    input.checked = input.value === (input.name === 'palette' ? palette : mode);
  }
}

// The default the page's owner set (page.theme in the package lists), kept
// so the next visit starts with it before the data loads.
function setSitePalette(palette) {
  if (palette === stored(SITE_PALETTE)) return;
  store(SITE_PALETTE, palette);
  applyTheme();
}

// The row's dot, on hover (the legend popover lists them all).
// Repology's statuses as the page says them, where the code isn't clear
// ("unlisted": with every package, one Repology doesn't know).
const STATUS_LABEL = { unlisted: 'not on Repology', unique: 'only in nixpkgs' };
// Repology's unique with nothing to compare (nothingCompared).
const ONLY_NIXPKGS_TEXT =
  "Only nixpkgs packages it, and nixkeeper has no update check for it: there's nothing to compare its version with";
// nixpkgs' 0-unsupported (rows.UNSUPPORTED): not built in its default
// configuration, so no version to compare.
const UNSUPPORTED_TEXT =
  "nixpkgs doesn't build it in its default configuration (0-unsupported: for the CUDA it defaults to, say), so there's no version to compare";
// An older version kept beside a newer one (olderVersionKept): which.
const keptText = (pkg) =>
  pkg.keptBeside
    ? `An older version nixpkgs keeps on purpose: it also has ${pkg.keptBeside.attr} ${pkg.keptBeside.version}`
    : 'An older version nixpkgs keeps on purpose, beside a newer one';
const statusLabel = (status) => STATUS_LABEL[status] || status;
// A set kept current in bulk by its own tooling (rPackages: the CRAN
// import), not one PR per package: what updates it, from index.json's
// "profiles" (config.SET_PROFILES). Data from before has none: said plainly.
const profileOf = (set) => manifest?.profiles?.[set] || null;
const bulkText = (set) =>
  `Kept current in bulk by ${profileOf(set)?.updatedBy || 'its own tooling'}, not one PR per package`;
const bulkShort = (set) => profileOf(set)?.short || 'updated in bulk';
const bulkBadge = (set) =>
  html`<span class="badge neutral" title="${bulkText(set)} (${set}): counted on its set's line on the overview">${bulkShort(set)}</span>`;
// No longer on CRAN or in the Bioconductor release nixpkgs pins (the row's
// "archived", sources/cran_digest.py).
const ARCHIVED_TITLE =
  "No longer on CRAN or in the Bioconductor release nixpkgs pins: CRAN archived it (it failed CRAN's checks and wasn't fixed, or its maintainer left), or Bioconductor dropped it";
const archivedText = (pkg) =>
  `${ARCHIVED_TITLE}. ${pkg.markedBroken ? 'nixpkgs marks it broken.' : "nixpkgs doesn't mark it broken: likely broken anyway, or due for removal."}`;
const LOOKUP_FAILED = "Repology couldn't be reached on the last sync, and there's no earlier data";
const UNVERSIONED_TITLE =
  "Not software with releases to compare (a system component): its builds are what's checked";

const DOT_TITLE = {
  ok: 'Up to date: nixpkgs has the newest version',
  warn: 'Outdated: a newer release is out',
  merged: 'On master: the update is merged, waiting for nixos-unstable',
  missing: 'Not packaged: not in nixpkgs unstable',
  neutral:
    "Can't compare (a rolling or unusual version scheme), or an older version kept on purpose",
};

function showLegend(open) {
  document.getElementById('legendPanel').hidden = !open;
  document.getElementById('legendBtn').setAttribute('aria-expanded', open);
}

function showSources(open) {
  document.getElementById('sourcesPanel').hidden = !open;
  document.getElementById('checked').setAttribute('aria-expanded', open);
}

// Where the data is from: the daily sync's sources as it noted them
// (nixkeeper/sources/about.py), each with when its data is from, or why the
// sync didn't use it (it then asked per package instead). Those read from
// one of nixkeeper's digests are grouped under it (DIGESTS), in this order.
const DIGESTS = {
  hydra: 'https://github.com/nixkeeper/digest-builds',
  versions: 'https://github.com/nixkeeper/digest-versions',
  updates: 'https://github.com/nixkeeper/digest-update-bot',
  vulnerabilities: 'https://github.com/nixkeeper/digest-vulnerabilities',
  prs: 'https://github.com/nixkeeper/digest-prs',
};
const hydraEval = (s) =>
  html`evaluation <a class="files-link" href="https://hydra.nixos.org/eval/${s.eval}" target="_blank" rel="noopener">${s.eval}</a>, read ${timeAgo(s.at)}`;
const SOURCES = [
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

function sourcesHtml() {
  const when = (iso) =>
    new Date(iso).toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  const noted = (key) =>
    key === 'nixkeeper'
      ? sources?.versions && checkedAt && { used: true, at: checkedAt }
      : sources?.[key];
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
      <li><b>Last sync</b><span title="${checkedAt ? when(checkedAt) : ''}">${checkedAt ? `${timeAgo(checkedAt)}, ${when(checkedAt)}` : 'not yet'}</span></li>
      ${nix?.used ? html`<li><b>nixpkgs</b><span>${SOURCES[0].says(nix)}</span></li>` : ''}
    </ul>
    <a class="files-link" href="https://status.nixkeeper.com/" target="_blank" rel="noopener">Every source, and how fresh it is ↗</a>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
  }
  return html`<p class="pop-title">Where the data is from</p>
    <ul>
      <li><b>Last sync</b><span title="${checkedAt ? when(checkedAt) : ''}">${checkedAt ? `${timeAgo(checkedAt)}, ${when(checkedAt)}` : 'not yet'}</span></li>
      <li><b>Hourly checks</b><span>frequent update checks and update PRs, between syncs</span></li>
      ${own}
      ${digests}
    </ul>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
}

function showThemePanel(open) {
  document.getElementById('themePanel').hidden = !open;
  document.getElementById('themeBtn').setAttribute('aria-expanded', open);
}

// Mistakes the sync found in the package lists (nixkeeper/listcheck.py): a
// maintainer handle no package lists tracks nothing, so it's said up front.
function showListProblems(problems) {
  const el = document.getElementById('listProblems');
  if (!el) return;
  el.hidden = problems.length === 0;
  el.innerHTML = problems.length
    ? html`⚠ ${problems.length === 1 ? 'A problem' : `${problems.length} problems`} in the package lists, found by the last sync:
      <ul>${problems.map((p) => html`<li>${p}</li>`)}</ul>`
    : '';
}

// The summary's entries, a short one per package (summary.json).
async function summaryOf() {
  const res = await fetch(dataUrl('summary.json'), { cache: 'no-store' });
  if (!res.ok) throw new Error(res.status);
  return (await res.json()).packages || [];
}

// A package's full row (what its panels show): its shard's, loaded once (a
// failed load isn't kept, so opening it again tries again). null if it
// couldn't be loaded.
async function fullRow(pkg) {
  const n = shardOf(pkg.name, shardCount);
  if (!shardCache.has(n)) {
    shardCache.set(
      n,
      fetch(dataUrl(`rows/${n}.json`), { cache: 'no-store' })
        .then((res) => {
          if (!res.ok) throw new Error(res.status);
          return res.json();
        })
        .then(
          (shard) =>
            new Map(shard.packages.map((row) => [row.name, withRunStamps(row, checkedAt)])),
        ),
    );
  }
  try {
    return (await shardCache.get(n)).get(pkg.name) || null;
  } catch {
    shardCache.delete(n);
    return null;
  }
}

// With every package: load the view the address asks for (viewPath) into
// `packages`, unless it's there already. A maintainer, team or list with no
// file has no packages here. Throws if a view can't be loaded.
// Typing @someone in the overview's own box: the overview stays (that box
// with it), showing the maintainers who match, until one is picked, Enter
// is pressed or the box is left; the top search opens theirs at once.
const typingHandleOnOverview = () =>
  shownView === 'overview' &&
  document.activeElement?.id === 'overviewSearch' &&
  document.getElementById('search').value.trim().startsWith('@');

async function ensureView() {
  const path = typingHandleOnOverview()
    ? 'overview'
    : viewPath({
        pkg: pkgParam,
        query: document.getElementById('search').value,
        team: teamFilter,
        list: listFilter,
        set: setFilter,
        view: viewParam,
        cause: causeFilter,
      });
  // Something else shown instead (a package, a maintainer...): ?set= and
  // ?view= no longer apply, and nothing on the page would take them off
  // again (a set's filter would hide every row: the other views leave out
  // what's pending).
  if (setFilter && path !== `views/set/${setFilter}.json`) setFilter = null;
  if (causeFilter && path !== `views/cause/${causeFilter}.json`) causeFilter = null;
  if (viewParam && path !== VIEWS[viewParam]) viewParam = null;
  if (path === shownView) return;
  wantedView = path;
  let found;
  if (path === 'overview') {
    found = []; // the overview lists nothing (renderScope)
    loadHistory();
  } else if (path === 'maintainers') {
    found = []; // maintainers, not packages (maintainersHtml)
    loadMaintainers();
  } else if (path.startsWith('pkg:')) {
    const row = await fullRow({ name: path.slice(4) });
    found = row ? [row] : [];
  } else {
    const res = await fetch(dataUrl(path), { cache: 'no-store' });
    if (!res.ok && res.status !== 404) throw new Error(res.status);
    const data = res.ok ? await res.json() : { packages: [] };
    found = data.packages;
    causeShown = path.startsWith('views/cause/') ? data : null;
  }
  if (wantedView !== path) return; // another view was asked for meanwhile
  packages = found.map((p) => withRunStamps(p, checkedAt));
  pruneHidden(packages);
  shownView = path;
}

// history.json's points, for the overview's trends: loaded once, then the
// overview is drawn again. Without it (data from before, or not yet), the
// cards have no line.
function loadHistory() {
  if (historyLoading) return;
  historyLoading = true;
  fetch(dataUrl('history.json'), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : { points: [] }))
    .then((data) => {
      trendPoints = data.points || [];
      trendEvents = data.events || [];
      if (shownView === 'overview') renderScope();
    })
    .catch(() => {
      trendPoints = [];
    });
}

// The name index, for searches beyond the view shown: loaded once, when a
// search first needs it, then the list is drawn again.
// With every package: every maintainer (maintainers.json: [handle, packages,
// outdated, failing]), loaded when a search starts with @ or the maintainers
// page opens; then the list is drawn again.
let maintainersList = null;
let maintainersLoading = null;
function loadMaintainers() {
  if (maintainersLoading) return;
  maintainersLoading = fetch(dataUrl('maintainers.json'), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : { maintainers: [] }))
    .then((data) => {
      maintainersList = data.maintainers || [];
      update({ keepPage: true });
    })
    .catch(() => {
      maintainersLoading = null; // tried again with the next search
    });
}

// views/merge.json: the PRs maintainers can merge now with the merge bot
// (nixkeeper/sources/prs_digest.py: mergeable), for "You can merge these" in
// a maintainer's or team's view. Loaded once, when one is first shown.
let mergeList = null;
let mergeLoading = null;
let mergeAll = false; // every one shown, not the first MERGE_SHOWN
const MERGE_SHOWN = 5;
const MERGE_COMMAND = '@NixOS/nixpkgs-merge-bot merge';
function loadMerge() {
  if (mergeLoading) return;
  mergeLoading = fetch(dataUrl('views/merge.json'), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : { prs: [] }))
    .then((data) => {
      mergeList = data.prs || [];
      // Hidden PRs that changed, or left the list: not hidden anymore.
      const now = new Map(mergeList.map((p) => [String(p.number), prPrint(p)]));
      for (const number of Object.keys(hiddenPrPrints))
        if (now.get(number) !== hiddenPrPrints[number]) delete hiddenPrPrints[number];
      saveHiddenPrs();
      update({ keepPage: true });
    })
    .catch(() => {
      mergeLoading = null; // tried again with the next view
    });
}

// "You can merge these": in @handle's view, the PRs they can merge (their
// own first); in a team's, those touching the packages nixpkgs lists under
// the team (meta.teams: its members are their maintainers, so the merge bot
// counts them), not those a list of the same name adds (teamsByList: their
// own maintainers merge those), with who can. Nothing when there are none,
// or before views/merge.json is in.
function mergeHtml(path, handle) {
  const mine = path.startsWith('views/maintainer/') && handle && handle !== 'none';
  const team = path.startsWith('views/team/');
  if (!mine && !team) return '';
  if (!mergeList) {
    loadMerge();
    return '';
  }
  const who = handle.toLowerCase();
  const theirs = team && teamName();
  const names = team
    ? new Set(packages.filter((p) => !p.teamsByList?.includes(theirs)).map((p) => p.name))
    : null;
  const own = (p) => mine && p.author.toLowerCase() === who;
  // Their own first, then those for a vulnerable package, then the
  // longest waiting (the list's own order).
  const prs = mergeList
    .filter((p) =>
      mine ? p.who.some((w) => w.toLowerCase() === who) : p.packages.some((n) => names.has(n)),
    )
    .sort((a, b) => own(b) - own(a) || Boolean(b.vulnerable) - Boolean(a.vulnerable));
  if (!prs.length) return '';
  // Those hidden here (Hide), left out unless shown again, greyed.
  const hiddenN = prs.filter(isPrHidden).length;
  const listed = showHiddenPrs ? prs : prs.filter((p) => !isPrHidden(p));
  const hiddenToggle = hiddenN
    ? html`<button type="button" class="merge-hidden-toggle" aria-pressed="${showHiddenPrs}" title="PRs you hid here, in this browser, until they change (a newer version, or a CVE)">${fmt(hiddenN)} hidden · ${showHiddenPrs ? 'hide them' : 'show them'}</button>`
    : '';
  if (!listed.length)
    return html`<section class="merge-block merge-all-hidden"><p class="merge-how">You've hidden ${hiddenN === 1 ? 'the PR' : html`the ${fmt(hiddenN)} PRs`} ready to merge here. ${hiddenToggle}</p></section>`;
  const shown = mergeAll ? listed : listed.slice(0, MERGE_SHOWN);
  const days = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso)) / 86400000));
  const waited = (iso) => {
    const d = days(iso);
    return d < 1 ? 'opened today' : `waiting ${d} day${d === 1 ? '' : 's'}`;
  };
  const people = (list) => list.map((h) => `@${h}`).join(', ');
  const line = (p) => {
    const facts = [
      own(p) ? html`<b>your own PR</b>` : `by @${p.author}`,
      html`<span title="Opened ${new Date(p.created).toLocaleDateString()}">${waited(p.created)}</span>`,
      p.base !== 'master' && html`into <span class="mono">${p.base}</span>`,
      p.approvedBy?.length && `approved by ${people(p.approvedBy)}`,
      p.vulnerable &&
        html`<span class="merge-warn" title="The package counts as vulnerable: worth reviewing this first">for a vulnerable package</span>`,
      p.behind &&
        html`<span class="merge-warn" title="Merged as it is, the package would still be outdated: worth updating the PR first">behind: upstream has ${p.behind}</span>`,
      team && `${people(p.who)} can merge it`,
    ].filter(Boolean);
    const hidden = isPrHidden(p);
    return html`<li${hidden ? raw(' class="is-hidden"') : ''}><a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${p.number}" target="_blank" rel="noopener">${p.title}</a> <span class="merge-n">#${p.number}</span><button type="button" class="merge-hide" data-pr="${p.number}" title="${hidden ? 'Shown again here' : 'Leave it out of this list, in this browser only, until it changes: a newer version in its title, or a CVE'}">${hidden ? 'Show it again' : 'Hide'}</button><span class="merge-facts">${facts.map((f, i) => html`${i ? ' · ' : ''}${f}`)}</span></li>`;
  };
  const n = listed.length;
  const what = mine
    ? html`You can merge ${n === 1 ? 'this PR' : html`these ${fmt(n)} PRs`}`
    : html`${fmt(n)} PR${n === 1 ? '' : 's'} on the team's packages, ready to merge`;
  // The merge bot also asks that whoever comments be in
  // @NixOS/nixpkgs-maintainers (nixpkgs' ci/README.md): not public, so said.
  const why = mine
    ? 'CI passed, and you maintain every package it touches: if you’re in @NixOS/nixpkgs-maintainers, the merge bot merges it for you'
    : 'CI passed, and the people named under each maintain every package it touches: the merge bot merges it for any of them in @NixOS/nixpkgs-maintainers';
  const more =
    listed.length > MERGE_SHOWN
      ? html`<button type="button" class="merge-more">${mergeAll ? 'Show fewer' : `Show all ${fmt(listed.length)}`}</button>`
      : '';
  return html`<section class="merge-block" aria-labelledby="mergeHead">
    <h3 id="mergeHead">${what} <span class="scope-hint">${why}</span> ${hiddenToggle}</h3>
    <ul class="merge-list">${shown.map(line)}</ul>
    ${more}
    <p class="merge-how">Review it, then comment on the PR: <code>${MERGE_COMMAND}</code>
      <button type="button" class="merge-copy" data-copy="${MERGE_COMMAND}" title="Copy the comment">Copy</button>
      <a class="files-link" href="https://github.com/NixOS/nixpkgs/blob/master/ci/README.md" target="_blank" rel="noopener">how the merge bot works ↗</a></p>
  </section>`;
}

// On a maintainer's or a team's page: the open update PRs nixpkgs is
// already past, on its packages (the rows' supersededPRs): "Can be closed".
// Hide as for "You can merge these" (in this browser, until it changes).
const CLOSE_SHOWN = 5;
let closeAll = false;
function closeHtml(path, handle) {
  const mine = path.startsWith('views/maintainer/') && handle && handle !== 'none';
  const team = path.startsWith('views/team/');
  if (!mine && !team) return '';
  const who = (handle || '').toLowerCase();
  const theirs = team && teamName();
  const seen = new Set();
  const prs = packages
    .filter((p) => !team || !p.teamsByList?.includes(theirs))
    .flatMap((p) => (p.supersededPRs || []).map((pr) => ({ ...pr, pkg: p.name })))
    .filter((pr) => !seen.has(pr.number) && seen.add(pr.number))
    .sort((a, b) => (a.created < b.created ? -1 : a.created > b.created ? 1 : 0));
  if (!prs.length) return '';
  const hiddenN = prs.filter(isPrHidden).length;
  const listed = showHiddenPrs ? prs : prs.filter((p) => !isPrHidden(p));
  if (!listed.length) return '';
  const shown = closeAll ? listed : listed.slice(0, CLOSE_SHOWN);
  const days = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso)) / 86400000));
  const line = (p) => {
    const own = mine && p.author.toLowerCase() === who;
    const facts = [
      own ? html`<b>your own PR</b>` : `by @${p.author}`,
      html`<span title="Opened ${new Date(p.created).toLocaleDateString()}">open ${fmt(days(p.created))} days</span>`,
      html`nixpkgs has <span class="mono">${p.now}</span>`,
      p.draft && 'a draft',
    ].filter(Boolean);
    const hidden = isPrHidden(p);
    return html`<li${hidden ? raw(' class="is-hidden"') : ''}><a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${p.number}" target="_blank" rel="noopener">${p.title}</a> <span class="merge-n">#${p.number}</span><button type="button" class="merge-hide" data-pr="${p.number}" title="${hidden ? 'Shown again here' : 'Leave it out of this list, in this browser only, until it changes'}">${hidden ? 'Show it again' : 'Hide'}</button><span class="merge-facts">${facts.map((f, i) => html`${i ? ' · ' : ''}${f}`)}</span></li>`;
  };
  const n = listed.length;
  const more =
    listed.length > CLOSE_SHOWN
      ? html`<button type="button" class="merge-more" data-close-more>${closeAll ? 'Show fewer' : `Show all ${fmt(listed.length)}`}</button>`
      : '';
  return html`<section class="merge-block close-block" aria-labelledby="closeHead">
    <h3 id="closeHead">${n === 1 ? 'This update PR can' : html`These ${fmt(n)} update PRs can`} be closed <span class="scope-hint">nixpkgs already has their version or a newer one${hiddenN && !showHiddenPrs ? html` · ${fmt(hiddenN)} hidden` : ''}</span></h3>
    <ul class="merge-list">${shown.map(line)}</ul>
    ${more}
    <p class="merge-how">Close it with a word on why (nixpkgs has a newer version), or update it to the newest.${
      community && manifest.views?.superseded
        ? html` <a class="files-link" href="${scopeHref({ view: 'superseded' })}" data-card-view="superseded">All ${fmt(manifest.views.superseded)} packages with one, in all of nixpkgs →</a>`
        : ''
    }</p>
  </section>`;
}

function loadNames() {
  if (namesLoading) return;
  namesLoading = fetch(dataUrl('names.json'), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : { names: [] }))
    .then((data) => {
      names = data.names || [];
      update({ keepPage: true });
    })
    .catch(() => {
      namesLoading = null; // tried again with the next search
    });
}

// The search's maintainer, team and platform filters' data (facets.json),
// on first use: about 120 KB.
function loadFacets() {
  if (facetsLoading || !names) return;
  facetsLoading = fetch(dataUrl('facets.json'), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : null))
    .then((data) => {
      const found = data ? decodeFacets(data) : [];
      if (found.length === names.length) {
        facetIndex = found;
        nameIndex = new Map(names.map((entry, i) => [entry, i]));
        update({ keepPage: true });
      }
    })
    .catch(() => {
      facetsLoading = null; // tried again with the next search
    });
}

// Draw the list again after the view's state changed (a filter, the search,
// the address): with every package, its view loaded first. keepPage: as
// render's.
// A load, in steps with the browser free in between, so the page stays
// responsive on a slow phone: filtering and sorting every package; then the
// counts, tiles and first rows (drawn together: nothing above the list
// moves later); then the rest of the page's rows, below. In one go, a
// mid-range phone was busy for over half a second (Lighthouse, 2026-10-07).
// A newer update stops an older one between steps (typing, say).
let updateRun = 0;
const yieldToBrowser = () =>
  globalThis.scheduler?.yield ? scheduler.yield() : new Promise((r) => setTimeout(r, 0));

async function update({ keepPage = false } = {}) {
  const run = ++updateRun;
  if (community) {
    try {
      await ensureView();
    } catch {
      document.getElementById('content').innerHTML = html`<div class="error">
        Couldn't load these packages' data. Reload the page to try again.</div>`;
      return;
    }
  }
  await yieldToBrowser();
  if (run !== updateRun) return;
  const list = currentFiltered();
  await yieldToBrowser();
  if (run !== updateRun) return;
  await render(list, { keepPage, run });
}

async function loadIndex() {
  const content = document.getElementById('content');
  dataBase = dataBase || (await findDataBase());
  if (!dataBase) {
    doneLoading();
    content.innerHTML = `<div class="error">
      Couldn't find the data to show.<br>
      Serve it as <code>data/</code> next to this page, set it with
      <code>&lt;meta name="nixkeeper-data"&gt;</code> in <code>index.html</code>,
      or open this from its GitHub Pages site.
    </div>`;
    return;
  }
  try {
    const res = await fetch(dataUrl('index.json'), { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    if (!(data.format >= 2 && data.shardCount)) {
      // Format 1, which only nixkeeper 0.11.0 and before write alone.
      doneLoading();
      content.innerHTML = html`<div class="error">
        This data is from nixkeeper 0.11.0 or older, which this page no longer reads.<br>
        The next sync rewrites it.
      </div>`;
      return;
    }
    checkedAt = data.checkedAt || null;
    sources = data.sources || null;
    shardCount = data.shardCount;
    if (data.allPackages) {
      community = true;
      manifest = data;
      myHandle = stored('nixkeeper-handle');
      myTeam = stored('nixkeeper-team');
      loadMyCount();
    } else {
      packages = (await summaryOf()).map((p) => withRunStamps(p, checkedAt));
      // An instance of its own lists, not every package: the line by the
      // logo and the tab's title say so (index.html has nixkeeper.com's;
      // link previews, which run no script, keep it).
      document.querySelector('.wordmark .tag').textContent = OWN_TAG;
      document.documentElement.dataset.start = 'list'; // its skeleton (theme.js)
      document.title = `nixkeeper — ${OWN_TAG}`;
    }
    // The nixkeeper that made the data, in the footer (older data has none).
    document.getElementById('version').textContent =
      data.version && data.version !== 'unknown' ? ` ${data.version}` : '';
    showListProblems(data.listProblems || []);
    setSitePalette(data.page?.theme || null);
    document.getElementById('search').disabled = false;
    await update({ keepPage: true });
  } catch {
    doneLoading();
    content.innerHTML = html`<div class="error">
      Couldn't load <code>${dataUrl('index.json')}</code>.<br>
      Check that the sync has run at least once (and, on GitHub, that the repo is public).
    </div>`;
  }
}

function longDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

// The tab's icon shows what needs attention among packages (faviconKey).
function setFavicon(base) {
  const key = faviconKey(base, platformFilter);
  const link = document.getElementById('favicon');
  if (link && !link.href.endsWith(`favicon-${key}.svg`)) link.href = `favicon-${key}.svg`;
}

function renderStats() {
  // Counts follow the platform and list filters, so "outdated" means
  // outdated on Darwin, or on the gaming-team list, while that's selected.
  const base = packages.filter((p) => inPlatform(p) && inList(p) && inPeople(p) && notHidden(p));
  setFavicon(base);
  renderLists();
  // With every package, the counts are the list's tiles (renderScope), and
  // the bar's chip is the way into what needs attention.
  const attention = shownView === 'views/attention.json';
  const attentionChip = community
    ? html`<button class="stat-btn" data-view="attention" aria-pressed="${attention}"
        title="${attention ? 'Back to the overview' : 'Failing, outdated or vulnerable, worst first'}">
        <b style="color:var(--warn)">${fmt(manifest.views?.attention)}</b> needs attention</button>`
    : '';
  const buttons = Object.entries(community ? {} : FILTERS).map(([key, f]) => {
    if (['broken', 'builds', 'updates'].includes(key)) return ''; // with every package only
    const count = base.filter((p) => f.test(p) && refined(p, key)).length;
    // "vulnerable", "fixes to backport" and "blocked" only show up when
    // there's some.
    if (['vuln', 'backport', 'blocked'].includes(key) && !count && activeFilter !== key) return '';
    const pressed = activeFilter === key;
    return html`<button class="stat-btn" data-filter="${key}" aria-pressed="${pressed}"
      ${!count && key !== 'all' && !pressed ? raw('disabled') : ''}>
      <b${f.color ? html` style="color:${f.color}"` : ''}>${count}</b> ${key === 'all' && community ? 'here' : f.label}</button>`;
  });
  const stale =
    !checkedAt || Date.now() - new Date(checkedAt).getTime() > STALE_AFTER_HOURS * 3600e3;
  const platformChip = platformFilter
    ? html`<button class="plat-filter" data-clear="platform" title="Show all platforms">${PLATFORMS[platformFilter].label} only ✕</button>`
    : '';
  // With every package, the list header says which team ("Showing").
  const teamChip =
    teamFilter && !community
      ? html`<button class="plat-filter" data-clear="team" title="Show every team's packages">team: ${teamName()} ✕</button>`
      : '';
  document.getElementById('stats').innerHTML =
    html`${attentionChip}${buttons}${platformChip}${teamChip}${community ? '' : teamOutChips()}`;
  // Without every package, the list's narrowing under the counts; with
  // every package, it's in the list's header, under the tiles.
  const refine = document.getElementById('refine');
  refine.hidden = community;
  refine.innerHTML = community ? '' : refineHtml();
  const checked = document.getElementById('checked');
  checked.classList.toggle('stale', stale);
  // The exact time on hover: "checked 4h ago" is friendly, but vague.
  const exact = checkedAt
    ? `Last full sync: ${new Date(checkedAt).toLocaleString(undefined, {
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
  checked.textContent = `checked ${timeAgo(checkedAt)}${stale ? ' — sync may be failing' : ''}`;
  document.getElementById('sourcesPanel').innerHTML = sourcesHtml();
}

// The lists from package-lists/, as more filters after the counts (a
// divider between). Hidden when there's only one (or data from before lists
// existed).
// With every package: the visitor's own GitHub handle, for "Your packages"
// (kept in their browser only, nixkeeper-handle), and how many packages
// list them, once their view is loaded.
let myHandle = null;
let myCount = null;
let editingHandle = false;
// And the visitor's team (nixkeeper-team), for "Your team".
let myTeam = null;
let editingTeam = false;
const isMyTeam = () =>
  Boolean(myTeam) &&
  shownView === `views/team/${viewSlug(myTeam)}.json` &&
  !document.getElementById('search').value.trim().startsWith('@');
const isMine = () =>
  Boolean(myHandle) &&
  document.getElementById('search').value.trim().toLowerCase() === `@${myHandle.toLowerCase()}`;

function loadMyCount() {
  if (!myHandle) return;
  const handle = myHandle;
  fetch(dataUrl(`views/maintainer/${handle.toLowerCase()}.json`), { cache: 'no-store' })
    .then((res) => (res.ok ? res.json() : { packages: [] }))
    .then((data) => {
      if (handle !== myHandle) return; // changed meanwhile
      myCount = (data.packages || []).length;
      renderLists();
    })
    .catch(() => {});
}

// "Your packages": the visitor's handle (a chip opening their packages,
// ✎ to change it), or a field to give it.
function mineHtml() {
  if (editingHandle)
    return html`<form class="mine-form" id="mineForm">
      <input id="mineInput" name="handle" placeholder="your GitHub handle" aria-label="Your GitHub handle" autocomplete="off" spellcheck="false" value="${myHandle || ''}">
      <button class="stat-btn" type="submit">Show</button>
    </form>`;
  if (!myHandle)
    return html`<button class="stat-btn" type="button" data-mine-edit title="Give your GitHub handle to find your packages (kept in this browser only)">Your packages…</button>`;
  return html`<button class="stat-btn" type="button" data-mine aria-pressed="${isMine()}"
      title="${isMine() ? 'Back to the overview' : 'The packages that list you as a maintainer'}">${myCount != null ? html`<b>${fmt(myCount)}</b> ` : ''}@${myHandle}</button><button type="button" class="mine-edit" data-mine-edit aria-label="Change your GitHub handle" title="Change your GitHub handle">✎</button>`;
}

// "Your team": the visitor's team (a chip opening its packages, ✎ to change
// it), or a picker to choose it.
function myTeamHtml() {
  const teams = Object.keys(manifest.views?.teams || {}).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' }),
  );
  if (!teams.length) return '';
  if (editingTeam)
    return html`<form class="mine-form" id="teamForm">
      <select id="teamInput" name="team" aria-label="Your team"><option value="">No team</option>${teams.map((t) => html`<option value="${t}"${t === myTeam ? raw(' selected') : ''}>${t}</option>`)}</select>
      <button class="stat-btn" type="submit">Show</button>
    </form>`;
  if (!myTeam || !manifest.views.teams[myTeam])
    return html`<button class="stat-btn" type="button" data-team-edit title="Choose your nixpkgs team to find its packages (kept in this browser only)">Your team…</button>`;
  return html`<button class="stat-btn" type="button" data-my-team aria-pressed="${isMyTeam()}"
      title="${isMyTeam() ? 'Back to the overview' : "The team's packages"}"><b>${fmt(manifest.views.teams[myTeam])}</b> ${myTeam} team</button><button type="button" class="mine-edit" data-team-edit aria-label="Change your team" title="Change your team">✎</button>`;
}

function renderLists() {
  const el = document.getElementById('lists');
  if (community) {
    // The visitor's own: their packages and their team. This instance's
    // lists ("maintained", its named lists) mean little to them: not shown,
    // though their addresses (?list=) still work.
    el.innerHTML = html`${mineHtml()}${myTeamHtml()}`;
    return;
  }
  const names = allLists();
  if (listFilter && !names.includes(listFilter)) names.push(listFilter); // e.g. a renamed list
  if (names.length < 2) {
    el.innerHTML = '';
    return;
  }
  const base = packages.filter((p) => inPlatform(p) && inPeople(p) && refined(p, 'all'));
  const listCount = (name) =>
    community
      ? manifest.views.lists[name] || 0
      : base.filter((p) => (p.lists || []).includes(name)).length;
  el.innerHTML = html`<span class="lists-label">lists</span>${names.map((name) => {
    const pressed = listFilter === name;
    const count = listCount(name);
    return html`<button class="stat-btn" type="button" data-list="${name}" aria-pressed="${pressed}"
        title="${pressed ? 'Show every list' : `Show only the ${name} list (shareable: it's in the address)`}">
        <b>${count}</b> ${name}</button>`;
  })}`;
}

// The packages the table shows, in order: a row's data-i is its place here.
let shown = [];
// Packages one update moves together, folded into one row (foldFamilies):
// the folds of the list drawn (lead's name → its fold), the names shown
// behind an open one's lead, and the folds opened (by key, until reload).
let folds = new Map();
let inOpenFold = new Set();
const openFolds = new Set();

// A fold's lead: how many more it stands for, a button showing or folding
// them.
function foldButton(pkg) {
  const fold = folds.get(pkg.name);
  if (!fold) return '';
  const more = fold.members.length - 1;
  const label = familyLabel(fold.members.map((m) => m.name)) || `${pkg.name} and the like`;
  return html`<button type="button" class="fold-btn" data-fold="${fold.key}" aria-expanded="${fold.open}" title="${fmt(more + 1)} packages one update moves together (${label}): ${fold.open ? 'fold them into one row' : 'show them all'}">${fold.open ? `fold ${fmt(more)}` : `+${fmt(more)} like it`}</button>`;
}

const CHEVRON = raw(
  '<svg class="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
);

// What a row's dot means, in words: its colour's, or why it's grey when
// only nixpkgs packages it.
const dotTitle = (pkg, st) =>
  waitingForChannel(pkg)
    ? DOT_TITLE.merged
    : nothingCompared(pkg)
      ? `Not compared: ${ONLY_NIXPKGS_TEXT.charAt(0).toLowerCase()}${ONLY_NIXPKGS_TEXT.slice(1)}`
      : DOT_TITLE[st];

function rowHtml(pkg, i) {
  const st = computeStatus(pkg);
  return html`<tr class="row${isHidden(pkg) ? ' is-hidden' : ''}${inOpenFold.has(pkg.name) ? ' fold-member' : ''}" tabindex="0" data-i="${i}">
      <td class="c-name"><div class="pkg-name"><span class="who"><span class="status-dot ${waitingForChannel(pkg) ? 'merged' : st}" role="img" aria-label="${dotTitle(pkg, st)}" title="${dotTitle(pkg, st)}"></span><a class="n pkg-link" href="${scopeHref({ pkg: pkg.name })}" tabindex="-1">${breakableName(pkg.name)} ${ageTag(pkg, st)}</a></span>${platformTags(pkg)}${foldButton(pkg)}</div></td>
      <td class="c-ver ver mono">${versionCell(pkg, st)}</td>
      <td class="c-gh${pkg.openPRs || pkg.openIssues ? '' : ' quiet'}">${githubLinks(pkg)}</td>
      <td class="c-build">${buildCell(pkg)}</td>
      <td class="c-update">${updateCell(pkg)}</td>
      <td class="c-chev"><span class="chev" aria-hidden="true">${CHEVRON}</span></td>
    </tr>`;
}

// The pages of the list, when there's more than one: "1–200 of 241" and
// links to the others (real links, so one can open in a new tab).
function pagerHtml(total, pages) {
  // The page size can be picked whenever a smaller one would split the list
  // (and so be put back after picking a bigger one).
  const sizes =
    total > PAGE_SIZES[0]
      ? html`<label class="page-size">Per page <select data-per aria-label="Packages per page">${PAGE_SIZES.map(
          (n) => html`<option value="${n}"${n === pageSize ? raw(' selected') : ''}>${n}</option>`,
        )}</select></label>`
      : '';
  if (pages < 2) return sizes ? html`<nav class="pager" aria-label="Pages">${sizes}</nav>` : '';
  const first = (pageNum - 1) * pageSize + 1;
  const last = Math.min(pageNum * pageSize, total);
  const link = (p, text, label) =>
    p === pageNum
      ? html`<span class="page-btn" aria-current="page">${text}</span>`
      : html`<a class="page-btn" href="${viewQuery(p)}" data-page="${p}"${label ? html` aria-label="${label}"` : ''}>${text}</a>`;
  return html`<nav class="pager" aria-label="Pages">
    <span class="page-count">${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()}</span>
    ${pageNum > 1 ? link(pageNum - 1, '‹', 'Previous page') : ''}
    ${pageLinks(pageNum, pages).map((p) => (p === null ? html`<span class="page-gap" aria-hidden="true">…</span>` : link(p, String(p), `Page ${p}`)))}
    ${pageNum < pages ? link(pageNum + 1, '›', 'Next page') : ''}
    ${sizes}
  </nav>`;
}

// One page of the table at once, as one piece of markup: many rows draw
// far faster that way than one by one. Each row's panel is only made when
// it's first opened (toggle), and the table's clicks are handled once, for
// every row (below). The list changed (a filter, the search, the order):
// back to the first page, unless keepPage (loading a shared address,
// following a page link).
// Says something to screen readers (#announce, a polite live region): only
// the last of quick changes (typing a search), once things settle.
let announceTimer = null;
function announce(text, delay = 0) {
  clearTimeout(announceTimer);
  announceTimer = setTimeout(() => {
    document.getElementById('announce').textContent = text;
  }, delay);
}
let rendered = false; // the first render is the page loading: nothing said

// The data is there (or isn't coming): the loading line goes, what's shown
// takes its place, and the footer appears below it (index.html).
function doneLoading() {
  document.getElementById('loading')?.remove();
  const about = document.getElementById('about');
  if (about) about.hidden = false;
}

async function render(list, { keepPage = false, run = updateRun } = {}) {
  doneLoading();
  // How many packages a change leaves, to hear without looking.
  if (rendered && !(community && shownView === 'overview') && shownView !== 'maintainers')
    announce(`${fmt(list.length)} ${list.length === 1 ? 'package' : 'packages'}`, 700);
  rendered = true;
  renderStats();
  renderScope();
  const content = document.getElementById('content');
  if (community && shownView === 'maintainers') {
    // Maintainers, not packages: paged by their own count (maintainersHtml).
    if (!keepPage) pageNum = 1;
    shown = [];
    content.innerHTML = maintainersHtml();
    writeViewToUrl();
    return;
  }
  // One update moving many packages: one row (foldFamilies), alike by dot.
  ({ list, folds, inOpen: inOpenFold } = foldFamilies(list, computeStatus, openFolds));
  const pages = Math.max(1, Math.ceil(list.length / pageSize));
  pageNum = keepPage ? Math.min(pageNum, pages) : 1;
  writeViewToUrl();
  shown = list.slice((pageNum - 1) * pageSize, pageNum * pageSize);
  if (community && shownView === 'overview') {
    // The overview lists nothing: its header has the ways in (renderScope),
    // and a search finds packages in all of nixpkgs.
    content.innerHTML = moreMatchesHtml();
    return;
  }
  if (!list.length) {
    const narrowed = refines.size || ageFilter || becauseFilter || buildFailedFilter;
    const handle = document.getElementById('search').value.trim();
    if (community && /^@\S/.test(handle) && !narrowed && activeFilter === 'all') {
      // No such maintainer (yet: still typing): the ones whose handle matches.
      content.innerHTML = html`<div class="empty">No maintainer is ${handle}.</div>${moreMatchesHtml()}`;
      return;
    }
    content.innerHTML = html`<div class="empty">No packages match${narrowed ? ' these filters' : activeFilter !== 'all' && !document.getElementById('search').value.trim() ? ` the “${FILTERS[activeFilter].label}” filter` : ''}${community ? ' here' : ''}.</div>${moreMatchesHtml()}`;
    return;
  }
  content.innerHTML = html`<div class="wrap"><table>
    <thead><tr>
      <th style="padding-left:10px">Package</th><th>nixpkgs unstable</th><th>Open on GitHub</th><th>Build failures</th><th>Update failures</th><th><span class="sr-only">Details</span></th>
    </tr></thead>
    <tbody id="rows">${shown.slice(0, FIRST_ROWS).map(rowHtml)}</tbody>
  </table></div>${pagerHtml(list.length, pages)}${moreMatchesHtml()}`;
  watchErrors();
  // One package shown by its link (?pkg=): its details open at once, the
  // reason the link was followed.
  if (pkgParam && list.length === 1 && pkgOpenedFor !== pkgParam) {
    pkgOpenedFor = pkgParam;
    const tr = document.querySelector('#rows tr.row');
    if (tr) toggle(tr, 'info');
  }
  // The rest of the page's rows, below the screen, a moment later.
  if (shown.length <= FIRST_ROWS) return;
  await yieldToBrowser();
  if (run !== updateRun) return;
  document
    .getElementById('rows')
    ?.insertAdjacentHTML(
      'beforeend',
      String(html`${shown.slice(FIRST_ROWS).map((pkg, i) => rowHtml(pkg, FIRST_ROWS + i))}`),
    );
  watchErrors();
}

// Show errors (errorsHere): each failing row's build panel, opened under it
// as it comes near the screen, so a page of 200 loads only what's looked
// at. Beside the panel a click opens: that one closes the others, these
// stay; a click on one of these works as on any panel.
let errorsObserver = null;
function watchErrors() {
  errorsObserver?.disconnect();
  errorsObserver = null;
  if (!errorsHere()) return;
  errorsObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        errorsObserver?.unobserve(entry.target);
        openErrors(entry.target);
      }
    },
    { rootMargin: '600px 0px' },
  );
  for (const tr of document.querySelectorAll('#rows tr.row')) {
    const pkg = shown[tr.dataset.i];
    if (pkg && failedBuilds(pkg).length) errorsObserver.observe(tr);
  }
}
async function openErrors(tr) {
  if (tr.nextElementSibling?.classList.contains('detail')) return;
  const pkg = shown[tr.dataset.i];
  const detail = document.createElement('tr');
  detail.className = 'detail open errors';
  detail.dataset.mode = 'build';
  detail.innerHTML = `<td colspan="6"><div class="detail-inner">
      <div class="nix-line">Loading its builds…</div>
    </div></td>`;
  tr.after(detail);
  const row = await fullRow(pkg);
  const inner = detail.querySelector('.detail-inner');
  if (row) fillBuilds(row, inner);
  else inner.innerHTML = html`<div class="nix-line">Couldn't load its builds.</div>`;
}

// With every package, the header. The overview (no list chosen): all of
// nixpkgs, split into the fully checked and the sets updated in bulk;
// cards for the fully checked ones' outdated, failing, vulnerable and broken
// (their count, its change over a week, a month's trend), each opening its
// list; the sets updated in bulk; and ways to find packages (what needs attention is
// the filter bar's chip, renderStats, on every view). A
// list: what it is ("Showing", ✕ back to the overview), tiles counting and
// filtering it, and the team picker.
function renderScope() {
  const el = document.getElementById('scope');
  if (!el) return;
  el.hidden = !community;
  if (!community) return;
  if (shownView === 'maintainers') {
    el.dataset.drawn = '';
    el.innerHTML = html`<div class="scope-view">
      <span class="scope-label">Showing</span>
      <span class="view-chip">Maintainers · ${fmt(maintainersList?.length)}<a class="view-x" href="${scopeHref({})}" data-scope-home aria-label="Back to the overview" title="Back to the overview">✕</a></span>
      <span class="scope-hint">by handle; the search narrows them, and one opens their packages</span>
    </div>`;
    return;
  }
  if (shownView !== 'overview') {
    el.dataset.drawn = '';
    el.innerHTML = listHeaderHtml();
    return;
  }
  // Drawn again only when it changes (its history arrives, a team is
  // picked), not while someone types in its search box.
  const drawn = `${trendPoints?.length ?? -1}:${trendEvents.length}:${teamFilter || ''}:${Object.values(highlightShown)}:${allCauses ? 'all' : ''}`;
  if (el.dataset.drawn !== drawn) {
    el.dataset.drawn = drawn;
    el.innerHTML = overviewHtml();
  }
  // While searching, the matches (drawn under the overview) get the room:
  // the newest and longest-standing and the sets updated in bulk step aside, and
  // come back once the search is cleared.
  const query = document.getElementById('search').value;
  const more = el.querySelector('.overview-more');
  if (more) more.hidden = Boolean(query.trim());
  // Typed in the top search: the overview's box says the same.
  const box = document.getElementById('overviewSearch');
  if (box && box !== document.activeElement && box.value !== query) box.value = query;
}

const fmt = (x) => (x || 0).toLocaleString();
const teamPicker = (label) => {
  // By name, whatever its case (the data's keys sort capitals first).
  const teams = Object.entries(manifest.views?.teams || {}).sort(([a], [b]) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' }),
  );
  return teams.length
    ? html`<label class="team-pick"><span class="team-pick-label">Team</span> <select id="teamPick"><option value="">${label}</option>${teams.map(([t, count]) => html`<option value="${t}"${teamFilter && t.toLowerCase() === teamFilter.toLowerCase() ? raw(' selected') : ''}>${t} (${fmt(count)})</option>`)}</select></label>`
    : '';
};

// A magnifying glass, for the overview's search (currentColor).
const SEARCH_ICON =
  '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="7" cy="7" r="4.75"/><path d="m10.5 10.5 3.5 3.5"/></svg>';

// The overview's cards: the manifest's count, which list they open
// (?view=, ?filter=), and history.json's key.
const CARDS = [
  { key: 'outdated', label: 'Outdated', view: 'attention', filter: 'warn', color: 'var(--warn)' },
  {
    key: 'buildFailures',
    label: 'Build failures',
    view: 'attention',
    filter: 'builds',
    color: 'var(--danger)',
  },
  {
    key: 'updateFailures',
    label: 'Update failures',
    view: 'attention',
    filter: 'updates',
    color: 'var(--caution)',
  },
  {
    key: 'vulnerable',
    label: 'Vulnerable',
    view: 'attention',
    filter: 'vuln',
    color: 'var(--danger)',
  },
  { key: 'broken', label: 'Marked broken', view: 'broken', filter: null, color: 'var(--caution)' },
];
// A package that moves with others (one package file, one version: the
// sync's family, datastore.grouped) is one line in the overview's lists:
// what they're called together and how many (huaweicloudsdk* ·187),
// opening a search for them; without a shared start, its name and +N,
// opening it.
const familyName = (name, family) =>
  family
    ? html`<span class="hl-name mono" title="${fmt(family.more + 1)} packages, one update: ${family.label || name} and the like">${family.label || name}</span><span class="hl-family">${family.label ? fmt(family.more + 1) : `+${fmt(family.more)}`}</span>`
    : html`<span class="hl-name mono">${name}</span>`;
const familyLink = (name, family) =>
  family?.label
    ? html`href="?q=${encodeURIComponent(family.label.replace(/\*$/, ''))}"`
    : html`href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}"`;

// The overview's lists of the newest and longest-standing (the manifest's
// highlights), and which of the two each shows.
const HIGHLIGHTS = [
  { key: 'failing', label: 'Build failures', filter: 'builds', color: 'var(--danger)' },
  { key: 'outdated', label: 'Outdated', filter: 'warn', color: 'var(--warn)' },
  { key: 'updateFailing', label: 'Update failures', filter: 'updates', color: 'var(--caution)' },
];
const highlightShown = {
  failing: 'newest',
  outdated: 'newest',
  updateFailing: 'newest',
  blockers: 'master',
};

function highlightsHtml() {
  const found = manifest.highlights;
  if (!found) return '';
  const columns = HIGHLIGHTS.map(({ key, label, filter, color }) => {
    const h = found[key] || { count: 0, newest: [], oldest: [] };
    const mode = highlightShown[key];
    const items = h[mode] || [];
    const toggle = (m, text) =>
      html`<button type="button" class="hl-mode" data-hl="${key}" data-mode="${m}" aria-pressed="${mode === m}">${text}</button>`;
    return html`<section class="hl-card" style="--hl:${color}" aria-label="${label}">
      <div class="hl-head">
        <h3 class="hl-title"><span class="hl-label">${label}</span><span class="hl-n">${fmt(h.count)}</span></h3>
        <div class="hl-modes" role="group" aria-label="${label}: show">${toggle('newest', 'Newest')}${toggle('oldest', 'Oldest')}</div>
      </div>
      ${
        items.length
          ? html`<ol class="hl-list">${items.map(
              ([name, since, letter, family]) =>
                html`<li><a class="hl-row" ${familyLink(name, family)}><span class="status-dot ${NAME_DOTS[letter[0]] || 'neutral'}" aria-hidden="true"></span>${familyName(name, family)}<span class="hl-age" title="Since ${longDate(since)}">${shortAge(since)}</span></a></li>`,
            )}</ol>`
          : html`<p class="hl-none">None right now.</p>`
      }
      ${h.count ? html`<a class="hl-all" href="${scopeHref({ view: 'attention', filter })}" data-card-view="attention" data-card-filter="${filter}">Show all ${fmt(h.count)} <span aria-hidden="true">→</span></a>` : ''}
    </section>`;
  });
  return html`<h2 class="scope-label">Newest and longest-standing · fully checked</h2>
    <div class="hl-cols">${columns}${blockersHtml()}</div>`;
}

// Why things fail, across packages (the manifest's causes, nixkeeper's
// causes.py): failed builds grouped by the same error (a friendly title
// where the pattern is known, else the error line), each opening its
// packages; and the update bot's failures by cause, each opening the list
// of them (?updateFailed=). Not with data from before.
// The update bot's own problems, not the package's (FAILED_BECAUSE: bot,
// request), with how the card says them; and how many of the package's
// causes it shows as bars.
const BOT_OWN = new Map([
  ['bot', "the bot's own outage"],
  ['request', 'its request failed'],
]);
const BOT_SHOWN = 8;
const botCause = (key) => (key === 'noLog' ? 'build, no log' : FAILED_BECAUSE[key]?.short || key);

// Every group of failed builds sharing an error (views/causes.json), once
// "Show all" asked for them: the card then lists them all.
let allCauses = null;

function causesHtml() {
  const c = manifest.causes;
  if (!c?.builds?.length && !Object.keys(c?.bot || {}).length) return '';
  const groups = c.builds.length
    ? html`<section class="hl-card" style="--hl:var(--danger)" aria-label="Same error, many packages">
    <div class="hl-head">
      <h3 class="hl-title" title="Failed builds grouped by the line of their log that says why (paths, numbers and names left out): one cause, one fix pattern"><span class="hl-label">Same error, many packages</span><span class="hl-n">${fmt(c.packages)}</span></h3>
      <span class="hl-unit">in ${fmt(c.groups)} groups</span>
    </div>
    <ol class="hl-list">${(allCauses || c.builds).map(
      (g) =>
        html`<li><a class="hl-row" href="${scopeHref({ cause: g.key })}" data-scope-cause="${g.key}" title="${g.line}"><span class="status-dot missing" aria-hidden="true"></span><span class="hl-name${g.title ? '' : ' mono'}">${g.title || g.signature}</span>${g.about ? html`<span class="fixed-by">${g.about}</span>` : ''}<span class="hl-age">${fmt(g.count)}</span></a></li>`,
    )}</ol>
    ${
      c.groups > c.builds.length
        ? html`<button type="button" class="hl-all cause-more" aria-expanded="${!!allCauses}">${allCauses ? 'Show the biggest only' : html`Show all ${fmt(c.groups)} groups`} <span aria-hidden="true">${allCauses ? '↑' : '↓'}</span></button>`
        : ''
    }
  </section>`
    : '';
  // The commonest first (the data's keys are written sorted by name).
  const all = Object.entries(c.bot || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const total = all.reduce((n, [, v]) => n + v, 0);
  // The bot's own problems (its outage, its request failing): not the
  // package's, said apart however few; the package's causes as bars.
  const own = all.filter(([key]) => BOT_OWN.has(key));
  const bot = all.filter(([key]) => !BOT_OWN.has(key));
  const most = Math.max(1, ...bot.map(([, v]) => v));
  const failedHref = (key) =>
    `${scopeHref({ view: 'attention', filter: 'updates' })}&updateFailed=${encodeURIComponent(key)}`;
  const more = bot.slice(BOT_SHOWN);
  const reasons = bot.length
    ? html`<section class="hl-card" style="--hl:var(--warn-dot)" aria-label="Why the update bot fails">
    <div class="hl-head">
      <h3 class="hl-title" title="nixpkgs-update's last attempt at each package, by why it failed (its log)"><span class="hl-label">Why the update bot fails</span><span class="hl-n">${fmt(total)}</span></h3>
      <span class="hl-unit">packages, by cause</span>
    </div>
    <ol class="hl-list cause-bars">${bot
      .slice(0, BOT_SHOWN)
      .map(
        ([key, n]) =>
          html`<li><a class="hl-row" href="${failedHref(key)}"><span class="hl-name">${botCause(key)}</span><span class="cause-bar" aria-hidden="true"><span style="width:${Math.round((100 * n) / most)}%"></span></span><span class="hl-age">${fmt(n)}</span></a></li>`,
      )}</ol>
    ${
      own.length
        ? html`<p class="cause-own" title="Failures that aren't the package's: the update bot's own outage, or its request to the builders failing">Not the package's: ${own.map(([key, n], i) => html`${i ? ' · ' : ''}<a class="files-link" href="${failedHref(key)}">${BOT_OWN.get(key)} ${fmt(n)}</a>`)}</p>`
        : ''
    }
    ${more.length ? html`<a class="hl-all" href="${scopeHref({ view: 'attention', filter: 'updates' })}">and ${more.length} more ${more.length === 1 ? 'cause' : 'causes'} (${more.map(([key]) => botCause(key)).join(', ')}) <span aria-hidden="true">→</span></a>` : ''}
  </section>`
    : '';
  return html`<h2 class="scope-label">Why things fail · fully checked</h2>
    <div class="hl-cols">${groups}${reasons}</div>`;
}

// "Blocking the most": the failing dependencies stopping the most packages'
// builds (nixkeeper-hydra's blockedBy: fix one, and they all build again;
// of all of nixpkgs, as zh.fail counts them; not with data from before, or
// before the digest has read any), on master (the manifest's blockers) or,
// while Hydra has evaluated
// the current cycle, on staging-next before its merge (blockers.stagingNext,
// branches.apply_staging_next_blocked), switched in its header as the other
// lists switch newest and oldest: one list, one height, the cards aligned.
function blockersHtml() {
  const b = manifest.blockers;
  const sn = b?.stagingNext?.top?.length ? b.stagingNext : null;
  if (!b?.count && !sn) return '';
  const onNext = sn && highlightShown.blockers === 'stagingNext';
  const shown = onNext ? sn : b;
  const toggle = (m, text, title) =>
    html`<button type="button" class="hl-mode" data-hl="blockers" data-mode="${m}" aria-pressed="${(onNext ? 'stagingNext' : 'master') === m}" title="${title}">${text}</button>`;
  const when = sn?.evaluatedAt
    ? ` (Hydra's evaluation of ${shortDay(sn.evaluatedAt.slice(0, 10))})`
    : '';
  const title = onNext
    ? `On staging-next${when}, ${fmt(sn.count)} failing dependencies stop ${fmt(sn.packages)} packages that build on master: unless fixed there, they're stopped on master too when staging-next is merged`
    : `${fmt(b.count)} failing dependencies stop ${fmt(b.packages)} packages' builds, in all of nixpkgs`;
  return html`<section class="hl-card" style="--hl:var(--danger)" aria-label="Blocking the most">
    <div class="hl-head">
      <h3 class="hl-title" title="${title}"><span class="hl-label">Blocking the most</span><span class="hl-n">${fmt(shown.packages)}</span></h3>
      ${
        sn
          ? html`<div class="hl-modes" role="group" aria-label="Blocking the most: on">${toggle('master', 'Master', 'On master, now')}${toggle('stagingNext', 'Next', 'On staging-next, before its merge into master')}</div>`
          : html`<span class="hl-unit">packages stopped</span>`
      }
    </div>
    <ol class="hl-list">${shown.top.map(
      ([name, isRow, packages, builds]) =>
        html`<li>${
          isRow
            ? html`<a class="hl-row" href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}">`
            : raw('<span class="hl-row">')
        }<span class="status-dot missing" aria-hidden="true"></span><span class="hl-name mono">${name}</span><span class="hl-age" title="Stops ${fmt(packages)} ${packages === 1 ? 'package' : 'packages'} (${fmt(builds)} ${builds === 1 ? 'build' : 'builds'})${onNext ? ' on staging-next' : ''}">stops ${fmt(packages)}</span>${raw(isRow ? '</a>' : '</span>')}</li>`,
    )}</ol>
    ${
      onNext
        ? html`<p class="hl-all hl-when" title="${title}">On staging-next${sn.evaluatedAt ? `, evaluated ${shortDay(sn.evaluatedAt.slice(0, 10))}` : ''}</p>`
        : html`<a class="hl-all" href="${scopeHref({ view: 'blocked' })}" data-card-view="blocked">Show all ${fmt(b.packages)} <span aria-hidden="true">→</span></a>`
    }
  </section>`;
}

// Days of history the cards draw, and how many points before they do.
const TREND_DAYS = 30;
// How many days the trends shown span, the first and the last included (9
// while there are 9 days of history, then TREND_DAYS).
const trendSpan = (points) =>
  Math.round((Date.parse(points.at(-1).day) - Date.parse(points[0].day)) / 864e5) + 1;
const TREND_MIN_POINTS = 2;

// A card's trend: its count at each point, placed by date (dayPosition),
// with a thin mark on each day something explains a jump (TREND_EVENTS).
function sparkline(points, key, color) {
  const values = points.map((p) => p[key] ?? 0);
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const xy = points.map(
    (p, i) =>
      `${dayPosition(points, p.day).toFixed(1)},${(20 - (18 * (values[i] - lo)) / span).toFixed(1)}`,
  );
  const marks = shownEvents(points)
    .filter((e) => MARKED.has(e.kind))
    .map(
      (e) =>
        `<line class="spark-mark ${e.kind}" x1="${e.x.toFixed(1)}" x2="${e.x.toFixed(1)}" y1="0" y2="22" vector-effect="non-scaling-stroke"/>`,
    )
    .join('');
  return raw(
    `<svg class="spark" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true">${marks}<polyline points="${xy.join(' ')}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`,
  );
}

// Under the cards: what the marks on the trends are, one short entry per
// kind with its days ("counting changed Oct 6, Oct 7"), each day saying in
// full what happened when hovered (a staging-next one links its PR).
// nixkeeper's own releases aren't marked nor listed: the footer says the
// version, and a release that changes counting has its own mark.
const MARK_LABELS = { counting: 'counting changed', 'staging-next': 'staging-next merged' };
function marksHtml(points) {
  const marked = shownEvents(points).filter((e) => MARKED.has(e.kind));
  if (!marked.length) return '';
  const kinds = [...new Set(marked.map((e) => e.kind))];
  return html`<p class="spark-legend">${kinds.map((kind, i) => {
    // One date per day: two changes the same day share it, both said.
    const days = new Map();
    for (const e of marked.filter((m) => m.kind === kind))
      days.set(e.day, [...(days.get(e.day) || []), e]);
    const dates = [...days].map(([day, es]) => {
      const said = es.map((e) => TREND_EVENTS[kind](e)).join('; ');
      return kind === 'staging-next'
        ? html`<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${es[0].pr}" target="_blank" rel="noopener" title="${said}">${shortDay(day)}</a>`
        : html`<span class="spark-day" title="${said}">${shortDay(day)}</span>`;
    });
    return html`${i ? ' · ' : ''}<span class="spark-key ${kind}" aria-hidden="true"></span>${MARK_LABELS[kind]} ${dates.flatMap((d, j) => (j ? [', ', d] : [d]))}`;
  })}</p>`;
}

// While nixkeeper-updates' digest is still reading the bot's past attempts
// (more than this many to go: a backfill, not a day's new ones), update
// failures keep turning up that were there all along: the Failing card
// says so, as its rise isn't packages breaking.
const BACKFILL_PENDING = 1000;
// Under Vulnerable: the CVEs fixed on unstable (a new version, or a patch
// named after the CVE) that the newest release is still affected by (their
// tile in Vulnerable's list: Fixes to backport). Not part of Vulnerable's
// count: unstable has the fix. Not on data from before nixkeeper-vulnerabilities
// (no count).
function backportCardNote() {
  const n = manifest.counts?.backport;
  if (n == null) return '';
  const release = manifest.sources?.tracker?.release;
  const to = release ? `to ${release}` : 'to the newest release';
  return html`<span class="card-sub" title="Fixed on nixpkgs unstable (a new version, or a patch named after the CVE), while the newest release is still affected: fixes to backport there, a tile in this card's list. Not counted above: unstable has the fix.">${n ? `${fmt(n)} fixed, to backport ${to}` : `none to backport ${to}`}</span>`;
}

function backfillNote() {
  const updates = manifest.sources?.updates;
  if (!updates?.used || !(updates.pending > BACKFILL_PENDING)) return '';
  return html`<span class="card-sub card-note" title="nixkeeper-updates is still reading nixpkgs-update's past attempts: update failures that were there all along keep turning up, so this count rises until it's done">update failures still being read: ${fmt(updates.pending)} attempts to go</span>`;
}

// What marks the trends, in words: a staging-next merge (mass rebuilds:
// failing builds jump for days after), a change in how nixkeeper counts
// (it can step a count overnight), or nixkeeper updated (said under the
// cards, not marked: a release that changes counting has its own mark).
const TREND_EVENTS = {
  'staging-next': (e) => `staging-next merged (#${e.pr})`,
  nixkeeper: (e) => `nixkeeper ${e.version}`,
  counting: (e) => e.text,
};
// The kinds drawn on the trends: grey for staging-next, amber for a counting
// change (style.css).
const MARKED = new Set(['staging-next', 'counting']);
// The events on the days the trends show, with where they fall.
function shownEvents(points) {
  return trendEvents
    .filter((e) => TREND_EVENTS[e.kind])
    .map((e) => ({ ...e, x: dayPosition(points, e.day) }))
    .filter((e) => e.x != null);
}
const shortDay = (day) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });

function overviewHtml() {
  const c = manifest.counts || {};
  const views = manifest.views || {};
  const sets = Object.entries(views.sets || {}).map(([name, v]) => [
    name,
    typeof v === 'number' ? { packages: v, failed: 0, broken: 0 } : v,
  ]);
  // In sets updated in bulk ("pending" before 0.14.0).
  const inSets = c.inSets ?? c.pending ?? 0;
  const total = (c.tracked || 0) + inSets;
  const share = total ? (100 * (c.tracked || 0)) / total : 0;
  const points = (trendPoints || []).slice(-TREND_DAYS);
  const trends = points.length >= TREND_MIN_POINTS;
  // Build failures from before the count was kept apart: the newest and
  // longest-standing lists' count of them.
  const count = (key) =>
    key === 'buildFailures' && c[key] == null ? manifest.highlights?.failing?.count : c[key];
  const cards = CARDS.filter((card) => !card.optional || count(card.key) != null).map((card) => {
    // The days that have this count (the split ones are newer than the rest).
    const mine = points.filter((p) => p[card.key] != null);
    const drawn = mine.length >= TREND_MIN_POINTS;
    const trend = drawn ? trendChange(mine, card.key) : null;
    const change = trend?.change;
    const over = trend?.since ? `Since ${shortDay(trend.since)}` : 'Over the last 7 days';
    const said =
      change == null
        ? ''
        : change === 0
          ? html`<span class="card-change" title="${over}">no change<span class="sr-only">, ${over.toLowerCase()}</span></span>`
          : html`<span class="card-change ${change > 0 ? 'worse' : 'better'}" title="${over}"><span aria-hidden="true">${change > 0 ? '↑' : '↓'}</span><span class="sr-only">${change > 0 ? 'up' : 'down'}</span> ${fmt(Math.abs(change))}<span class="sr-only">, ${over.toLowerCase()}</span></span>`;
    return html`<a class="card" href="${scopeHref({ view: card.view, filter: card.filter })}" data-card-view="${card.view}" data-card-filter="${card.filter || ''}">
      <span class="card-label">${card.label}<span class="card-go" aria-hidden="true">›</span></span>
      <span class="card-row"><span class="card-n" style="color:${card.color}">${fmt(count(card.key))}</span>${said}</span>
      ${
        card.key === 'buildFailures' && c.failingBuilds
          ? html`<span class="card-sub" title="Every Hydra job that didn't build, on every platform, in all of nixpkgs: as zh.fail counts them, with a dependency's failure counted for each package it stops, and timeouts. A package counts here only when its own build failed.">${fmt(c.failingBuilds)} failing builds on Hydra</span>${platformSplit(c.buildFailuresOn)}`
          : card.key === 'updateFailures'
            ? backfillNote()
            : card.key === 'vulnerable'
              ? backportCardNote()
              : card.key === 'outdated'
                ? html`<span class="card-sub" title="Each package counted once, its other attributes left out, and the sets updated in bulk (Haskell, R and the others) left out: they count on their own lines below. With nixkeeper's own update checks, which can overrule a newer version listed elsewhere (a development series, a version upstream withdrew). Counts of every attribute in nixpkgs come out higher.">Unique, outside sets updated in bulk</span>`
                : ''
      }
      ${drawn ? sparkline(mine, card.key, card.color) : ''}
    </a>`;
  });
  return html`<h2 class="scope-head">
      <span class="scope-label">All of nixpkgs</span>
      <span class="scope-total">${fmt(total)} packages</span>
    </h2>
    <div class="scope-bar" aria-hidden="true"><span style="width:${share.toFixed(1)}%"></span></div>
    <div class="scope-split">
      <span><i class="swatch full"></i><b>${fmt(c.tracked)}</b> fully checked</span>
      <span title="Generated from CRAN, Hackage and the like and kept current in bulk by their own tooling, not one PR per package: each set counted on its own line below, not in the cards"><i class="swatch gen"></i><b>${fmt(inSets)}</b> in sets updated in bulk · counted per set</span>
    </div>
    <h2 class="scope-label">Fully checked${trends ? `, last ${trendSpan(points)} days` : ''} · each opens its list${trends ? '' : html` <span class="scope-hint">(trends from the second daily sync)</span>`}</h2>
    <div class="cards">${cards}</div>${trends ? marksHtml(points) : ''}

    <div class="find" role="search">
      <label class="find-box"><span class="find-icon" aria-hidden="true">${raw(SEARCH_ICON)}</span>
        <input type="search" id="overviewSearch" class="find-input" placeholder="Find a package, or @maintainer" aria-label="Find a package, or @maintainer" value="${document.getElementById('search').value}"></label>
      ${teamPicker('Browse a team…')}
    </div>
    <p class="find-more">or <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">browse every maintainer</a></p>
    <div class="overview-more">${highlightsHtml()}${causesHtml()}${fixedHtml()}${setsHtml(sets)}${numbersHtml()}</div>`;
}

// The overview's recently fixed (the manifest's "fixed", from history.json):
// builds that work again, packages updated, nixpkgs-update failures
// cleared, the last week's of each. Not with data from before it.
// What a fix ended, for its age's hover ("failing since Jun 2").
const FIXED_SINCE = { build: 'failing', update: 'outdated', bot: 'the update bot failing' };
const FIXED = [
  { key: 'build', label: 'Builds fixed' },
  { key: 'update', label: 'Updated' },
  { key: 'bot', label: 'Update failures cleared' },
];
// Who a fix is credited to (history.credit in nixkeeper): its PR, who
// opened it and who merged it; "likely" for a build fix (a PR merged since
// the build began failing that touched it). The name shown: the author,
// unless it's a bot (the update bot), then who merged it, unless that's a
// bot too (the merge bot, asked by someone the data doesn't say yet): then
// none, the PR still in the tooltip.
const BOTS = new Set(['r-ryantm', 'nixpkgs-ci', 'nixpkgs-merge-bot', 'github-actions']);
const creditName = (c) => [c.author, c.mergedBy].find((who) => who && !BOTS.has(who)) || '';
const creditText = (c) =>
  `${c.likely ? 'Likely fixed by' : 'By'} #${c.pr}${c.author ? `, opened by @${c.author}` : ''}${c.mergedBy ? `, merged by @${c.mergedBy}` : ''}`;

function fixedHtml() {
  const fixed = manifest.fixed;
  if (!fixed) return '';
  const cards = FIXED.map(({ key, label }) => {
    const f = fixed[key] || { count: 0, newest: [] };
    return html`<section class="hl-card" style="--hl:var(--ok-devel)" aria-label="${label}">
      <div class="hl-head">
        <h3 class="hl-title"><span class="hl-label">${label}</span><span class="hl-n">${fmt(f.count)}</span></h3>
      </div>
      ${
        f.newest.length
          ? html`<ol class="hl-list">${f.newest.map(
              ([name, at, from, to, credit, since, family]) =>
                html`<li><a class="hl-row" ${familyLink(name, family)}${credit ? html` title="${creditText(credit)}"` : ''}><span class="status-dot ok" aria-hidden="true"></span>${familyName(name, family)}${to ? html`<span class="fixed-to mono" title="${from} → ${to}">→ ${to}</span>` : ''}${credit && creditName(credit) ? html`<span class="fixed-by">@${creditName(credit)}</span>` : ''}${
                  since
                    ? html`<span class="hl-age" title="Fixed ${longDate(at)}, ${FIXED_SINCE[key]} since ${longDate(since)}">after ${shortAge(since, new Date(at).getTime())}</span>`
                    : html`<span class="hl-age" title="${longDate(at)}">${shortAge(at)}</span>`
                }</a></li>`,
            )}</ol>`
          : html`<p class="hl-none">None this week yet.</p>`
      }
    </section>`;
  });
  return html`<h2 class="scope-label" title="The fixes that took longest first: how long each had been failing or outdated when it was fixed">Recently fixed · last ${fixed.days} days · longest-standing first · fully checked</h2>
    <div class="hl-cols">${cards}</div>`;
}

const SET_BAR_TITLE =
  'Outdated (orange), marked broken (yellow) and failing (red), each package once, at its worst: a failing package counts as failing only, a broken one as broken only. The counts below count each on its own, so a package can be in several.';

// The overview's sets updated in bulk: each one's size, what updates it,
// and how much of it is failing, marked broken or outdated (a bar, in
// their colours).
// The overview's last section, "nixpkgs in numbers": figures for the
// curious, out of the way of the lists above (the manifest's "numbers",
// datastore.numbers; "merge", prs_digest.merge_summary; the sources' PR and
// queue counts). Each says what it means, and opens its list when there is
// one. Only those the data has.
function numbersHtml() {
  const n = manifest.numbers;
  if (!n) return '';
  const m = manifest.merge;
  const prs = sources?.prs;
  const queue = sources?.queue;
  const link = (href, text) => html` <a class="files-link" href="${href}">${text} →</a>`;
  const items = [
    prs?.prs != null && [
      fmt(prs.prs),
      'open PRs',
      `in nixpkgs, and ${fmt(prs.issues)} open issues`,
    ],
    m?.prs != null && [
      fmt(m.prs),
      'ready for the merge bot',
      html`PRs waiting for their own maintainers (${fmt(m.maintainers)} people could each merge one), ${fmt(m.over90)} for over three months. Yours: "You can merge these", on <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">your page</a>`,
    ],
    manifest.close?.prs != null && [
      fmt(manifest.close.prs),
      'update PRs nixpkgs is past',
      html`it already has their version or a newer one: they can be closed (${fmt(manifest.close.bot)} of them the update bot's). Yours: "Can be closed", on <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">your page</a>${link(scopeHref({ view: 'superseded' }), 'all of them')}`,
    ],
    [
      fmt(n.behind),
      'update PRs behind upstream',
      'upstream has moved on since they were opened: merged as they are, the package would still be outdated',
    ],
    queue?.cycleDays != null && [
      `${queue.cycleDays} days`,
      "the update bot's round",
      'how long nixpkgs-update takes to go through its whole queue, trying each package once',
    ],
    // The top card's failing builds (counts.failingBuilds), split by kind.
    [
      fmt(n.failing + (n.blocked || 0) + (n.unfinished || 0)),
      'builds not built on Hydra',
      `${fmt(n.failing)} failing themselves · ${fmt(n.blocked || 0)} blocked by a failing dependency · ${fmt(n.unfinished || 0)} unfinished (timed out or aborted) · of ${fmt(n.builds)} in master's evaluation, every platform, sets included`,
    ],
    manifest.views?.unbuilt != null && [
      fmt(manifest.views.unbuilt),
      'not built where listed',
      html`nixpkgs lists them for a platform Hydra doesn't build them on${link(scopeHref({ view: 'unbuilt' }), 'see them')}`,
    ],
    manifest.counts?.tracked > 0 && [
      `${Math.round((100 * (manifest.counts.tracked - manifest.counts.outdated)) / manifest.counts.tracked)}%`,
      'up to date',
      `of the ${fmt(manifest.counts.tracked)} packages outside the sets: nixpkgs has the newest version (${fmt(manifest.counts.outdated)} outdated)`,
    ],
    [
      fmt(n.unmaintained),
      'without a maintainer',
      html`packages outside the sets nobody maintains${link('?maintainer=none', 'see them')}`,
    ],
  ].filter(Boolean);
  return html`<h2 class="scope-label">nixpkgs in numbers</h2>
    <div class="numbers">${items.map(
      ([value, label, what]) =>
        html`<div class="number"><span class="number-v">${value}</span><span class="number-l">${label}</span><span class="number-what">${what}</span></div>`,
    )}</div>`;
}

function setsHtml(sets) {
  if (!sets.length) return '';
  const pct = (n, of) => (of ? Math.min(100, (100 * n) / of) : 0).toFixed(1);
  const cards = sets.map(([s, v]) => {
    // Each package once, at its worst (from 0.14.0); before, broken and
    // failing as counted, overlapping.
    const worst = v.bar || { broken: v.broken, failed: v.failed };
    // In the order the text below says them.
    const bar = ['outdated', 'broken', 'failed'].filter((k) => worst[k]).map((k) => [k, worst[k]]);
    const problems = [
      v.outdated
        ? html`<span class="set-outdated">${fmt(v.outdated)} outdated</span>${v.onBranch ? html`, ${fmt(v.onBranch)} on ${profileOf(s)?.branch || 'its branch'}` : ''}`
        : '',
      v.archived
        ? html`<span class="set-broken" title="${ARCHIVED_TITLE}; nixpkgs marks most of them broken already">${fmt(v.archived)} archived${v.archivedUnmarked ? html` (${fmt(v.archivedUnmarked)} not marked broken)` : ''}</span>`
        : '',
      v.broken ? html`<span class="set-broken">${fmt(v.broken)} broken</span>` : '',
      v.failed ? html`<span class="set-failed">${fmt(v.failed)} failing</span>` : '',
    ].filter(Boolean);
    return html`<a class="set-card" href="${scopeHref({ set: s })}" data-scope-set="${s}">
      <span class="set-name mono">${s}</span>
      <span class="set-n">${fmt(v.packages)} <span class="set-unit">packages</span></span>
      <span class="set-by" title="${bulkText(s)}">by ${bulkShort(s)}</span>
      <span class="set-bar" aria-hidden="true" title="${SET_BAR_TITLE}">${bar.map(([kind, n]) => html`<span class="set-bar-${kind}" style="width:${pct(n, v.packages)}%"></span>`)}</span>
      <span class="set-meta">${problems.length ? problems.map((p, i) => html`${i ? ' · ' : ''}${p}`) : v.outdated == null ? 'None broken or failing' : 'None outdated, broken or failing'}</span>
    </a>`;
  });
  return html`<h2 class="scope-label">Sets updated in bulk <span class="scope-hint">each by its own tooling, not one PR per package: counted here, not in the cards above</span></h2>
    <div class="set-grid">${cards}</div>`;
}

function listHeaderHtml() {
  const handle = document.getElementById('search').value.trim().replace(/^@/, '');
  const path = shownView || '';
  // The tiles count the view shown, with the platform, list and team
  // filters, as the count chips do (renderStats).
  const base = packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && notHidden(p),
  );
  // Hidden here ("Hide until it changes"), by the same filters.
  const hiddenHere = packages.filter(
    (p) => inPlatform(p) && inList(p) && inPeople(p) && inSet(p) && isHidden(p),
  ).length;
  const shownCount = base.filter((p) => refined(p)).length;
  const tiles = Object.entries(TILES).map(([key, label]) => {
    const count = base.filter((p) => FILTERS[key].test(p) && refined(p, key)).length;
    const pressed = activeFilter === key;
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
          ? `${listFilter} list`
          : path.startsWith('views/set/')
            ? setFilter
            : path.startsWith('views/cause/')
              ? causeShown?.title || 'Failing with the same error'
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
          ? html`<button type="button" class="hidden-toggle" aria-pressed="${showHidden}" title="Packages you hid here, in this browser, until what they need attention for changes">${fmt(hiddenHere)} hidden · ${showHidden ? 'hide them' : 'show them'}</button>`
          : ''
      }<button type="button" class="close-all" title="Close every open package (Esc)" hidden>Close all</button>
      ${path.startsWith('views/cause/') && causeShown ? html`<span class="scope-hint cause-line" title="The error line these builds share (paths, numbers and names vary)"><code>${causeShown.line}</code></span>` : ''}
      ${
        // Marked broken's neighbour: listed for a platform, never built there.
        path === 'views/broken.json' && manifest.views?.unbuilt
          ? html`<a class="scope-hint files-link" href="${scopeHref({ view: 'unbuilt' })}" title="Packages nixpkgs lists for a platform Hydra doesn't build them on: usually a dependency isn't available there">also: ${fmt(manifest.views.unbuilt)} not built where listed →</a>`
          : path === 'views/superseded.json'
            ? html`<span class="scope-hint">an open update PR nixpkgs is already past (it has the PR’s version or a newer one): each package’s details link it</span>`
            : path === 'views/unbuilt.json'
              ? html`<span class="scope-hint">listed for a platform Hydra doesn't build them on (struck tags); pick a platform to see its own</span>`
              : ''
      }
      ${
        // "PR to close" on in another list: the whole of nixpkgs' are a view.
        refines.has('superseded') && path !== 'views/superseded.json' && manifest.views?.superseded
          ? html`<a class="scope-hint files-link" href="${scopeHref({ view: 'superseded' })}" data-card-view="superseded" title="Every package with an open update PR nixpkgs is already past, up to date or not">also: ${fmt(manifest.views.superseded)} in all of nixpkgs →</a>`
          : ''
      }
      ${path.startsWith('views/set/') ? html`<span class="scope-hint">${bulkText(setFilter)}${profileOf(setFilter) ? html` (<a class="files-link" href="${safeUrl(profileOf(setFilter).link)}" target="_blank" rel="noopener">in nixpkgs ↗</a>)` : ''}</span>` : ''}
      ${teamPicker('Any team')}${teamOutChips()}
    </div>
    ${mergeHtml(path, handle)}
    ${closeHtml(path, handle)}
    ${
      // One package: its row says it all, the tiles would only count to 1.
      path.startsWith('pkg:') ? '' : html`<div class="tiles">${tiles}</div>${refineHtml()}`
    }`;
}

// The address of a view (scopeHref({ set }), { pkg }, {} for what needs
// attention): the others' parameters cleared, the data's own kept.
function scopeHref({ set = null, pkg = null, view = null, filter = null, cause = null }) {
  const params = new URLSearchParams(location.search);
  for (const k of [
    'filter',
    'q',
    'maintainer',
    'sort',
    'platform',
    'list',
    'team',
    'set',
    'cause',
    'pkg',
    'page',
    'view',
    'updateFailed',
    'buildFailed',
    'in',
    'by',
    'status',
    'ofteam',
    'newer',
    'errors',
  ])
    params.delete(k);
  if (set) params.set('set', set);
  if (cause) params.set('cause', cause);
  if (pkg) params.set('pkg', pkg);
  if (view) params.set('view', view);
  if (filter && FILTERS[filter]?.param) params.set('filter', FILTERS[filter].param);
  const query = params.toString();
  return location.pathname + (query ? `?${query}` : '');
}

// Show a view: set (a generated set), pkg (one package), neither: what needs
// attention. The search, filters and page start over.
function showView({ set = null, pkg = null, view = null, filter = null, cause = null }) {
  setFilter = set;
  causeFilter = cause;
  pkgParam = pkg;
  viewParam = view;
  teamFilter = null;
  teamsLeftOut = [];
  noTeam = false;
  maintainersLeftOut = [];
  listFilter = null;
  activeFilter = filter || 'all';
  refines = new Set();
  ageFilter = null;
  becauseFilter = null;
  buildFailedFilter = null;
  platformFilter = null;
  inFilter = null;
  byFilter = null;
  statusFilter = null;
  matchTeam = null;
  newerFilter = null;
  showErrors = false;
  document.getElementById('search').value = '';
  update();
  // From the page's top, as a new page would: scrolling the view's header
  // into view left it under the sticky top bar, its tiles hidden.
  window.scrollTo({ top: 0 });
}

// With every package, under a plain search: the packages beyond the view
// shown whose names match, from the name index (loaded on first use), each
// opening on its own (?pkg=).
// With every package, under a search for @someone: the maintainers whose
// handle matches, the closest first, each opening their packages.
function maintainerMatchesHtml(query) {
  if (!maintainersList) {
    loadMaintainers();
    return html`<div class="more-matches"><div class="other-label">Looking up maintainers…</div></div>`;
  }
  const typed = query.trim().slice(1).toLowerCase();
  const { found, total } = maintainerMatches(maintainersList, query, 20);
  // On the overview (typing in its box), the handle itself too: nothing
  // else shows it yet.
  const others =
    shownView === 'overview' ? found : found.filter(([handle]) => handle.toLowerCase() !== typed);
  if (!others.length) return '';
  return html`<div class="more-matches">
    <div class="other-label">${typed && total > others.length ? 'Other maintainers' : 'Maintainers'} matching @${typed}${total > found.length ? html`, the first ${found.length}` : ''}</div>
    <ul class="maint-list">${others.map(maintainerItem)}</ul>
  </div>`;
}

// One maintainer: their handle (opening their packages) and counts.
function maintainerItem([handle, count, outdated, failing]) {
  return html`<li><a class="files-link" href="${maintainerHref(handle)}" data-maintainer="${handle}">@${handle}</a><span class="maint-n">${fmt(count)} ${count === 1 ? 'package' : 'packages'}${outdated ? html` · <span class="warn-text">${fmt(outdated)} outdated</span>` : ''}${failing ? html` · <span class="danger-text">${fmt(failing)} failing</span>` : ''}</span></li>`;
}
function maintainerHref(handle) {
  const params = new URLSearchParams(new URL(scopeHref({}), location.href).search);
  params.set('maintainer', handle);
  return `${location.pathname}?${params.toString()}`;
}

// ?view=maintainers: every maintainer, by handle, a page at a time; the
// search narrows them (an @ in front or not).
function maintainersHtml() {
  if (!maintainersList) return html`<div class="empty">Loading the maintainers…</div>`;
  const query = document.getElementById('search').value.trim();
  const list = query ? maintainerMatches(maintainersList, query, Infinity).found : maintainersList;
  if (!list.length) return html`<div class="empty">No maintainer matches “${query}”.</div>`;
  const pages = Math.max(1, Math.ceil(list.length / pageSize));
  pageNum = Math.min(pageNum, pages);
  const page = list.slice((pageNum - 1) * pageSize, pageNum * pageSize);
  return html`<ul class="maint-list maint-page">${page.map(maintainerItem)}</ul>${pagerHtml(list.length, pages)}`;
}

function moreMatchesHtml() {
  const query = document.getElementById('search').value;
  if (community && !pkgParam && shownView !== 'maintainers' && /^@\S/.test(query.trim()))
    return maintainerMatchesHtml(query);
  if (!community || pkgParam || query.trim().length < 2 || query.trim().startsWith('@')) return '';
  if (!names) {
    loadNames();
    return html`<div class="more-matches"><div class="other-label">Searching all of nixpkgs…</div></div>`;
  }
  // Another search, or other filters: from the first ones again.
  const asked = [query.trim(), inFilter, statusFilter, byFilter, matchTeam, platformFilter].join(
    '\n',
  );
  if (asked !== matchQuery) {
    matchQuery = asked;
    matchLimit = MATCHES_SHOWN;
  }
  const { found: all, total } = nameMatches(
    names,
    query,
    new Set(packages.map((p) => p.name)),
    Infinity,
  );
  if (!total) return '';
  const narrowed = inFilter || statusFilter || byFilter || matchTeam || platformFilter;
  if (total > 1 || narrowed) loadFacets();
  const { kept, sets, statuses, by, teams, platforms } = matchFacets(
    all,
    {
      set: inFilter,
      status: statusFilter,
      by: byFilter,
      team: matchTeam,
      platform: platformFilter,
    },
    facetIndex ? facetsOf : null,
  );
  const shownHere = kept.slice(0, matchLimit);
  const setLabel = (v) => (v === TOP_LEVEL ? 'top level' : v);
  // python3Packages (an alias, ?in=): offered with its sets' counts together.
  const aliasCount = (v) => sets.filter(([s]) => inPickedSet(s, v)).reduce((n, [, c]) => n + c, 0);
  const setChoices =
    inFilter && !sets.some(([v]) => v === inFilter)
      ? [...sets, [inFilter, aliasCount(inFilter)]]
      : sets;
  const statusChoices =
    statusFilter && !statuses.some(([v]) => v === statusFilter)
      ? [...statuses, [statusFilter, 0]]
      : statuses;
  return html`<div class="more-matches">
    <div class="other-label">${total.toLocaleString()} ${shownView === 'overview' ? '' : 'more '}${total === 1 ? 'package matches' : 'packages match'} in all of nixpkgs${narrowed ? html`, ${kept.length.toLocaleString()} with these filters` : ''}</div>
    ${
      // Shown whenever one is picked, even for one match: else a filter
      // from an earlier search would hide it, with no way to undo it.
      total > 1 || narrowed
        ? html`<div class="refine match-filters" role="group" aria-label="Narrow the matches"><label class="refine-age" title="Only one package set, by the attribute's first part (python313Packages, vimPlugins), or the top-level packages: the list above too. Each with how many match.">In <select data-in><option value="">any set</option>${setChoices.map(
            ([v, n]) => facetOption(v, setLabel(v), n, inFilter),
          )}</select></label><label class="refine-age" title="Only the matches with this status, as their dot says. Each with how many match.">Status <select data-status><option value="">any status</option>${statusChoices.map(
            ([v, n]) => facetOption(v, NAME_STATUSES[v], n, statusFilter),
          )}</select></label>${facetIndex ? matchFacetsHtml(by, teams, platforms) : ''}${
            narrowed
              ? html`<button type="button" class="refine-btn" data-clear-matches title="Back to every match: any set, status, maintainer, team and platform">Clear filters</button>`
              : ''
          }</div>`
        : ''
    }
    <ul>${shownHere.map(
      ([name, letter, set]) =>
        html`<li><span class="status-dot ${NAME_DOTS[letter[0]] || 'neutral'}" role="img" aria-label="${DOT_TITLE[NAME_DOTS[letter[0]] || 'neutral'] || ''}"></span><a class="files-link mono" href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}">${name}</a>${set ? html` ${bulkBadge(set)}` : ''}${letter.endsWith('v') ? html` <span class="badge vuln">vulnerable</span>` : ''}</li>`,
    )}</ul>
    ${
      kept.length > shownHere.length
        ? html`<button type="button" class="more-btn more-matches-btn" data-more-matches>Show ${Math.min(MATCHES_MORE, kept.length - shownHere.length).toLocaleString()} more (${shownHere.length.toLocaleString()} of ${kept.length.toLocaleString()} shown)</button>`
        : ''
    }
  </div>`;
}

// The matches' filters from facets.json: by a maintainer (the BY_SHOWN with
// the most matches offered), a team, a platform; each with its count.
function matchFacetsHtml(by, teams, platforms) {
  const teamChoices =
    matchTeam && !teams.some(([t]) => t === matchTeam) ? [...teams, [matchTeam, 0]] : teams;
  return html`<label class="refine-age" title="Only the matches this maintainer is listed for (meta.maintainers): type a GitHub handle; those with the most matches are offered, each with how many. The list above too.">By <input type="search" class="by-pick" data-by list="matchByOptions" placeholder="any maintainer" value="${byFilter || ''}" autocomplete="off" spellcheck="false"><datalist id="matchByOptions">${by
    .slice(0, BY_SHOWN)
    .map(([h, n]) => html`<option value="${h}">${fmt(n)}</option>`)}</datalist></label>${
    teamChoices.length
      ? html`<label class="refine-age" title="Only the matches of this nixpkgs team (meta.teams). Each with how many match.">Team <select data-match-team><option value="">any team</option>${teamChoices.map(
          ([t, n]) => facetOption(t, t, n, matchTeam),
        )}</select></label>`
      : ''
  }<label class="refine-age" title="Only the matches available there (meta.platforms). Darwin is macOS. Each with how many match. The list above too.">On <select data-platform-pick><option value="">any platform</option>${Object.entries(
    PLATFORMS,
  ).map(([key, p]) =>
    facetOption(key, p.label, platforms[key] ?? 0, platformFilter),
  )}</select></label>`;
}

// One panel under the row, showing the package details (clicking the row),
// its builds or its latest update attempt (clicking those cells). Clicking
// what's shown closes it; clicking something else switches. Each row opens
// and closes on its own, several at once (they used to close the others);
// "Close all" beside the list's count, or Esc, closes them all.
function closeRows(rows) {
  for (const tr of rows) {
    tr.classList.remove('open');
    const detail = tr.nextElementSibling;
    if (detail?.classList.contains('detail')) {
      detail.classList.remove('open');
      detail.dataset.mode = '';
    }
    for (const btn of tr.querySelectorAll('.failure-btn')) {
      btn.setAttribute('aria-expanded', 'false');
    }
  }
  syncCloseAll();
}
const openRows = () => [...document.querySelectorAll('tbody tr.row.open')];

// "Close all (3)" beside the list's count, while two or more are open.
function syncCloseAll() {
  const btn = document.querySelector('button.close-all');
  if (!btn) return;
  const n = openRows().length;
  btn.hidden = n < 2;
  btn.textContent = `Close all (${fmt(n)})`;
}

async function toggle(tr, mode) {
  const pkg = shown[tr.dataset.i];
  let detail = tr.nextElementSibling;
  if (!detail?.classList.contains('detail')) {
    detail = document.createElement('tr');
    detail.className = 'detail';
    detail.innerHTML = `<td colspan="6"><div class="detail-inner">
      <div class="nix-line">Loading detail…</div>
    </div></td>`;
    tr.after(detail);
  }
  const inner = detail.querySelector('.detail-inner');
  const closing = tr.classList.contains('open') && detail.dataset.mode === mode;
  tr.classList.toggle('open', !closing);
  detail.classList.toggle('open', !closing);
  detail.dataset.mode = closing ? '' : mode;
  for (const btn of tr.querySelectorAll('.failure-btn')) {
    btn.setAttribute('aria-expanded', !closing && btn.dataset.kind === mode);
  }
  syncCloseAll();
  if (closing) return;
  // The panel needs the full row (the list has the summary's entry).
  const row = await fullRow(pkg);
  const entries = row && mode === 'info' ? row.repology || [] : null;
  if (detail.dataset.mode !== mode) return; // switched or closed meanwhile
  if (!row) {
    inner.innerHTML = html`<div class="nix-line">Couldn't load this package's details. Open it again to retry.</div>`;
  } else if (mode === 'build') fillBuilds(row, inner);
  else if (mode === 'update') fillUpdate(row, inner);
  else fillDetail(row, inner, entries);
}

// A row's full data (its shard) starts loading when the pointer rests on
// the row or keyboard focus reaches it, so a panel opens without waiting:
// a shard's first request at a Cloudflare edge that doesn't have it yet
// takes 0.3-0.6 s, most of a first open (measured 2026-10-07). A short
// rest, not every row the pointer crosses, so sweeping over the list
// doesn't load them all. fullRow keeps one request per shard: the click
// then waits for the same one.
const PRELOAD_AFTER_MS = 100;
let preloadTimer = null;
let preloadRow = null; // the row it's waiting on: moving within it changes nothing
function preload(tr, delay) {
  if (tr === preloadRow) return;
  clearTimeout(preloadTimer);
  preloadRow = tr;
  const pkg = tr && shown[tr.dataset.i];
  if (pkg) preloadTimer = setTimeout(() => fullRow(pkg), delay);
}
const table = document.getElementById('content');
table.addEventListener('pointerover', (e) => {
  if (e.pointerType === 'mouse' || e.pointerType === 'pen') {
    preload(e.target.closest('tbody tr.row'), PRELOAD_AFTER_MS);
  }
});
table.addEventListener('pointerleave', () => preload(null, 0));
table.addEventListener('focusin', (e) => preload(e.target.closest('tbody tr.row'), 0));

// The table's clicks, for every row: a link opens (and nothing else), the
// versions copy the update's title, a platform filters by it, the build and
// update cells open their panel, and anywhere else the details.
document.getElementById('content').addEventListener('click', (e) => {
  // A page link: that page, from its top (a click with a modifier opens it
  // elsewhere, as links do).
  const pageLink = e.target.closest('a.page-btn');
  if (pageLink && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button)) {
    e.preventDefault();
    pageNum = Number(pageLink.dataset.page);
    // Back to the table's top, the keyboard on its first row, once drawn.
    update({ keepPage: true }).then(() => {
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
    toggle(tr, 'info');
    return;
  }
  if (!tr || e.target.closest('a')) return;
  const copy = e.target.closest('.vcopy');
  if (copy) {
    copyTitle(copy);
    return;
  }
  const fold = e.target.closest('button.fold-btn');
  if (fold) {
    // Shown or folded again, the keyboard back on the same button.
    const key = fold.dataset.fold;
    if (openFolds.has(key)) openFolds.delete(key);
    else openFolds.add(key);
    update({ keepPage: true }).then(() =>
      [...document.querySelectorAll('button.fold-btn')]
        .find((b) => b.dataset.fold === key)
        ?.focus(),
    );
    return;
  }
  const plat = e.target.closest('button.plat');
  if (plat) {
    // Clicking the active platform again shows all platforms.
    platformFilter = platformFilter === plat.dataset.platform ? null : plat.dataset.platform;
    update();
    return;
  }
  // A cell's button or the "queued" badge: its panel; anywhere else, the
  // package's details.
  toggle(tr, e.target.closest('[data-kind]')?.dataset.kind || 'info');
});
document.getElementById('content').addEventListener('keydown', (e) => {
  if (e.target.matches('tr.row') && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    e.target.click();
  }
});

// A source the last sync couldn't refresh ("builds", "update", "upstream"):
// what's shown is from before `since`. null if it refreshed fine.
const notRefreshed = (pkg, source) => pkg.notRefreshed?.[source] || null;
const staleText = (info, what) =>
  `${what} since ${longDate(info.since)} (${daysText(info.since)}): ${info.reason}`;
// The vulnerable badge: "insecure" when nixpkgs' mark is all there is, else
// "vulnerable", coloured by the worst severity known, who says so on hover.
function vulnBadge(pkg) {
  if (!isVulnerable(pkg)) return '';
  const sources = vulnSources(pkg);
  const insecureOnly = sources.length === 1 && pkg.markedInsecure?.length;
  const found = vulnSummary(pkg);
  const severity = found?.severity;
  const n = found?.n;
  const title = insecureOnly
    ? `nixpkgs marks it insecure: ${pkg.markedInsecure.join(' · ')}`
    : `Vulnerable, says ${sources.join(', ')}${n ? `: ${n} ${n === 1 ? 'CVE or advisory' : 'CVEs or advisories'}` : ''}${severity ? ` (worst: ${severity})` : ''}`;
  return html`<span class="badge vuln${severity ? ` sev-${severity}` : ''}" title="${title}">${insecureOnly ? 'insecure' : 'vulnerable'}</span>`;
}

// What each verdict on a CVE or advisory says (nixkeeper-vulnerabilities,
// sources/vulnerabilities_digest.py); those in VULN_COUNTED count. Each:
// [a word or two for the line, the sentence its hover says].
const VERDICTS = {
  affected: ['affected', "Affected: nixpkgs' version is in the CVE's range"],
  byVersion: ['affected', "Affected: nixpkgs' version is in the CVE's range"], // data from before
  tracker: ['affected', "Affected, says the security tracker (the CVE's versions can't be read)"],
  wontFix: ["won't fix", "The security team won't fix it"],
  osv: ['OSV advisory', "An OSV advisory that lists nixpkgs' version"],
  unconfirmed: ['unconfirmed', "Unconfirmed: the CVE's versions can't be read"],
  fixed: ['fixed', "Fixed in nixpkgs' version"],
  patched: ['patched', 'Fixed by a patch in nixpkgs, named after it'],
  dismissed: ['dismissed', 'Dismissed by the security team'],
};

// The panel's CVEs and advisories (the row's "vulnerabilities"), counted
// ones first, worst first; the others folded. What the counted ones share
// is said once, above them: how many of each severity, the verdict and the
// release branches still affected (a fix to backport), when the same for
// all. Then they're grouped by the tracker's issue (its nixpkgs issue
// linked once), a line each: the id, its severity and its summary (cut
// short, whole on hover), and what it doesn't share. The worst VULNS_SHOWN,
// then "Show all": zitadel's 24 took 48 lines, most of them repeating
// (2026-10-23).
const VULNS_SHOWN = 5;
function vulnSection(pkg) {
  const all = pkg.vulnerabilities || [];
  if (!all.length) return '';
  const link = (id) =>
    id.startsWith('CVE-')
      ? `https://nvd.nist.gov/vuln/detail/${encodeURIComponent(id)}`
      : `https://osv.dev/vulnerability/${encodeURIComponent(id)}`;
  const stillAffected = (v) =>
    Object.entries(v.releases || {})
      .filter(([, status]) => status === 'affected')
      .map(([branch]) => branch.replace(/^release-/, ''))
      .join(', ');
  const verdict = (v) =>
    VERDICTS[v.verdict]
      ? html`<span class="vl-verdict" title="${VERDICTS[v.verdict][1]}">${VERDICTS[v.verdict][0]}<span class="sr-only">: ${VERDICTS[v.verdict][1]}</span></span>`
      : html`<span class="vl-verdict">${v.verdict}</span>`;
  const issueLink = (v) =>
    html`<a class="files-link mono" href="https://tracker.security.nixos.org/issues/${encodeURIComponent(v.issue)}" target="_blank" rel="noopener">${v.issue}</a>${v.github && safeUrl(v.github) ? html` (<a class="files-link" href="${safeUrl(v.github)}" target="_blank" rel="noopener">its nixpkgs issue</a>)` : ''}`;
  // One line: its id, severity and summary; and, when they aren't said
  // above (own: false), its verdict, its issue and the branches still affected.
  const line = (
    v,
    { sharedVerdict = false, sharedReleases = false, own = true } = {},
    hidden = false,
  ) => {
    const releases = stillAffected(v);
    return html`<li class="vl"${hidden ? raw(' hidden') : ''}><a class="files-link mono" href="${link(v.id)}" target="_blank" rel="noopener">${v.id}</a>${
      v.severity ? html` <span class="sev sev-${v.severity}">${v.severity}</span>` : ''
    }${sharedVerdict ? '' : html` ${verdict(v)}`}${v.summary ? html` <span class="vl-summary" title="${v.summary}">${v.summary}</span>` : ''}${
      own && v.issue ? html`<span>· ${issueLink(v)}</span>` : ''
    }${!sharedReleases && releases ? html`<span>· <span class="vl-backport">still affected on ${releases}</span></span>` : ''}</li>`;
  };
  const counted = all.filter((v) => VULN_COUNTED.includes(v.verdict));
  const rest = all.filter((v) => !VULN_COUNTED.includes(v.verdict));
  // What they all share, said once.
  const verdicts = new Set(counted.map((v) => v.verdict));
  const sharedVerdict = counted.length > 1 && verdicts.size === 1;
  const releaseSets = new Set(counted.map(stillAffected));
  const sharedReleases = counted.length > 1 && releaseSets.size === 1;
  const word = counted.every((v) => v.id.startsWith('CVE-')) ? 'CVE' : 'advisory';
  const severities = ['critical', 'high', 'medium', 'low']
    .map((sev) => [sev, counted.filter((v) => v.severity === sev).length])
    .filter(([, n]) => n);
  const head =
    counted.length > 1
      ? html`<p class="vl-head">${fmt(counted.length)} ${word === 'CVE' ? 'CVEs' : 'advisories'}${
          severities.length
            ? html`: ${severities.map(([sev, n], i) => html`${i ? ', ' : ''}${fmt(n)} <span class="sev sev-${sev}">${sev}</span>`)}`
            : ''
        }${sharedVerdict ? html` · all ${verdict(counted[0])}` : ''}${
          sharedReleases && [...releaseSets][0]
            ? html` · <span class="vl-backport">still affected on ${[...releaseSets][0]}</span>`
            : ''
        }</p>`
      : '';
  // Grouped by the tracker's issue, in the order of their worst.
  const groups = new Map();
  for (const v of counted) groups.set(v.issue || '', [...(groups.get(v.issue || '') || []), v]);
  let shownSoFar = 0;
  const grouped = [...groups.values()].map((vs) => {
    const first = shownSoFar;
    shownSoFar += vs.length;
    const hideGroup = first >= VULNS_SHOWN;
    const opts = { sharedVerdict, sharedReleases, own: !vs[0].issue || vs.length === 1 };
    return html`<div class="vl-group"${hideGroup ? raw(' hidden') : ''}>${
      vs[0].issue && vs.length > 1
        ? html`<p class="vl-issue">${issueLink(vs[0])} · ${fmt(vs.length)} ${word === 'CVE' ? 'CVEs' : 'advisories'}</p>`
        : ''
    }<ul class="vl-list">${vs.map((v, i) => line(v, opts, first + i >= VULNS_SHOWN))}</ul></div>`;
  });
  const more =
    counted.length > VULNS_SHOWN
      ? html`<button type="button" class="more-btn vl-more" aria-expanded="false" data-all="${counted.length}">Show all ${fmt(counted.length)}</button>`
      : '';
  // Its open update PR, here rather than as a pill under On GitHub: whether
  // its version fixes them is for a person to check (the tracker gives no
  // fixed version).
  const pr = pkg.openPR?.facts?.vulnerable && counted.length ? pkg.openPR : null;
  return html`<section class="pd-sec vl-sec"><h4 class="other-label">Vulnerabilities</h4>${
    counted.length ? html`${head}${grouped}${more}` : html`<p class="pd-text">None counted.</p>`
  }${
    pr
      ? html`<p class="pd-text vl-pr"><a class="files-link gh-item pr" href="${safeUrl(pr.url)}" target="_blank" rel="noopener">${GH_ICONS.pr}<span class="sr-only">PR </span>#${pr.number} ↗</a> updates it to <span class="mono">${pr.to}</span>: check whether that fixes ${counted.length === 1 ? 'it' : 'them'}, and review it first</p>`
      : ''
  }${
    rest.length
      ? html`<details class="vl-rest"><summary>${rest.length} not counted (fixed, unconfirmed or dismissed)</summary><ul class="vl-list">${rest.map((v) => line(v))}</ul></details>`
      : ''
  }</section>`;
}

// CVEs fixed on master but still affected on the newest release branch
// ("backport", from the sync): a fix to backport.
function backportNote(pkg) {
  if (!pkg.backport?.length) return '';
  const entry = (id) => (pkg.vulnerabilities || []).find((v) => v.id === id) || {};
  const releases = [
    ...new Set(
      pkg.backport.flatMap((id) =>
        Object.entries(entry(id).releases || {})
          .filter(([, status]) => status === 'affected')
          .map(([branch]) => branch.replace(/^release-/, '')),
      ),
    ),
  ];
  return html`<div class="master-note">A fix to backport: ${pkg.backport.map(
    (id, i) => html`${i ? ', ' : ''}<span class="mono">${id}</span>`,
  )} ${pkg.backport.length === 1 ? 'is' : 'are'} fixed on nixpkgs master, still affected on ${releases.join(', ') || 'the newest release'}.</div>`;
}

// nixpkgs marks it insecure (meta.knownVulnerabilities): its reasons, with
// their CVE ids linked to NVD.
function insecureNote(pkg) {
  if (!pkg.markedInsecure?.length) return '';
  const reason = (text) =>
    cvePieces(text).map((p) =>
      p.cve
        ? html`<a class="files-link mono" href="https://nvd.nist.gov/vuln/detail/${p.cve}" target="_blank" rel="noopener">${p.cve}</a>`
        : p.text,
    );
  return html`<div class="vuln-note">⚠ nixpkgs marks it insecure: it won't build unless allowed (<span class="mono">permittedInsecurePackages</span>).<ul class="vuln-reasons">${pkg.markedInsecure.map((r) => html`<li>${reason(r)}</li>`)}</ul></div>`;
}

// The same, as a line at the top of a panel.
const staleNote = (info, what, after) =>
  info ? html`<div class="stale-note">⚠ ${staleText(info, what)}. ${after}</div>` : '';

// quiet: nothing that needs attention, so it's drawn muted, without a dot
// ("none reported" as a dash), and the phone layout leaves it out. Only
// what needs a look keeps its colour.
// mark: in place of the dot (a build's hard hat, the bot's robot), when
// given; marked: what it says that the text doesn't, for screen readers
// ("queued for an update").
function failureButton(
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

// Whether Hydra built this at all: not for unfree packages, nor ones nixpkgs
// keeps off Hydra (hydraPlatforms).
function hydraBuildsIt(pkg) {
  return !pkg.unfree && pkg.builds.some((b) => b.status !== 'notBuilt');
}

function buildCell(pkg) {
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
    const [why, ...more] = buildFailedBecause(pkg, platformFilter);
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
function updateCell(pkg) {
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
function queuedOrDash(pkg, why) {
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

// Why the bot's attempt failed ("failedBecause"), as the log says: short in
// the list, said in full in the panel. None recognised: "other".
const FAILED_BECAUSE = {
  unavailable: {
    short: 'unavailable',
    text: "nixpkgs won't build it where the bot builds (x86_64-linux): it or a dependency is broken, insecure or not for that platform",
  },
  patch: {
    short: 'patch',
    text: "nixpkgs' changes to the source (patches, substitutions) don't apply to the new version",
  },
  dependency: {
    short: 'dependency',
    text: "the new version needs a dependency nixpkgs doesn't give it: missing, or too old",
  },
  hash: {
    short: 'hash',
    text: "the bot couldn't work out a hash: of vendored dependencies, mostly, which failed to fetch or build",
  },
  source: { short: 'source', text: "the new version's source couldn't be fetched" },
  // restates: its text only says the pill again ("Failed: updateScript"),
  // so the panel leaves it out (the log lines say the rest).
  updateScript: {
    short: 'updateScript',
    text: "the package's updateScript failed",
    restates: true,
  },
  tests: { short: 'tests', text: 'the new version built, but its tests failed' },
  noLog: { short: 'build', text: 'the build failed, and nix kept no log of why' },
  build: { short: 'build', text: 'the new version failed to build', restates: true },
  request: {
    short: 'request',
    text: "a request of the bot's failed (to GitHub, mostly), not the package",
  },
  // The bot's own machine (its build users, its nix daemon): not the
  // package. Worth telling nixpkgs-update's maintainers while it's recent
  // (REPORT_DAYS); an older one was a past outage, fixed since (2026-09-28:
  // four hours, 1,306 attempts), which the bot's next round clears.
  bot: {
    short: 'bot',
    text: "the bot's machine failed (its build users group, or its nix daemon), not the package",
    report: true,
  },
};

// Why a build failed on Hydra (nixkeeper-hydra's reasons, from its log): a
// word for the filter, a sentence for the panel.
const BUILD_FAILED = {
  compile: { short: 'compile error', text: 'the compiler stopped at an error in the source' },
  tests: { short: 'tests', text: 'it built, but its tests failed' },
  link: {
    short: 'link error',
    text: "linking failed: a symbol or library the linker couldn't find",
  },
  header: { short: 'missing header', text: "a header the compiler couldn't find" },
  cmake4: {
    short: 'CMake 4',
    text: 'CMake 4 refuses projects asking for CMake older than 3.5 (cmake_minimum_required)',
  },
  cmake: { short: 'CMake', text: 'CMake failed to configure it' },
  boost: { short: 'Boost 1.89', text: "CMake couldn't use Boost 1.89" },
  pythonImport: { short: 'Python import', text: "a Python module it imports isn't there" },
  pythonDeps: {
    short: 'Python dependencies',
    text: "a Python dependency is missing, or its version isn't one the package accepts",
  },
  pythonBuild: { short: 'Python build', text: 'the Python build backend or setup failed' },
  pythonMetadata: {
    short: 'Python metadata',
    text: "the package's metadata doesn't match nixpkgs' (its version or name)",
  },
  haskellDeps: {
    short: 'Haskell dependencies',
    text: 'a Haskell dependency is missing, or the wrong version',
  },
  npm: { short: 'npm', text: "npm couldn't install its dependencies" },
  lisp: { short: 'Lisp', text: 'the Lisp build (SBCL) failed' },
  home: {
    short: 'writes to $HOME',
    text: "it writes to the home directory, which builds don't have",
  },
  download: { short: 'download', text: "a source couldn't be downloaded from any mirror" },
  hash: {
    short: 'hash',
    text: "a download's hash isn't the one nixpkgs expects: the source changed",
  },
  patch: { short: 'patch', text: "one of nixpkgs' patches no longer applies" },
  substitute: {
    short: 'substitute',
    text: 'a text substitution in nixpkgs no longer finds what it replaces',
  },
  missingFile: { short: 'missing file', text: 'a file the build expects is missing' },
  symlinks: { short: 'broken symlinks', text: 'it installs symlinks that point nowhere' },
  patchelf: {
    short: 'missing libraries',
    text: "autoPatchelf couldn't find libraries the binaries need",
  },
  autotools: { short: 'autotools', text: 'aclocal failed: an autotools dependency is missing' },
  disk: {
    short: 'out of disk',
    text: "Hydra's builder ran out of disk space: not the package",
    infra: true,
  },
  other: { short: 'other', text: 'none of the known reasons' },
  noLog: { short: 'no log', text: 'Hydra has no log of it' },
  unread: { short: 'not read yet', text: "nixkeeper-hydra hasn't read its log yet" },
};

// How recent a "bot" failure is worth reporting (its panel's note).
const REPORT_DAYS = 3;
const DAY_MS = 86400e3;

const prLink = (n, text) =>
  html`<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${n}" target="_blank" rel="noopener">${text}</a>`;
// Each outcome: its colour, its pill in the panel (`label`), and what it
// means (`text`).
const UPDATE_OUTCOME = {
  failed: {
    dot: 'missing',
    label: (u) =>
      `Failed${FAILED_BECAUSE[u.failedBecause] ? `: ${FAILED_BECAUSE[u.failedBecause].short}` : ''}`,
    text: (u) => {
      const because = FAILED_BECAUSE[u.failedBecause];
      return because ? `failed: ${because.text}` : 'failed';
    },
  },
  // nixpkgs has moved on since the attempt (updated another way): in the
  // channel, or merged on master and not in the channel yet. Or a rule
  // ignores the version it tried: your own (package-lists/ignored-updates.nix)
  // or a community one (community/ignored-updates.nix).
  superseded: {
    dot: 'neutral',
    label: () => 'Superseded',
    text: (u, pkg) => {
      const what = u.supersededOutcome === 'cantUpdate' ? "couldn't update it" : 'failed';
      const version = u.to === '1' ? pkg.nixVersion : u.to;
      return u.supersededOn === 'ignored'
        ? html`failed trying <span class="mono">${version}</span>, a version ignored by ${u.community ? 'a community rule' : 'a manual rule'}: ${u.reason}`
        : u.supersededOn === 'master'
          ? html`${what}, but master already has <span class="mono">${onMaster(pkg)}</span> (merged, waiting for nixos-unstable)`
          : html`${what}, but nixpkgs has moved on to <span class="mono">${pkg.nixVersion}</span> since`;
    },
  },
  // Every way the bot has of updating a package declined (the excerpt says
  // why): the update needs doing by hand, or an updateScript.
  cantUpdate: {
    dot: 'caution',
    label: () => "Can't update",
    text: () =>
      "couldn't update it: none of the bot's ways of updating a package apply here. Update it by hand, or give the package an updateScript so the bot can next time",
  },
  prOpened: {
    dot: 'ok',
    label: () => 'PR opened',
    text: (u) => html`opened ${prLink(u.pr, `PR #${u.pr} ↗`)}`,
  },
  prExists: {
    dot: 'ok',
    label: () => 'PR open',
    text: (u) => html`a PR was already open${u.pr ? html` (${prLink(u.pr, `#${u.pr} ↗`)})` : ''}`,
  },
  // The update's already on its way: the bot pushed it to its branch, and
  // its PR is open or will be.
  branchExists: {
    dot: 'ok',
    label: () => 'On its way',
    text: () =>
      'already done: the bot pushed this update to its branch, and its PR is open or on its way',
  },
  noChange: { dot: 'ok', label: () => 'Nothing to update', text: () => 'nothing to update' },
  // Its skiplist or the package itself says not to: the excerpt says why.
  skipped: {
    dot: 'neutral',
    label: () => 'Skipped',
    text: () => 'skipped on purpose: the bot passes this package over, for the reason below',
  },
  other: {
    dot: 'neutral',
    label: () => 'Unclear',
    text: () => 'finished without a recognisable result',
  },
};

// When the bot will try the package again, from its queue (the row's
// "queued"), and what it would update it to: a version it found that
// nixpkgs doesn't have (from a GitHub release, say), which doesn't make the
// package outdated here, the bot's picking can be wrong. Not in the queue:
// it sees nothing to update to. Nothing without the queue.
function queueHtml(pkg) {
  if (!sources?.queue?.used) return '';
  const q = pkg.queued;
  const queueLink = html`<a class="files-link" href="https://nixpkgs-update-logs.nixos.org/~supervisor/queue.html" target="_blank" rel="noopener">queue ↗</a>`;
  if (!q) {
    return html`<section class="pd-sec"><h4 class="other-label">Next attempt</h4><p class="pd-text">Not in nixpkgs-update's ${queueLink}: it sees nothing to update this package to right now.</p></section>`;
  }
  const days = daysUntil(q.by);
  // Each version once, with where the bot found it (GitHub's releases,
  // Repology, ...).
  const byVersion = new Map();
  for (const [to, url] of q.candidates || []) {
    byVersion.set(to, [...(byVersion.get(to) || []), url]);
  }
  const where = (url) =>
    onHost(url, 'github.com')
      ? 'GitHub release'
      : onHost(url, 'repology.org')
        ? 'Repology'
        : 'its source';
  const candidates = [...byVersion].map(
    ([to, urls], i) =>
      html`${i ? ', ' : ''}<span class="mono">${to}</span> (${urls.map(
        (url, j) =>
          html`${j ? ' · ' : ''}${url ? html`<a class="files-link" href="${safeUrl(url)}" target="_blank" rel="noopener">${where(url)} ↗</a>` : where(url)}`,
      )})`,
  );
  const facts = [
    [
      'expected',
      days < 1
        ? 'within a day'
        : html`${longDate(`${q.by}T12:00:00Z`)} <span class="pd-ago">(in ${days === 1 ? 'a day' : `${days} days`})</span>`,
    ],
    candidates.length && ['would update to', candidates],
    ['from', queueLink],
  ].filter(Boolean);
  return html`<section class="pd-sec"><h4 class="other-label">Next attempt</h4><dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl></section>`;
}

function fillUpdate(pkg, el) {
  const u = pkg.update;
  const unread = pkg.unread?.includes('update')
    ? html`<div class="stale-note">Not read on the last sync: with every package, nixpkgs-update's attempts come from a digest of them, which hasn't read this package's yet.${u ? ' Showing the last attempt read.' : ''}</div>`
    : '';
  if (unread && !u) {
    el.innerHTML = html`${unread}<div class="pd">${queueHtml(pkg)}</div>`;
    return;
  }
  const stale = html`${unread}${staleNote(
    notRefreshed(pkg, 'update'),
    'Not refreshed',
    'Showing the last known attempt.',
  )}`;
  if (!u) {
    el.innerHTML = html`${stale}<div class="pd">
      <div class="pd-head"><span class="pd-verdict neutral">Not tried</span></div>
      <p class="pd-text">${
        pkg.set
          ? html`nixpkgs-update hasn't tried to update this package: ${bulkText(pkg.set).replace(/^K/, 'k')}.`
          : "nixpkgs-update hasn't tried to update this package (it may have no update source it understands)."
      }</p>
      ${queueHtml(pkg)}
    </div>`;
    return;
  }
  const dir = u.log.slice(0, u.log.lastIndexOf('/') + 1); // every attempt's log
  // A plain day: read as midday UTC, so no time zone moves it to the day before.
  const day = `${u.date}T12:00:00Z`;
  // "0 -> 1" means the package's updateScript picks the version.
  const versions = u.from && u.to && !(u.from === '0' && u.to === '1');
  const o = UPDATE_OUTCOME[u.outcome] || UPDATE_OUTCOME.other;
  const tone = { missing: 'danger', caution: 'caution', ok: 'ok' }[o.dot] || 'neutral';
  const facts = [
    ['attempted', html`${longDate(day)} <span class="pd-ago">(${shortAge(day)} ago)</span>`],
    versions && ['tried', html`<span class="mono">${u.from} → ${u.to}</span>`],
    (pkg.attrs || []).length > 1 && ['attribute', html`<span class="mono">${u.attr}</span>`],
  ].filter(Boolean);
  // The pill says "Failed: patch"; the sentence then only why.
  const because = u.outcome === 'failed' && FAILED_BECAUSE[u.failedBecause];
  const text = because
    ? because.text
    : u.outcome === 'failed'
      ? `the log doesn't say why in a way nixkeeper recognises${u.excerpt?.length ? '; its last lines are below' : ''}`
      : o.text(u, pkg);
  el.innerHTML = html`${stale}<div class="pd">
    <div class="pd-head">
      <span class="pd-verdict ${tone}">${o.label(u)}</span>
      <dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
    </div>
    ${
      because?.restates
        ? ''
        : html`<p class="pd-text">${String(text).charAt(0).toUpperCase()}${raw(String(text).slice(1))}.</p>`
    }${
      because?.report
        ? Date.now() - new Date(day).getTime() <= REPORT_DAYS * DAY_MS
          ? html`<p class="pd-text">Worth telling <a class="files-link" href="https://github.com/NixOS/nixpkgs-update/issues" target="_blank" rel="noopener">nixpkgs-update's maintainers ↗</a>, if no one has yet.</p>`
          : html`<p class="pd-text">A past problem of the bot's (on ${longDate(day)}): it will try again on its next round.</p>`
        : ''
    }
    ${
      u.excerpt?.length
        ? html`<section class="pd-sec"><h4 class="other-label">From the log</h4><pre class="log-excerpt mono">${u.excerpt.join('\n')}</pre></section>`
        : ''
    }
    ${queueHtml(pkg)}
    <div class="pd-links">
      <a class="pd-link" href="${safeUrl(u.log)}" target="_blank" rel="noopener">${icon('file-text')}Log</a>
      <a class="pd-link" href="${safeUrl(dir)}" target="_blank" rel="noopener">${icon('history')}All attempts</a>
    </div>
  </div>`;
}

const HYDRA = 'https://hydra.nixos.org';
const BUILD_STATUS = {
  ok: { dot: 'ok', text: 'built OK', short: 'built' },
  failed: { dot: 'missing', text: 'failed', short: 'failed' },
  broken: { dot: 'caution', text: 'marked broken in nixpkgs', short: 'marked broken' },
  dependency: {
    dot: 'caution',
    text: "didn't build: a dependency failed",
    short: 'dependency failed',
  },
  unfinished: {
    dot: 'caution',
    text: "didn't finish (timed out or aborted)",
    short: "didn't finish",
  },
  notBuilt: { dot: 'neutral', text: 'not built by Hydra on this platform', short: 'not built' },
  unknown: { dot: 'neutral', text: "couldn't check Hydra on the last run", short: 'unknown' },
};

// Which dependency stopped a build (nixkeeper-hydra's blockedBy): its
// package, opening it (with every package), or the name Hydra gave it.
function blockedByHtml(blockers) {
  return html`blocked by ${blockers.map(
    ({ name, row }, i) =>
      html`${i ? ', ' : ''}${
        row && community
          ? html`<a class="files-link mono" href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}">${name}</a>`
          : html`<span class="mono">${name}</span>`
      }`,
  )} (its build failed)`;
}

// One system's build in the builds panel: where, its status, when it last
// built, and what to open (the log, the job, the build, the source).
// alike: how many builds fail as this one does, and whether this line shows
// their log's lines (the last of them: groupedBuilds); the others have their
// Log link instead.
function buildLine(pkg, b, alike = { n: 1, shows: true }) {
  const s = BUILD_STATUS[b.status] || BUILD_STATUS.unknown;
  const multi = (pkg.attrs || []).length > 1;
  // The versions only when they differ: the same version means something else
  // broke it (a dependency, the toolchain), not the update.
  const versionsDiffer = b.version && b.lastSuccessVersion && b.version !== b.lastSuccessVersion;
  const at =
    versionsDiffer && b.status === 'failed' ? html` at <span class="mono">${b.version}</span>` : '';
  let lastGood = '';
  if (versionsDiffer) {
    const v = b.lastSuccessVersion;
    lastGood = b.lastSuccessBuild
      ? html` at <a class="files-link mono" href="${HYDRA}/build/${b.lastSuccessBuild}" target="_blank" rel="noopener">${v}</a>`
      : html` at <span class="mono">${v}</span>`;
  }
  const since =
    'lastSuccess' in b
      ? b.lastSuccess
        ? html`last built${lastGood} <span title="${longDate(b.lastSuccess)}">${shortAge(b.lastSuccess)} ago</span>`
        : 'never built successfully'
      : '';
  // Why it failed, from its log (nixkeeper-hydra), and the lines that say so:
  // in the status badge itself ("failed: missing file", as the list's cell
  // says it), not beside it.
  const why = b.status === 'failed' && BUILD_FAILED[b.failedBecause];
  const what =
    b.status === 'dependency' && b.blockedBy?.length
      ? html`${blockedByHtml(b.blockedBy)}${since ? html` · ${since}` : ''}`
      : html`${at}${at && since ? ' · ' : ''}${since}`;
  const act = (href, name, label, title) =>
    html`<a class="pd-link" href="${href}" target="_blank" rel="noopener"${title ? html` title="${title}"` : ''}>${icon(name)}${label}</a>`;
  const excerpt = why && b.failedExcerpt && alike.shows;
  const acts = [
    // With the log's lines shown, their own link ("full log") instead.
    b.status === 'failed' && !excerpt && act(`${HYDRA}/build/${b.build}/log`, 'file-text', 'Log'),
    // A failed build's page too: every step, when the failure is in a
    // derivation built for it rather than the package's own step.
    ['failed', 'dependency', 'unfinished'].includes(b.status) &&
      b.build &&
      act(`${HYDRA}/build/${b.build}`, 'hammer', 'Build', `Hydra build ${b.build}`),
    b.status === 'broken' &&
      safeUrl(pkg.source) &&
      act(safeUrl(pkg.source), 'file-code', 'Source', 'Where nixpkgs marks it broken'),
    b.status !== 'notBuilt' &&
      act(
        `${HYDRA}/job/nixpkgs/unstable/${encodeURIComponent(`${b.attr}.${b.system}`)}`,
        'external-link',
        'Job',
        `Hydra job ${b.attr}.${b.system}: every build of it`,
      ),
  ].filter(Boolean);
  return html`<div class="br${alike.n > 1 && !alike.shows ? ' alike' : ''}">
    <span class="br-sys"><span class="mono">${b.system}</span>${multi ? html`<span class="mono br-attr">${b.attr}</span>` : ''}</span>
    <span class="br-st ${s.dot}" title="${why ? `${s.text}: ${why.text}` : s.text}">${why ? html`<span class="sr-only">${s.short}: </span>${why.short}` : s.short}</span>
    <span class="br-what">${what}</span>
    <span class="br-acts">${acts}</span>
    ${excerpt ? html`<div class="br-log-wrap"><pre class="br-log" title="From the build's log on Hydra">${b.failedExcerpt}</pre><span class="br-log-foot"><a class="files-link br-full-log" href="${HYDRA}/build/${b.build}/log" target="_blank" rel="noopener">full log ↗</a>${alike.n > 1 ? ` · the same on ${alike.n === 2 ? 'both' : `all ${alike.n}`}` : ''}</span></div>` : ''}
  </div>`;
}

// A failure's log lines as compared between builds: without what changes
// from one run to the next (pytest's timings, its "=" padding around them).
const sameFailure = (b) =>
  `${b.failedBecause}\n${(b.failedExcerpt || '')
    .replace(/ in [\d.]+s( \(\d+:\d\d:\d\d\))?/g, '')
    .replace(/=+/g, '=')
    .replace(/\s+/g, ' ')}`;

// The builds in their order, those failing alike (same reason, same log
// lines: python313Packages and python314Packages, on two platforms) brought
// together where the first of them is, each with its alike for buildLine:
// their lines shown once, under the last.
function groupedBuilds(builds) {
  const key = (b) => (b.status === 'failed' && b.failedExcerpt ? sameFailure(b) : null);
  const groups = new Map();
  for (const b of builds) if (key(b)) groups.set(key(b), [...(groups.get(key(b)) || []), b]);
  const out = [];
  for (const b of builds) {
    const k = key(b);
    if (!k) out.push([b, { n: 1, shows: true }]);
    else if (groups.get(k)[0] === b) {
      const all = groups.get(k);
      all.forEach((x, i) => {
        out.push([x, { n: all.length, shows: i === all.length - 1 }]);
      });
    }
  }
  return out;
}

function fillBuilds(pkg, el) {
  const stale = staleNote(
    notRefreshed(pkg, 'builds'),
    'Not refreshed',
    'Showing the last known results.',
  );
  // Why there's nothing to show: a verdict and a sentence, nothing more.
  const none = (label, text) =>
    html`<div class="pd"><div class="pd-head"><span class="pd-verdict neutral">${label}</span></div><p class="pd-text">${text}</p></div>`;
  if (pkg.unfree) {
    el.innerHTML = html`${stale}${none('Not built', "Hydra doesn't build unfree packages, so there are no build results for this one.")}`;
    return;
  }
  if (!hydraBuildsIt(pkg) && pkg.markedBroken) {
    el.innerHTML = html`${stale}${none('Marked broken', html`nixpkgs marks this package broken (<span class="mono">meta.broken</span>), so Hydra doesn't build it.${safeUrl(pkg.source) ? html` <a class="files-link" href="${safeUrl(pkg.source)}" target="_blank" rel="noopener">Source ↗</a>` : ''}`)}`;
    return;
  }
  if (!hydraBuildsIt(pkg)) {
    el.innerHTML = html`${stale}${none('Not built', html`Hydra doesn't build this package (nixpkgs may exclude it with <span class="mono">hydraPlatforms</span>).`)}`;
    return;
  }
  // Each platform's line says how it stands: no summary above them (a
  // count the lines show at a glance). Builds with nothing going on are
  // checked every few days, not daily (nixkeeper/sources/hydra.py): when
  // the oldest was, under them, if it isn't today.
  const checked = pkg.builds
    .map((b) => b.checkedAt)
    .filter(Boolean)
    .sort()[0];
  const age = checked && daysText(checked);
  el.innerHTML = html`${stale}<div class="pd">
    <div class="br-list">${groupedBuilds(pkg.builds).map(([b, alike]) => buildLine(pkg, b, alike))}</div>
    ${
      checked && age !== 'today'
        ? html`<p class="pd-foot" title="${new Date(checked).toLocaleString()}">Checked on Hydra ${age} ago.</p>`
        : ''
    }
  </div>`;
}

// From nixpkgs meta.platforms; null means nixpkgs doesn't restrict it.
// Linux and Darwin, and the one Linux system when it's on only one ("Linux
// x86_64": the exception named, the rule not).
function platformTags(pkg) {
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
    return html`<button class="plat${unbuilt ? ' unbuilt' : ''}" type="button" data-platform="${key}" aria-pressed="${platformFilter === key}"
      title="${said}. ${platformFilter === key ? 'Show all platforms' : `Click to show only packages available on ${p.label}`}">${short || p.label}${unbuilt ? html`<span class="sr-only"> (not built by Hydra)</span>` : ''}</button>`;
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
function githubLinks(pkg) {
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

// ", by @author, merged by @merger", each a link (either may be missing).
const whoDid = (author, mergedBy) => {
  const at = (who) =>
    html`<a class="files-link" href="https://github.com/${encodeURIComponent(who)}" target="_blank" rel="noopener">@${who}</a>`;
  return html`${author ? html`, by ${at(author)}` : ''}${mergedBy ? html`, merged by ${at(mergedBy)}` : ''}`;
};

// What nixkeeper-prs found of a package's PRs and issues (the daily sync's
// facts, nixkeeper/sources/prs_digest.py): its update PR's merge-bot
// eligibility, state, bot blocking and duplicates; open PRs touching it
// while its build fails on Hydra; and its issues checked against Hydra and
// nixpkgs now. Nothing when there's none.
// Each: [the pill's few words, the sentence its hover says].
const PR_STATES = {
  superseded: (now) => [`superseded (${now})`, `Superseded: nixpkgs has ${now} already`],
  overtaken: (now) => [
    `needs a rebase (${now})`,
    `Overtaken: nixpkgs moved to ${now}, a rebase is needed`,
  ],
  downgrade: () => ['a downgrade', 'It would downgrade the package'],
  snapshotToRelease: () => ['back to a release', 'From a snapshot back to a release'],
  preRelease: () => ['a pre-release', 'To a pre-release, by its version suffix'],
};
function githubSection(pkg) {
  // Each PR and issue with GitHub's icon for it: open, draft, merged, issue.
  const link = (item, kind = item.draft ? 'draft' : 'pr', who = '') =>
    html`<a class="files-link gh-item ${kind}" href="${safeUrl(item.url)}" target="_blank" rel="noopener"${who ? html` title="${who[0].toUpperCase()}${who.slice(1)}"` : ''}>${GH_ICONS[kind]}<span class="sr-only">${kind === 'issue' ? 'issue' : kind === 'merged' ? 'merged PR' : kind === 'draft' ? 'draft PR' : 'PR'} </span>#${item.number} ↗</a>`;
  // A pill of a few words; the sentence behind them on hover, and for
  // screen readers (they were whole sentences, in the pill, 2026-10-23).
  const fact = (kind, text, title) =>
    html`<span class="gh-fact ${kind}"${title ? html` title="${title}"` : ''}>${text}${title ? html`<span class="sr-only">: ${title}</span>` : ''}</span>`;
  const lines = [];
  // Marked broken with open PRs: one may fix it, or be moot now.
  if (pkg.markedBroken && pkg.openPRs > 0)
    lines.push(
      html`<li>${fact('warn', `broken · ${fmt(pkg.openPRs)} open PR${pkg.openPRs === 1 ? '' : 's'}`, `Marked broken, and ${pkg.openPRs === 1 ? 'an open PR touches' : `${fmt(pkg.openPRs)} open PRs touch`} it: one may fix it, or be moot while it stays broken; worth a look before reviewing it`)}</li>`,
    );
  const pr = pkg.openPR;
  const f = pr?.facts;
  if (f) {
    const said = [
      f.fixesBuild &&
        fact(
          '',
          'may fix the build',
          'It changes the package while its build fails on Hydra: maybe its fix',
        ),
      f.mergeBot === 'ready' &&
        fact(
          'ok',
          'merge-bot ready',
          'Ready for the merge bot: CI green, no conflict; a maintainer of the package can merge it by commenting @NixOS/nixpkgs-merge-bot merge',
        ),
      f.mergeBot === 'eligible' &&
        fact(
          '',
          'merge-bot eligible',
          'The merge bot could merge it once CI is green and any conflict is sorted out',
        ),
      f.state && fact('warn', ...(PR_STATES[f.state] || (() => [f.state]))(f.now || '?')),
      f.behind &&
        fact(
          'warn',
          `behind (${f.behind})`,
          `Behind: upstream has ${f.behind}. Merged as it is, the package would still be outdated: worth updating the PR first`,
        ),
      f.blocksBot &&
        fact(
          'warn',
          'blocks the bot',
          `Blocks the update bot${typeof f.blocksBot === 'string' ? ` (its next try ~${shortDay(f.blocksBot)})` : ''}: it has the very title nixpkgs-update would use, so the bot skips this update while it is open`,
        ),
      f.duplicates?.length &&
        html`<span class="gh-fact">also open: ${f.duplicates.map((n, i) => html`${i ? ' ' : ''}<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${n}" target="_blank" rel="noopener">#${n}</a>`)}</span>`,
    ].filter(Boolean);
    if (said.length)
      lines.push(html`<li>Update PR ${link(pr)} <span class="mono">${pr.to}</span>: ${said}</li>`);
  }
  // Open update PRs nixpkgs is already past (prs_digest.mark_superseded).
  for (const sp of pkg.supersededPRs || [])
    lines.push(
      html`<li>${link({ ...sp, url: `https://github.com/NixOS/nixpkgs/pull/${sp.number}` })} ${sp.title} ${fact('warn', `can be closed (${sp.now})`, `nixpkgs has ${sp.now}, this version or a newer one: the PR can be closed, or updated to the newest`)}</li>`,
    );
  // Its other open PRs, a removal first (prs_digest.add_facts).
  const KIND = {
    drop: (other) => {
      const attr = /^([\w.+-]+):/.exec(other.title)?.[1];
      const what = attr && attr.toLowerCase() !== pkg.name.toLowerCase() ? attr : 'it';
      // Only proposed (changes requested, or no activity for months): said
      // quietly, no "being removed" badge in the list.
      return other.proposed
        ? fact(
            '',
            'removal proposed',
            `This PR would remove ${what} from nixpkgs (${other.proposed}), but it doesn't look likely to be merged as it is`,
          )
        : fact('warn', 'removes it', `It removes ${what} from nixpkgs`);
    },
    init: () => fact('', 'adds it'),
    update: () => fact('', 'an update'),
  };
  for (const other of pkg.otherPRs || [])
    lines.push(
      html`<li>${link({ ...other, url: `https://github.com/NixOS/nixpkgs/pull/${other.number}` })} ${other.title} ${other.kind ? KIND[other.kind]?.(other) || '' : ''}${
        other.mergeBot === 'ready'
          ? fact('ok', 'merge-bot ready', 'Ready for the merge bot: CI green, no conflict')
          : other.mergeBot === 'eligible'
            ? fact('', 'merge-bot eligible')
            : ''
      }</li>`,
    );
  // A PR merged since its build began failing that touched it: likely the
  // fix, once Hydra builds it (prs_digest.build_fix_prs).
  const bf = pkg.buildFixPR;
  if (bf)
    lines.push(
      // Who wrote and merged it on the link's hover, not the line: the icon
      // says merged, and no other line here names people.
      html`<li>${link(bf, 'merged', [bf.author && `by @${bf.author}`, bf.mergedBy && `merged by @${bf.mergedBy}`].filter(Boolean).join(', '))} ${bf.title} ${fact('ok', 'likely fix', "Merged since its build began failing: likely its fix, which Hydra hasn't built yet (or the failure was elsewhere)")}</li>`,
    );
  for (const fix of pkg.fixPRs || [])
    lines.push(
      html`<li>${link(fix)} ${fix.title} ${fact('', 'may fix the build', 'It touches the package while its build fails on Hydra: maybe its fix')}</li>`,
    );
  const ISSUE = {
    builds: (c) =>
      c.condition
        ? fact(
            'warn',
            'builds now · check it',
            'It builds on Hydra now, but the title adds a condition to check',
          )
        : fact('ok', 'builds now · can close', 'It builds on Hydra now: a candidate to close'),
    failing: () => fact('', 'still failing', 'Still failing on Hydra'),
    done: (c) =>
      fact(
        'ok',
        `done${c.now ? ` (${c.now})` : ''} · can close`,
        `nixpkgs has ${c.now || 'it'}: a candidate to close`,
      ),
    partly: (c) =>
      fact(
        'warn',
        `partly done${c.now ? ` (${c.now})` : ''}`,
        `nixpkgs moved to ${c.now || 'a newer version'}, not to the one asked`,
      ),
    cveFixed: (c) =>
      fact(
        'ok',
        `CVE${c.cves?.length > 1 ? 's' : ''} fixed · can close`,
        `${(c.cves || []).join(', ')}: ${c.cves?.length > 1 ? "none affect nixpkgs' version" : "it doesn't affect nixpkgs' version"}, as nixkeeper reads the security tracker and OSV: a candidate to close. Check before closing`,
      ),
  };
  for (const c of pkg.issueChecks || [])
    lines.push(
      html`<li>${link(c, 'issue')} ${c.title} ${(ISSUE[c.verdict] || (() => c.verdict))(c)}</li>`,
    );
  return lines.length
    ? html`<section class="pd-sec"><h4 class="other-label">On GitHub</h4><ul class="gh-checks">${lines}</ul></section>`
    : '';
}

// A package's name, able to wrap after each dot (python313Packages. /
// requests) and at its hyphens, as a long one would otherwise widen the
// table past the screen for every row.
function breakableName(name) {
  return name.split('.').map((part, i) => (i ? html`.<wbr>${part}` : part));
}

// "…/pkgs/by-name/we/wesnoth/package.nix#L147" -> "package.nix"
function sourceFileName(url) {
  return url.split('#')[0].split('/').pop();
}

// Icons in the panels: Tabler Icons' outlines (MIT,
// https://tabler.io/icons, @tabler/icons 3.49.0), inline: no font to load.
const ICONS = {
  'chart-dots-3':
    '<path d="M3 7a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M14 15a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 6a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M3 18a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M9 17l5 -1.5"/><path d="M6.5 8.5l7.81 5.37"/><path d="M7 7l8 -1"/>',
  'chevron-down': '<path d="M6 9l6 6l6 -6"/>',
  'external-link':
    '<path d="M12 6h-6a2 2 0 0 0 -2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-6"/><path d="M11 13l9 -9"/><path d="M15 4h5v5"/>',
  'file-text':
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M9 9l1 0"/><path d="M9 13l6 0"/><path d="M9 17l6 0"/>',
  history: '<path d="M12 8l0 4l2 2"/><path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"/>',
  hammer:
    '<path d="M11.414 10l-7.383 7.418a2.091 2.091 0 0 0 0 2.967a2.11 2.11 0 0 0 2.976 0l7.407 -7.385"/><path d="M18.121 15.293l2.586 -2.586a1 1 0 0 0 0 -1.414l-7.586 -7.586a1 1 0 0 0 -1.414 0l-2.586 2.586a1 1 0 0 0 0 1.414l7.586 7.586a1 1 0 0 0 1.414 0"/>',
  'file-code':
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M10 13l-1 2l1 2"/><path d="M14 13l1 2l-1 2"/>',
  'git-branch':
    '<path d="M5 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M7 8l0 8"/><path d="M9 18h6a2 2 0 0 0 2 -2v-5"/><path d="M14 14l3 -3l3 3"/>',
  'git-merge':
    '<path d="M5 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 12a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M7 8l0 8"/><path d="M7 8a4 4 0 0 0 4 4h4"/>',
  home: '<path d="M5 12l-2 0l9 -9l9 9l-2 0"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7"/><path d="M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"/>',
  'list-check':
    '<path d="M3.5 5.5l1.5 1.5l2.5 -2.5"/><path d="M3.5 11.5l1.5 1.5l2.5 -2.5"/><path d="M3.5 17.5l1.5 1.5l2.5 -2.5"/><path d="M11 6l9 0"/><path d="M11 12l9 0"/><path d="M11 18l9 0"/>',
  package:
    '<path d="M12 3l8 4.5l0 9l-8 4.5l-8 -4.5l0 -9l8 -4.5"/><path d="M12 12l8 -4.5"/><path d="M12 12l0 9"/><path d="M12 12l-8 -4.5"/><path d="M16 5.25l-8 4.5"/>',
  tag: '<path d="M6.5 7.5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M3 6v5.172a2 2 0 0 0 .586 1.414l7.71 7.71a2.41 2.41 0 0 0 3.408 0l5.592 -5.592a2.41 2.41 0 0 0 0 -3.408l-7.71 -7.71a2 2 0 0 0 -1.414 -.586h-5.172a3 3 0 0 0 -3 3"/>',
  world:
    '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0"/><path d="M3.6 9h16.8"/><path d="M3.6 15h16.8"/><path d="M11.5 3a17 17 0 0 0 0 18"/><path d="M12.5 3a17 17 0 0 1 0 18"/>',
};
const icon = (name) =>
  raw(
    `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`,
  );
// entries: the row's Repology entries, or null if they couldn't be loaded
// (its shard).
function fillDetail(pkg, el, entries) {
  const loaded = Array.isArray(entries);

  const others = loaded ? comparedRepos(entries.filter((e) => e.repo !== NIX_REPO)) : [];
  // With every package, a row no list has keeps the newest repositories
  // only (nixkeeper/datastore.py, kept_entries): the rest are on Repology.
  const notKept =
    community && !pkg.lists?.length && pkg.repoCount > others.length
      ? pkg.repoCount - others.length
      : 0;
  const compared = others.length + notKept;
  // Repology is asked every few days for packages with nothing going on
  // (nixkeeper/lookup.py): how old its data is, if it isn't from today.
  const repologyDays = pkg.repologyCheckedAt && daysText(pkg.repologyCheckedAt);
  const repologyAge =
    repologyDays && repologyDays !== 'today'
      ? html` <span class="since" title="${new Date(pkg.repologyCheckedAt).toLocaleString()}">· ${repologyDays} ago</span>`
      : '';
  // Repology's page of the package, and how old its data is, in the
  // sentence: "compared with 14 other repositories (5 days ago)".
  const repologyUrl = pkg.project
    ? `https://repology.org/project/${encodeURIComponent(pkg.project)}/versions`
    : null;
  const repologyLink = (text) =>
    repologyUrl
      ? html`<a class="files-link" href="${repologyUrl}" target="_blank" rel="noopener">${text}</a>`
      : text;
  const repologyWhen =
    repologyDays && repologyDays !== 'today'
      ? html` <span title="${new Date(pkg.repologyCheckedAt).toLocaleString()}">(${repologyDays} ago)</span>`
      : '';
  // The sentence after the verdict, without "nixpkgs unstable has 1.3.5"
  // (the row says the version): what came after it, as a sentence of its own.
  const opening = (tail) => {
    const text = String(tail).replace(/^\s*(—|,|;)\s*/, '');
    return raw(/^[a-z]/.test(text) ? text.charAt(0).toUpperCase() + text.slice(1) : text);
  };
  const homepage = safeUrl(pkg.homepage);

  const st = computeStatus(pkg);
  const up = pkg.upstream;
  // nixkeeper's update check, and whether it was worked out from nixpkgs.
  const ours = up?.inferred
    ? "nixkeeper's update check (worked out from nixpkgs' source)"
    : "nixkeeper's update check";
  // The repositories it's compared against, nixkeeper's update check first.
  const mine = nixkeeperEntry(pkg);
  const checkedDays = up?.checkedAt && daysText(up.checkedAt);
  const chips = [
    ...(mine
      ? [
          {
            ...mine,
            title: `${mine.kind}${mine.where ? `: ${mine.where}` : ''}${checkedDays && checkedDays !== 'today' ? `, checked ${checkedDays} ago` : ''}`,
          },
        ]
      : []),
    ...others.map((e) => ({
      repo: e.repo,
      version: e.version,
      // Repology's newest, when it's newer than nixpkgs' (not when one of its
      // rules makes an older one newest: google-chrome's, at times).
      ahead:
        e.status === 'newest' &&
        Boolean(pkg.nixVersion) &&
        compareVersions(e.version, pkg.nixVersion) > 0,
    })),
  ];
  // "in the wesnoth/wesnoth tags" or "on www.barebones.com".
  const upLabel = up ? up.label || (up.repo ? `${up.repo} tags` : 'its update check') : '';
  const upLink = up
    ? html`${up.repo ? 'in the' : 'on'} ${safeUrl(up.url) ? html`<a class="files-link" href="${safeUrl(up.url)}" target="_blank" rel="noopener">${upLabel} ↗</a>` : upLabel}`
    : '';
  const since = pkg.outdatedSince
    ? ` — outdated since ${longDate(pkg.outdatedSince)} (${daysText(pkg.outdatedSince)})`
    : '';
  // What Repology said, where the update check decided otherwise
  // (repologySaid, upstream.apply in nixkeeper).
  // Its update check decides too when only nixpkgs packages it: Repology
  // compared it with nothing (nothingCompared without the check).
  const said = pkg.repologySaid;
  const repologyOutdated = (said?.status ?? pkg.nixStatus) === 'outdated';
  // A branch check (unstable versions): how many commits nixpkgs is behind,
  // and what makes that count as outdated ("90 days or 50 commits").
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const behind = up?.behind ? `${plural(up.behind, 'newer commit')}` : '';
  const limits = up?.outdatedAfter
    ? [
        up.outdatedAfter.days != null && `one has waited ${plural(up.outdatedAfter.days, 'day')}`,
        up.outdatedAfter.commits != null && `there are ${up.outdatedAfter.commits}`,
      ]
        .filter(Boolean)
        .join(' or ')
    : '';
  // A package updated together with another (follows): which, and that its
  // newest version and update PRs are that package's.
  const follows = up?.follows
    ? html`updated together with <b>${up.follows}</b> (${communityCheck(pkg) ? 'a community rule' : 'your update checks'}): its newest version and update PRs count for this package too`
    : '';
  // When the update check is what makes it outdated, say where the newer
  // version came from, and how it compares with Repology.
  // Outdated by nixkeeper's update check (the head says what it found, its
  // badge links where): how Repology differs, or what it is when it follows
  // another package.
  // Only nixpkgs packages it: its update check is what decided (the source
  // badge), nothing else for it to agree with.
  const nothingElse = pkg.onlyNixpkgs && pkg.nixStatus === 'unique';
  const upstreamExtra = () =>
    follows
      ? html`It's ${follows}.`
      : pkg.refVersion && pkg.refVersion !== up.version
        ? targetVersion(pkg) && targetVersion(pkg) !== up.version
          ? html`The newest above is Repology's; ${ours} found <span class="mono">${up.version}</span>.`
          : html`Repology's newest is <span class="mono">${pkg.refVersion}</span>.`
        : repologyOutdated
          ? ''
          : up.commit
            ? `${behind ? `${behind.charAt(0).toUpperCase()}${behind.slice(1)}` : 'Newer commits'}: Repology only tracks releases, so it can't tell.`
            : "Repology doesn't count it as the newest yet.";
  // A check that can't refresh needs fixing in nixkeeper, so the details say
  // so plainly, with the last result it's still using.
  const failing = notRefreshed(pkg, 'upstream');
  const checkNote = failing
    ? html`<div class="stale-note">⚠ ${staleText(failing, "nixkeeper's update check has been failing")}.${
        up
          ? html` Still using its last result: <span class="mono">${up.version}</span>${up.checkedAt ? ` (${longDate(up.checkedAt)})` : ''}.`
          : ' It has no result yet.'
      } ${
        communityCheck(pkg)
          ? html`It's a community rule (<span class="mono">community/update-checks.nix</span> in nixkeeper): report it there, or give this package a rule of your own in your update checks.`
          : html`Fix it in <span class="mono">package-lists/update-checks.nix</span>.`
      }</div>`
    : '';
  // An up-to-date rule: Repology gets this version wrong, so it counts as
  // up to date. What Repology said, and why the rule says otherwise.
  const rule = pkg.upToDate;
  const ruleText = rule
    ? html` — up to date by ${rule.community ? 'a community rule' : 'a manual rule'}: ${rule.reason || ''} (Repology calls it <span class="mono">${rule.status || '?'}</span>${
        rule.newest
          ? html`, with <span class="mono">${rule.newest}</span> as the newest elsewhere`
          : ''
      }).`
    : '';
  // Compared with its own source instead of Repology (Typst Universe):
  // the row's "feed".
  const feed = pkg.feed;
  const feedLink = feed
    ? html`<a class="files-link" href="${safeUrl(feed.url)}" target="_blank" rel="noopener">${feed.name} ↗</a>`
    : '';
  // MELPA's versions are a build's date and time (20251005.508): said as days.
  const builtOn = (v) => {
    const d = /^(\d{4})(\d{2})(\d{2})\./.exec(v || '');
    return d ? longDate(`${d[1]}-${d[2]}-${d[3]}T12:00:00Z`) : null;
  };
  const feedDay = feed?.followed
    ? feed.followed !== feed.snapshot
      ? ` (nixpkgs follows ${feed.followed}; ${feed.snapshot} is out)`
      : ''
    : feed?.released
      ? ` (published ${longDate(`${feed.released}T12:00:00Z`)})`
      : feed?.dated && builtOn(feed.version)
        ? ` (a build from ${builtOn(feed.version)}${st === 'warn' && builtOn(pkg.nixVersion) ? `; nixpkgs' is from ${builtOn(pkg.nixVersion)}` : ''})`
        : '';
  // What the head (verdict, newest, since when, the linked source) doesn't
  // say already: how Repology differs from the check that decided, why a
  // version isn't compared, a rule's reason; nothing when the head says it
  // all (outdated by Repology: its newest and since when).
  const nixLine =
    up?.newer && !fromMaster(pkg)
      ? upstreamExtra()
      : st === 'missing'
        ? html`Not found in <span class="mono">nix_unstable</span>: nixpkgs doesn't currently package this.`
        : opening(
            html`${
              rule
                ? ruleText
                : feed && st === 'ok' && feed.heldBack
                  ? html` Hackage has <span class="mono">${feed.heldBack}</span>, which Stackage holds back until its next series.`
                  : st === 'warn'
                    ? pkg.refFromPR && !fromMaster(pkg)
                      ? ' — Repology names no newer version: the newest comes from an update PR.'
                      : ''
                    : olderVersionKept(pkg)
                      ? html` — an older version nixpkgs keeps on purpose${pkg.keptBeside ? html`, beside <b class="mono">${pkg.keptBeside.attr}</b> <span class="mono">${pkg.keptBeside.version}</span>` : ', beside a newer one'}: not outdated while nothing newer is out in its own series.`
                      : st === 'neutral'
                        ? nothingCompared(pkg)
                          ? ` — ${ONLY_NIXPKGS_TEXT}.`
                          : pkg.nixStatus === 'unsupported'
                            ? ` — ${UNSUPPORTED_TEXT}.`
                            : pkg.nixStatus === 'unlisted'
                              ? pkg.lookupFailed
                                ? ` — ${LOOKUP_FAILED}, so there's nothing to compare it with yet.`
                                : " — Repology doesn't list this package, so there's nothing to compare it with."
                              : html` — Repology classifies this version as <span class="mono">${pkg.nixStatus}</span>.`
                        : feed || (said && up && !failing)
                          ? ''
                          : loaded && compared
                            ? html` — compared with ${repologyLink(`${compared} other ${compared === 1 ? 'repository' : 'repositories'}`)}${repologyWhen}.`
                            : ''
            }${
              up && !up.newer && !failing
                ? follows
                  ? html` It's ${follows}.`
                  : up.behind
                    ? html` ${ours}: ${behind} ${upLink} (up to <span class="mono">${up.version}</span>), not counted as outdated until ${limits}.`
                    : said
                      ? html` Repology counts it <span class="mono">${said.status}</span>${said.newest ? html`, with <span class="mono">${said.newest}</span> as the newest elsewhere` : ''}: the update check decides, being this package's own source.`
                      : !feed && !rule && !fromMaster(pkg) && !nothingElse
                        ? html` ${ours} ${st === 'warn' ? 'found nothing newer' : 'agrees'}: the latest version ${upLink} is <span class="mono">${up.version}</span>.`
                        : ''
                : ''
            }`,
          );
  // Where master is: the PR that brought it, and whether Hydra built it.
  const masterSaid = [
    pkg.masterPR &&
      html`merged in <a class="files-link" href="${safeUrl(pkg.masterPR.url)}" target="_blank" rel="noopener">#${pkg.masterPR.number} ↗</a>${whoDid(pkg.masterPR.author, pkg.masterPR.mergedBy)}`,
    pkg.master ? 'built by Hydra' : 'not built by Hydra yet',
  ]
    .filter(Boolean)
    .flatMap((part, i) => (i ? [', ', part] : [part]));

  const unloaded = loaded
    ? ''
    : html`<div class="stale-note">⚠ Couldn't load Repology's details for this package, so the repositories it's compared with aren't shown. Close and reopen it to try again.</div>`;
  const profile = profileOf(pkg.set);
  const inBulk = pkg.set
    ? html`<div class="nix-line">In ${profile ? `the ${profile.name} set` : 'a set'} (<span class="mono">${pkg.set}</span>): ${bulkText(pkg.set).replace(/^K/, 'k')}${profile ? html` (<a class="files-link" href="${safeUrl(profile.link)}" target="_blank" rel="noopener">in nixpkgs ↗</a>)` : ''}. It counts on its set's line on the overview, not in the cards; GitHub's PR counts and nixkeeper's update checks aren't collected for it.</div>`
    : pkg.unversioned
      ? html`<div class="nix-line">${UNVERSIONED_TITLE}.</div>`
      : '';
  const archived = pkg.archived ? html`<div class="stale-note">${archivedText(pkg)}</div>` : '';
  // The verdict at a glance: what it is, the versions, since when, and
  // which source decided (the chain in docs/design: a check, a version
  // source, an up-to-date rule, master, or Repology), as a badge: ours in
  // the accent's tint, Repology grey, so it shows when Repology isn't the
  // judge.
  const target = targetVersion(pkg);
  const verdict =
    st === 'missing'
      ? ['danger', 'Not in nixpkgs']
      : st === 'warn'
        ? waitingForChannel(pkg)
          ? ['merged', 'Waiting for the channel']
          : ['warn', 'Outdated']
        : st === 'ok'
          ? ['ok', 'Up to date']
          : olderVersionKept(pkg)
            ? ['neutral', 'Older version kept']
            : ['neutral', 'Not compared'];
  const checkKind = communityCheck(pkg)
    ? 'a community update check'
    : up?.inferred
      ? "nixkeeper's update check, worked out from nixpkgs' source"
      : 'your update check';
  const source =
    st === 'missing' || verdict[1] === 'Not compared'
      ? null
      : fromMaster(pkg)
        ? [
            'merged',
            'git-merge',
            'master',
            "master's version, built by Hydra or merged",
            safeUrl(pkg.masterPR?.url),
          ]
        : rule
          ? [
              'ours',
              'list-check',
              'up-to-date rule',
              `${rule.community ? 'A community' : 'Your'} up-to-date rule: ${rule.reason || ''}`,
              rule.community
                ? 'https://github.com/nixkeeper/nixkeeper/blob/main/community/up-to-date.nix'
                : null,
            ]
          : feed
            ? [
                'ours',
                'package',
                feed.name,
                `Compared with ${feed.name}, this package's own source`,
                safeUrl(feed.url),
              ]
            : (said || up?.newer) && up.follows
              ? [
                  'ours',
                  'git-merge',
                  `with ${up.follows}`,
                  `Updated together with ${up.follows} (${communityCheck(pkg) ? 'a community rule' : 'your update checks'}): its newest version counts for this package too`,
                ]
              : said || up?.newer || (up && pkg.onlyNixpkgs && pkg.nixStatus === 'unique')
                ? [
                    'ours',
                    up.commit ? 'git-branch' : up.repo ? 'tag' : 'world',
                    upLabel,
                    `${checkKind.replace(/^[ay]/, (c) => c.toUpperCase())}: ${upLabel}`,
                    safeUrl(up.url),
                  ]
                : [
                    'repology',
                    'chart-dots-3',
                    'Repology',
                    'Repology: the repositories it compares',
                    repologyUrl,
                  ];
  const facts = [
    st === 'warn' && target && ['newest', html`<span class="mono pd-newer">${target}</span>`],
    st === 'warn' &&
      pkg.outdatedSince && [
        'outdated since',
        html`${longDate(pkg.outdatedSince)} <span class="pd-ago">(${daysText(pkg.outdatedSince)})</span>`,
      ],
  ].filter(Boolean);
  // Notes that call for something first; then the rest, the context.
  const urgent = html`${unloaded}${archived}${checkNote}${insecureNote(pkg)}${backportNote(pkg)}${
    pkg.nixVulnerable
      ? html`<div class="vuln-note">⚠ Repology flags nixpkgs' version <span class="mono">${pkg.nixVersion}</span> as vulnerable.${
          pkg.project
            ? html` <a class="files-link" href="https://repology.org/project/${encodeURIComponent(pkg.project)}/cves" target="_blank" rel="noopener">Known CVEs ↗</a>`
            : ''
        }</div>`
      : ''
  }`;
  // Its fixes of the last month (history.add_recent_fixes in nixkeeper),
  // with who, when a PR is known.
  const fixesSaid = (pkg.recentFixes || []).map((f) => {
    const what =
      f.kind === 'update'
        ? html`Updated <span class="mono">${f.from || '?'}</span> → <span class="mono">${f.to || '?'}</span>`
        : f.kind === 'build'
          ? 'Build fixed'
          : "The update bot's failures cleared";
    const pr = f.pr
      ? html`, ${f.likely ? 'likely by' : 'in'} <a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${f.pr}" target="_blank" rel="noopener">#${f.pr} ↗</a>${whoDid(f.author, f.mergedBy)}`
      : '';
    const after = f.since ? ` (after ${shortAge(f.since, new Date(f.at).getTime())})` : '';
    return html`<div class="master-note">✓ ${what} on ${longDate(f.at)}${after}${pr}.</div>`;
  });
  const context = html`${fixesSaid}${inBulk}${
    onMaster(pkg)
      ? html`<div class="master-note">master already has <span class="mono">${onMaster(pkg)}</span> (${masterSaid})${
          waitingForChannel(pkg)
            ? ': the update is merged, and reaches nixos-unstable when the channel next advances, usually within a few days.'
            : ', not in nixos-unstable yet.'
        }</div>`
      : ''
  }${waitingForChannel(pkg) ? '' : stagingNote(pkg)}${stagingNextBreaksNote(pkg)}${stagingNextBlockedNote(pkg)}${branchNote(pkg)}`;
  const people = [
    Array.isArray(pkg.maintainers) &&
      html`<section class="pd-sec"><h4 class="other-label">Maintainers</h4><div class="pd-pills">${
        pkg.maintainers.length
          ? pkg.maintainers.map(
              (m) =>
                html`<span class="pd-pill maintainer"><button type="button" class="maint-btn" data-handle="${m}" title="Their packages here"><img class="avatar" src="https://github.com/${encodeURIComponent(m)}.png?size=40" alt="" width="18" height="18" loading="lazy" referrerpolicy="no-referrer">${m}</button><a class="pd-pill-go" href="https://github.com/${encodeURIComponent(m)}" target="_blank" rel="noopener" aria-label="${m} on GitHub" title="${m} on GitHub">↗</a></span>`,
            )
          : html`<span class="none-note">none in nixpkgs · <button type="button" class="maint-btn" data-handle="none" title="Every package with no maintainer">see all packages without one</button></span>`
      }</div></section>`,
    pkg.teams?.length &&
      html`<section class="pd-sec"><h4 class="other-label">Teams</h4><div class="pd-pills">${pkg.teams.map(
        (t) =>
          html`<button type="button" class="pd-pill maint-btn team-btn" data-team="${t}" title="${
            pkg.teamsByList?.includes(t)
              ? `On the list named after the team (package-lists), not under it in nixpkgs (meta.teams). The team's packages here`
              : "The team's packages here"
          }">${t}${pkg.teamsByList?.includes(t) ? html`<span class="pd-pill-note">list</span>` : ''}</button>`,
      )}</div></section>`,
  ].filter(Boolean);
  const links = [
    homepage &&
      html`<a class="pd-link" href="${homepage}" target="_blank" rel="noopener">${icon('home')}Homepage</a>`,
    safeUrl(pkg.source) &&
      html`<a class="pd-link" href="${safeUrl(pkg.source)}" target="_blank" rel="noopener" title="Where nixpkgs defines this package">${icon('file-code')}${sourceFileName(pkg.source)}</a>`,
  ].filter(Boolean);
  el.innerHTML = html`<div class="pd">
    <div class="pd-head">
      <span class="pd-verdict ${verdict[0]}">${verdict[1]}</span>
      <dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
      ${
        source
          ? source[4]
            ? html`<a class="pd-source ${source[0]}" href="${source[4]}" target="_blank" rel="noopener" title="${source[3]}">${icon(source[1])}<span class="pd-source-text">${source[2]}</span> <span aria-hidden="true">↗</span></a>`
            : html`<span class="pd-source ${source[0]}" title="${source[3]}">${icon(source[1])}<span class="pd-source-text">${source[2]}</span></span>`
          : ''
      }
    </div>
    ${String(urgent).trim() ? html`<div class="pd-notes">${urgent}</div>` : ''}
    ${vulnSection(pkg)}
    <div class="pd-why-body">
      ${String(nixLine).trim() ? html`<p class="pd-text">${nixLine}</p>` : ''}${
        up?.tagged
          ? html`<p class="pd-text" title="nixkeeper prefers a release, when the project makes them: a tag alone may not be published yet">Tagged <span class="mono">${up.tagged}</span> on GitHub, not released yet.</p>`
          : ''
      }
      ${String(context).trim() ? html`<div class="pd-notes">${context}</div>` : ''}
    </div>
    ${
      // Up to date, they'd all say the same version: the sentence's link
      // has them. Outdated or not compared, they show who has what. Not for
      // an older version kept on purpose: they're the newer series' (and
      // its betas: firefox 159.0b5 beside firefox-esr 153.5.1).
      chips.length && st !== 'ok' && !olderVersionKept(pkg)
        ? html`<section class="pd-sec"><h4 class="other-label">Compared against${repologyAge}</h4><div class="repo-chips">
      ${chips.map((e, i) => html`<span class="repo-chip ${e.ahead ? 'ahead' : ''}"${e.title ? html` title="${e.title}"` : ''}${i >= COMPARED_SHOWN ? raw(' hidden') : ''}>${e.repo} <span class="v mono">${e.version || '?'}</span></span>`)}${
        chips.length > COMPARED_SHOWN
          ? html`<button type="button" class="more-btn" aria-expanded="false">Show all ${chips.length}</button>`
          : ''
      }
    </div></section>`
        : ''
    }
    ${githubSection(pkg)}
    ${people.length ? html`<div class="pd-people">${people}</div>` : ''}
    <div class="pd-links">${links}<span class="pd-links-end">${hideButton(pkg)}</span></div>
  </div>`;
  el.querySelector('.pd-hide')?.addEventListener('click', () => setHidden(pkg, !isHidden(pkg)));
  // A maintainer's packages: searches for them (the search box, so the
  // address can be shared).
  // A team's packages: the team filter (?team=, shareable too).
  for (const btn of el.querySelectorAll('.team-btn')) {
    btn.addEventListener('click', () => {
      teamFilter = btn.dataset.team;
      update();
      document.getElementById('stats').scrollIntoView({ block: 'nearest' });
    });
  }
  for (const btn of el.querySelectorAll('.maint-btn:not(.team-btn)')) {
    btn.addEventListener('click', () => {
      const search = document.getElementById('search');
      search.value = `@${btn.dataset.handle}`;
      search.dispatchEvent(new Event('input'));
      search.scrollIntoView({ block: 'nearest' });
    });
  }
  // Vulnerabilities: the worst VULNS_SHOWN, or all of them.
  el.querySelector('.vl-more')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    const sec = btn.closest('.vl-sec');
    sec.querySelectorAll('.vl-group > .vl-list > .vl').forEach((li, i) => {
      li.hidden = !open && i >= VULNS_SHOWN;
    });
    sec.querySelectorAll('.vl-group').forEach((g) => {
      g.hidden = !g.querySelector('.vl:not([hidden])');
    });
    btn.setAttribute('aria-expanded', open);
    btn.textContent = open ? 'Show fewer' : `Show all ${btn.dataset.all}`;
  });
  el.querySelector('.more-btn:not(.vl-more)')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    el.querySelectorAll('.repo-chip').forEach((chip, i) => {
      chip.hidden = !open && i >= COMPARED_SHOWN;
    });
    btn.setAttribute('aria-expanded', open);
    btn.textContent = open ? 'Show fewer' : `Show all ${chips.length}`;
  });
}

// The panel's "Hide until it changes" (or "Show it again" while hidden):
// for something that needs attention, kept in this browser.
function hideButton(pkg) {
  const hidden = isHidden(pkg);
  // Something to hide: what the list's tiles count as needing attention.
  const needs = ['warn', 'builds', 'updates', 'vuln', 'broken'].some((k) => FILTERS[k]?.test(pkg));
  if (!hidden && !needs) return '';
  return html`<button type="button" class="pd-hide" title="${
    hidden
      ? 'Shown again in your lists'
      : 'Leave it out of your lists, in this browser only, until what it needs attention for changes (a newer version, another failing build, a new CVE). Wrong for everyone? Report it, or add a community rule'
  }">${hidden ? 'Show it again' : 'Hide until it changes'}</button>`;
}

// How many repositories a panel shows before "Show all".
const COMPARED_SHOWN = 8;

// What every filter but the facets (set, maintainer, platform) keeps.
const passesOthers = (p, q) =>
  inList(p) &&
  inPeople(p) &&
  inSet(p) &&
  notHidden(p) &&
  refined(p) &&
  FILTERS[activeFilter].test(p) &&
  matchesSearch(p, q);

function currentFiltered() {
  const q = document.getElementById('search').value;
  facetBase = packages.filter((p) => passesOthers(p, q));
  const list = facetBase.filter((p) => inPlatform(p) && inNameSet(p) && byMaintainer(p));
  return sortedList(list, sortReverse ? -1 : 1);
}

// The list in the order picked (sortMode), reversed with dir -1; those with
// nothing to sort by (no date, no newer version) last either way. Each
// package's key worked out once, not at every comparison: sorting every
// package compares about 170,000 pairs, and on a mid-range phone working
// them out each time took half a second (Lighthouse, 2026-10-07). ISO dates
// in UTC compare correctly as plain strings; undated ones last ("~").
function sortedList(list, dir = 1) {
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // The data arrives sorted by name, and Array.sort is stable.
  if (sortMode === 'az') return dir > 0 ? list : [...list].reverse();
  if (sortMode === 'oldest' || sortMode === 'newest') {
    // How long its problem has lasted (the tile's kind, when one is picked).
    const keyed = list.map((p) => ({ p, since: problemSince(p, activeFilter) || '' }));
    const order = sortMode === 'oldest' ? dir : -dir;
    keyed.sort((a, b) =>
      !a.since || !b.since ? !a.since - !b.since : order * cmp(a.since, b.since),
    );
    return keyed.map((k) => k.p);
  }
  if (sortMode === 'gap') {
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
  if (activeFilter === 'vuln') {
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

document.getElementById('stats').addEventListener('click', (e) => {
  const clear = e.target.closest('.plat-filter[data-clear]');
  if (clear) {
    if (clear.dataset.clear === 'team') teamFilter = null;
    else platformFilter = null;
    update();
    return;
  }
  const btn = e.target.closest('.stat-btn');
  if (!btn) return;
  if (btn.dataset.view) {
    // With every package: the list, or (pressed) back to the overview.
    showView({ view: btn.getAttribute('aria-pressed') === 'true' ? null : btn.dataset.view });
    return;
  }
  // Clicking the active filter again goes back to showing everything.
  activeFilter = btn.dataset.filter === activeFilter ? 'all' : btn.dataset.filter;
  update();
});

// ?team='s left-out teams and none: their chips (teamOutChips) and the
// maintainer page's "Not via a team".
document.addEventListener('click', (e) => {
  const out = e.target.closest('button[data-team-out]');
  const person = e.target.closest('button[data-maintainer-out]');
  if (out) teamsLeftOut = teamsLeftOut.filter((t) => t !== out.dataset.teamOut);
  else if (person)
    maintainersLeftOut = maintainersLeftOut.filter((h) => h !== person.dataset.maintainerOut);
  else if (e.target.closest('button[data-team-none]')) noTeam = false;
  else if (e.target.closest('button[data-no-team]')) noTeam = !noTeam;
  else return;
  update();
});
// Show errors: on or off.
document.addEventListener('click', (e) => {
  if (!e.target.closest('button[data-show-errors]')) return;
  showErrors = !showErrors;
  update({ keepPage: true });
});
// ↓/↑: the list's order reversed, or back.
document.addEventListener('click', (e) => {
  if (!e.target.closest('button[data-sort-dir]')) return;
  sortReverse = !sortReverse;
  update();
});
// The search's matches in all of nixpkgs: the next ones, or every one again
// (moreMatchesHtml).
document.addEventListener('click', (e) => {
  if (e.target.closest('button[data-more-matches]')) {
    matchLimit += MATCHES_MORE;
    update({ keepPage: true });
  } else if (e.target.closest('button[data-clear-matches]')) {
    inFilter = null;
    statusFilter = null;
    byFilter = null;
    matchTeam = null;
    platformFilter = null;
    update();
  }
});
// Narrowing the list (refineHtml), wherever it's drawn.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-refine]');
  if (!btn) return;
  const key = btn.dataset.refine;
  if (refines.has(key)) refines.delete(key);
  else refines.add(key);
  update();
});
document.addEventListener('change', (e) => {
  if (e.target.matches('select[data-age]')) ageFilter = e.target.value || null;
  else if (e.target.matches('select[data-because]')) becauseFilter = e.target.value || null;
  else if (e.target.matches('select[data-build-failed]'))
    buildFailedFilter = e.target.value || null;
  else if (e.target.matches('select[data-platform-pick]')) platformFilter = e.target.value || null;
  else if (e.target.matches('select[data-in]')) inFilter = e.target.value || null;
  else if (e.target.matches('select[data-sort]')) sortMode = e.target.value || 'pressing';
  else if (e.target.matches('select[data-newer]')) newerFilter = e.target.value || null;
  else if (e.target.matches('select[data-pr-pick]')) {
    refines.delete('withpr');
    refines.delete('nopr');
    if (e.target.value) refines.add(e.target.value);
  } else if (e.target.matches('select[data-status]')) statusFilter = e.target.value || null;
  else if (e.target.matches('select[data-match-team]')) matchTeam = e.target.value || null;
  else if (e.target.matches('input[data-by]')) {
    const by = e.target.value.trim().replace(/^@/, '').toLowerCase();
    byFilter = /^[\w.-]{1,60}$/.test(by) ? by : null;
  } else if (e.target.matches('select[data-per]')) {
    // The page holding the first row shown before, at the new size.
    const first = (pageNum - 1) * pageSize;
    pageSize = Number(e.target.value);
    pageNum = Math.floor(first / pageSize) + 1;
    update({ keepPage: true });
    return;
  } else return;
  update();
});

// With every package, the header's tiles: filters, as the count chips are.
document.getElementById('scope')?.addEventListener('click', (e) => {
  // The overview's lists: newest or longest-standing.
  const mode = e.target.closest('button.hl-mode');
  if (mode) {
    highlightShown[mode.dataset.hl] = mode.dataset.mode;
    renderScope();
    return;
  }
  if (e.target.closest('button.close-all')) {
    closeRows(openRows());
    return;
  }
  if (e.target.closest('button.hidden-toggle')) {
    showHidden = !showHidden;
    update({ keepPage: true });
    return;
  }
  const copy = e.target.closest('button.merge-copy');
  if (copy) {
    copyTitle(copy);
    return;
  }
  const hidePr = e.target.closest('button.merge-hide');
  if (hidePr) {
    const number = Number(hidePr.dataset.pr);
    const pr = (mergeList || []).find((p) => p.number === number);
    if (pr) setPrHidden(number, !isPrHidden(pr));
    return;
  }
  if (e.target.closest('button.merge-hidden-toggle')) {
    showHiddenPrs = !showHiddenPrs;
    renderScope();
    return;
  }
  if (e.target.closest('button[data-close-more]')) {
    closeAll = !closeAll;
    renderScope();
    return;
  }
  if (e.target.closest('button.merge-more')) {
    mergeAll = !mergeAll;
    renderScope();
    return;
  }
  const tile = e.target.closest('button.tile');
  if (!tile) return;
  activeFilter = tile.dataset.filter === activeFilter ? 'all' : tile.dataset.filter;
  update();
});

document.getElementById('lists').addEventListener('click', (e) => {
  if (e.target.closest('[data-mine-edit]')) {
    editingHandle = true;
    renderLists();
    document.getElementById('mineInput')?.focus();
    return;
  }
  if (e.target.closest('[data-mine]')) {
    showMine(!isMine());
    return;
  }
  if (e.target.closest('[data-team-edit]')) {
    editingTeam = true;
    renderLists();
    document.getElementById('teamInput')?.focus();
    return;
  }
  if (e.target.closest('[data-my-team]')) {
    showMyTeam(!isMyTeam());
    return;
  }
  const btn = e.target.closest('.stat-btn[data-list]');
  if (!btn) return;
  // Clicking the active list again shows every list.
  listFilter = btn.dataset.list === listFilter ? null : btn.dataset.list;
  update();
});

// Typing redraws the table once it pauses (150 ms), not at every key: with
// thousands of packages, each redraw takes a moment.
let searchTimer;
document.getElementById('search').addEventListener('input', () => {
  pkgParam = null; // a search leaves a package shown alone (?pkg=)
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => update(), 150);
});
// With every package: the links between views (a generated set, one
// package, back to what needs attention) and the team picker. A click with
// a modifier opens the link elsewhere, as links do.
document.addEventListener('click', (e) => {
  const a = e.target.closest(
    'a[data-scope-set], a[data-scope-pkg], a[data-scope-home], a[data-card-view], a[data-scope-cause]',
  );
  if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button) return;
  e.preventDefault();
  showView({
    set: a.dataset.scopeSet || null,
    pkg: a.dataset.scopePkg || null,
    view: a.dataset.cardView || null,
    filter: a.dataset.cardFilter || null,
    cause: a.dataset.scopeCause || null,
  });
});
// A maintainer, from the maintainers page or a suggestion: their packages.
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[data-maintainer]');
  if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button) return;
  e.preventDefault();
  showView({});
  const search = document.getElementById('search');
  search.value = `@${a.dataset.maintainer}`;
  search.dispatchEvent(new Event('input'));
});
// The visitor's packages (their maintainer view), or (show false) back to
// the overview.
function showMine(show) {
  showView({});
  if (!show) return;
  const search = document.getElementById('search');
  search.value = `@${myHandle}`;
  search.dispatchEvent(new Event('input'));
}
// The visitor's team's packages, or (show false) back to the overview.
function showMyTeam(show) {
  showView({});
  if (!show) return;
  teamFilter = myTeam;
  update();
}
document.getElementById('lists').addEventListener('submit', (e) => {
  if (e.target.id !== 'teamForm') return;
  e.preventDefault();
  myTeam = e.target.team.value || null;
  editingTeam = false;
  store('nixkeeper-team', myTeam);
  if (myTeam) showMyTeam(true);
  else renderLists();
});
document.getElementById('lists').addEventListener('submit', (e) => {
  if (e.target.id !== 'mineForm') return;
  e.preventDefault();
  const handle = e.target.handle.value.trim().replace(/^@/, '');
  myHandle = handle || null;
  myCount = null;
  editingHandle = false;
  store('nixkeeper-handle', myHandle);
  if (myHandle) {
    loadMyCount();
    showMine(true);
  } else renderLists();
});
document.getElementById('lists').addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && e.target.id === 'mineInput') {
    editingHandle = false;
    renderLists();
  }
  if (e.key === 'Escape' && e.target.id === 'teamInput') {
    editingTeam = false;
    renderLists();
  }
});

// The overview's own search box: the page's search, from there.
document.addEventListener('input', (e) => {
  if (e.target.id !== 'overviewSearch') return;
  const search = document.getElementById('search');
  search.value = e.target.value;
  search.dispatchEvent(new Event('input'));
});
// Enter, or leaving it, with @someone typed there: their packages.
document.addEventListener('keydown', (e) => {
  if (e.target.id !== 'overviewSearch' || e.key !== 'Enter') return;
  if (e.target.value.trim().startsWith('@')) e.target.blur();
});
document.addEventListener('focusout', (e) => {
  if (e.target.id !== 'overviewSearch') return;
  if (e.target.value.trim().startsWith('@')) setTimeout(update); // after a click lands
});
document.addEventListener('change', (e) => {
  if (e.target.id !== 'teamPick') return;
  // A team's packages, from all of nixpkgs (not within a set or a package).
  teamFilter = e.target.value || null;
  setFilter = null;
  causeFilter = null;
  pkgParam = null;
  viewParam = null;
  update();
});

// The groups card shown in full (or back to the biggest): every group,
// loaded once from views/causes.json, then the overview drawn again.
document.addEventListener('click', async (e) => {
  const button = e.target.closest('.cause-more');
  if (!button) return;
  if (allCauses) {
    allCauses = null;
  } else {
    try {
      const res = await fetch(dataUrl('views/causes.json'), { cache: 'no-store' });
      if (!res.ok) throw new Error(res.status);
      allCauses = (await res.json()).groups || [];
    } catch {
      return; // the biggest stay
    }
  }
  if (shownView === 'overview') renderScope();
});

// "/" jumps to the filter, as on GitHub; Escape in it clears it.
document.addEventListener('keydown', (e) => {
  const search = document.getElementById('search');
  if (e.key === '/' && !e.target.closest('input, textarea') && !search.disabled) {
    e.preventDefault();
    search.focus();
  } else if (
    // Typing with the list focused (a row): into the search, as it filters
    // as you type. Only there, not anywhere on the page: a letter alone
    // shortcuts only its own component (WCAG 2.1.4), and Ctrl+F stays the
    // browser's.
    e.target.matches?.('tr.row') &&
    e.key.length === 1 &&
    e.key !== ' ' &&
    !e.ctrlKey &&
    !e.metaKey &&
    !e.altKey &&
    !search.disabled
  ) {
    e.preventDefault();
    search.focus();
    search.value += e.key;
    search.dispatchEvent(new Event('input', { bubbles: true }));
  } else if (e.key === 'Escape' && e.target === search && search.value) {
    search.value = '';
    clearTimeout(searchTimer);
    update();
  }
});

document
  .getElementById('themeBtn')
  .addEventListener('click', () => showThemePanel(document.getElementById('themePanel').hidden));
document.getElementById('themePanel').addEventListener('change', (e) => {
  const { name, value } = e.target;
  if (name === 'palette') store('nixkeeper-palette', value);
  // Auto is no choice: the system's setting.
  if (name === 'mode') store('nixkeeper-mode', value === 'auto' ? null : value);
  applyTheme();
});
document
  .getElementById('legendBtn')
  .addEventListener('click', () => showLegend(document.getElementById('legendPanel').hidden));
document
  .getElementById('checked')
  .addEventListener('click', () => showSources(document.getElementById('sourcesPanel').hidden));
// The Theme menu and the legend close on a click elsewhere, or Escape (back
// to their button).
document.addEventListener('click', (e) => {
  if (!e.target.closest('.theme')) showThemePanel(false);
  if (!e.target.closest('.legend')) showLegend(false);
  if (!e.target.closest('.sources')) showSources(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  let closed = false;
  for (const [panel, btn, show] of [
    ['themePanel', 'themeBtn', showThemePanel],
    ['legendPanel', 'legendBtn', showLegend],
    ['sourcesPanel', 'checked', showSources],
  ]) {
    if (document.getElementById(panel).hidden) continue;
    show(false);
    document.getElementById(btn).focus();
    closed = true;
  }
  // No popover to close, and not in a field (Esc empties the search): the
  // open packages, the keyboard on the row it was in, if any.
  if (closed || e.target.matches('input, select, textarea')) return;
  const rows = openRows();
  if (!rows.length) return;
  const at = document.activeElement?.closest('tr.detail')?.previousElementSibling;
  closeRows(rows);
  if (at?.matches('tr.row')) at.focus();
});

// The sticky header's height, for the column headings to stick under it.
new ResizeObserver(([entry]) =>
  document.documentElement.style.setProperty(
    '--sticky-h',
    `${Math.round(entry.borderBoxSize[0].blockSize)}px`,
  ),
).observe(document.getElementById('stickyTop'));

// Phones and tablets: once the filters are stuck at the top, "checked ..."
// hides (stuck), and comes back at the top of the page. The bar keeps its
// place in the page (a margin for the hidden line), so the list doesn't jump.
const narrow = matchMedia('(max-width: 1080px)');
new IntersectionObserver(([entry]) => {
  const bar = document.getElementById('filterbar');
  const stuck = narrow.matches && !entry.isIntersecting && entry.boundingClientRect.top < 0;
  if (stuck === bar.classList.contains('stuck')) return;
  const before = bar.offsetHeight;
  bar.classList.toggle('stuck', stuck);
  bar.style.marginBottom = stuck ? `${before - bar.offsetHeight}px` : '';
}).observe(document.getElementById('stickMark'));

applyTheme();
readViewFromUrl();
loadIndex();
