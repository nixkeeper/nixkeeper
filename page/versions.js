// Comparing versions as Repology does (libversion's rules), and what
// differs between two: the list's highlighted part, the gap's size.

// Version order as the sync compares them (nixkeeper/versions.py):
// Repology's algorithm (libversion, doc/ALGORITHM.md), tested against its
// test suite (tests/data/version-comparison-tests.txt). Components, numeric
// or alphabetic, each ranked: pre-release (alpha, beta, rc, pre..., any
// other word) < zero < post-release (post..., patch..., pl, errata) <
// nonzero < a letter suffix (1.0a); then words by their first letter, any
// case, numbers as numbers; the shorter version padded with zeros (1 ==
// 1.0, 1.0rc1 < 1.0 < 1.0patch1 < 1.0.1 < 1.0a). And nixpkgs' "unstable"
// snapshots after the version before the word (versionParts).
const PRE_RELEASE = 0;
const ZERO = 1;
const POST_RELEASE = 2;
const NONZERO = 3;
const LETTER_SUFFIX = 4;
const PAD = [ZERO, 0, 0];

function versionKeyword(word) {
  const w = word.toLowerCase();
  if (w === 'alpha' || w === 'beta' || w === 'rc' || w.startsWith('pre')) return PRE_RELEASE;
  if (w.startsWith('post') || w.startsWith('patch') || w === 'pl' || w === 'errata')
    return POST_RELEASE;
  return null;
}

// [rank, kind, value]: kind 0 for a zero, 1 for a word (its first letter),
// 2 for a number. Trailing zeros left out: padding adds them.
function versionComponents(version) {
  const found = [];
  let pos = 0;
  for (const m of version.matchAll(/([A-Za-z]+)|([0-9]+)/g)) {
    const [, word, number] = m;
    if (word) {
      // Right after a number and not followed by one: a letter suffix.
      const afterNumber = m.index === pos && found.length > 0 && found.at(-1)[1] !== 1;
      const followed = /[0-9]/.test(version.charAt(m.index + word.length));
      let rank = versionKeyword(word);
      if (rank === null) rank = afterNumber && !followed ? LETTER_SUFFIX : PRE_RELEASE;
      found.push([rank, 1, word[0].toLowerCase()]);
    } else {
      // As text without its leading zeros: no number is too long.
      const digits = number.replace(/^0+/, '');
      found.push(digits ? [NONZERO, 2, digits] : [...PAD]);
    }
    pos = m.index + m[0].length;
  }
  while (found.length && found.at(-1)[0] === ZERO) found.pop();
  return found;
}

function compareComponent(x, y) {
  for (let i = 0; i < 3; i++) {
    if (x[i] === y[i]) continue;
    // Numbers (text without leading zeros): the longer is bigger.
    if (i === 2 && x[1] === 2 && x[i].length !== y[i].length)
      return x[i].length < y[i].length ? -1 : 1;
    return x[i] < y[i] ? -1 : 1;
  }
  return 0;
}

function compareComponents(pa, pb) {
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const c = compareComponent(pa[i] || PAD, pb[i] || PAD);
    if (c) return c;
  }
  return 0;
}

// nixpkgs' "unstable" versions (0-unstable-2022-07-13, 1.2-unstable-2025-05-
// 01; unstable-2015-10-15, with none before it, as 0): the version before
// the word, a snapshot after it, and its date (versions.py's Version).
function versionParts(version) {
  const m = /unstable/i.exec(version);
  return m
    ? [
        versionComponents(version.slice(0, m.index)),
        1,
        versionComponents(version.slice(m.index + 8)),
      ]
    : [versionComponents(version), 0, []];
}

export function compareVersions(a, b) {
  const [pa, snapA, afterA] = versionParts(a || '');
  const [pb, snapB, afterB] = versionParts(b || '');
  const c = compareComponents(pa, pb);
  if (c) return c;
  if (snapA !== snapB) return snapA < snapB ? -1 : 1;
  return compareComponents(afterA, afterB);
}

// What changed between two versions, compared by whole parts (split at
// . - _ + ~, so 1.19.24 -> 1.19.28 changes "24", not just the "4"): the
// start they share, the rest of each. The page shows the newest version
// under nixpkgs', the shared start faded and the rest in colour.
//   versionDiff('1.19.24', '1.19.28') -> { same: '1.19.', from: '24', to: '28' }
export function versionDiff(from, to) {
  const parts = (v) => (v || '').match(/[^.\-_+~]+|[.\-_+~]/g) || [];
  const [a, b] = [parts(from), parts(to)];
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  return { same: a.slice(0, i).join(''), from: a.slice(i).join(''), to: b.slice(i).join('') };
}

// The repositories a package's panel compares nixpkgs with: one entry per
// repository (Repology lists one per subpackage: alpine has xournalpp,
// xournalpp-doc, ...), its newest version, then newest version first (ties
// by name). Repology's statuses for versions that don't compare (rolling,
// ignored, incorrect, noscheme, untrusted) go last, so a "9999" doesn't top
// the list.
const UNCOMPARABLE = new Set(['rolling', 'ignored', 'incorrect', 'noscheme', 'untrusted']);
const newer = (a, b) =>
  UNCOMPARABLE.has(a.status) - UNCOMPARABLE.has(b.status) ||
  compareVersions(b.version || '', a.version || '');
export function comparedRepos(entries) {
  const best = new Map();
  for (const e of entries) {
    const kept = best.get(e.repo);
    if (!kept || newer(e, kept) < 0) best.set(e.repo, e);
  }
  return [...best.values()].sort(
    (a, b) => newer(a, b) || (a.repo || '').localeCompare(b.repo || ''),
  );
}

// How big an update from → to is, to sort by: {level, step, scheme},
// level the number of version parts that stay (0: the first part changes,
// a major update), step the change in the first differing part, relative to
// where it was, when both are numbers (2.8.2 → 3.2.4: level 0, step 0.5;
// 5.0.0 → 5.0.1: level 2, step 1; a build number 10798 → 11832: 0.1), so
// numbering styles compare; for dates as versions (20221026), the years
// apart; else 1. scheme: the numbering changed rather than the version
// (2026-10 → 202610050438, 0-unstable-2021-04-19 → 2021041900: parts more
// than a digit apart in length), no real size; sorted after the rest. null
// without a newer version. Bigger first: scheme last, then level
// ascending, then step descending.
export function versionGap(from, to) {
  if (!from || !to || from === to) return null;
  const parts = (v) => v.split(/[.\-_+~]/);
  const [a, b] = [parts(from), parts(to)];
  let level = 0;
  while (level < a.length && level < b.length && a[level] === b[level]) level++;
  const [pa, pb] = [a[level] ?? '', b[level] ?? ''];
  const [x, y] = [Number(pa), Number(pb)];
  const numbers = pa !== '' && pb !== '' && Number.isFinite(x) && Number.isFinite(y);
  const scheme = numbers && Math.abs(pa.length - pb.length) > 1;
  const dated = (p) => p.length >= 8 && /^(19|20)/.test(p);
  const years = (p) => Number(p.slice(0, 4));
  let step = 1;
  if (numbers && !scheme && y !== x) {
    step =
      dated(pa) && dated(pb) ? Math.abs(years(pb) - years(pa)) : Math.abs(y - x) / Math.max(x, 1);
  }
  return { level, step, scheme };
}
