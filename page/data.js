// Where the page's data is and how it's read (docs/data.md, format 2): its
// address, its files as JSON, and the packages' full rows from their
// shards, each loaded once. No page state: app.js keeps what's read and
// draws the page.

import { githubRepo as repoFrom, withSlash } from './address.js';
import { shardOf } from './facets.js';

export const githubRepo = (params) => repoFrom(params, location);

// Where the data (index.json, summary.json, the shards) lives, as a URL
// ending in "/". First of:
//   1. ?data=<url> in the address: for testing; same site only, so a link
//      can't point someone's page at data from elsewhere
//   2. <meta name="nixkeeper-data" content="<url>"> in index.html: a host
//      that keeps the data somewhere else sets it
//   3. data/ next to the page, when one server serves both (self-hosting)
//   4. on a GitHub Pages project site (https://<owner>.github.io/<repo>/),
//      the repo's data branch; ?owner=...&repo=... names another repo
async function findDataBase() {
  const params = new URLSearchParams(location.search);
  const asked = params.get('data');
  if (asked) {
    const url = new URL(asked, location.href);
    if (url.origin === location.origin) return withSlash(url.href);
  }
  const meta = document.querySelector('meta[name="nixkeeper-data"]')?.content;
  if (meta) return withSlash(new URL(meta, location.href).href);
  try {
    const res = await fetch('data/index.json', { method: 'HEAD', cache: 'no-store' });
    if (res.ok) return new URL('data/', location.href).href;
  } catch {
    // not served here: try GitHub
  }
  const repo = githubRepo(params);
  return repo ? `https://raw.githubusercontent.com/${repo}/data/data/` : null;
}

let dataBase = null;
// The data's address, found once (findDataBase); null when there's none.
export async function locateData() {
  dataBase = dataBase || (await findDataBase());
  return dataBase;
}
export const dataUrl = (path) => new URL(path, dataBase).href;

// A data file as JSON, never from the browser's cache. A failed response
// throws, unless there's a stand-in: otherwise for any (an optional file,
// a list that may be empty), missing for a 404 only (a maintainer, team or
// list with no file).
export async function readJson(path, { otherwise, missing } = {}) {
  const res = await fetch(dataUrl(path), { cache: 'no-store' });
  if (res.ok) return res.json();
  if (otherwise !== undefined) return otherwise;
  if (missing !== undefined && res.status === 404) return missing;
  throw new Error(res.status);
}

// A package's full row (what its panels show), from its shard
// (rows/<n>.json, of count shards): each shard loaded once and its rows
// passed through prepare (a failed load isn't kept, so asking again tries
// again). null if it couldn't be loaded.
const shards = new Map(); // n -> Promise of Map(name -> prepared row)
export async function fullRowOf(name, count, prepare = (row) => row) {
  const n = shardOf(name, count);
  if (!shards.has(n)) {
    shards.set(
      n,
      readJson(`rows/${n}.json`).then(
        (shard) => new Map(shard.packages.map((row) => [row.name, prepare(row)])),
      ),
    );
  }
  try {
    return (await shards.get(n)).get(name) || null;
  } catch {
    shards.delete(n);
    return null;
  }
}
