// The page's rules, without the page: statuses, versions, ages, links and the
// tab icon's signals, from a package's data alone. app.js draws the page with
// them; tests/js/ tests them (node --test, in the flake checks).
//
// Where a rule depends on the selected platform, it takes it as an argument
// (null for all platforms, or 'linux', 'darwin'); times take `now` so tests
// can fix it.

import { AGE_DAYS, DAY } from './dates.js';
import { compareVersions } from './versions.js';
import { isVulnerable, vulnSummary } from './vulns.js';

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
// (restored in nixkeeper/datastore/shards.py): each build's and its update check's
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
// data at a time (nixkeeper/datastore/view_files.py, views): which one the address
// asks for, narrowest first. A team's or list's name as its file's
// (slug in nixkeeper/naming.py): "Security review" -> "security-review".
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
  superseded: 'views/superseded.json',
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

// The names index's status letters (status in nixkeeper/datastore/facts.py) as the dot
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
  // python3Packages.x, as nixpkgs titles write python313Packages.x
  // (config.SEARCH_ALIASES): tried only when the search asks for it.
  const alias = q.includes('python3packages')
    ? (n) => n.replace(/^python3\d+packages\./, 'python3packages.')
    : (n) => n;
  const all = names
    .filter(([name]) => {
      const n = name.toLowerCase();
      return (n.includes(q) || alias(n).includes(q)) && !shown.has(name);
    })
    .sort((a, b) => rank(a[0]) - rank(b[0]) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return { found: all.slice(0, limit), total: all.length };
}

// The shard (data/rows/<n>.json) holding a package's full row: a hash of its
// name (shard_of in nixkeeper/naming.py).
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

// What a package needs attention for, as one string: hidden ("Hide until
// it changes") while it stays the same. Its status, the version it's
// outdated against, each failing build (system and status), the update
// bot's outcome and why it failed, its counted CVEs, and nixpkgs' broken
// mark: any of them changing (1.3 out after 1.2 was hidden, a new failing
// system, a new CVE) brings it back. A vulnerable package's has the sync's
// time too (checkedAt): a CVE comes back at the next sync, never hidden
// for long.
export function attentionPrint(pkg, checkedAt = '') {
  const failing = (pkg.builds || [])
    .filter((b) => b.status === 'failed' || b.status === 'dependency')
    .map((b) => `${b.system}:${b.status}`)
    .sort();
  return JSON.stringify([
    computeStatus(pkg),
    pkg.refVersion || '',
    failing,
    pkg.updateFailure ? [pkg.update?.outcome || '', pkg.update?.failedBecause || ''] : [],
    // The list's entry has vuln, the full row vulnerabilities: the same
    // count either way (vulnSummary), so a panel's hide matches the list.
    vulnSummary(pkg)?.n || (pkg.nixVulnerable ? 1 : 0),
    Boolean(pkg.markedBroken),
    isVulnerable(pkg) ? checkedAt || '' : '',
  ]);
}

// What a PR of "You can merge these" is, as one string: hidden there
// ("Hide") while it stays the same. Its title, which the update bot
// rewrites when it pushes a newer version ("foo: 1.2 -> 1.4"), and whether
// it's for a vulnerable package. Not upstream moving on ("behind"): a PR
// held back on purpose stays hidden through new releases.
export function prPrint(pr) {
  return JSON.stringify([pr.title, Boolean(pr.vulnerable)]);
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
// Repology's "unique" with nothing to compare: no repository outside
// nixpkgs has it, and no update check or feed of nixkeeper's own knows its
// releases (python313Packages.pbar2): not up to date, not compared
// (datastore.nothing_compared).
export const nothingCompared = (pkg) =>
  pkg.nixStatus === 'unique' && Boolean(pkg.onlyNixpkgs) && !pkg.upstream && !pkg.feed;

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
  if (nothingCompared(pkg)) return 'neutral';
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

// The version master has, when ahead of the channel: Hydra's build there, or
// what an update PR merged into master brings (before Hydra has built it),
// whichever is higher (on_master in nixkeeper/changes.py).
export function onMaster(pkg) {
  const versions = [pkg.master, pkg.masterPR?.to].filter(
    (v) => v && !sameRelease(v, pkg.nixVersion),
  );
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

// Whether version is the channel's release with a suffix Repology leaves
// out of nixpkgs' version (firefox-esr's 153.5.1esr is 153.5.1 there), not
// a newer one; a pre-release's suffix isn't that (same_release in
// nixkeeper/changes.py).
export function sameRelease(version, channel) {
  if (!version || !channel || !version.startsWith(channel)) return false;
  const rest = version.slice(channel.length);
  return (
    /^[A-Za-z]+$/.test(rest) && !/^(a|b|c|alpha|beta|rc|pre|preview|dev|snapshot)$/i.test(rest)
  );
}

// Hydra's build of master is newer than the channel's version: there's a
// newer release, whatever Repology and the update checks know
// (ahead_on_master in nixkeeper/changes.py). Not the channel's release
// with a suffix Repology drops (sameRelease).
export function aheadOnMaster(pkg) {
  return (
    Boolean(pkg.master && pkg.nixVersion) &&
    compareVersions(pkg.master, pkg.nixVersion) > 0 &&
    !sameRelease(pkg.master, pkg.nixVersion)
  );
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
  // searchTerm: the name as nixpkgs titles write it (python3Packages.x for
  // python313Packages.x), which is what people type.
  return [pkg.name, pkg.project, pkg.searchTerm, ...(pkg.attrs || [])].some((n) =>
    n?.toLowerCase().includes(q),
  );
}

// The version an update would bring.
export function targetVersion(pkg) {
  return fromMaster(pkg) ? pkg.master : pkg.refVersion;
}

// What fixes a package's CVEs, from the versions their ranges say fix them
// (fixedIn, fixed_in in nixkeeper/sources/vulnerabilities_digest.py): the
// version that fixes all of those (need), how many name one, and how many
// master, the open update PR and the newest release each fix. null when
// none names one.
export function vulnFixes(pkg, vulns) {
  const named = vulns.filter((v) => v.fixedIn);
  if (!named.length) return null;
  const fixes = (version) =>
    version ? named.filter((v) => compareVersions(version, v.fixedIn) >= 0).length : null;
  return {
    need: named
      .map((v) => v.fixedIn)
      .sort(compareVersions)
      .pop(),
    named: named.length,
    master: fixes(onMaster(pkg)),
    pr: fixes(pkg.openPR?.to),
    newest: fixes(targetVersion(pkg)),
  };
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
// by what's picked: a package set (logic.nameSet's), a status (a
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
