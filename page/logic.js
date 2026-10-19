// The page's rules, without the page: statuses, versions, ages, links and the
// tab icon's signals, from a package's data alone. app.js draws the page with
// them; tests/js/ tests them (node --test, in the flake checks).
//
// Where a rule depends on the selected platform, it takes it as an argument
// (null for all platforms, or 'linux', 'darwin'); times take `now` so tests
// can fix it.

const DAY = 86400e3;

export const withSlash = (url) => (url.endsWith('/') ? url : `${url}/`);

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

// The page links to show among `total` pages, on page `current`: the first
// and last, and two either side of the current one, with null for each gap
// ("1 … 4 5 6 7 8 … 20"). A gap of one page shows that page instead; up to
// 7 pages, all of them.
export function pageLinks(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const near = new Set([1, total]);
  for (let p = current - 2; p <= current + 2; p++) if (p >= 1 && p <= total) near.add(p);
  const pages = [...near].sort((a, b) => a - b);
  const out = [];
  for (const p of pages) {
    const last = out.at(-1);
    if (last != null && p - last === 2) out.push(last + 1);
    else if (last != null && p - last > 2) out.push(null);
    out.push(p);
  }
  return out;
}

// A row with the dates the data leaves out when they're the sync's own
// (restored in nixkeeper/datastore.py): each build's and its update check's
// checkedAt, its countedAt. Each is always there otherwise, so a missing one
// was `run` (index.json's checkedAt). Changes row in place, and returns it.
export function withRunStamps(row, run) {
  if (!run) return row;
  for (const b of row.builds || []) b.checkedAt ??= run;
  if (row.upstream) row.upstream.checkedAt ??= run;
  if ('openPRs' in row) row.countedAt ??= run;
  return row;
}

// With every package (a community instance), the page loads one view of the
// data at a time (nixkeeper/datastore.py, views): which one the address
// asks for, narrowest first. A team's or list's name as its file's
// (slug in datastore.py): "Security review" -> "security-review".
export const viewSlug = (name) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

// The view to load, as a path under data/ ("views/attention.json"),
// "pkg:<name>" for one package (?pkg=), or "overview" for none (the start
// page: all of nixpkgs in numbers, and the ways in): one package, else a
// maintainer's (?maintainer=handle, @handle in the search; none: those
// without), a team's, a list's, a
// generated set's, a list by name (?view=attention, ?view=broken,
// ?view=blocked), else the overview.
// ?view=maintainers: every maintainer (maintainers.json), not a list of
// packages.
export const VIEWS = {
  attention: 'views/attention.json',
  broken: 'views/broken.json',
  blocked: 'views/blocked.json',
  backport: 'views/backport.json',
  unbuilt: 'views/unbuilt.json',
  maintainers: 'maintainers',
};
export function viewPath({
  pkg = null,
  query = '',
  team = null,
  list = null,
  set = null,
  view = null,
  cause = null,
} = {}) {
  if (pkg) return `pkg:${pkg}`;
  const q = query.trim().toLowerCase();
  if (q.startsWith('@') && q.length > 1) return `views/maintainer/${q.slice(1)}.json`;
  if (team) return `views/team/${viewSlug(team)}.json`;
  if (list) return `views/list/${viewSlug(list)}.json`;
  if (set) return `views/set/${set}.json`;
  if (cause) return `views/cause/${cause}.json`;
  return VIEWS[view] || 'overview';
}

// maintainers.json's entries ([handle, packages, outdated, failing]) whose
// handle contains the query (an @ in front or not, any case): at most limit,
// and how many there are. The handle itself first, then those starting with
// it, then by handle.
export function maintainerMatches(list, query, limit = 20) {
  const q = query.trim().replace(/^@/, '').toLowerCase();
  if (!q) return { found: [], total: 0 };
  const rank = (handle) => (handle === q ? 0 : handle.startsWith(q) ? 1 : 2);
  const hits = list
    .filter(([handle]) => handle.toLowerCase().includes(q))
    .sort(
      ([a], [b]) =>
        rank(a.toLowerCase()) - rank(b.toLowerCase()) ||
        a.toLowerCase().localeCompare(b.toLowerCase()),
    );
  return { found: hits.slice(0, limit), total: hits.length };
}

// A count's change over the last week, from history.json's points (oldest
// first, a point a day): the newest point's value less the value of the
// newest point at least 7 days older; null without one.
export function weekChange(points, key) {
  const last = points.at(-1);
  if (!last) return null;
  const week = new Date(Date.parse(`${last.day}T00:00:00Z`) - 7 * 86400e3)
    .toISOString()
    .slice(0, 10);
  const before = points.filter((p) => p.day <= week).at(-1);
  return before ? last[key] - before[key] : null;
}

// A count's change for its card: over the last week (weekChange) once
// there's a week of points, else since the oldest point there is (the
// first daily syncs). {change, since: that point's day}, or null with fewer
// than two points.
export function trendChange(points, key) {
  const week = weekChange(points, key);
  if (week != null) return { change: week, since: null };
  if (points.length < 2) return null;
  return { change: points.at(-1)[key] - points[0][key], since: points[0].day };
}

// Where a day (YYYY-MM-DD) falls on a trend of points (oldest first), from
// 0 (the first point's day) to 100 (the last's), by date, so missing days
// keep their room; null outside them.
export function dayPosition(points, day) {
  if (points.length < 2) return null;
  const at = (d) => Date.parse(`${d}T00:00:00Z`);
  const first = at(points[0].day);
  const span = at(points.at(-1).day) - first;
  const t = at(day);
  if (!span || Number.isNaN(t) || t < first || t > first + span) return null;
  return (100 * (t - first)) / span;
}

// The names index's status letters (status in datastore.py) as the dot
// they stand for.
export const NAME_DOTS = { f: 'missing', m: 'merged', o: 'warn', u: 'ok', n: 'neutral' };

// The names index's entries ([name, status, set?]) whose name contains the
// search (any case), leaving out those in `shown` (a Set of names): at most
// `limit` of them, and how many there are. The closest first: the name
// itself, then names starting with it, then top-level packages before those
// in sets, then by name.
export function nameMatches(names, query, shown, limit = 50) {
  const q = query.trim().toLowerCase();
  if (!q || q.startsWith('@')) return { found: [], total: 0 };
  const rank = (name) => {
    const n = name.toLowerCase();
    return (n === q ? 0 : 4) + (n.startsWith(q) ? 0 : 2) + (n.includes('.') ? 1 : 0);
  };
  const all = names
    .filter(([name]) => name.toLowerCase().includes(q) && !shown.has(name))
    .sort((a, b) => rank(a[0]) - rank(b[0]) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return { found: all.slice(0, limit), total: all.length };
}

// The shard (data/rows/<n>.json) holding a package's full row: a hash of its
// name (shard_of in nixkeeper/datastore.py).
export const shardOf = (name, count) => crc32(name) % count;

// Whether pkg is available on key: a family ("linux", "darwin") or a system
// ("x86_64-linux"). "any platform" (no restriction in nixpkgs) counts as all.
// platforms.systems, when there, says which systems of a family it's on
// (available_on in nixkeeper/sources/nixpkgs.py); without it, all of them.
export function onPlatform(pkg, key) {
  const pl = pkg.platforms;
  if (pl === null) return true;
  const family = key.split('-').pop();
  if (!pl?.[family]) return false;
  return key === family || !pl.systems || pl.systems.includes(key);
}

// A build is on platform: its system, or any system of that family.
const onSystem = (system, platform) =>
  platform.includes('-') ? system === platform : system.endsWith(`-${platform}`);

// Listed for key (a family or a system) but not built there by Hydra: none
// of its builds there exists ("notBuilt": no job, usually as a dependency
// isn't available there, so the job fails to evaluate and Hydra drops it),
// while Hydra builds it elsewhere (not a package Hydra skips altogether:
// unfree, or kept off it). 1,659 Darwin listings on 2026-10-19, juce's and
// driftnet's among them.
export function unbuiltOn(pkg, key) {
  const here = (pkg.builds || []).filter((b) => onSystem(b.system, key));
  return (
    here.length > 0 &&
    here.every((b) => b.status === 'notBuilt') &&
    (pkg.builds || []).some((b) => !onSystem(b.system, key) && b.status !== 'notBuilt')
  );
}

// The systems pkg is listed for but not built on (unbuiltOn), each Linux
// system apart, Darwin as one: [] when Hydra builds it everywhere listed.
export function unbuiltWhere(pkg) {
  return ['x86_64-linux', 'aarch64-linux', 'darwin'].filter(
    (key) => onPlatform(pkg, key) && unbuiltOn(pkg, key),
  );
}

// Follows Repology's statuses, but "legacy" (an older version nixpkgs keeps
// beside a newer one under another attribute: tracy_0_11 beside tracy) isn't
// outdated by itself: only by a newer release in its own series (an update
// check), or, for a devel variant (a beta), a newer devel version elsewhere
// (config.KEPT in nixkeeper). Whether a row is a devel variant comes
// separately from pkg.devel and only shades its "devel" badge.
export function computeStatus(pkg) {
  if (pkg.nixStatus === 'missing') return 'missing';
  if (pkg.nixStatus === 'outdated') return 'warn';
  if (
    pkg.nixStatus === 'legacy' &&
    pkg.devel &&
    pkg.refVersion &&
    pkg.nixVersion &&
    compareVersions(pkg.refVersion, pkg.nixVersion) > 0
  )
    return 'warn';
  // nixkeeper's own update check found a release Repology hasn't seen.
  if (pkg.upstream?.newer) return 'warn';
  // Or master already has a newer version than the channel.
  if (aheadOnMaster(pkg)) return 'warn';
  if (pkg.nixStatus === 'newest' || pkg.nixStatus === 'unique' || pkg.nixStatus === 'devel')
    return 'ok';
  return 'neutral';
}

// An older version nixpkgs keeps on purpose beside a newer one (Repology's
// "legacy"), and nothing newer in its own series: shown as such, not as
// outdated. pkg.keptBeside names the newer one, when the data has it.
export function olderVersionKept(pkg) {
  return pkg.nixStatus === 'legacy' && computeStatus(pkg) !== 'warn';
}

// Hydra builds with a status, on the selected platform only while one is.
export function buildsWith(pkg, status, platform = null) {
  return (pkg.builds || []).filter(
    (b) => b.status === status && (!platform || onSystem(b.system, platform)),
  );
}

// Everything shown in red: not found in nixpkgs, or a build or update
// failure reported.
export function hasFailure(pkg, platform = null) {
  return (
    computeStatus(pkg) === 'missing' ||
    buildsWith(pkg, 'failed', platform).length > 0 ||
    Boolean(pkg.updateFailure)
  );
}

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

// The version master has, when ahead of the channel: Hydra's build there, or
// what an update PR merged into master brings (before Hydra has built it),
// whichever is higher (on_master in nixkeeper/changes.py).
export function onMaster(pkg) {
  const versions = [pkg.master, pkg.masterPR?.to].filter(Boolean);
  return versions.sort(compareVersions).pop() || null;
}

// Outdated, but master already has the target version (or newer): the update
// is merged and waits for nixos-unstable, usually a few days (see
// waiting_for_channel in nixkeeper/changes.py).
export function waitingForChannel(pkg) {
  return (
    computeStatus(pkg) === 'warn' &&
    Boolean(onMaster(pkg)) &&
    compareVersions(targetVersion(pkg) || '', onMaster(pkg)) <= 0
  );
}

// Outdated, and nixpkgs-update won't update it by itself, so it takes
// someone: the bot can't (none of its ways apply), passes it over on
// purpose (skipped), or has never tried it and isn't about to (not in its
// queue; queueRead: whether the data has the queue at all). Not while an
// update PR is open or merged (someone is on it), nor where the bot's
// attempts aren't known (generated sets, not read yet, not in nixpkgs).
export function botWontUpdate(pkg, queueRead = true) {
  if (computeStatus(pkg) !== 'warn' || pkg.pending || pkg.update === undefined) return false;
  if (pkg.openPR || waitingForChannel(pkg)) return false;
  const outcome = pkg.update?.outcome;
  if (outcome === 'cantUpdate' || outcome === 'skipped') return true;
  return pkg.update === null && !pkg.unread?.includes('update') && !(queueRead && pkg.queued);
}

// Outdated, but the branch that updates its set before master
// (haskell-updates: pkg.branch) already has the target version or newer:
// waiting for the branch's merge into master (on_branch in
// nixkeeper/changes.py).
export function onBranch(pkg) {
  return (
    computeStatus(pkg) === 'warn' &&
    Boolean(pkg.branch?.version) &&
    compareVersions(targetVersion(pkg) || '', pkg.branch.version) <= 0
  );
}

// Hydra's build of master is newer than the channel's version: there's a
// newer release, whatever Repology and the update checks know
// (ahead_on_master in nixkeeper/changes.py).
export function aheadOnMaster(pkg) {
  return Boolean(pkg.master && pkg.nixVersion) && compareVersions(pkg.master, pkg.nixVersion) > 0;
}

// Whether the version to update to is master's, newer than anything
// Repology or an update check knows (count_master in nixkeeper/changes.py;
// data from before that rule only has master, not refFromMaster).
export function fromMaster(pkg) {
  return (
    aheadOnMaster(pkg) &&
    (Boolean(pkg.refFromMaster) ||
      !pkg.refVersion ||
      compareVersions(pkg.master, pkg.refVersion) > 0)
  );
}

// Whether the package's update check is a community rule
// (community/update-checks.nix): its result says so, or its failure does.
export function communityCheck(pkg) {
  return Boolean(
    pkg.upstream?.community || pkg.notRefreshed?.upstream?.reason?.startsWith('community rule'),
  );
}

// nixkeeper's own entry among the repositories a package is compared
// against, first: its update check's version (your rule, a community rule,
// or worked out from nixpkgs' source), "ahead" when it counts as newer than
// nixpkgs', as a repository's newest version is. kind and where (the tags,
// the page) say where it came from. null without a result.
export function nixkeeperEntry(pkg) {
  const up = pkg.upstream;
  if (!up?.version) return null;
  return {
    repo: 'nixkeeper',
    version: up.version,
    ahead: Boolean(up.newer),
    kind: up.community
      ? 'A community update check'
      : up.inferred
        ? "Worked out from nixpkgs' source"
        : 'Your update check',
    where: up.label || (up.repo ? `${up.repo} tags` : ''),
  };
}

// Whether pkg matches a search: its name, project or an attribute contains
// it; or for "@handle", nixpkgs lists that maintainer for it (the whole
// GitHub handle, in any case), and "@none", no maintainer with a handle.
// Rows from before maintainers were synced have none to match.
// The maintainer a search names (@handle, lowercase), or null: none, only
// "@" so far, or @none (packages without one).
export function searchHandle(query) {
  const q = query.trim().toLowerCase();
  if (!q.startsWith('@') || q.length < 2 || q === '@none') return null;
  return q.slice(1);
}

// Whether handle maintains pkg directly: listed in the package's own
// maintainers, not only as a member of one of its teams (nixpkgs adds those
// to meta.maintainers; nonTeamMaintainers, when the sync found fewer, are
// the direct ones).
export function maintainsDirectly(pkg, handle) {
  return (pkg.nonTeamMaintainers || pkg.maintainers || []).some((m) => m.toLowerCase() === handle);
}

// ?maintainer=, comma-separated: one maintainer whose page it is (l0b0),
// and maintainers whose packages are left out (-iedame), any list; an @ in
// front of a handle is fine.
export function parseMaintainers(value) {
  const tokens = (value || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
  const bare = (t) => t.replace(/^@/, '');
  return {
    handle: bare(tokens.find((t) => !t.startsWith('-')) || '') || null,
    leftOut: [
      ...new Set(
        tokens
          .filter((t) => t.startsWith('-'))
          .map((t) => bare(t.slice(1)).toLowerCase())
          .filter(Boolean),
      ),
    ],
  };
}

// parseMaintainers' answer as ?maintainer='s value ('' for none of it).
export function maintainersParam({ handle = null, leftOut = [] }) {
  return [handle, ...leftOut.map((h) => `-${h}`)].filter(Boolean).join(',');
}

// Whether a list keeps pkg: none of the maintainers left out (lowercase
// handles) maintains it, directly or through a team.
export const maintainersKeep = (pkg, leftOut) =>
  !leftOut.length || !(pkg.maintainers || []).some((m) => leftOut.includes(m.toLowerCase()));

// Which teams' packages a list keeps (?team=, comma-separated): one team
// (Gaming: its packages; its own page unless a maintainer's is shown),
// teams left out (-Geospatial), and none: not through a team (on a
// maintainer's page, the packages they maintain themselves; elsewhere,
// packages without a team).
export function parseTeams(value) {
  const tokens = (value || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
  const none = (t) => t.toLowerCase() === 'none';
  return {
    include: tokens.find((t) => !t.startsWith('-') && !none(t)) || null,
    leftOut: [
      ...new Set(tokens.filter((t) => t.length > 1 && t.startsWith('-')).map((t) => t.slice(1))),
    ],
    none: tokens.some(none),
  };
}

// parseTeams' answer as ?team='s value ('' for none of it).
export function teamsParam({ include = null, leftOut = [], none = false }) {
  return [include, ...leftOut.map((t) => `-${t}`), none ? 'none' : null].filter(Boolean).join(',');
}

// Whether a list keeps pkg, by its teams (parseTeams' answer); handle: the
// maintainer whose page it is, if any (for none).
export function teamsKeep(pkg, { include = null, leftOut = [], none = false }, handle = null) {
  const teams = (pkg.teams || []).map((t) => t.toLowerCase());
  if (include && !teams.includes(include.toLowerCase())) return false;
  if (leftOut.some((t) => teams.includes(t.toLowerCase()))) return false;
  if (none) return handle ? maintainsDirectly(pkg, handle) : teams.length === 0;
  return true;
}

export function matchesSearch(pkg, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if (q.startsWith('@')) {
    const handle = q.slice(1);
    if (!handle) return true; // only "@" typed so far
    if (handle === 'none') return Array.isArray(pkg.maintainers) && pkg.maintainers.length === 0;
    return (pkg.maintainers || []).some((m) => m.toLowerCase() === handle);
  }
  return [pkg.name, pkg.project, ...(pkg.attrs || [])].some((n) => n?.toLowerCase().includes(q));
}

// The version an update would bring.
export function targetVersion(pkg) {
  return fromMaster(pkg) ? pkg.master : pkg.refVersion;
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

// Default order: failed, then outdated (longest outdated first), then
// outdated but already fixed on master, then the rest; otherwise
// alphabetical (the index arrives sorted by name and Array.sort is stable).
export function attentionRank(pkg, platform = null) {
  if (hasFailure(pkg, platform)) return 0;
  if (waitingForChannel(pkg)) return 1.5;
  if (computeStatus(pkg) === 'warn') return 1;
  return 2;
}

// Whether a package counts as vulnerable: Repology flags nixpkgs' version
// (nixVulnerable), or nixpkgs itself marks it insecure (markedInsecure, its
// meta.knownVulnerabilities).
export const isVulnerable = (pkg) => {
  const found = vulnSummary(pkg);
  return found !== undefined
    ? Boolean(found) // the sync's verdict, from nixkeeper-vulnerabilities
    : Boolean(pkg.nixVulnerable || pkg.markedInsecure?.length);
};

// The verdicts of a row's "vulnerabilities" that count (changes.py's
// COUNTED_VULNERABILITIES), and severities worst first.
export const VULN_COUNTED = ['affected', 'byVersion', 'tracker', 'wontFix', 'osv'];
const SEVERITIES = ['critical', 'high', 'medium', 'moderate', 'low'];

// A package's vulnerability verdict as the list's entries have it ("vuln":
// {n, severity?, by}, or null when nothing says so), worked out from the
// full row's "vulnerabilities" (a package's own page, or a panel) as
// vulnerabilities_digest.summary does; undefined when there are neither:
// Repology's flag and nixpkgs' mark decide.
export function vulnSummary(pkg) {
  if (pkg.vuln !== undefined) return pkg.vuln;
  if (!pkg.vulnerabilities) return undefined;
  const counted = pkg.vulnerabilities.filter((v) => VULN_COUNTED.includes(v.verdict));
  const by = [...new Set(counted.map((v) => v.source))].sort();
  if (pkg.markedInsecure?.length) by.push('nixpkgs');
  if (pkg.nixVulnerable) by.push('repology');
  if (!by.length) return null;
  const known = counted.map((v) => v.severity).filter((s) => SEVERITIES.includes(s));
  known.sort((a, b) => SEVERITIES.indexOf(a) - SEVERITIES.indexOf(b));
  return { n: counted.length, ...(known.length ? { severity: known[0] } : {}), by };
}

// A vulnerable package's worst severity, as a rank (0 worst); the last
// for one with none known: the vulnerable list's order.
export const severityRank = (pkg) => {
  const i = SEVERITIES.indexOf(vulnSummary(pkg)?.severity);
  return i < 0 ? SEVERITIES.length : i;
};

// Who says a package is vulnerable (its summary's "vuln.by", else from
// Repology's flag and nixpkgs' mark), in words for the badge's title.
const SOURCE_WORDS = {
  tracker: 'the NixOS security tracker',
  osv: 'OSV',
  nixpkgs: 'nixpkgs (marked insecure)',
  repology: 'Repology',
};
export function vulnSources(pkg) {
  const by =
    vulnSummary(pkg)?.by ||
    [pkg.markedInsecure?.length && 'nixpkgs', pkg.nixVulnerable && 'repology'].filter(Boolean);
  return by.map((s) => SOURCE_WORDS[s] || s);
}

// A reason nixpkgs gives for marking a package insecure, in pieces: plain
// text, and the CVE ids in it (CVE-2020-25031), to link.
const CVE_ID = /CVE-\d{4}-\d{4,}/g;
export function cvePieces(text) {
  const pieces = [];
  let at = 0;
  for (const m of text.matchAll(CVE_ID)) {
    if (m.index > at) pieces.push({ text: text.slice(at, m.index) });
    pieces.push({ cve: m[0] });
    at = m.index + m[0].length;
  }
  if (at < text.length) pieces.push({ text: text.slice(at) });
  return pieces;
}

// The tab's icon among packages: each signal turns its own chevron of the
// mark (assets/brand/BRAND.md, "Status icon"): r, a new release nothing has
// been done about yet (not already on master); f, a failure; v, a
// vulnerability. "rfv" order, or "ok" with none: favicon-<key>.svg.
export function faviconKey(packages, platform = null) {
  const signals = {
    r: packages.some((p) => computeStatus(p) === 'warn' && !waitingForChannel(p)),
    f: packages.some((p) => hasFailure(p, platform)),
    v: packages.some(isVulnerable),
  };
  return ['r', 'f', 'v'].filter((s) => signals[s]).join('') || 'ok';
}

// Why a package's latest update attempt failed (its "update.failedBecause",
// read from the bot's log): "other" when none was recognised; null when its
// attempt didn't fail. ?updateFailed= narrows a list to one.
export function failedBecause(pkg) {
  if (!pkg.updateFailure) return null;
  return pkg.update?.failedBecause || 'other';
}

// Why a package's failed builds failed (on platform, when given), each
// once: nixkeeper-hydra's reasons, from their logs ("unread" while a log
// isn't read yet). ?buildFailed= narrows a list to one. Empty when no build
// failed.
export function buildFailedBecause(pkg, platform = null) {
  return [...new Set(buildsWith(pkg, 'failed', platform).map((b) => b.failedBecause || 'unread'))];
}

// "Older than" (?age=): how many days each choice means. ?age=never is
// the builds that never succeeded on Hydra instead (neverBuiltOn): no date.
export const AGE_DAYS = { '1m': 30, '6m': 182, '1y': 365, '2y': 730, '3y': 1095 };
export const NEVER_BUILT = 'never';

// Since when a row has had the problem kind names (the list's filter):
// failing (its builds or update attempts, the earlier; or builds or updates
// alone), outdated, or for any other, the earliest of them; null when it has
// none of them.
export function problemSince(pkg, kind) {
  const failing = [pkg.failingSince, pkg.updateFailingSince];
  const dates =
    kind === 'failed'
      ? failing
      : kind === 'builds'
        ? [pkg.failingSince]
        : kind === 'updates'
          ? [pkg.updateFailingSince]
          : kind === 'warn'
            ? [pkg.outdatedSince]
            : [...failing, pkg.outdatedSince];
  return dates.filter(Boolean).sort()[0] || null;
}

// The systems where a row's failing builds never succeeded on Hydra
// (neverBuiltOn), only those on platform when one is picked.
export const neverBuiltOn = (pkg, platform = null) =>
  (pkg.neverBuiltOn || []).filter((system) => !platform || onSystem(system, platform));

// Whether a row has had that problem for longer than age (an AGE_DAYS key;
// NEVER_BUILT: a failing build of it never succeeded, on platform if one is
// picked, for any kind of problem but outdated and update failures; any
// other: no limit, so every row is).
export function olderThan(pkg, age, kind, now = Date.now(), platform = null) {
  if (age === NEVER_BUILT)
    return neverBuiltOn(pkg, platform).length > 0 && kind !== 'warn' && kind !== 'updates';
  if (!AGE_DAYS[age]) return true;
  const since = problemSince(pkg, kind);
  return Boolean(since) && now - new Date(since).getTime() > AGE_DAYS[age] * DAY;
}

// How long a package has been outdated, one letter per unit: <1 d, 3 d, 2 w,
// 5 m (months), 2 y.
export function shortAge(iso, now = Date.now()) {
  const days = Math.floor((now - new Date(iso).getTime()) / DAY);
  if (days < 1) return '<1 d';
  if (days < 7) return `${days} d`;
  if (days < 30) return `${Math.floor(days / 7)} w`;
  if (days < 365) return `${Math.min(11, Math.floor(days / 30))} m`; // 360-364 days: not "12 m" before "1 y"
  return `${Math.floor(days / 365)} y`;
}

export function daysText(iso, now = Date.now()) {
  const days = Math.floor((now - new Date(iso).getTime()) / DAY);
  return days < 1 ? 'today' : days === 1 ? '1 day' : `${days} days`;
}

// Whole days from now until a day to come (a plain day, read as its midday
// UTC): 0 for today or one past.
export function daysUntil(day, now = Date.now()) {
  return Math.max(0, Math.round((new Date(`${day}T12:00:00Z`).getTime() - now) / DAY));
}

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return 'never';
  const diff = now - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function escapeHtml(s) {
  return (s || '')
    .toString()
    .replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
}

// A link from data, only if it's a web address: escaping stops markup, but
// not a javascript: link, which would run when clicked. '' otherwise.
export function safeUrl(url) {
  try {
    const { protocol } = new URL(url);
    return protocol === 'https:' || protocol === 'http:' ? url : '';
  } catch {
    return '';
  }
}

// Markup, built with the html`...` tag: every ${...} in it is escaped,
// unless it's markup itself (another html`...`, or raw() for markup the page
// writes itself), so text from the data can't add markup, even where an
// escape would have been forgotten. Arrays are joined; null and undefined
// give nothing (and the rest prints as in a template string: false as
// "false", for aria-pressed). The result goes into innerHTML as is.
class Markup {
  constructor(text) {
    this.text = text;
  }
  toString() {
    return this.text;
  }
}
const piece = (v) =>
  v instanceof Markup
    ? v.text
    : Array.isArray(v)
      ? v.map(piece).join('')
      : v == null
        ? ''
        : escapeHtml(String(v));
export function html(strings, ...values) {
  return new Markup(strings.reduce((out, s, i) => out + piece(values[i - 1]) + s));
}
// Markup the page writes itself, as is. Never for text from the data.
export const raw = (text) => new Markup(String(text));

// Whether url's host is host or one of its subdomains (github.com, or
// api.github.com), by its parsed hostname: not "github.com" anywhere in it
// (https://example.org/?github.com). False for what isn't a URL.
export function onHost(url, host) {
  try {
    const name = new URL(url).hostname.toLowerCase();
    return name === host || name.endsWith(`.${host}`);
  } catch {
    return false;
  }
}

// "owner/repo" from ?owner=&repo=, or from a GitHub Pages project site's
// address (a location: its hostname and pathname). Only names GitHub allows
// (null otherwise): the page loads that repository's data, so a link can't
// make it build a URL out of anything else.
const GITHUB_OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const GITHUB_NAME = /^(?!\.\.?$)[A-Za-z0-9._-]{1,100}$/;
// The address of the overview with no filters, from the page at pathname
// and search: the view's parameters dropped, only those saying where the
// data lives kept (?data=, ?owner=&repo=), so a copy pointed at other data
// stays on it.
export const HOME_PARAMS = ['data', 'owner', 'repo'];
export function homeHref(pathname, search) {
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const key of HOME_PARAMS) {
    const value = params.get(key);
    if (value) kept.set(key, value);
  }
  const query = kept.toString();
  return pathname + (query ? `?${query}` : '');
}

export function githubRepo(params, { hostname, pathname }) {
  const asked = params.get('owner') && params.get('repo');
  const owner = asked
    ? params.get('owner')
    : hostname.endsWith('.github.io')
      ? hostname.split('.')[0]
      : null;
  const name = asked ? params.get('repo') : pathname.split('/').filter(Boolean)[0];
  return GITHUB_OWNER.test(owner || '') && GITHUB_NAME.test(name || '') ? `${owner}/${name}` : null;
}

// The page's look: a palette and light or dark. The visitor's choice (the
// Theme menu, kept in their browser) wins, then the page's default (the
// lists' page.theme, from the data), then classic; light or dark follows the
// system ('auto') unless chosen. Unknown values count as not set.
export const PALETTES = ['classic', 'catppuccin'];
export const MODES = ['auto', 'light', 'dark'];

export function themeFor(chosen = {}, siteDefault = null) {
  const palette = [chosen.palette, siteDefault].find((p) => PALETTES.includes(p)) || 'classic';
  const mode = MODES.includes(chosen.mode) ? chosen.mode : 'auto';
  return { palette, mode };
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

// An update's title as nixpkgs writes it, for commits and PRs:
// "unciv: 4.22.1 -> 4.22.6". Only for an outdated package with a known
// newest version; null otherwise.
// Starting from master's version when master is partway there (the next
// update goes on from it): "google-chrome: 154.0.8037.92 -> 154.0.8037.97".
export function updateTitle(pkg) {
  const target = targetVersion(pkg);
  const from = midway(pkg) || pkg.nixVersion;
  return computeStatus(pkg) === 'warn' && from && target
    ? `${pkg.name}: ${from} -> ${target}`
    : null;
}

// Master's version when it's partway between the channel and the newest: an
// update merged (waiting for the channel), and a newer one after it. Null
// otherwise (nothing on master, or master already has the newest).
export function midway(pkg) {
  const master = onMaster(pkg);
  const target = targetVersion(pkg);
  return computeStatus(pkg) === 'warn' &&
    master &&
    target &&
    pkg.nixVersion &&
    compareVersions(master, pkg.nixVersion) > 0 &&
    compareVersions(master, target) < 0
    ? master
    : null;
}
