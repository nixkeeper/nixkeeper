// The page's filters, sort and paging, in one object (state), and the
// address they live in, so a view survives a reload and can be bookmarked
// or shared: readState and writeState, pure (tests/js/state.test.mjs), and
// a view's address (scopeHref). app.js changes the state (the chips, the
// selects, the search) and draws the page from it. Other parameters
// (owner, repo) are left alone. And the rules that follow the selected
// platform.
import { NAME_STATUSES } from './facets.js';
import { maintainersParam, parseMaintainers, parseTeams, teamsParam } from './people.js';
import {
  buildsWith as buildsOn,
  hasFailure as failureOn,
  attentionRank as rankOn,
} from './status.js';
import { store } from './store.js';

// The page's tables (FILTERS, SORTS, PLATFORMS, REFINES, AGES), by their
// keys: app.js gives them once (they hold the list's rules), for what here
// writes an address without being handed them (scopeHref).
export const known = {};

export const PAGE_SIZES = [50, 100, 200, 500, 1000];
export const DEFAULT_PAGE_SIZE = 200;

// What the address can hold, besides the search box's text (read and
// written apart: the box is the page's).
export const state = {
  activeFilter: 'all', // a FILTERS key: 'all' | 'warn' | 'failed' | 'vuln' ...
  maintainersLeftOut: [],
  sortMode: 'pressing',
  sortReverse: false,
  platformFilter: null, // null | 'linux' | 'darwin' ..., combined with activeFilter
  listFilter: null,
  teamFilter: null,
  teamsLeftOut: [],
  noTeam: false,
  setFilter: null,
  causeFilter: null,
  pkgParam: null,
  viewParam: null,
  refines: new Set(),
  ageFilter: null,
  becauseFilter: null,
  buildFailedFilter: null,
  inFilter: null,
  byFilter: null,
  statusFilter: null,
  newerFilter: null,
  showErrors: false,
  matchTeam: null,
  pageNum: 1,
  pageSize: DEFAULT_PAGE_SIZE,
};

// The state an address says, and the search box's text (query), from its
// parameters (URLSearchParams). known: the filters, sorts, platforms,
// refines and ages the page has ({ FILTERS, SORTS, PLATFORMS, REFINES,
// AGES }), by their keys; an unknown value is left out.
export function readState(params, { FILTERS, SORTS, PLATFORMS, REFINES, AGES }) {
  const read = {};
  read.activeFilter =
    Object.keys(FILTERS).find(
      (k) => FILTERS[k].param && FILTERS[k].param === params.get('filter'),
    ) || 'all';
  // A maintainer's page: ?maintainer=handle (the search shows @handle);
  // ?q=@handle, as it was first written, opens it too and becomes that.
  // -handle in it: their packages left out, on any list.
  const maintainers = parseMaintainers(params.get('maintainer'));
  read.maintainersLeftOut = maintainers.leftOut;
  const query = maintainers.handle ? `@${maintainers.handle}` : params.get('q') || '';
  read.sortMode = SORTS[params.get('sort')] ? params.get('sort') : 'pressing';
  read.sortReverse = params.get('order') === 'reverse';
  read.platformFilter =
    Object.keys(PLATFORMS).find((k) =>
      [PLATFORMS[k].param, PLATFORMS[k].also].includes(params.get('platform')),
    ) || null;
  // Any name: which lists exist is only known once the data has loaded.
  read.listFilter = params.get('list') || null;
  const teams = parseTeams(params.get('team'));
  read.teamFilter = teams.include;
  read.teamsLeftOut = teams.leftOut;
  read.noTeam = teams.none;
  read.setFilter = params.get('set') || null;
  read.causeFilter = /^[0-9a-f]{10}$/.test(params.get('cause') || '') ? params.get('cause') : null;
  read.pkgParam = params.get('pkg') || null;
  read.viewParam = params.get('view') || null;
  const refineKeys = (params.get('refine') || '').split(',');
  // refine=direct: ?team=none, as it was first called.
  if (refineKeys.includes('direct')) read.noTeam = true;
  read.refines = new Set(refineKeys.filter((key) => REFINES[key]));
  read.ageFilter = AGES[params.get('age')] ? params.get('age') : null;
  // Any reason the data may have (checked by the list, not here). ?because=
  // is its name from before ?buildFailed= came (2026-10-08), still read.
  const updateFailed = params.get('updateFailed') ?? params.get('because') ?? '';
  read.becauseFilter = /^[A-Za-z]{1,30}$/.test(updateFailed) ? updateFailed : null;
  const buildFailed = params.get('buildFailed') || '';
  read.buildFailedFilter = /^[A-Za-z]{1,30}$/.test(buildFailed) ? buildFailed : null;
  const inSetParam = params.get('in') || '';
  read.inFilter = /^[\w.+-]{1,100}$/.test(inSetParam) ? inSetParam : null;
  const by = (params.get('by') || '').replace(/^@/, '').toLowerCase();
  read.byFilter = /^[\w.-]{1,60}$/.test(by) ? by : null;
  read.statusFilter = NAME_STATUSES[params.get('status')] ? params.get('status') : null;
  read.newerFilter = ['yes', 'no'].includes(params.get('newer')) ? params.get('newer') : null;
  read.showErrors = params.get('errors') === '1';
  const ofTeam = params.get('ofteam') || '';
  read.matchTeam = /^[\w .+-]{1,60}$/.test(ofTeam) ? ofTeam : null;
  read.pageNum = Math.max(1, Number.parseInt(params.get('page'), 10) || 1);
  const per = Number(params.get('per'));
  read.pageSize = PAGE_SIZES.includes(per) ? per : DEFAULT_PAGE_SIZE;
  return { state: read, query };
}

// The address's query ("?filter=builds&platform=darwin", or "") for a
// state, the search box's text (query) and the page (page), over the
// address's other parameters (params, changed). known: as for readState.
export function writeState(st, query, params, { FILTERS, PLATFORMS }, page = st.pageNum) {
  const q = query.trim();
  const set = (k, v) => (v ? params.set(k, v) : params.delete(k));
  set('filter', FILTERS[st.activeFilter].param);
  // @handle in the search: ?maintainer=handle; anything else: ?q=.
  const handle = q.startsWith('@') && q.length > 1 ? q.slice(1) : '';
  set('maintainer', maintainersParam({ handle, leftOut: st.maintainersLeftOut }));
  set('q', handle ? '' : q);
  set('sort', st.sortMode === 'pressing' ? '' : st.sortMode);
  set('order', st.sortReverse ? 'reverse' : '');
  set('platform', st.platformFilter && PLATFORMS[st.platformFilter].param);
  set('list', st.listFilter);
  set('team', teamsParam({ include: st.teamFilter, leftOut: st.teamsLeftOut, none: st.noTeam }));
  set('set', st.setFilter);
  set('cause', st.causeFilter);
  set('pkg', st.pkgParam);
  set('view', st.viewParam);
  set('refine', [...st.refines].join(','));
  set('age', st.ageFilter);
  set('buildFailed', st.buildFailedFilter);
  set('updateFailed', st.becauseFilter);
  set('in', st.inFilter);
  set('by', st.byFilter);
  set('status', st.statusFilter);
  set('newer', st.newerFilter);
  set('errors', st.showErrors ? '1' : '');
  set('ofteam', st.matchTeam);
  params.delete('because'); // the old name, written as the new one
  set('page', page > 1 ? page : '');
  set('per', st.pageSize !== DEFAULT_PAGE_SIZE ? st.pageSize : '');
  // "@" and "," are fine in a query: ?q=@ and ?refine=a,b read better in
  // a shared link.
  const out = params.toString().replaceAll('%40', '@').replaceAll('%2C', ',');
  return out ? `?${out}` : '';
}

// The rules that follow the platform filter (status.js), on the selected one.
export const hasFailure = (pkg) => failureOn(pkg, state.platformFilter);

export const buildsWith = (pkg, status) => buildsOn(pkg, status, state.platformFilter);

export const failedBuilds = (pkg) => buildsWith(pkg, 'failed');

export const attentionRank = (pkg) => rankOn(pkg, state.platformFilter);

// The address of a view (scopeHref({ set }), { pkg }, {} for what needs
// attention): the others' parameters cleared, the data's own kept.
export function scopeHref({ set = null, pkg = null, view = null, filter = null, cause = null }) {
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
  if (filter && known.FILTERS[filter]?.param) params.set('filter', known.FILTERS[filter].param);
  const query = params.toString();
  return location.pathname + (query ? `?${query}` : '');
}

// null, or a nixpkgs team (meta.teams, by its short name; any case):
// ?team=gaming is a page of the team's packages here.
// ?team= besides one team: teams left out (-Geospatial), and none (not
// through a team: people.js parseTeams).
// ?maintainer='s handles left out (-iedame), lowercase.
export const isTeam = (name) => name.toLowerCase() === state.teamFilter.toLowerCase();

// The team's name as nixpkgs writes it ("Qt-KDE"), or as the address has it.
export const teamName = () =>
  store.packages.flatMap((p) => p.teams || []).find(isTeam) || state.teamFilter;

export function maintainerHref(handle) {
  const params = new URLSearchParams(new URL(scopeHref({}), location.href).search);
  params.set('maintainer', handle);
  return `${location.pathname}?${params.toString()}`;
}
