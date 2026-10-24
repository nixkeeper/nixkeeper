// The search box as a query, as GitHub's is: the list's filters written as
// qualifiers (is:builds on:darwin age:1y), beside the name or @handle
// searched for. parseQuery reads one into the state's fields, writeQuery
// writes the state back; both pure, with the address's own words
// (tests/js/search.test.mjs). The chips and selects still set the state;
// the box shows it. Where the page is (a view, a set, a list, a cause, one
// package) stays the address's: not in the box.

import {
  maintainersParam,
  NAME_STATUSES,
  parseMaintainers,
  parseTeams,
  teamsParam,
} from './logic.js';
import { known, state } from './state.js';

// The refines (REFINES keys), as qualifiers.
const REFINE_WORDS = {
  unmaintained: '-has:maintainer',
  notbroken: '-is:broken',
  notonmaster: '-is:merged',
  stagingnext: 'is:staging-next-breaks',
  withpr: 'has:pr',
  nopr: '-has:pr',
  unbuilt: 'is:unbuilt',
  superseded: 'has:pr-to-close',
  nobot: 'is:bot-wont-update',
};
const REFINE_OF = Object.fromEntries(Object.entries(REFINE_WORDS).map(([k, w]) => [w, k]));

// What the box can hold, with what each is when it says nothing of it.
export const QUERY_FIELDS = {
  activeFilter: 'all',
  refines: () => new Set(),
  newerFilter: null,
  ageFilter: null,
  becauseFilter: null,
  buildFailedFilter: null,
  platformFilter: null,
  inFilter: null,
  byFilter: null,
  teamFilter: null,
  teamsLeftOut: () => [],
  noTeam: false,
  maintainersLeftOut: () => [],
  statusFilter: null,
  matchTeam: null,
  sortMode: 'pressing',
  sortReverse: false,
};
const KEYS = [
  'is',
  'has',
  'age',
  'update',
  'build',
  'on',
  'in',
  'by',
  'team',
  'maintainer',
  'status',
  'ofteam',
  'sort',
  'order',
];

// The fields a query sets, every other one as when it says nothing.
export const queryFields = (fields) => ({
  ...Object.fromEntries(
    Object.entries(QUERY_FIELDS).map(([k, v]) => [k, typeof v === 'function' ? v() : v]),
  ),
  ...fields,
});

// The closest of words to word (edit distance), for "did you mean": one
// within a third of its length, or none.
function closest(word, words) {
  const distance = (a, b) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++)
      for (let j = 1; j <= b.length; j++)
        d[i][j] = Math.min(
          d[i - 1][j] + 1,
          d[i][j - 1] + 1,
          d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
        );
    return d[a.length][b.length];
  };
  const best = words
    .map((w) => [w, distance(word.toLowerCase(), w.toLowerCase())])
    .sort((a, b) => a[1] - b[1])[0];
  return best && best[1] <= Math.max(1, Math.floor(word.length / 3)) ? best[0] : null;
}

// A query: { fields: those its qualifiers set, text: the rest (a name,
// @handle), problems: [{ token, message, suggestion? }] }. A value with
// spaces in quotes (ofteam:"Security review"). known: the page's tables
// ({ FILTERS, SORTS, PLATFORMS, REFINES, AGES }).
export function parseQuery(query, { FILTERS, SORTS, PLATFORMS, REFINES, AGES } = known) {
  const fields = {};
  const text = [];
  const problems = [];
  const teams = [];
  const leftOut = [];
  const tileParams = Object.fromEntries(
    Object.entries(FILTERS)
      .filter(([, f]) => f.param)
      .map(([k, f]) => [f.param, k]),
  );
  const refine = (word) => {
    const key = REFINE_OF[word];
    if (key && REFINES[key]) {
      fields.refines = new Set([...(fields.refines || []), key]);
      return true;
    }
    return false;
  };
  // words: what was likely meant, compared with the token's own form (as: a
  // whole qualifier with is: and has:, else its value).
  const problem = (token, message, words, as = token.split(':').pop()) => {
    const suggestion = words && closest(as, words);
    problems.push({ token, message, ...(suggestion ? { suggestion } : {}) });
  };
  for (const token of (query || '').match(/-?[A-Za-z]+:"[^"]*"|\S+/g) || []) {
    const m = token.match(/^(-?)([A-Za-z]+):(.*)$/);
    if (!m || /^@/.test(token)) {
      text.push(token);
      continue;
    }
    const [, neg, rawKey, rawValue] = m;
    const key = rawKey.toLowerCase();
    const value = rawValue.replace(/^"(.*)"$/, '$1');
    if (!KEYS.includes(key)) {
      problem(
        token,
        `no ${key}: qualifier`,
        KEYS.map((k) => `${k}:`),
        `${key}:`,
      );
      continue;
    }
    if (!value) {
      problem(token, `${key}: needs a value`);
      continue;
    }
    const word = `${neg}${key}:${value}`;
    if ((key === 'is' || key === 'has') && refine(word)) continue;
    if (key === 'is' && !neg && tileParams[value]) fields.activeFilter = tileParams[value];
    else if (key === 'has' && value === 'newer') fields.newerFilter = neg ? 'no' : 'yes';
    else if (key === 'is' || key === 'has')
      problem(
        token,
        `no ${word}`,
        [
          ...Object.keys(tileParams).map((p) => `is:${p}`),
          ...Object.values(REFINE_WORDS),
          'has:newer',
          '-has:newer',
        ],
        word,
      );
    else if (neg && key !== 'team' && key !== 'maintainer')
      problem(token, `-${key}: leaves nothing out`);
    else if (key === 'age')
      if (AGES[value]) fields.ageFilter = value;
      else problem(token, `no age:${value}`, Object.keys(AGES));
    else if (key === 'update' || key === 'build')
      if (/^[A-Za-z]{1,30}$/.test(value))
        fields[key === 'update' ? 'becauseFilter' : 'buildFailedFilter'] = value;
      else problem(token, `no ${key}: reason ${value}`);
    else if (key === 'on') {
      const platform = Object.keys(PLATFORMS).find((k) =>
        [PLATFORMS[k].param, PLATFORMS[k].also].includes(value),
      );
      if (platform) fields.platformFilter = platform;
      else
        problem(
          token,
          `no on:${value}`,
          Object.values(PLATFORMS).map((p) => p.param),
        );
    } else if (key === 'in')
      if (/^[\w.+-]{1,100}$/.test(value)) fields.inFilter = value;
      else problem(token, `no in:${value}`);
    else if (key === 'by') {
      const by = value.replace(/^@/, '').toLowerCase();
      if (/^[\w.-]{1,60}$/.test(by)) fields.byFilter = by;
      else problem(token, `no by:${value}`);
    } else if (key === 'team') teams.push(`${neg}${value}`);
    else if (key === 'maintainer')
      if (neg) leftOut.push(`-${value}`);
      else problem(token, "a maintainer's page: @handle", null);
    else if (key === 'status')
      if (NAME_STATUSES[value]) fields.statusFilter = value;
      else problem(token, `no status:${value}`, Object.keys(NAME_STATUSES));
    else if (key === 'ofteam')
      if (/^[\w .+-]{1,60}$/.test(value)) fields.matchTeam = value;
      else problem(token, `no ofteam:${value}`);
    else if (key === 'sort')
      if (SORTS[value]) fields.sortMode = value;
      else problem(token, `no sort:${value}`, Object.keys(SORTS));
    else if (key === 'order')
      if (value === 'reverse') fields.sortReverse = true;
      else problem(token, `order:${value}: only order:reverse`, ['reverse']);
  }
  if (teams.length) {
    const t = parseTeams(teams.join(','));
    Object.assign(fields, { teamFilter: t.include, teamsLeftOut: t.leftOut, noTeam: t.none });
  }
  if (leftOut.length) fields.maintainersLeftOut = parseMaintainers(leftOut.join(',')).leftOut;
  return { fields, text: text.join(' '), problems };
}

// The query for st's fields, then text: the qualifiers in the table's
// order, a value with spaces quoted.
export function writeQuery(st, text, { FILTERS, PLATFORMS } = known) {
  const quoted = (v) => (/\s/.test(v) ? `"${v}"` : v);
  const words = [];
  if (st.activeFilter !== 'all' && FILTERS[st.activeFilter]?.param)
    words.push(`is:${FILTERS[st.activeFilter].param}`);
  for (const key of Object.keys(REFINE_WORDS))
    if (st.refines.has(key)) words.push(REFINE_WORDS[key]);
  if (st.newerFilter) words.push(st.newerFilter === 'yes' ? 'has:newer' : '-has:newer');
  if (st.ageFilter) words.push(`age:${st.ageFilter}`);
  if (st.becauseFilter) words.push(`update:${st.becauseFilter}`);
  if (st.buildFailedFilter) words.push(`build:${st.buildFailedFilter}`);
  if (st.platformFilter)
    words.push(`on:${PLATFORMS[st.platformFilter]?.param || st.platformFilter}`);
  if (st.inFilter) words.push(`in:${st.inFilter}`);
  if (st.byFilter) words.push(`by:${st.byFilter}`);
  const teams = teamsParam({ include: st.teamFilter, leftOut: st.teamsLeftOut, none: st.noTeam });
  for (const t of teams ? teams.split(',') : [])
    words.push(t.startsWith('-') ? `-team:${quoted(t.slice(1))}` : `team:${quoted(t)}`);
  const leftOut = maintainersParam({ leftOut: st.maintainersLeftOut });
  for (const m of leftOut ? leftOut.split(',') : []) words.push(`-maintainer:${m.slice(1)}`);
  if (st.statusFilter) words.push(`status:${st.statusFilter}`);
  if (st.matchTeam) words.push(`ofteam:${quoted(st.matchTeam)}`);
  if (st.sortMode !== 'pressing') words.push(`sort:${st.sortMode}`);
  if (st.sortReverse) words.push('order:reverse');
  return [...words, (text || '').trim()].filter(Boolean).join(' ');
}

// The search box's free text: what's searched for by name, or @handle.
export const searchText = () => parseQuery(document.getElementById('search').value).text;

// The box written from the state, with text as its free text (the box's
// own, by default). Not while it's being typed in (what's typed stays),
// unless force (the page itself setting it: a view picked, an address).
export function showQuery(text = searchText(), { force = false } = {}) {
  const box = document.getElementById('search');
  if (!force && document.activeElement === box) return;
  box.value = writeQuery(state, text);
}

// What's typed set in the state: every field the box can hold, those it
// doesn't name back to nothing. Its problems, for the box to show.
export function readBox() {
  const { fields, problems } = parseQuery(document.getElementById('search').value);
  Object.assign(state, queryFields(fields));
  return problems;
}
