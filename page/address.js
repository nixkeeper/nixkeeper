// The page's addresses and links: its views' paths, home links with the
// current settings, and where the repository and its data live.

export const withSlash = (url) => (url.endsWith('/') ? url : `${url}/`);

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
