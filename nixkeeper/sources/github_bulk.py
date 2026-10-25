"""List nixpkgs' pull requests and issues in bulk.

Instead of two or three searches per package (github.py), every open PR
and issue is listed in about 120 GraphQL requests (100 of each per
request), and the PRs merged into master since the channel's commit in
about 10 more, however many packages are tracked. Each package's open PR
and issue counts, its open update PR and its update PR merged into master
are then found in the lists locally (add_counts, add_master_prs).

The lists come from nixkeeper-prs' digest when it's current (prs_digest),
else from GitHub here. The daily sync falls back to the searches when a
listing fails; the hourly update-PR check (prcheck.py), for a few
packages, keeps using them.
"""

import re
import sys
import urllib.error
from datetime import datetime, timedelta

from .. import config
from . import github

# One page of open PRs and issues; each kind stops being asked for once it
# has no next page.
QUERY = """query($owner: String!, $name: String!, $prs: String, $issues: String,
               $morePrs: Boolean!, $moreIssues: Boolean!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $prs) @include(if: $morePrs) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url isDraft baseRefName }
    }
    issues(states: OPEN, first: 100, after: $issues) @include(if: $moreIssues) {
      pageInfo { hasNextPage endCursor }
      nodes { number title }
    }
  }
}"""

# GitHub's title search matches whole words, in any case, as checked
# against its answers. "wine" doesn't match "winetricks: ...", but does
# match "... WINE_BIN ..." (a title's words are also split at underscores),
# while "_1password-gui" matches "_1password-gui: ..." and not
# "1password-gui: ..." (a search's words keep theirs). It also stems English
# words: "trigger" matches "... triggers", "velocity" "... velocities".
# Plurals are copied here; GitHub goes further ("zoom" matching "zoomer"),
# which isn't.
WORD = re.compile(r"\w+")
# A word's parts between underscores.
PART = re.compile(r"[^\W_]+")


def stem(word):
    """Return word without a plural ending.

    velocities → velocity, triggers → trigger, patches → patch; class stays
    class.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def words(text):
    """Return a search's words.

    That's each run of letters, digits and underscores, stemmed, in lower
    case.
    """
    return {stem(w.lower()) for w in WORD.findall(text or "")}


def title_words(text):
    """Return a title's words: as a search's, and each part between underscores.

    WINE_BIN gives wine_bin, wine and bin.
    """
    found = set()
    for word in WORD.findall(text or ""):
        word = word.lower()
        found.add(stem(word))
        if "_" in word:
            found.update(stem(part) for part in PART.findall(word))
    return found


# A nixpkgs name in a title: an attribute or a package's name, letters,
# digits and _ . + - (python3Packages.requests, gtk+3, wesnoth-devel), a
# final "." being the sentence's.
NAME = re.compile(r"[A-Za-z0-9_][\w.+-]*")


def title_names(text):
    """Return the names in a title, in lower case.

    "pkg: 2.7.5 -> 2.8.4" has pkg; "Build failure: pkg-config" has
    pkg-config, not pkg.
    """
    return {n.rstrip(".").lower() for n in NAME.findall(text or "")}


def list_open(token):
    """List nixpkgs' open pull requests and issues, as GraphQL nodes.

    Returns:
        (open PRs, open issues).

    Raises:
        urllib.error.URLError, OSError, ValueError: A request failed, or
            GitHub's answer was incomplete: a partial list would give wrong
            counts.
    """
    owner, name = config.GITHUB_REPO.split("/")
    prs, issues = [], []
    cursors = {"prs": None, "issues": None}
    more = {"prs": True, "issues": True}
    while more["prs"] or more["issues"]:
        data = github.graphql(
            token,
            QUERY,
            {
                "owner": owner,
                "name": name,
                "prs": cursors["prs"],
                "issues": cursors["issues"],
                "morePrs": more["prs"],
                "moreIssues": more["issues"],
            },
        )
        repo = data.get("repository")
        if not repo:
            raise ValueError("GitHub didn't answer for the repository")
        for key, field, found in (
            ("prs", "pullRequests", prs),
            ("issues", "issues", issues),
        ):
            if not more[key]:
                continue
            page = repo.get(field)
            if page is None:
                raise ValueError(f"GitHub didn't answer for its {field}")
            found += [n for n in page["nodes"] if n]
            more[key] = page["pageInfo"]["hasNextPage"]
            cursors[key] = page["pageInfo"]["endCursor"]
    return prs, issues


class Listing:
    """Open pull requests and issues, indexed for the per-package lookups.

    They're indexed by the names and the words in their titles, and the PRs
    by the package their titles start with ("wesnoth-devel: ...").
    """

    def __init__(self, prs, issues):
        """Index prs and issues, as GraphQL nodes."""
        self.prs, self.issues = prs, issues
        self.pr_words = self._index(prs)
        self.issue_words = self._index(issues)
        self.issue_names = self._index(issues, title_names)
        self.by_package = {}
        self.pr_packages = {}  # by_package in lower case, for the PR counts
        for i, pr in enumerate(prs):
            for package in github.title_packages(pr.get("title")):
                self.by_package.setdefault(package, []).append(pr)
                self.pr_packages.setdefault(package.lower(), set()).add(i)

    @staticmethod
    def _index(nodes, split=title_words):
        """Index nodes by the words split takes from their titles."""
        index = {}
        for i, node in enumerate(nodes):
            for word in split(node.get("title")):
                index.setdefault(word, set()).add(i)
        return index

    @staticmethod
    def _matching(index, term):
        """Return the nodes whose titles have every word of term."""
        found = None
        for word in words(term):
            ids = index.get(word, set())
            found = ids if found is None else found & ids
        return found or set()

    def search_counts(self, term):
        """Count the open PRs and issues with term's words in their titles.

        That's as GitHub's `in:title term` search counts them.

        Returns:
            (open PRs, open issues).
        """
        return (
            len(self._matching(self.pr_words, term)),
            len(self._matching(self.issue_words, term)),
        )

    def counts(self, row):
        """Count the open PRs and issues about row.

        A PR counts when its title names the row, or one of its attributes,
        as nixpkgs' convention does ("pkg: 2.7.5 -> 2.8.2", "foo, pkg: ...";
        title_packages). Issues are free-form, so one counts when it has the
        row's name or search term whole in its title ("Build failure: pkg",
        not "pkg-config" or "pkgs/"). That isn't GitHub's search's count,
        whose words match far more for a name that's a word: "pkg" matched
        120 PRs and 96 issues, against the 2 PRs about it ("pkg: remove
        unicode arrow") and 8 issues; 1,000 of the 13,523 rows needing
        attention count fewer this way (2026-10-23).

        Returns:
            (open PRs, open issues).
        """

        def naming(index, names):
            """Count the nodes index has under any of names, any case."""
            names = {n.lower() for n in names}
            return len(set().union(*(index.get(n, set()) for n in names)))

        # Issues by its own name only: an attribute can be a word too (bind's
        # host and dig matched 59 issues about hosts).
        return (
            naming(self.pr_packages, [row["name"], *github.pr_names(row)]),
            naming(self.issue_names, [row["name"], row["searchTerm"]]),
        )

    def open_update_pr(self, row):
        """Return the open update PR for row, as github.open_update_pr finds it.

        github.open_update_pr picks it among a search's results; here, it
        picks among all open PRs whose title starts with one of row's names.
        """
        return github.open_update_pr(row, self.titled(row))

    def titled(self, row):
        """Return the open PRs whose titles start with one of row's names."""
        found = {}
        for n in github.pr_names(row):
            for pr in self.by_package.get(n, []):
                found.setdefault(pr["number"], pr)  # once, under any name
        return list(found.values())


def add_counts(rows, now, listed=None):
    """Count every row's open PRs and issues, and find its open update PR.

    Each row gets "openPRs", "openIssues" and "openPR", from one listing of
    all open PRs and issues, dated now ("countedAt"); and
    "searchShowsMore" where GitHub's search, which the page links, finds
    more than those that name the row.

    Args:
        rows: The rows, changed in place.
        now: The run's time.
        listed: (PRs, issues) from the digest, or None to list them here.

    Returns:
        True, or False, changing nothing, when there's no listing and no
        token, or the listing fails (the sync then searches per package).
    """
    if listed is not None:
        listing = Listing(*listed)
    else:
        tok = github.token()
        if not tok:
            return False
        print("Listing nixpkgs' open PRs and issues...", file=sys.stderr)
        try:
            listing = Listing(*list_open(tok))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print(
                f"::warning::Listing open PRs/issues failed ({e}); searching per "
                "package",
                file=sys.stderr,
            )
            return False
    for row in rows:
        prs, issues = listing.counts(row)
        row.update(openPRs=prs, openIssues=issues, countedAt=now)
        # Where GitHub's search, which the page links, finds more than those
        # that name the row, the page's hover says so.
        search = listing.search_counts(row["searchTerm"])
        more = [
            k
            for k, n, s in zip(("pr", "issue"), (prs, issues), search, strict=True)
            if s > n
        ]
        if more:
            row["searchShowsMore"] = more
        else:
            row.pop("searchShowsMore", None)
        row.pop("openPR", None)
        if pr := listing.open_update_pr(row):
            row["openPR"] = pr
    print(
        f"  {len(listing.prs):,} open PRs and {len(listing.issues):,} issues: "
        f"{len(rows)} packages counted",
        file=sys.stderr,
    )
    for warning in github.count_warnings(rows):
        print(f"::warning::{warning}", file=sys.stderr)
    return True


# One page of the PRs a search finds.
MERGED = """query($q: String!, $after: String) {
  search(type: ISSUE, query: $q, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number title url isDraft baseRefName } }
  }
}"""
# When a commit was committed.
COMMIT_DATE = """query($owner: String!, $name: String!, $rev: String!) {
  repository(owner: $owner, name: $name) {
    object(expression: $rev) { ... on Commit { committedDate } }
  }
}"""
# GitHub's search gives at most 1,000 results: merged PRs are listed in
# windows of this many hours (nixpkgs merges a few hundred a day into master).
WINDOW_HOURS = 12


def channel_date(token, revision):
    """Return when the channel's commit was committed (ISO), or None."""
    owner, name = config.GITHUB_REPO.split("/")
    data = github.graphql(
        token, COMMIT_DATE, {"owner": owner, "name": name, "rev": revision}
    )
    return ((data.get("repository") or {}).get("object") or {}).get("committedDate")


def merged_since(revision):
    """Return when the channel's commit was made, or None.

    It's for the per-package searches of merged PRs (github.add_update_prs).
    None when there's no token, the revision isn't known, or GitHub can't
    say.
    """
    tok = github.token()
    if not tok or not revision or revision == config.NIXPKGS_BRANCH:
        return None
    try:
        return channel_date(tok, revision)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"::warning::The channel's commit date: {e}", file=sys.stderr)
        return None


def list_merged(token, since, now):
    """List the PRs merged into master between since and now (ISO times).

    Returns:
        The PRs, as GraphQL nodes.

    Raises:
        urllib.error.URLError, OSError, ValueError: A request failed,
            GitHub's answer was incomplete, or a window has more than
            search's 1,000 results (some would be missing).
    """
    start = datetime.fromisoformat(since.replace("Z", "+00:00"))
    end = datetime.fromisoformat(now)
    found = []
    while start < end:
        stop = min(start + timedelta(hours=WINDOW_HOURS), end)
        window = f"{start:%Y-%m-%dT%H:%M:%SZ}..{stop:%Y-%m-%dT%H:%M:%SZ}"
        query = f"repo:{config.GITHUB_REPO} is:pr is:merged base:master merged:{window}"
        after = None
        while True:
            data = github.graphql(token, MERGED, {"q": query, "after": after})
            page = data.get("search")
            if page is None:
                raise ValueError("GitHub didn't answer the search for merged PRs")
            if page["issueCount"] > 1000:
                raise ValueError(f"more than 1,000 PRs merged in {window}")
            found += [n for n in page["nodes"] if n and n.get("number")]
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        start = stop
    return found


def add_master_prs(rows, revision, now, listed=None):
    """Find each row's update PR merged into master since the channel's commit.

    That's an update the channel doesn't have yet ("masterPR"), found in
    one listing of the PRs merged since.

    Args:
        rows: The rows, changed in place.
        revision: The channel's commit.
        now: The run's time.
        listed: The digest's merged PRs (since that same commit), or None
            to list them here.

    Returns:
        True, or False, changing nothing, when there's no listing and no
        token, or the listing fails (the sync then searches per package).
    """
    if listed is not None:
        merged, since = listed, "the digest"
    else:
        tok = github.token()
        if not tok:
            return False
        try:
            since = channel_date(tok, revision)
            if not since:
                raise ValueError(
                    f"no commit date for the channel's revision {revision}"
                )
            merged = list_merged(tok, since, now)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print(
                f"::warning::Listing merged PRs failed ({e}); searching per package",
                file=sys.stderr,
            )
            return False
    by_package = {}
    for pr in merged:
        for package in github.title_packages(pr.get("title")):
            by_package.setdefault(package, []).append(pr)
    for row in rows:
        row.pop("masterPR", None)
        titled = list(
            {
                pr["number"]: pr
                for n in github.pr_names(row)
                for pr in by_package.get(n, [])
            }.values()
        )
        if pr := github.merged_update_pr(row, titled):
            row["masterPR"] = pr
    print(
        f"  {len(merged):,} PRs merged into master since the channel's commit "
        f"({since})",
        file=sys.stderr,
    )
    return True
