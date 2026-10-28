// The search box as a query, as GitHub's is: the list's filters written as
// qualifiers (is:builds on:darwin age:1y), beside the name or @handle
// searched for. parseQuery reads one into the state's fields, writeQuery
// writes the state back; both pure, with the address's own words
// (tests/js/search.test.mjs). The chips and selects still set the state;
// the box shows it. Where the page is (a view, a set, a list, a cause, one
// package) stays the address's: not in the box.

import { NAME_STATUSES } from './facets.js';
import { html, setHtml } from './markup.js';
import { maintainersParam, parseMaintainers, parseTeams, teamsParam } from './people.js';
import { known, state } from './state.js';

// The refines (REFINES keys), as qualifiers.
export const REFINE_WORDS = {
  unmaintained: '-has:maintainer',
  notbroken: '-is:broken',
  notonmaster: '-is:merged',
  stagingnext: 'is:staging-next-breaks',
  withpr: 'has:pr',
  nopr: '-has:pr',
  unbuilt: 'is:unbuilt',
  superseded: 'has:pr-to-close',
  nobot: 'is:bot-wont-update',
  upstream: 'has:upstream',
  upstreamgone: 'is:upstream-gone',
  upstreamarchived: 'is:upstream-archived',
  upstreamrenamed: 'is:upstream-renamed',
  upstreammoved: 'is:upstream-moved',
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

// The fields the matches in all of nixpkgs read too (on the overview, under
// a name): status:, ofteam:, on:, in:, by:, and team: (a team's page).
const MATCH_FIELDS = new Set([
  'statusFilter',
  'matchTeam',
  'platformFilter',
  'inFilter',
  'byFilter',
  'teamFilter',
]);
// Whether st sets a field only a list reads (is:, has:, age:, -team:,
// sort:...): on the overview, which has none, it opens what needs
// attention, as a tile does.
export const needsList = (st) =>
  Object.entries(QUERY_FIELDS).some(([k, v]) => {
    if (MATCH_FIELDS.has(k)) return false;
    if (typeof v !== 'function') return st[k] !== v;
    const value = st[k];
    return Boolean(value && (value.size ?? value.length));
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

// A value as the box writes it: in quotes with spaces.
const quoted = (v) => (/\s/.test(v) ? `"${v}"` : v);

// A query: { fields: those its qualifiers set, text: the rest (a name,
// @handle), problems: [{ token, message, suggestion? }] }. A value with
// spaces in quotes (ofteam:"Security review"). known: the page's tables
// ({ FILTERS, SORTS, PLATFORMS, REFINES, AGES }, and TEAMS once the data
// says them: nixpkgs' teams, as the matches name them).
export function parseQuery(
  query,
  { FILTERS, SORTS, PLATFORMS, REFINES, AGES, TEAMS = [] } = known,
) {
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
    // Not finished yet (is:): nothing set, and nothing to say.
    if (!value) continue;
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
    else if (key === 'ofteam') {
      // As the team is written (ofteam:python is Python's): the matches
      // compare it exactly. Before the data says the teams, as typed.
      const team = TEAMS.find((t) => t.toLowerCase() === value.toLowerCase());
      if (team) fields.matchTeam = team;
      else if (!TEAMS.length && /^[\w .+-]{1,60}$/.test(value)) fields.matchTeam = value;
      else
        problem(
          token,
          `no ofteam:${value}`,
          TEAMS.map((t) => `ofteam:${quoted(t)}`),
          `ofteam:${value}`,
        );
    } else if (key === 'sort')
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
// Parsed once for each value the box has: the filters ask for it for every
// package (inPeople's shownHandle), and parsing at each took 150 ms a
// redraw with qualifiers typed.
let parsedBox = { value: null, text: '' };
export const searchText = () => {
  const { value } = document.getElementById('search');
  if (value !== parsedBox.value) parsedBox = { value, text: parseQuery(value).text };
  return parsedBox.text;
};

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

// What st's words for the matches in all of nixpkgs (status:, ofteam:)
// wait for: a name (two letters or more, not an @handle) to list them.
// null once there's one, or with neither word.
export function matchNote(st, text) {
  const name = text.trim();
  if (name.length >= 2 && !name.startsWith('@')) return null;
  const words = [st.statusFilter && 'status:', st.matchTeam && 'ofteam:'].filter(Boolean);
  if (!words.length) return null;
  return `${words.join(' and ')} ${words.length > 1 ? 'narrow' : 'narrows'} the matches in all of nixpkgs: add a name`;
}

// The qualifiers the menu offers at a word's start, each with what it does.
export const QUALIFIERS = [
  ['is:', 'a tile, or what a package is'],
  ['-is:', 'what a package is not'],
  ['has:', 'an open PR, a newer version...'],
  ['-has:', 'without one'],
  ['age:', 'failing or outdated for longer than'],
  ['on:', 'a platform'],
  ['in:', 'a package set'],
  ['by:', 'a maintainer, within the list'],
  ['team:', "a team's packages"],
  ['-team:', 'a team left out'],
  ['-maintainer:', 'a maintainer left out'],
  ['build:', 'why a build failed'],
  ['update:', 'why an update failed'],
  ['status:', 'in all of nixpkgs: their status'],
  ['ofteam:', 'in all of nixpkgs: their team'],
  ['sort:', 'the order'],
  ['order:', 'the other way round'],
];

// What the menu offers for the word at caret in text: { start, end (the
// word's span), items: [{ text (to put there), label, count?, done (a
// whole qualifier: false for a key still wanting its value) }] }, or null.
// At a word's start, the qualifiers it begins; after one, its values
// (values: { is: [{ value, label?, count? }], ... }, from list.js) that
// begin with, or are labelled with, what's typed. A name or @handle: none.
export function suggest(text, caret, values, shown = 12) {
  const start = text.lastIndexOf(' ', caret - 1) + 1;
  const space = text.indexOf(' ', caret);
  const end = space < 0 ? text.length : space;
  const word = text.slice(start, end);
  if (word.startsWith('@')) return null;
  const m = word.match(/^(-?[A-Za-z]+):(.*)$/);
  if (m) {
    const key = m[1].toLowerCase();
    const typed = m[2].replace(/^"/, '').replace(/"$/, '').toLowerCase();
    const items = (values[key] || [])
      .filter(
        (v) =>
          v.value.toLowerCase().startsWith(typed) ||
          (typed && v.label?.toLowerCase().includes(typed)),
      )
      .slice(0, shown)
      .map((v) => ({
        text: `${m[1]}:${/\s/.test(v.value) ? `"${v.value}"` : v.value}`,
        label: v.label || '',
        ...(v.count != null ? { count: v.count } : {}),
        done: true,
      }));
    // Typed whole already, and the only one: nothing to offer.
    if (items.length === 1 && items[0].text.toLowerCase() === word.toLowerCase()) return null;
    return items.length ? { start, end, items } : null;
  }
  const typed = word.toLowerCase();
  const items = QUALIFIERS.filter(([k]) => k.startsWith(typed)).map(([k, label]) => ({
    text: k,
    label,
    done: false,
  }));
  // A word that begins none is a name: no menu.
  return items.length ? { start, end, items } : null;
}

// The box's menu (a combobox's listbox, #searchMenu): what suggest offers
// for the word being typed. Arrows move in it, Enter or Tab picks the one
// moved to (not before: Enter on a name stays a search), a click picks,
// Escape closes it (the box's own Escape next time). It opens on focus
// and wherever the caret goes, as on GitHub: in an empty box, or after a
// space, it lists the qualifiers. values: () => the values (list.js's
// searchValues).
export function wireSearchMenu(values) {
  const box = document.getElementById('search');
  const menu = document.getElementById('searchMenu');
  let found = null;
  let active = -1;
  const close = () => {
    found = null;
    active = -1;
    menu.hidden = true;
    menu.textContent = '';
    box.setAttribute('aria-expanded', 'false');
    box.removeAttribute('aria-activedescendant');
  };
  const draw = () => {
    setHtml(
      menu,
      html`${found.items.map(
        (it, i) =>
          html`<div role="option" id="searchOption${i}" class="search-option" data-i="${i}" aria-selected="${i === active}"><span class="so-text">${it.text}</span><span class="so-label">${it.label}</span>${
            it.count != null ? html`<span class="so-count">${it.count.toLocaleString()}</span>` : ''
          }</div>`,
      )}`,
    );
    if (active >= 0) box.setAttribute('aria-activedescendant', `searchOption${active}`);
    else box.removeAttribute('aria-activedescendant');
  };
  // next: on focus or a click, the caret at the end of a word the menu has
  // nothing for (a name, a whole one): the qualifiers, as the next word.
  const open = (next = false) => {
    const text = box.value;
    const caret = box.selectionStart ?? text.length;
    found = suggest(text, caret, values());
    if (!found && next && text && caret === text.length && !text.endsWith(' ')) {
      const after = suggest(`${text} `, caret + 1, values());
      if (after) {
        found = {
          start: caret,
          end: caret,
          items: after.items.map((it) => ({ ...it, text: ` ${it.text}` })),
        };
      }
    }
    if (!found) return close();
    active = -1;
    menu.hidden = false;
    box.setAttribute('aria-expanded', 'true');
    draw();
  };
  const pick = (i) => {
    const it = found.items[i];
    const rest = box.value.slice(found.end).replace(/^ /, '');
    const head = `${box.value.slice(0, found.start)}${it.text}${it.done ? ' ' : ''}`;
    box.value = head + rest;
    box.setSelectionRange(head.length, head.length);
    // Read as typed (the page's own input listener), then what follows.
    box.dispatchEvent(new Event('input', { bubbles: true }));
    if (it.done) close();
    else open();
  };
  box.addEventListener('input', () => open());
  box.addEventListener('focus', () => open(true));
  // A click places the caret (after focus), and moves it in a focused box.
  box.addEventListener('click', () => open(true));
  box.addEventListener('keyup', (e) => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) open(true);
  });
  box.addEventListener('blur', close);
  box.addEventListener('keydown', (e) => {
    if (menu.hidden) {
      if (e.key === 'ArrowDown') {
        open(true);
        if (found) {
          e.preventDefault();
          active = 0;
          draw();
        }
      }
      return;
    }
    const n = found.items.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = e.key === 'ArrowDown' ? (active + 1) % n : (active - 1 + n) % n;
      draw();
    } else if ((e.key === 'Enter' || e.key === 'Tab') && active >= 0) {
      e.preventDefault();
      pick(active);
    } else if (e.key === 'Escape') {
      // The menu only: the box's text and filters stay.
      e.preventDefault();
      e.stopPropagation();
      close();
    }
  });
  // The pointer moves the active option, as the arrows do: one is
  // highlighted, not one hovered and another moved to.
  menu.addEventListener('mousemove', (e) => {
    const i = Number(e.target.closest('[data-i]')?.dataset.i ?? -1);
    if (i >= 0 && i !== active) {
      active = i;
      draw();
    }
  });
  // A press keeps the box focused (no blur), then picks.
  menu.addEventListener('mousedown', (e) => {
    const option = e.target.closest('[data-i]');
    if (!option) return;
    e.preventDefault();
    pick(Number(option.dataset.i));
  });
}
