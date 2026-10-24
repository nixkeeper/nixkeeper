// What the page has loaded of its data (docs/data.md, format 2), in one
// object (store), so the page's parts can read it from their own modules:
// app.js fills it as data.js's reads return, and draws the page from it.
// The filters, sort and paging are state.js's.

export const store = {
  // The list from summary.json (a short entry per package), each package's
  // full row from its shard (rows/<n>.json, of shardCount), loaded when a
  // panel opens.
  shardCount: 1,
  // With every package (a community instance: index.json's allPackages),
  // the page shows one view of the data at a time (viewPath): `packages` is
  // that view's, `manifest` index.json, with the counts of all of nixpkgs.
  community: false,
  manifest: null,
  sources: null, // the daily sync's sources (index.json's "sources")
  checkedAt: null,
  packages: [],
  shownView: null, // the path of the view in `packages`
  wantedView: null, // the one being loaded (the newest asked for wins)
  // ?cause=: what its view file says of the group (views/cause/<key>.json).
  causeShown: null,
  // The name index (names.json), once loaded for a search beyond the view
  // shown: [[name, status, set?]].
  names: null,
  namesLoading: null,
  // facets.json, decoded (decodeFacets): each names entry's maintainers,
  // teams and platforms, by its position there (nameIndex), once loaded for
  // a search's filters. Null if it doesn't line up with names (a sync
  // between the two loads): the search then filters without them.
  facetIndex: null,
  facetsLoading: null,
  nameIndex: null,
  // history.json's points, once loaded (the overview's trends), and what
  // marks them (staging-next merges, nixkeeper updates).
  trendPoints: null,
  trendEvents: [],
  historyLoading: false,
  // With every package: every maintainer (maintainers.json: [handle,
  // packages, outdated, failing]), loaded when a search starts with @ or the
  // maintainers page opens.
  maintainersList: null,
  maintainersLoading: null,
  // views/merge.json: the PRs maintainers can merge now with the merge bot,
  // for "You can merge these", loaded when one is first shown.
  mergeList: null,
  mergeLoading: null,
  // Every group of failed builds sharing an error (views/causes.json), once
  // "Show all" asked for them: the card then lists them all.
  allCauses: null,
};
