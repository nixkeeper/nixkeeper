import { homeHref, pageLinks, VIEWS, viewPath, withRunStamps } from './address.js';
import { dataUrl, fullRowOf, githubRepo, locateData, readJson } from './data.js';
import {
  decodeFacets,
  foldFamilies,
  inPickedSet,
  matchFacets,
  NAME_STATUSES,
  TOP_LEVEL,
} from './facets.js';
import { currentFiltered, FILTERS, KNOWN, PLATFORMS } from './filters.js';
import {
  BY_SHOWN,
  bulkBadge,
  DOT_TITLE,
  facetOption,
  listHeaderHtml,
  listView,
  renderLists,
  renderStats,
  rowHtml,
  searchValues,
  wireList,
} from './list.js';
import { themeFor } from './logic.js';
import {
  hiddenPrPrints,
  maintainerItem,
  maintainersHtml,
  saveHiddenPrs,
  wireMaintainerView,
} from './maintainer-view.js';
import { appendHtml, html, NO_MARKUP, raw, setHtml } from './markup.js';
import { highlightShown, overviewHtml, wireOverview } from './overview.js';
import { fillBuilds, fillDetail, fillUpdate } from './package-view.js';
import { maintainerMatches, NAME_DOTS, nameMatches } from './people.js';
import { HIDDEN_KEY, hiddenPrints, isHidden, pruneHidden, remember, stored } from './prefs.js';
import {
  matchNote,
  needsList,
  parseQuery,
  readBox,
  searchText,
  showQuery,
  wireSearchMenu,
  writeQuery,
} from './search.js';
import {
  failedBuilds,
  known,
  PAGE_SIZES,
  readState,
  scopeHref,
  state,
  writeState,
} from './state.js';
import { attentionPrint, computeStatus, prPrint } from './status.js';
import { store } from './store.js';
import { timer } from './timing.js';
import { fmt } from './ui.js';

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

// The line by the logo on an instance of its own lists (index.html's is
// for every package).
const OWN_TAG = 'health of your nixpkgs packages';
// A names entry's maintainers, teams and platforms (store.facetIndex).
const facetsOf = (entry) => store.facetIndex[store.nameIndex.get(entry)];
// ?pkg=: one package alone (with every package); ?set=: a generated set;
// ?view=: a list by name (attention, broken).
// The ?pkg= its details were opened for, once: a link to a package opens
// them, and closing them keeps them closed while it's shown.
let pkgOpenedFor = null;
// ?cause=: a group of failed builds sharing an error (views/cause/<key>.json,
// nixkeeper's causes.py), and what its view file says of it.
// Narrowing any list further, with everything else (?refine=, REFINES keys
// comma-separated, and ?age=, an AGES key).
// ?updateFailed=: update failures for one reason (a FAILED_BECAUSE key, or
// other).
// ?buildFailed=: build failures for one reason (a BUILD_FAILED key).
// ?newer=: whether a newer version is known ("yes": outdated, merged or
// not; "no": not outdated), with any tile: build failures an update won't
// fix (?filter=builds&newer=no), say.
// ?errors=1: with Build failures (or Failed), every failing row's build
// panel open under it, loaded as it scrolls into view (watchErrors).
const errorsHere = () =>
  state.showErrors && (state.activeFilter === 'builds' || state.activeFilter === 'failed');
// ?status=: the search's matches in all of nixpkgs of one status (a
// NAME_STATUSES key: what the name index's letter says). How many of them
// are shown, more on asking (moreMatchesHtml), from MATCHES_SHOWN again
// with another search or filter (matchQuery: what was asked).
// ?ofteam=: the matches of one team (its name as nixpkgs writes it); the
// maintainer (?by=) and platform (?platform=) ones are the list's own.
const MATCHES_SHOWN = 50;
const MATCHES_MORE = 200;
let matchLimit = MATCHES_SHOWN;
let matchQuery = '';
// What the matches last counted, for the search box's menu (searchValues).
let matchCounts = null;
// What the box asks, as of the last update(): its filters and text, as
// written back, and a package shown alone. Typing that leaves it the same
// (is: before its value, a space) draws nothing again.
let lastAsked = null;
const asking = () => `${state.pkgParam || ''}\n${writeQuery(state, searchText().trim())}`;
// The menu's values (searchValues, each worked out when first asked for),
// kept until the page is drawn again: not again at every key.
let menuValues = null;
// The table shows pageSize rows at a time: drawing stays fast whatever the
// data's size, and the page keeps working with Ctrl+F and screen readers
// (no virtual scrolling). ?page= in the address, past the first; ?per= for
// another of PAGE_SIZES (only those: a huge one would draw every package at
// once), also picked under the table.
// Of those, drawn first, with the counts and tiles: more than a screen's
// worth; the rest follow a moment later (update).
const FIRST_ROWS = 50;

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
  const read = readState(new URLSearchParams(location.search), KNOWN);
  Object.assign(state, read.state);
  // ?q= may hold qualifiers too (is:builds on:darwin): they set what they
  // name, over the address's other parameters.
  const typed = parseQuery(read.query);
  Object.assign(state, typed.fields);
  showQuery(typed.text, { force: true });
}

// The address for the current view, on page `page`.
function viewQuery(page = state.pageNum) {
  const query = searchText();
  const params = new URLSearchParams(location.search);
  return location.pathname + writeState(state, query, params, KNOWN, page);
}
function writeViewToUrl() {
  // replaceState, not pushState: typing a search shouldn't fill the history.
  history.replaceState(null, '', viewQuery() + location.hash);
}

// The Theme menu. theme.js applied the saved choice before the page drew;
// this keeps it, and the page's default from the data, in the browser
// (localStorage: nothing is sent anywhere) and applies changes.
const SITE_PALETTE = `nixkeeper-site-palette:${location.pathname}`;

// What a package's panel (package-view.js) needs of the page: a package's
// address, hiding it, whether it needs attention (the list's tiles), and
// drawing the page again (after its team and maintainer buttons).
const panelPage = {
  pkgHref: (name) => scopeHref({ pkg: name }),
  isHidden: (pkg) => isHidden(pkg),
  setHidden: (pkg, hide) => setHidden(pkg, hide),
  needsAttention: (pkg) =>
    ['warn', 'builds', 'updates', 'vuln', 'broken'].some((k) => FILTERS[k]?.test(pkg)),
  update: (options) => update(options),
};

function setHidden(pkg, hide) {
  if (hide) hiddenPrints[pkg.name] = attentionPrint(pkg, store.checkedAt);
  else delete hiddenPrints[pkg.name];
  remember(HIDDEN_KEY, Object.keys(hiddenPrints).length ? JSON.stringify(hiddenPrints) : '');
  announce(hide ? `${pkg.name} hidden until it changes` : `${pkg.name} shown again`);
  update({ keepPage: true });
}

function setPrHidden(number, hide) {
  const pr = (store.mergeList || []).find((p) => p.number === number);
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
  remember(SITE_PALETTE, palette);
  applyTheme();
}

function showLegend(open) {
  document.getElementById('legendPanel').hidden = !open;
  document.getElementById('legendBtn').setAttribute('aria-expanded', open);
}

function showSources(open) {
  document.getElementById('sourcesPanel').hidden = !open;
  document.getElementById('checked').setAttribute('aria-expanded', open);
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
  if (!problems.length) {
    el.textContent = '';
    return;
  }
  setHtml(
    el,
    html`⚠ ${problems.length === 1 ? 'A problem' : `${problems.length} problems`} in the package lists, found by the last sync:
      <ul>${problems.map((p) => html`<li>${p}</li>`)}</ul>`,
  );
}

// The summary's entries, a short one per package (summary.json).
async function summaryOf() {
  return (await readJson('summary.json')).packages || [];
}

// A package's full row (what its panels show): its shard's, loaded once (a
// failed load isn't kept, so opening it again tries again). null if it
// couldn't be loaded.
async function fullRow(pkg) {
  return fullRowOf(pkg.name, store.shardCount, (row) => withRunStamps(row, store.checkedAt));
}

// With every package: load the view the address asks for (viewPath) into
// `packages`, unless it's there already. A maintainer, team or list with no
// file has no packages here. Throws if a view can't be loaded.
async function ensureView() {
  const asked = {
    pkg: state.pkgParam,
    query: searchText(),
    team: state.teamFilter,
    list: state.listFilter,
    set: state.setFilter,
    view: state.viewParam,
    cause: state.causeFilter,
  };
  let path = viewPath(asked);
  // ofteam:Python with no name: every match of the team, its own page (as
  // team:Python).
  if (path === 'overview' && state.matchTeam && asked.query.trim().length < 2) {
    state.teamFilter = state.matchTeam;
    state.matchTeam = null;
    lastAsked = null; // the box says ofteam:, the page team:
    path = viewPath({ ...asked, team: state.teamFilter });
  }
  // The overview has no list: a word for one (is:builds, age:1y...) opens
  // what needs attention, as a tile does, the box keeping the query.
  if (path === 'overview' && needsList(state)) {
    state.viewParam = 'attention';
    path = viewPath({ ...asked, view: 'attention' });
  }
  // Something else shown instead (a package, a maintainer...): ?set= and
  // ?view= no longer apply, and nothing on the page would take them off
  // again (a set's filter would hide every row: the other views leave out
  // what's pending).
  if (state.setFilter && path !== `views/set/${state.setFilter}.json`) state.setFilter = null;
  if (state.causeFilter && path !== `views/cause/${state.causeFilter}.json`)
    state.causeFilter = null;
  if (state.viewParam && path !== VIEWS[state.viewParam]) state.viewParam = null;
  if (path === store.shownView) return;
  store.wantedView = path;
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
    const data = await readJson(path, { missing: { packages: [] } });
    found = data.packages;
    store.causeShown = path.startsWith('views/cause/') ? data : null;
  }
  if (store.wantedView !== path) return; // another view was asked for meanwhile
  store.packages = found.map((p) => withRunStamps(p, store.checkedAt));
  pruneHidden(store.packages);
  store.shownView = path;
}

// history.json's points, for the overview's trends: loaded once, then the
// overview is drawn again. Without it (data from before, or not yet), the
// cards have no line.
function loadHistory() {
  if (store.historyLoading) return;
  store.historyLoading = true;
  readJson('history.json', { otherwise: { points: [] } })
    .then((data) => {
      store.trendPoints = data.points || [];
      store.trendEvents = data.events || [];
      if (store.shownView === 'overview') renderScope();
    })
    .catch(() => {
      store.trendPoints = [];
    });
}

// The name index, for searches beyond the view shown: loaded once, when a
// search first needs it, then the list is drawn again.
// With every package: every maintainer (maintainers.json: [handle, packages,
// outdated, failing]), loaded when a search starts with @ or the maintainers
// page opens; then the list is drawn again.
function loadMaintainers() {
  if (store.maintainersLoading) return;
  store.maintainersLoading = readJson('maintainers.json', { otherwise: { maintainers: [] } })
    .then((data) => {
      store.maintainersList = data.maintainers || [];
      update({ keepPage: true });
    })
    .catch(() => {
      store.maintainersLoading = null; // tried again with the next search
    });
}

function loadMerge() {
  if (store.mergeLoading) return;
  store.mergeLoading = readJson('views/merge.json', { otherwise: { prs: [] } })
    .then((data) => {
      store.mergeList = data.prs || [];
      // Hidden PRs that changed, or left the list: not hidden anymore.
      const now = new Map(store.mergeList.map((p) => [String(p.number), prPrint(p)]));
      for (const number of Object.keys(hiddenPrPrints))
        if (now.get(number) !== hiddenPrPrints[number]) delete hiddenPrPrints[number];
      saveHiddenPrs();
      update({ keepPage: true });
    })
    .catch(() => {
      store.mergeLoading = null; // tried again with the next view
    });
}

function loadNames() {
  if (store.namesLoading) return;
  store.namesLoading = readJson('names.json', { otherwise: { names: [] } })
    .then((data) => {
      store.names = data.names || [];
      update({ keepPage: true });
    })
    .catch(() => {
      store.namesLoading = null; // tried again with the next search
    });
}

// The search's maintainer, team and platform filters' data (facets.json),
// on first use: about 120 KB.
function loadFacets() {
  if (store.facetsLoading || !store.names) return;
  store.facetsLoading = readJson('facets.json', { otherwise: null })
    .then((data) => {
      const found = data ? decodeFacets(data) : [];
      if (found.length === store.names.length) {
        store.facetIndex = found;
        store.nameIndex = new Map(store.names.map((entry, i) => [entry, i]));
        update({ keepPage: true });
      }
    })
    .catch(() => {
      store.facetsLoading = null; // tried again with the next search
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
  const took = timer('update');
  menuValues = null;
  lastAsked = asking();
  // The box says the filters the chips and selects set (not while typed in).
  showQuery();
  if (store.community) {
    try {
      await ensureView();
    } catch {
      setHtml(
        document.getElementById('content'),
        html`<div class="error">
        Couldn't load these packages' data. Reload the page to try again.</div>`,
      );
      return;
    }
  }
  showProblems();
  took.lap('view');
  await yieldToBrowser();
  if (run !== updateRun) return;
  took.lap('browser');
  const list = currentFiltered();
  took.lap('filter');
  await yieldToBrowser();
  if (run !== updateRun) return;
  took.lap('browser');
  await render(list, { keepPage, run, took });
  took.done();
}

async function loadIndex() {
  const content = document.getElementById('content');
  if (!(await locateData())) {
    doneLoading();
    setHtml(
      content,
      html`<div class="error">
      Couldn't find the data to show.<br>
      Serve it as <code>data/</code> next to this page, set it with
      <code>&lt;meta name="nixkeeper-data"&gt;</code> in <code>index.html</code>,
      or open this from its GitHub Pages site.
    </div>`,
    );
    return;
  }
  try {
    const data = await readJson('index.json');
    if (!(data.format >= 2 && data.shardCount)) {
      // Format 1, which only nixkeeper 0.11.0 and before write alone.
      doneLoading();
      setHtml(
        content,
        html`<div class="error">
        This data is from nixkeeper 0.11.0 or older, which this page no longer reads.<br>
        The next sync rewrites it.
      </div>`,
      );
      return;
    }
    store.checkedAt = data.checkedAt || null;
    store.sources = data.sources || null;
    store.shardCount = data.shardCount;
    if (data.allPackages) {
      store.community = true;
      store.manifest = data;
      // The teams ofteam: names (search.js), as the data writes them.
      known.TEAMS = Object.keys(data.views?.teams || {});
      listView.myHandle = stored('nixkeeper-handle');
      listView.myTeam = stored('nixkeeper-team');
      loadMyCount();
    } else {
      store.packages = (await summaryOf()).map((p) => withRunStamps(p, store.checkedAt));
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
    setHtml(
      content,
      html`<div class="error">
      Couldn't load <code>${dataUrl('index.json')}</code>.<br>
      Check that the sync has run at least once (and, on GitHub, that the repo is public).
    </div>`,
    );
  }
}

function loadMyCount() {
  if (!listView.myHandle) return;
  const handle = listView.myHandle;
  readJson(`views/maintainer/${handle.toLowerCase()}.json`, { otherwise: { packages: [] } })
    .then((data) => {
      if (handle !== listView.myHandle) return; // changed meanwhile
      listView.myCount = (data.packages || []).length;
      renderLists();
    })
    .catch(() => {});
}

// The packages the table shows, in order: a row's data-i is its place here.
let shown = [];
// The folds opened (by key, until reload); the folds drawn are listView's.

// The pages of the list, when there's more than one: "1–200 of 241" and
// links to the others (real links, so one can open in a new tab).
function pagerHtml(total, pages) {
  // The page size can be picked whenever a smaller one would split the list
  // (and so be put back after picking a bigger one).
  const sizes =
    total > PAGE_SIZES[0]
      ? html`<label class="page-size">Per page <select data-per aria-label="Packages per page">${PAGE_SIZES.map(
          (n) =>
            html`<option value="${n}"${n === state.pageSize ? raw(' selected') : ''}>${n}</option>`,
        )}</select></label>`
      : '';
  if (pages < 2) return sizes ? html`<nav class="pager" aria-label="Pages">${sizes}</nav>` : '';
  const first = (state.pageNum - 1) * state.pageSize + 1;
  const last = Math.min(state.pageNum * state.pageSize, total);
  const link = (p, text, label) =>
    p === state.pageNum
      ? html`<span class="page-btn" aria-current="page">${text}</span>`
      : html`<a class="page-btn" href="${viewQuery(p)}" data-page="${p}"${label ? html` aria-label="${label}"` : ''}>${text}</a>`;
  return html`<nav class="pager" aria-label="Pages">
    <span class="page-count">${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()}</span>
    ${state.pageNum > 1 ? link(state.pageNum - 1, '‹', 'Previous page') : ''}
    ${pageLinks(state.pageNum, pages).map((p) => (p === null ? html`<span class="page-gap" aria-hidden="true">…</span>` : link(p, String(p), `Page ${p}`)))}
    ${state.pageNum < pages ? link(state.pageNum + 1, '›', 'Next page') : ''}
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

async function render(list, { keepPage = false, run = updateRun, took = timer('render') } = {}) {
  doneLoading();
  // How many packages a change leaves, to hear without looking.
  if (
    rendered &&
    !(store.community && store.shownView === 'overview') &&
    store.shownView !== 'maintainers'
  )
    announce(`${fmt(list.length)} ${list.length === 1 ? 'package' : 'packages'}`, 700);
  rendered = true;
  renderStats();
  took.lap('stats');
  renderScope();
  took.lap('header');
  const content = document.getElementById('content');
  if (store.community && store.shownView === 'maintainers') {
    // Maintainers, not packages: paged by their own count (maintainersHtml).
    if (!keepPage) state.pageNum = 1;
    shown = [];
    setHtml(content, maintainersHtml(pagerHtml));
    writeViewToUrl();
    return;
  }
  // One update moving many packages: one row (foldFamilies), alike by dot.
  ({
    list,
    folds: listView.folds,
    inOpen: listView.inOpenFold,
  } = foldFamilies(list, computeStatus, listView.openFolds));
  const pages = Math.max(1, Math.ceil(list.length / state.pageSize));
  state.pageNum = keepPage ? Math.min(state.pageNum, pages) : 1;
  writeViewToUrl();
  shown = list.slice((state.pageNum - 1) * state.pageSize, state.pageNum * state.pageSize);
  if (store.community && store.shownView === 'overview') {
    // The overview lists nothing: its header has the ways in (renderScope),
    // and a search finds packages in all of nixpkgs.
    setHtml(content, moreMatchesHtml());
    return;
  }
  if (!list.length) {
    const narrowed =
      state.refines.size || state.ageFilter || state.becauseFilter || state.buildFailedFilter;
    const handle = searchText().trim();
    if (store.community && /^@\S/.test(handle) && !narrowed && state.activeFilter === 'all') {
      // No such maintainer (yet: still typing): the ones whose handle matches.
      setHtml(
        content,
        html`<div class="empty">No maintainer is ${handle}.</div>${moreMatchesHtml()}`,
      );
      return;
    }
    const which = narrowed
      ? ' these filters'
      : state.activeFilter !== 'all' && !searchText().trim()
        ? ` the “${FILTERS[state.activeFilter].label}” filter`
        : '';
    setHtml(
      content,
      html`<div class="empty">No packages match${which}${store.community ? ' here' : ''}.</div>${moreMatchesHtml()}`,
    );
    return;
  }
  setHtml(
    content,
    html`<div class="wrap"><table>
    <thead><tr>
      <th style="padding-left:10px">Package</th><th>nixpkgs unstable</th><th>Open on GitHub</th><th>Build failures</th><th>Update failures</th><th><span class="sr-only">Details</span></th>
    </tr></thead>
    <tbody id="rows">${shown.slice(0, FIRST_ROWS).map(rowHtml)}</tbody>
  </table></div>${pagerHtml(list.length, pages)}${moreMatchesHtml()}`,
  );
  took.lap('rows');
  watchErrors();
  // One package shown by its link (?pkg=): its details open at once, the
  // reason the link was followed.
  if (state.pkgParam && list.length === 1 && pkgOpenedFor !== state.pkgParam) {
    pkgOpenedFor = state.pkgParam;
    const tr = document.querySelector('#rows tr.row');
    if (tr) toggle(tr, 'info');
  }
  // The rest of the page's rows, below the screen, a moment later.
  if (shown.length <= FIRST_ROWS) return;
  await yieldToBrowser();
  if (run !== updateRun) return;
  took.lap('browser');
  const rows = document.getElementById('rows');
  if (rows) {
    appendHtml(
      rows,
      html`${shown.slice(FIRST_ROWS).map((pkg, i) => rowHtml(pkg, FIRST_ROWS + i))}`,
    );
  }
  took.lap('more rows');
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
  setHtml(
    detail,
    html`<td colspan="6"><div class="detail-inner">
      <div class="nix-line">Loading its builds…</div>
    </div></td>`,
  );
  tr.after(detail);
  const row = await fullRow(pkg);
  const inner = detail.querySelector('.detail-inner');
  if (row) fillBuilds(row, inner, panelPage);
  else setHtml(inner, html`<div class="nix-line">Couldn't load its builds.</div>`);
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
  el.hidden = !store.community;
  if (!store.community) return;
  if (store.shownView === 'maintainers') {
    el.dataset.drawn = '';
    setHtml(
      el,
      html`<div class="scope-view">
      <span class="scope-label">Showing</span>
      <span class="view-chip">Maintainers · ${fmt(store.maintainersList?.length)}<a class="view-x" href="${scopeHref({})}" data-scope-home aria-label="Back to the overview" title="Back to the overview">✕</a></span>
      <span class="scope-hint">by handle; the search narrows them, and one opens their packages</span>
    </div>`,
    );
    return;
  }
  if (store.shownView !== 'overview') {
    el.dataset.drawn = '';
    setHtml(el, listHeaderHtml(loadMerge));
    return;
  }
  // Drawn again only when it changes (its history arrives, a team is
  // picked), not while someone types in its search box.
  const drawn = `${store.trendPoints?.length ?? -1}:${store.trendEvents.length}:${state.teamFilter || ''}:${Object.values(highlightShown)}:${store.allCauses ? 'all' : ''}`;
  if (el.dataset.drawn !== drawn) {
    el.dataset.drawn = drawn;
    setHtml(el, overviewHtml());
  }
  // While searching, the matches (drawn under the overview) get the room:
  // the newest and longest-standing and the sets updated in bulk step aside, and
  // come back once the search is cleared.
  const query = searchText();
  const more = el.querySelector('.overview-more');
  if (more) more.hidden = Boolean(query.trim());
}

// Show a view: set (a generated set), pkg (one package), neither: what needs
// attention. The search, filters and page start over.
function showView({ set = null, pkg = null, view = null, filter = null, cause = null }) {
  state.setFilter = set;
  state.causeFilter = cause;
  state.pkgParam = pkg;
  state.viewParam = view;
  state.teamFilter = null;
  state.teamsLeftOut = [];
  state.noTeam = false;
  state.maintainersLeftOut = [];
  state.listFilter = null;
  state.activeFilter = filter || 'all';
  state.refines = new Set();
  state.ageFilter = null;
  state.becauseFilter = null;
  state.buildFailedFilter = null;
  state.platformFilter = null;
  state.inFilter = null;
  state.byFilter = null;
  state.statusFilter = null;
  state.matchTeam = null;
  state.newerFilter = null;
  state.showErrors = false;
  showQuery('', { force: true });
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
  if (!store.maintainersList) {
    loadMaintainers();
    return html`<div class="more-matches"><div class="other-label">Looking up maintainers…</div></div>`;
  }
  const typed = query.trim().slice(1).toLowerCase();
  const { found, total } = maintainerMatches(store.maintainersList, query, 20);
  // On the overview (typing in its box), the handle itself too: nothing
  // else shows it yet.
  const others =
    store.shownView === 'overview'
      ? found
      : found.filter(([handle]) => handle.toLowerCase() !== typed);
  if (!others.length) return NO_MARKUP;
  return html`<div class="more-matches">
    <div class="other-label">${typed && total > others.length ? 'Other maintainers' : 'Maintainers'} matching @${typed}${total > found.length ? html`, the first ${found.length}` : ''}</div>
    <ul class="maint-list">${others.map(maintainerItem)}</ul>
  </div>`;
}

function moreMatchesHtml() {
  matchCounts = null;
  menuValues = null;
  const query = searchText();
  if (
    store.community &&
    !state.pkgParam &&
    store.shownView !== 'maintainers' &&
    /^@\S/.test(query.trim())
  )
    return maintainerMatchesHtml(query);
  if (!store.community || state.pkgParam || query.trim().length < 2 || query.trim().startsWith('@'))
    return NO_MARKUP;
  if (!store.names) {
    loadNames();
    return html`<div class="more-matches"><div class="other-label">Searching all of nixpkgs…</div></div>`;
  }
  // Another search, or other filters: from the first ones again.
  const asked = [
    query.trim(),
    state.inFilter,
    state.statusFilter,
    state.byFilter,
    state.matchTeam,
    state.platformFilter,
  ].join('\n');
  if (asked !== matchQuery) {
    matchQuery = asked;
    matchLimit = MATCHES_SHOWN;
  }
  const { found: all, total } = nameMatches(
    store.names,
    query,
    new Set(store.packages.map((p) => p.name)),
    Infinity,
  );
  if (!total) return NO_MARKUP;
  const narrowed =
    state.inFilter ||
    state.statusFilter ||
    state.byFilter ||
    state.matchTeam ||
    state.platformFilter;
  if (total > 1 || narrowed) loadFacets();
  const { kept, sets, statuses, by, teams, platforms } = matchFacets(
    all,
    {
      set: state.inFilter,
      status: state.statusFilter,
      by: state.byFilter,
      team: state.matchTeam,
      platform: state.platformFilter,
    },
    store.facetIndex ? facetsOf : null,
  );
  matchCounts = { sets, statuses, by, teams, platforms };
  menuValues = null;
  const shownHere = kept.slice(0, matchLimit);
  const setLabel = (v) => (v === TOP_LEVEL ? 'top level' : v);
  // python3Packages (an alias, ?in=): offered with its sets' counts together.
  const aliasCount = (v) => sets.filter(([s]) => inPickedSet(s, v)).reduce((n, [, c]) => n + c, 0);
  const setChoices =
    state.inFilter && !sets.some(([v]) => v === state.inFilter)
      ? [...sets, [state.inFilter, aliasCount(state.inFilter)]]
      : sets;
  const statusChoices =
    state.statusFilter && !statuses.some(([v]) => v === state.statusFilter)
      ? [...statuses, [state.statusFilter, 0]]
      : statuses;
  return html`<div class="more-matches">
    <div class="other-label">${total.toLocaleString()} ${store.shownView === 'overview' ? '' : 'more '}${total === 1 ? 'package matches' : 'packages match'} in all of nixpkgs${narrowed ? html`, ${kept.length.toLocaleString()} with these filters` : ''}</div>
    ${
      // Shown whenever one is picked, even for one match: else a filter
      // from an earlier search would hide it, with no way to undo it.
      total > 1 || narrowed
        ? html`<div class="refine match-filters" role="group" aria-label="Narrow the matches"><label class="refine-age" title="Only one package set, by the attribute's first part (python313Packages, vimPlugins), or the top-level packages: the list above too. Each with how many match.">In <select data-in><option value="">any set</option>${setChoices.map(
            ([v, n]) => facetOption(v, setLabel(v), n, state.inFilter),
          )}</select></label><label class="refine-age" title="Only the matches with this status, as their dot says. Each with how many match.">Status <select data-status><option value="">any status</option>${statusChoices.map(
            ([v, n]) => facetOption(v, NAME_STATUSES[v], n, state.statusFilter),
          )}</select></label>${store.facetIndex ? matchFacetsHtml(by, teams, platforms) : ''}${
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
    state.matchTeam && !teams.some(([t]) => t === state.matchTeam)
      ? [...teams, [state.matchTeam, 0]]
      : teams;
  return html`<label class="refine-age" title="Only the matches this maintainer is listed for (meta.maintainers): type a GitHub handle; those with the most matches are offered, each with how many. The list above too.">By <input type="search" class="by-pick" data-by list="matchByOptions" placeholder="any maintainer" value="${state.byFilter || ''}" autocomplete="off" spellcheck="false"><datalist id="matchByOptions">${by
    .slice(0, BY_SHOWN)
    .map(([h, n]) => html`<option value="${h}">${fmt(n)}</option>`)}</datalist></label>${
    teamChoices.length
      ? html`<label class="refine-age" title="Only the matches of this nixpkgs team (meta.teams). Each with how many match.">Team <select data-match-team><option value="">any team</option>${teamChoices.map(
          ([t, n]) => facetOption(t, t, n, state.matchTeam),
        )}</select></label>`
      : ''
  }<label class="refine-age" title="Only the matches available there (meta.platforms). Darwin is macOS. Each with how many match. The list above too.">On <select data-platform-pick><option value="">any platform</option>${Object.entries(
    PLATFORMS,
  ).map(([key, p]) =>
    facetOption(key, p.label, platforms[key] ?? 0, state.platformFilter),
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
    setHtml(
      detail,
      html`<td colspan="6"><div class="detail-inner">
      <div class="nix-line">Loading detail…</div>
    </div></td>`,
    );
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
    setHtml(
      inner,
      html`<div class="nix-line">Couldn't load this package's details. Open it again to retry.</div>`,
    );
  } else if (mode === 'build') fillBuilds(row, inner, panelPage);
  else if (mode === 'update') fillUpdate(row, inner);
  else fillDetail(row, inner, entries, panelPage);
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

// What the views' controls (wireList, wireOverview, wireMaintainerView)
// need of the page: drawing it again, a row's panel, the views, Your
// packages and Your team, copying, hiding a PR. Each a call, not the
// function itself: some are defined further down.
const pageHooks = {
  update: (...a) => update(...a),
  renderScope: (...a) => renderScope(...a),
  toggle: (...a) => toggle(...a),
  copyTitle: (...a) => copyTitle(...a),
  showView: (...a) => showView(...a),
  showMine: (...a) => showMine(...a),
  showMyTeam: (...a) => showMyTeam(...a),
  loadMyCount: (...a) => loadMyCount(...a),
  closeRows: (...a) => closeRows(...a),
  openRows: (...a) => openRows(...a),
  setPrHidden: (...a) => setPrHidden(...a),
};
wireList(pageHooks);
wireOverview(pageHooks);
wireMaintainerView(pageHooks);
// The search box's menu: the qualifiers, then their values with counts.
wireSearchMenu(() => {
  menuValues ??= searchValues(matchCounts);
  return menuValues;
});

// The search's matches in all of nixpkgs: the next ones, or every one again
// (moreMatchesHtml).
document.addEventListener('click', (e) => {
  if (e.target.closest('button[data-more-matches]')) {
    matchLimit += MATCHES_MORE;
    update({ keepPage: true });
  } else if (e.target.closest('button[data-clear-matches]')) {
    state.inFilter = null;
    state.statusFilter = null;
    state.byFilter = null;
    state.matchTeam = null;
    state.platformFilter = null;
    update();
  }
});

// Typing redraws the table once it pauses (250 ms, longer than between
// two keys typed on), not at every key: with thousands of packages, each
// redraw takes a moment. And only when what's asked changed (asking, as of
// the last update()).
let searchTimer;
document.getElementById('search').addEventListener('input', () => {
  state.pkgParam = null; // a search leaves a package shown alone (?pkg=)
  clearTimeout(searchTimer);
  // Its qualifiers set the filters (search.js), the rest is searched for.
  searchTimer = setTimeout(() => {
    boxProblems = readBox();
    // Nothing new asked (is: before its value, a space): no redraw.
    if (asking() === lastAsked) showProblems();
    else update();
  }, 250);
});
// Left, the box written as the state says (its words in their usual
// order), unless something in it isn't understood: that stays, to fix.
document.getElementById('search').addEventListener('blur', () => {
  if (!parseQuery(document.getElementById('search').value).problems.length) showQuery();
});
// What the box couldn't read, under it: "no is:biulds: is:builds?"; else,
// while it's typed in, what a word waits for (matchNote: status: or
// ofteam: with no name), quieter. After update(): as the state ends up.
let boxProblems = [];
function showProblems(problems = boxProblems) {
  const box = document.getElementById('search');
  const el = document.getElementById('searchProblems');
  const note = problems.length ? null : matchNote(state, searchText());
  box.setAttribute('aria-invalid', String(problems.length > 0));
  el.hidden = !problems.length && !note;
  el.classList.toggle('note', Boolean(note));
  el.textContent =
    note ||
    problems.map((p) => `${p.message}${p.suggestion ? `: ${p.suggestion}?` : ''}`).join(' · ');
}
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
  search.value = writeQuery(state, `@${a.dataset.maintainer}`);
  search.dispatchEvent(new Event('input'));
});
// The visitor's packages (their maintainer view), or (show false) back to
// the overview.
function showMine(show) {
  showView({});
  if (!show) return;
  const search = document.getElementById('search');
  search.value = writeQuery(state, `@${listView.myHandle}`);
  search.dispatchEvent(new Event('input'));
}
// The visitor's team's packages, or (show false) back to the overview.
function showMyTeam(show) {
  showView({});
  if (!show) return;
  state.teamFilter = listView.myTeam;
  update();
}

document.addEventListener('change', (e) => {
  if (e.target.id !== 'teamPick') return;
  // A team's packages, from all of nixpkgs (not within a set or a package).
  state.teamFilter = e.target.value || null;
  state.setFilter = null;
  state.causeFilter = null;
  state.pkgParam = null;
  state.viewParam = null;
  update();
});

// "/" jumps to the filter, as on GitHub; Escape in it clears it.
document.addEventListener('keydown', (e) => {
  const search = document.getElementById('search');
  if (e.key === '/' && !e.target.closest('input, textarea') && !search.disabled) {
    e.preventDefault();
    // The caret at the end: the menu offers what comes next.
    search.setSelectionRange(search.value.length, search.value.length);
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
    // The name or @handle cleared, what's typed and not read yet dropped;
    // the filters stay, as the chips set them. Not the browser's own
    // clearing of a search field: its input event would read the empty
    // box as no filters.
    e.preventDefault();
    search.value = writeQuery(state, '');
    clearTimeout(searchTimer);
    boxProblems = [];
    update();
  }
});

document
  .getElementById('themeBtn')
  .addEventListener('click', () => showThemePanel(document.getElementById('themePanel').hidden));
document.getElementById('themePanel').addEventListener('change', (e) => {
  const { name, value } = e.target;
  if (name === 'palette') remember('nixkeeper-palette', value);
  // Auto is no choice: the system's setting.
  if (name === 'mode') remember('nixkeeper-mode', value === 'auto' ? null : value);
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
