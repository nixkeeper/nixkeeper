// Maintainers and teams: matching a search, a handle's spelling, and the
// lists of them in the page's address.

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

// The names index's status letters (status in nixkeeper/datastore/facts.py) as
// the dot they stand for.
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
