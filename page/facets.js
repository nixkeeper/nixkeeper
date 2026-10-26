// The names index's facets (names.json): the status letters and platform
// bits each package carries, shards by name, counts and folded families.

import { targetVersion } from './status.js';

// CRC-32 of a text's UTF-8 bytes, as zlib.crc32 computes it in Python.
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
export function crc32(text) {
  let c = 0xffffffff;
  for (const byte of new TextEncoder().encode(text)) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// The shard (data/rows/<n>.json) holding a package's full row: a hash of its
// name (shard_of in nixkeeper/naming.py).
export const shardOf = (name, count) => crc32(name) % count;

// Packages one update moves together (the sync's family: the same file,
// version and homepage, rows.add_families) as the list folds them: at the
// same status and target version, and also alike by key(pkg) (the list's
// dot), FOLD_MIN or more of them in the list are one row, the first in the
// list's order (the most pressing), with the others behind it; or, when
// their fold is in open (by its key), the others right after it. Returns
// {list, folds: lead's name → {key, members, open}, inOpen: the names shown
// behind an open fold's lead}.
export const FOLD_MIN = 3;
export function foldFamilies(list, key = () => '', open = new Set()) {
  const keyOf = (pkg) =>
    pkg.family ? [pkg.family, pkg.nixStatus, targetVersion(pkg) ?? '', key(pkg)].join('|') : null;
  const groups = new Map();
  for (const pkg of list) {
    const k = keyOf(pkg);
    if (k) groups.set(k, [...(groups.get(k) ?? []), pkg]);
  }
  const out = [];
  const folds = new Map();
  const inOpen = new Set();
  for (const pkg of list) {
    const k = keyOf(pkg);
    const members = k && groups.get(k);
    if (!members || members.length < FOLD_MIN) out.push(pkg);
    else if (members[0] === pkg) {
      folds.set(pkg.name, { key: k, members, open: open.has(k) });
      out.push(pkg);
      if (open.has(k)) {
        for (const m of members.slice(1)) inOpen.add(m.name);
        out.push(...members.slice(1));
      }
    }
  }
  return { list: out, folds, inOpen };
}

// What a family's members are called together (rows.family_label): the one
// name they all end in (a kernel module once per kernel); else their names'
// common start and a "*" ("python313Packages.huaweicloudsdk*"); null when
// they share fewer than 4 characters.
export function familyLabel(names) {
  const ends = new Set(names.map((n) => n.split('.').pop()));
  if (ends.size === 1) return [...ends][0];
  let start = names[0] ?? '';
  for (const n of names) while (!n.startsWith(start)) start = start.slice(0, -1);
  return start.length >= 4 ? `${start}*` : null;
}

// The package set a name is in, by its attribute's first part
// (python313Packages for python313Packages.requests, vimPlugins for
// vimPlugins.nvim-treesitter-parsers.lua); TOP_LEVEL for a top-level one
// (ripgrep). The list's "In" filter (?in=).
export const TOP_LEVEL = 'top-level';
export function nameSet(name) {
  const dot = name.indexOf('.');
  return dot < 0 ? TOP_LEVEL : name.slice(0, dot);
}

// Whether a package set (nameSet's) is the one picked (?in=): itself, or
// for python3Packages, as nixpkgs writes it, any python3xPackages
// (config.SEARCH_ALIASES).
export const inPickedSet = (set, picked) =>
  set === picked || (picked === 'python3Packages' && /^python3\d+Packages$/.test(set));

// How many of list have each value of key(pkg) (one or several values):
// [[value, count]], the most first, ties by name (any case). A list's
// filter counts. Names compared as plain lowercase strings: localeCompare
// over a view's 2,900 maintainers took 50 ms a sort (2026-10-22).
export function facetCounts(list, key) {
  const counts = new Map();
  for (const pkg of list) {
    const found = key(pkg);
    for (const value of Array.isArray(found) ? found : [found]) {
      if (value != null) counts.set(value, (counts.get(value) || 0) + 1);
    }
  }
  return [...counts]
    .map(([value, n]) => [value, n, value.toLowerCase()])
    .sort((a, b) => b[1] - a[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0))
    .map(([value, n]) => [value, n]);
}

// A name index entry's status ([name, letter, set?]: datastore.status's
// letter, then v when vulnerable), as the search's "Status" filter names
// it (?status=); vulnerable is any letter with a v.
export const NAME_STATUSES = {
  failing: 'failing',
  outdated: 'outdated',
  waiting: 'waiting for the channel',
  uptodate: 'up to date',
  notcompared: "can't be compared",
  vulnerable: 'vulnerable',
};
const LETTER_STATUS = {
  f: 'failing',
  m: 'waiting',
  o: 'outdated',
  u: 'uptodate',
  n: 'notcompared',
};
export const nameStatusIs = (letter, status) =>
  status === 'vulnerable' ? letter.endsWith('v') : LETTER_STATUS[letter[0]] === status;

// facets.json's platform bits (datastore.FACET_SYSTEMS) for each of the
// page's platforms: available there (any Linux system for linux).
export const PLATFORM_BITS = { linux: 3, 'x86_64-linux': 1, 'aarch64-linux': 2, darwin: 4 };
export const onBits = (bits, key) => (bits & PLATFORM_BITS[key]) !== 0;

// facets.json decoded: for each entry of names.json (same order), its
// {bits, handles (lowercase), teams}.
export function decodeFacets({ handles = [], teams = [], rows = [] }) {
  const lower = handles.map((h) => h.toLowerCase());
  const none = [];
  return rows.map((r) =>
    typeof r === 'number'
      ? { bits: r, handles: none, teams: none }
      : {
          bits: r[0],
          handles: r[1].map((i) => lower[i]),
          teams: (r[2] || none).map((i) => teams[i]),
        },
  );
}

// The search's matches in all of nixpkgs ([[name, letter, set?]]) narrowed
// by what's picked: a package set (nameSet's), a status (a
// NAME_STATUSES key), and with facetsOf (an entry's decodeFacets object, or
// undefined while facets.json loads) a maintainer (lowercase handle), a
// team and a platform (a PLATFORM_BITS key). {kept, sets, statuses, by,
// teams, platforms}: each facet counted with the others picked
// (facetCounts' [[value, count]]; statuses in NAME_STATUSES' order, those
// with none left out; platforms {key: count}).
export function matchFacets(matches, picked = {}, facetsOf = null) {
  const { set = null, status = null, by = null, team = null, platform = null } = picked;
  const of = (e) => (facetsOf && facetsOf(e)) || null;
  const tests = {
    set: ([name]) => !set || inPickedSet(nameSet(name), set),
    status: ([, letter]) => !status || nameStatusIs(letter, status),
    by: (e) => !by || !facetsOf || (of(e)?.handles || []).includes(by),
    team: (e) => !team || !facetsOf || (of(e)?.teams || []).includes(team),
    platform: (e) => !platform || !facetsOf || (of(e) ? onBits(of(e).bits, platform) : true),
  };
  const keys = Object.keys(tests);
  const except = (skip) => matches.filter((e) => keys.every((k) => k === skip || tests[k](e)));
  const sets = facetCounts(except('set'), ([name]) => nameSet(name));
  const ofOthers = except('status');
  const statuses = Object.keys(NAME_STATUSES)
    .map((s) => [s, ofOthers.filter(([, letter]) => nameStatusIs(letter, s)).length])
    .filter(([, n]) => n);
  const found = { kept: except(null), sets, statuses };
  if (facetsOf) {
    found.by = facetCounts(except('by'), (e) => of(e)?.handles || []);
    found.teams = facetCounts(except('team'), (e) => of(e)?.teams || []);
    const near = except('platform');
    found.platforms = Object.fromEntries(
      Object.keys(PLATFORM_BITS).map((k) => [
        k,
        near.filter((e) => (of(e) ? onBits(of(e).bits, k) : true)).length,
      ]),
    );
  }
  return found;
}
