// The list: its header (where it's from, the tiles, the refines and facets,
// Your packages and Your team), each package's row and its cells (version,
// builds, updates, GitHub), and the sources it was worked out from. HTML
// from the store, the state and the filters; app.js draws it (render) and
// handles its controls. Its own state is listView.

import { timeAgo } from './dates.js';
import { NAME_STATUSES } from './facets.js';
import {
  AGES,
  FILTERS,
  filtering,
  inList,
  inPeople,
  inPlatform,
  notHidden,
  PLATFORMS,
  REFINES,
  refined,
  SORTS,
} from './filters.js';
import {
  allLists,
  becauseCounts,
  buildFailedCounts,
  facetOptions,
  isMine,
  isMyTeam,
  MANIFEST_COUNTS,
  mineHtml,
  myTeamHtml,
  refineHtml,
  teamOutChips,
} from './list-controls.js';
import { html, raw, setHtml } from './markup.js';
import { faviconKey } from './palette.js';
import { remember } from './prefs.js';
import { REFINE_WORDS } from './search.js';
import { sourcesHtml } from './sources.js';
import { listView, state, teamName } from './state.js';
import { store } from './store.js';
import { BUILD_FAILED, FAILED_BECAUSE, fmt } from './ui.js';

// The sync runs daily; older than this means runs are failing or GitHub has
// paused the schedule (it does after 60 days without commits).
const STALE_AFTER_HOURS = 48;

// The tab's icon shows what needs attention among packages (faviconKey).
function setFavicon(base) {
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
