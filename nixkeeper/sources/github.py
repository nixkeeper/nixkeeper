"""Talk to GitHub: PR and issue counts, update PRs, status issues and tags.

The per-package searches count nixpkgs' open PRs and issues, and find the
update PRs among them, in batched GraphQL searches (github_bulk lists them
in bulk instead, when it can). This module also keeps the status issues
(notify.py), and reads the tags and branch commits the update checks need.
"""

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from .. import config, log, schedule
from ..changes import is_outdated
from ..versions import is_newer, version_key


def token(use_gh=True):
    """Return a GitHub token, or None.

    It's read from the file NIXKEEPER_GITHUB_TOKEN_FILE names (how a service
    gets its secrets, such as systemd credentials), else GITHUB_TOKEN (set
    by the workflows), else the local gh login, unless use_gh is false.
    """
    path = os.environ.get("NIXKEEPER_GITHUB_TOKEN_FILE")
    if path:
        try:
            with open(path) as f:
                return f.read().strip() or None
        except OSError as e:
            log.warn(f"couldn't read NIXKEEPER_GITHUB_TOKEN_FILE ({e})")
            return None
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    if not use_gh:
        return None
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return result.stdout.strip() or None
    except FileNotFoundError:
        return None


def graphql(token, query, variables):
    """Send one GitHub GraphQL request.

    Errors GitHub reports for parts of the query are printed; those parts
    are then missing or null in the data.

    Returns:
        The answer's data.

    Raises:
        urllib.error.URLError, OSError, ValueError: The request itself
            failed.
    """
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "User-Agent": config.user_agent(),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    result = _send(req, timeout=60)
    for err in result.get("errors") or []:
        log.info(f"  GitHub error: {err.get('message')}")
    return result.get("data") or {}


def rate_limit_wait(err, now=None):
    """Return the seconds GitHub asked to wait, when err is its rate limit.

    That's a 403 or 429 with Retry-After (its secondary limits), or, once
    x-ratelimit-remaining is 0, the time until x-ratelimit-reset (the
    hourly limit).

    Returns:
        The seconds, or None when err is another error.
    """
    if not isinstance(err, urllib.error.HTTPError) or err.code not in (403, 429):
        return None
    headers = err.headers or {}
    retry_after = str(headers.get("Retry-After", "")).strip()
    if retry_after.isdigit():
        return int(retry_after)
    reset = str(headers.get("x-ratelimit-reset", "")).strip()
    if headers.get("x-ratelimit-remaining") == "0" and reset.isdigit():
        return max(0, int(reset) - int(now if now is not None else time.time()))
    return None


def _open_json(req, timeout):
    """Send req and return its JSON answer."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _send(req, timeout):
    """Send req and return GitHub's JSON answer.

    When GitHub says to slow down (its rate limits), this waits as long as
    it asks and tries once more, if that's at most MAX_RETRY_AFTER seconds;
    otherwise it raises, like any failure.
    """
    try:
        return _open_json(req, timeout)
    except urllib.error.HTTPError as e:
        e.close()  # an HTTP error is also an open response
        wait = rate_limit_wait(e)
        if wait is None or wait > config.MAX_RETRY_AFTER:
            raise
        log.info(f"  GitHub asks to slow down: waiting {wait}s")
        time.sleep(wait)
    return _open_json(req, timeout)


# The fields asked for each pull request a search returns.
PR_FIELDS = "nodes { ... on PullRequest { number title url isDraft baseRefName } }"


def search_batch(token, searches):
    """Run several GitHub issue and PR searches in one GraphQL request.

    Args:
        token: The GitHub token.
        searches: [(query, first)], first being how many matching pull
            requests to return besides the count (0 to only count).

    Returns:
        [(count, [pull requests])], in order. A search GitHub couldn't
        answer gives (None, []); a failed request gives that for all of
        them.
    """
    params = ", ".join(f"$q{i}: String!" for i in range(len(searches)))
    fields = "\n".join(
        f"  s{i}: search(type: ISSUE, first: {first}, query: $q{i}) "
        f"{{ issueCount{' ' + PR_FIELDS if first else ''} }}"
        for i, (_, first) in enumerate(searches)
    )
    try:
        data = graphql(
            token,
            f"query({params}) {{\n{fields}\n}}",
            {f"q{i}": q for i, (q, _) in enumerate(searches)},
        )
    except (urllib.error.URLError, OSError, ValueError) as e:
        if isinstance(e, urllib.error.HTTPError):
            e.close()
        log.info(f"  GitHub search batch failed ({e})")
        return [(None, [])] * len(searches)
    results = []
    for i in range(len(searches)):
        found = data.get(f"s{i}") or {}
        nodes = [n for n in found.get("nodes") or [] if n and n.get("number")]
        results.append((found.get("issueCount"), nodes))
    return results


def search_counts(token, queries):
    """Return the result counts of several searches, in order.

    A search GitHub couldn't answer gives None.
    """
    return [count for count, _ in search_batch(token, [(q, 0) for q in queries])]


def pr_names(row):
    """Return the names a row's update PR can be titled with.

    That's its search term and each of its attributes, all at its one
    version (heroic's update is titled "heroic-unwrapped: 2.22.3 ->
    2.22.4").
    """
    return list(dict.fromkeys([row["searchTerm"], *(row.get("attrs") or [])]))


# Punctuation that can follow a title's version when the title goes on.
TITLE_PUNCTUATION = ",;:."


# One update in a title: "names: from -> to". A title can have several,
# separated by ";" ("minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0"),
# and an update several names, separated by "," ("chromium,chromedriver:
# 155.0.8059.79 -> 155.0.8059.84").
TITLE_UPDATE = re.compile(r"^\s*([\w.+-]+(?:\s*,\s*[\w.+-]+)*): (\S+) -> (\S+)")


def title_updates(title):
    """Return each update a PR's title makes, in order, as [(names, from, to)]."""
    found = []
    for part in (title or "").split(";"):
        if m := TITLE_UPDATE.match(part):
            names = [n.strip() for n in m.group(1).split(",")]
            found.append((names, m.group(2), m.group(3)))
    return found


# Tags before a title's package: "[Backport release-26.05] ", "[26.05] ",
# "[WIP] " (232 of 12,554 open PRs, 2026-10-23).
TITLE_TAGS = re.compile(r"^\s*(?:(?:\[[^\]]*\]|\([^)]*\))\s*)+")


def title_packages(title):
    """Return the names a PR's title is about, to find it by.

    That's each update's names, and what comes before the title's first ":"
    (an update or not), after any tags ("[26.05] libsidplayfp: Apply fix
    for CVE-2026-111148").
    """
    names = {n for found, _, _ in title_updates(title) for n in found}
    return names | {TITLE_TAGS.sub("", title or "").split(":", 1)[0]}


def update_prs(nodes, names):
    """Return the pull requests that update a package named one of names.

    A PR counts when its title follows nixpkgs' convention,
    "wesnoth-devel: 1.19.24 -> 1.19.28", for exactly one of names (not
    wesnoth-devel-extra, which a search would also find), anywhere in the
    title (title_updates).

    Args:
        nodes: The pull requests, as GraphQL nodes.
        names: A name, or several.

    Returns:
        [{"number", "title", "url", "draft", "base", "from", "to",
        "author"?, "mergedBy"?}].
    """
    names = {names} if isinstance(names, str) else set(names)
    prs = []
    for node in nodes:
        mine = [u for u in title_updates(node.get("title")) if names & set(u[0])]
        if mine:
            _, before, after = mine[0]
            prs.append(
                {
                    "number": node["number"],
                    "title": node["title"],
                    "url": node["url"],
                    "draft": bool(node.get("isDraft")),
                    "base": node.get("baseRefName"),
                    # Without the punctuation of a title that goes on
                    # ("fribidi: 1.0.16 -> 1.0.17, ...", "-> 3.13.16; ...").
                    "from": before.rstrip(TITLE_PUNCTUATION),
                    "to": after.rstrip(TITLE_PUNCTUATION),
                    # Who opened and merged it, when the listing says
                    # (nixkeeper-prs' merged PRs): an update's fix credits
                    # them (history.fixes).
                    **{k: node[k] for k in ("author", "mergedBy") if node.get(k)},
                }
            )
    return prs


def open_update_pr(row, nodes):
    """Return the open PR updating row past nixpkgs' version, or None.

    Of several, it's the one going to the highest version, a ready one
    before a draft.
    """
    prs = [
        pr
        for pr in update_prs(nodes, pr_names(row))
        if not row.get("nixVersion") or is_newer(pr["to"], row["nixVersion"])
    ]
    return max(prs, key=lambda p: (version_key(p["to"]), not p["draft"]), default=None)


def merged_update_pr(row, nodes):
    """Return row's update PR merged into master past the channel's version.

    Of several, it's the one going to the highest version; None when
    there's none. Only master counts: updates merged into staging reach
    master weeks later, through staging-next.
    """
    prs = [
        pr
        for pr in update_prs(nodes, pr_names(row))
        if pr["base"] == "master"
        and (not row.get("nixVersion") or is_newer(pr["to"], row["nixVersion"]))
    ]
    return max(prs, key=lambda p: version_key(p["to"]), default=None)


def latest_tags(token, repos):
    """Read the 100 most recent tags of each repository, in one request.

    The tags are ordered by their commit's date.

    Args:
        token: The GitHub token.
        repos: The repositories, as "owner/repo".

    Returns:
        {repo: [tag names]}; a repository GitHub couldn't answer is missing.

    Raises:
        urllib.error.URLError, OSError, ValueError: The request failed.
    """
    params = ", ".join(f"$o{i}: String!, $n{i}: String!" for i in range(len(repos)))
    fields = "\n".join(
        f"  r{i}: repository(owner: $o{i}, name: $n{i}) {{ refs(refPrefix: "
        '"refs/tags/", first: 100, orderBy: {field: TAG_COMMIT_DATE, '
        "direction: DESC}) { nodes { name } } }"
        for i in range(len(repos))
    )
    variables = {}
    for i, repo in enumerate(repos):
        variables[f"o{i}"], variables[f"n{i}"] = repo.split("/", 1)
    data = graphql(token, f"query({params}) {{\n{fields}\n}}", variables)
    return {
        repo: [n["name"] for n in data[f"r{i}"]["refs"]["nodes"]]
        for i, repo in enumerate(repos)
        if (data.get(f"r{i}") or {}).get("refs")
    }


def branch_commits(token, branches):
    """Read each branch's newest commit and its commit counts, in one request.

    Args:
        token: The GitHub token.
        branches: [(owner/repo, branch, since, until)], since and until as
            ISO times; until may be None.

    Returns:
        For each branch, in order: {"oid", "committedDate", "since",
        "until"}, its newest commit, and how many commits it has since
        `since`, and between `since` and `until`. None where GitHub
        couldn't answer (no such repository or branch).

    Raises:
        urllib.error.URLError, OSError, ValueError: The request failed.
    """
    params, fields, variables = [], [], {}
    for i, (repo, branch, since, until) in enumerate(branches):
        params.append(f"$o{i}: String!, $n{i}: String!, $b{i}: String!")
        params.append(f"$s{i}: GitTimestamp!")
        counts = f"since: history(since: $s{i}) {{ totalCount }}"
        if until:
            params.append(f"$u{i}: GitTimestamp!")
            counts += f" until: history(since: $s{i}, until: $u{i}) {{ totalCount }}"
            variables[f"u{i}"] = until
        commit = f"... on Commit {{ oid committedDate {counts} }}"
        fields.append(
            f"  r{i}: repository(owner: $o{i}, name: $n{i}) "
            f"{{ ref(qualifiedName: $b{i}) {{ target {{ {commit} }} }} }}"
        )
        variables[f"o{i}"], variables[f"n{i}"] = repo.split("/", 1)
        variables[f"b{i}"] = f"refs/heads/{branch}"
        variables[f"s{i}"] = since
    data = graphql(
        token, f"query({', '.join(params)}) {{\n" + "\n".join(fields) + "\n}", variables
    )
    results = []
    for i in range(len(branches)):
        target = ((data.get(f"r{i}") or {}).get("ref") or {}).get("target") or {}
        if not target.get("committedDate"):
            results.append(None)
            continue
        results.append(
            {
                "oid": target["oid"],
                "committedDate": target["committedDate"],
                "since": (target.get("since") or {}).get("totalCount", 0),
                "until": (target.get("until") or {}).get("totalCount", 0),
            }
        )
    return results


# How many pull requests to look through for update PRs: those with the
# attribute in the title, most recently updated first.
PR_CANDIDATES = 20


def query(row, state):
    """Return the GitHub search for row's PRs or issues.

    The search is in titles only, as nixpkgs' titles name the package,
    while the bodies of big rebuild PRs list hundreds of unrelated ones.

    Args:
        row: The row.
        state: "pr state:open", "pr is:merged" or "issue state:open", and
            any further qualifiers.
    """
    return (
        f"repo:{config.GITHUB_REPO} is:{state} in:title {row['searchTerm']} "
        "sort:updated-desc"
    )


def run_searches(tok, searches, handle):
    """Run searches in batches, calling handle for each result.

    Args:
        tok: The GitHub token.
        searches: [(row, what, query, first)].
        handle: Called as handle(row, what, count, pull requests).
    """
    for start in range(0, len(searches), config.GITHUB_SEARCH_BATCH):
        batch = searches[start : start + config.GITHUB_SEARCH_BATCH]
        results = search_batch(tok, [(q, first) for _, _, q, first in batch])
        for (row, what, _, _), (count, nodes) in zip(batch, results, strict=True):
            handle(row, what, count, nodes)


def quiet(row, before):
    """Return whether row's counts have nothing going on.

    That's when nothing was open at the last sync (no PRs, no issues), and
    the package isn't outdated. Those are searched every QUIET_DAYS
    (schedule.due), the rest daily (schedule.daily).
    """
    return (
        before is not None
        and before.get("openPRs") == 0
        and before.get("openIssues") == 0
        and not is_outdated(row)
    )


def add_counts(rows, previous=None, now=None):
    """Count each row's open PRs and issues with GitHub's searches.

    The searches look for its attribute name in the title, as the ones the
    page links to do. Each row gets "openPRs" and "openIssues", and
    "openPR", the open update PR among them, if any (their titles come with
    the same search). Counted ones are dated ("countedAt").

    With the last run's data (previous) and the time (now), a package with
    nothing open and nothing pending keeps its counts until it's due
    (quiet), and one counted less than a day ago keeps them too.

    Args:
        rows: The rows, changed in place.
        previous: The last run's data, or None.
        now: The run's time, or None.
    """
    tok = token()
    if not tok:
        log.info("No GITHUB_TOKEN or gh login: skipping open PR/issue counts.")
        return
    before = {row["name"]: row for row in (previous or {}).get("packages", [])}
    searches = []
    searched = []
    for row in rows:
        old = before.get(row.get("name"))
        row.pop("openPR", None)  # found again below, if still there
        if (
            now
            and quiet(row, old)
            and not schedule.due(row["name"], old.get("countedAt"), now)
        ):
            row.update(openPRs=0, openIssues=0, countedAt=old["countedAt"])
            continue
        if (
            now
            and old
            and old.get("openPRs") is not None
            and old.get("countedAt")
            and not schedule.daily(old["countedAt"], now)
        ):
            # Counted less than a day ago: kept (a sync every few hours
            # searches daily, as a daily one does).
            row.update(
                openPRs=old["openPRs"],
                openIssues=old.get("openIssues", 0),
                countedAt=old["countedAt"],
            )
            if old.get("openPR"):
                row["openPR"] = old["openPR"]
            continue
        searched.append(row)
        searches.append((row, "openPRs", query(row, "pr state:open"), PR_CANDIDATES))
        searches.append((row, "openIssues", query(row, "issue state:open"), 0))

    def handle(row, what, count, nodes):
        """Record one search's result on row."""
        row[what] = count
        if what == "openPRs" and (pr := open_update_pr(row, nodes)):
            row["openPR"] = pr

    kept = len(rows) - len(searched)
    log.info(
        f"Searching open PRs/issues ({len(searches)} searches"
        + (
            f"; {kept} packages with none open were counted in the last "
            f"{config.QUIET_DAYS} days)"
            if kept
            else ")"
        )
        + "..."
    )
    run_searches(tok, searches, handle)
    for row in searched:
        if now and row.get("openPRs") is not None and row.get("openIssues") is not None:
            row["countedAt"] = now
    for warning in count_warnings(rows):
        log.warn(f"{warning}")


def add_update_prs(rows, open_prs=True, merged_since=None):
    """Find the rows' update PRs with GitHub's searches.

    That's for outdated rows, typically. Each gets "masterPR", the update
    PR merged into master that the channel doesn't have yet, and, with
    open_prs, "openPR" as add_counts finds it (skip it when add_counts just
    ran). A search that fails leaves that field as it was.

    Args:
        rows: The rows, changed in place.
        open_prs: Whether to search for the open update PRs too.
        merged_since: When the channel's commit was made (ISO). Only PRs
            merged since can be what the channel lacks: a PR merged before
            is in it, whatever its version says (xmage's 1.4.60 sorts above
            nixpkgs' later 1.4.60-dev_2026-06-28 snapshot). Without it,
            masterPR is left as it was.
    """
    tok = token()
    if not tok:
        log.info("No GITHUB_TOKEN or gh login: skipping update PRs.")
        return
    if not merged_since:
        log.info("The channel's commit date isn't known: merged PRs not searched.")
    searches = []
    for row in rows:
        if open_prs:
            searches.append((row, "openPR", query(row, "pr state:open"), PR_CANDIDATES))
        if merged_since:
            merged = query(row, f"pr is:merged merged:>={merged_since}")
            searches.append((row, "masterPR", merged, PR_CANDIDATES))

    def handle(row, what, count, nodes):
        """Record one search's result on row, unless the search failed."""
        if count is None:
            return  # the search failed: keep what the row had
        find = open_update_pr if what == "openPR" else merged_update_pr
        row.pop(what, None)
        if pr := find(row, nodes):
            row[what] = pr

    log.info(f"Searching update PRs ({len(searches)} searches)...")
    run_searches(tok, searches, handle)


def count_warnings(rows):
    """Warn of counts that are probably wrong, though no error says so.

    add_counts (here and in github_bulk) says them as warnings (log.warn),
    which show up as annotations on the workflow run.

    Returns:
        The warnings.
    """
    warnings = []
    fields = ("openPRs", "openIssues")
    missing = sum(1 for row in rows for f in fields if row.get(f) is None)
    if missing:
        warnings.append(
            f"{missing} of {2 * len(rows)} open PR/issue searches failed; "
            "those counts are blank"
        )
    counted = [
        (row["openPRs"], row["openIssues"])
        for row in rows
        if row.get("openPRs") is not None and row.get("openIssues") is not None
    ]
    # A token that can't see pull requests gets issue counts back for the PR
    # searches (see permissions in .github/workflows/data-daily.yml).
    if (
        len(counted) >= 5
        and any(prs for prs, _ in counted)
        and all(prs == issues for prs, issues in counted)
    ):
        warnings.append(
            "every package's open PR count equals its open issue count: the token "
            "probably can't see pull requests (does the workflow grant "
            "pull-requests: read?)"
        )
    return warnings


# Merges of staging-next into master: mass rebuilds land then, and the
# failing counts jump for days after (the overview's trend markers).
STAGING_NEXT = (
    "repo:NixOS/nixpkgs is:pr is:merged base:master head:staging-next merged:>={since}"
)


def staging_next_merges(token, since):
    """List the merges of staging-next into nixpkgs master since a day.

    Returns:
        [{"day": the day it was merged (UTC), "kind": "staging-next", "pr",
        "title"}] for each merge since `since` (YYYY-MM-DD), or None without a
        token or when GitHub couldn't answer.
    """
    if not token:
        return None
    try:
        data = graphql(
            token,
            "query($q: String!) { search(type: ISSUE, first: 20, query: $q) "
            "{ nodes { ... on PullRequest { number title mergedAt } } } }",
            {"q": STAGING_NEXT.format(since=since)},
        )
    except (urllib.error.URLError, OSError, ValueError) as e:
        if isinstance(e, urllib.error.HTTPError):
            e.close()
        log.info(f"  staging-next merges: GitHub didn't answer ({e})")
        return None
    nodes = (data.get("search") or {}).get("nodes") or []
    return [
        {
            "day": n["mergedAt"][:10],
            "kind": "staging-next",
            "pr": n["number"],
            "title": n.get("title") or "",
        }
        for n in nodes
        if n and n.get("number") and n.get("mergedAt")
    ]


# The label of nixkeeper's own status issue.
STATUS_LABEL = "nixkeeper-status"


def api(method, path, token, body=None):
    """Call the GitHub REST API.

    Returns:
        The decoded JSON, or None when the answer is empty.
    """
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "User-Agent": config.user_agent(),
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return json.loads(data) if data else None


def status_issue_body(repo, token, label=STATUS_LABEL):
    """Return the body of the open issue labelled label, or None if there's none."""
    issues = api(
        "GET", f"/repos/{repo}/issues?labels={label}&state=open&per_page=1", token
    )
    return issues[0].get("body") or "" if issues else None


def update_status_issue(
    repo,
    token,
    title,
    body,
    comment=None,
    label=STATUS_LABEL,
    about="The issue nixkeeper keeps up to date",
):
    """Rewrite the open issue labelled label, opening it if there's none.

    The label is created first, if needed, with about as its description.
    comment is then posted, when given.

    Returns:
        The issue's number.
    """
    try:
        api(
            "POST",
            f"/repos/{repo}/labels",
            token,
            {"name": label, "color": "5319e7", "description": about},
        )
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422: the label already exists
            raise
        e.close()
    issues = api(
        "GET", f"/repos/{repo}/issues?labels={label}&state=open&per_page=1", token
    )
    if issues:
        number = issues[0]["number"]
        api("PATCH", f"/repos/{repo}/issues/{number}", token, {"body": body})
    else:
        number = api(
            "POST",
            f"/repos/{repo}/issues",
            token,
            {"title": title, "body": body, "labels": [label]},
        )["number"]
    if comment:
        api("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": comment})
    return number


# The issues of those who get a status issue of their own (notifications/,
# notify.py): one label for all, each told apart by its title.
SUBSCRIBER_LABEL = "nixkeeper-subscriber"


def ensure_label(repo, token, label, about, color="5319e7"):
    """Create label in repo unless it's there already."""
    try:
        api(
            "POST",
            f"/repos/{repo}/labels",
            token,
            {"name": label, "color": color, "description": about},
        )
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422: the label already exists
            raise
        e.close()


def open_issues(repo, token, label):
    """Return the open issues labelled label, all pages, as {title: number}."""
    found, page = {}, 1
    while True:
        issues = api(
            "GET",
            f"/repos/{repo}/issues?labels={label}&state=open&per_page=100&page={page}",
            token,
        )
        for issue in issues or []:
            if "pull_request" not in issue:
                found[issue["title"]] = issue["number"]
        if len(issues or []) < 100:
            return found
        page += 1


def write_issue(repo, token, number, title, body, label, comment=None):
    """Rewrite issue number's body, or open the issue when number is None.

    comment is then posted, when given.

    Returns:
        The issue's number.
    """
    if number:
        api("PATCH", f"/repos/{repo}/issues/{number}", token, {"body": body})
    else:
        number = api(
            "POST",
            f"/repos/{repo}/issues",
            token,
            {"title": title, "body": body, "labels": [label]},
        )["number"]
    if comment:
        api("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": comment})
    return number


def close_issue(repo, token, number, comment):
    """Comment on issue number, then close it."""
    api("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": comment})
    api("PATCH", f"/repos/{repo}/issues/{number}", token, {"state": "closed"})
