"""Run nixkeeper's own update checks.

The checks (package-lists/update-checks.nix) find the newest upstream
release of a package: from its GitHub repository's tags (or, worked out
from nixpkgs, its repository's on a GitLab instance or Codeberg), or from a
web page such as the vendor's release notes; or, for an unstable version
("1.0-unstable-2024-05-01"), the commits on the branch it follows. A
version only counts as newest on Repology once repositories it trusts
package it (the AUR alone doesn't), so without these checks a fresh release
leaves nixpkgs looking up to date.
"""

import hashlib
import json
import re
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta

from .. import community as community_rules
from .. import config, history, log, schedule, verdict
from ..shape import Row
from ..versions import is_newer, version_key
from . import github, http

__all__ = ["is_newer", "version_key"]  # also used from here (and the tests)


def highest(matches, regex):
    """Return the highest version among regex's matches, or None if there are none.

    The capture group, when regex has one, is the version.
    """
    versions = [m.group(1) if regex.groups else m.group(0) for m in matches if m]
    return max(versions, key=version_key, default=None)


def latest(tags, pattern):
    """Return the highest version among the tags matching pattern.

    Each tag is matched on its own, so ^ and $ are the tag's start and end.
    """
    regex = re.compile(pattern)
    return highest(map(regex.search, tags), regex)


def latest_on_page(text, pattern):
    """Return the highest version anywhere on a page.

    A release-notes page lists old versions too, so which comes first
    doesn't matter.
    """
    regex = re.compile(pattern)
    return highest(regex.finditer(text), regex)


# nixpkgs' unstable versions: what they're based on, then the date (UTC) of
# the commit they package, such as "5.1.0-b2-unstable-2022-11-14".
UNSTABLE = re.compile(r"^(.*-unstable-)([0-9]{4}-[0-9]{2}-[0-9]{2})$")

# When newer commits make an unstable version outdated: once one of them has
# waited this many days, or there are this many of them (whichever comes
# first; None: not that way). A check's outdatedAfter overrides either.
OUTDATED_AFTER = {"days": 90, "commits": None}


def unstable_date(nix_version):
    """Return the date in an unstable version, or None if it isn't one."""
    m = UNSTABLE.match(nix_version or "")
    return m.group(2) if m else None


def unstable_version(nix_version, committed):
    """Return nixpkgs' unstable version moved to a commit's date, if that's later.

    That's the version an update to that commit would have.

    Args:
        nix_version: nixpkgs' version.
        committed: The commit's date, as GitHub gives it (ISO).

    Returns:
        The version, or None when nix_version isn't an unstable version.
    """
    m = UNSTABLE.match(nix_version or "")
    if not m:
        return None
    when = datetime.fromisoformat(committed.replace("Z", "+00:00"))
    date = when.astimezone(UTC).date().isoformat()
    return m.group(1) + max(date, m.group(2))


def outdated_after(check):
    """Return a branch check's limits: the defaults, with its own outdatedAfter."""
    return {**OUTDATED_AFTER, **(check.get("outdatedAfter") or {})}


def record(row: Row, found):
    """Record an update check's result on its row, for verdict.decide.

    It's recorded with whether it counts as newer than nixpkgs' version
    ("newer"). found["newer"], when given, says so already: a branch
    check's newer commits may not count yet. How the result counts in the
    verdict is verdict.decide's (_update_check).

    A rule's check (yours, the community's, or one it follows) is the
    package's own source, as a version feed is: where it and Repology
    disagree on whether nixpkgs is outdated, the check decides. That way
    the verdict is wrong only when the rule is, while Repology's is wrong
    whenever one of its own rules lags (google-chrome's "155 and up are
    betas", kept after 155 went stable). A worked-out check (inferred)
    only adds a newer version Repology hasn't seen, and not even that for
    an older version kept beside a newer one, nor for the version an
    up-to-date rule names.

    Args:
        row: The row, changed in place.
        found: The check's result, {"version", "newer"?, "inferred"?, ...}.
    """
    kept = row.get("nixStatus") == config.KEPT or bool(row.get("keptBeside"))
    newer = found.get("newer")
    if newer is None:
        newer = is_newer(found["version"], row.get("nixVersion"))
    if newer and found.get("inferred") and kept and not row.get("devel"):
        # An older version nixpkgs keeps on purpose beside a newer one
        # (fuse 2.9.9, patchelf 0.15.2, ocamlformat_0_26_0, llvmPackages_18),
        # or one behind in its own series (electron_42 42.11.10, 42.11.14
        # out): a worked-out check can't tell its series, so its repository's
        # newest release (44.7.2) isn't one to update it to. A devel variant that's
        # fallen behind still counts (changes.behind_as_devel).
        newer = False
    if (
        newer
        and found.get("inferred")
        and found["version"] == (row.get("upToDate") or {}).get("ruleNewest")
    ):
        # An up-to-date rule names this very version as not a real release
        # (uptodate.py): a wrong worked-out result is silenced as a wrong
        # Repology verdict is. Any other version still counts (a rule for
        # twinejs about Repology's 7.0.0, another project's, leaves GitHub's
        # 2.12.1 a real release).
        newer = False
    row["upstream"] = {**found, "newer": newer}


def apply(row: Row, found):
    """Record an update check's result on its row, and decide its verdict again.

    Args:
        row: The row, changed in place.
        found: The check's result (record).
    """
    record(row, found)
    verdict.decide(row)


def fingerprint(check):
    """Return a short id of an update check's rule, recorded with its result.

    A rule edited since (another page, pattern, branch, ...) is then due at
    once.
    """
    text = json.dumps(check, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def due(name, check, row, before, now):
    """Return whether an update check should run now.

    A frequent one always runs: it's meant to be quick (browsers' security
    fixes). The rest run at once when never run, edited since, failed last
    time, or nixpkgs' version changed since; daily (schedule.daily) while
    the last run found a newer version; otherwise every QUIET_DAYS
    (schedule.due).

    Args:
        name: The row's name.
        check: The update check.
        row: The row.
        before: The row at the last sync, or None when it's new.
        now: The run's time.
    """
    last = (before or {}).get("upstream") or {}
    if (
        check.get("frequent")
        or not last.get("checkedAt")
        or last.get("rule") != fingerprint(check)
        or "upstream" in ((before or {}).get("notRefreshed") or {})
        or (before or {}).get("nixVersion") != row.get("nixVersion")
    ):
        return True
    if last.get("newer"):
        return schedule.daily(last["checkedAt"], now)
    return schedule.due(name, last["checkedAt"], now)


def add_checks(
    rows: list[Row], checks, previous, now, community=frozenset(), inferred=frozenset()
):
    """Run the update checks of the rows that have one.

    A check that can't run, on GitHub or a web page alike, keeps the
    previous run's result and marks the row as not refreshed: usually the
    check itself needs fixing (a moved page, a changed tag scheme). A check
    that isn't due keeps what it found last time.

    Args:
        rows: The rows, changed in place.
        checks: The update checks, by row name.
        previous: The last run's data.
        now: The run's time.
        community: The names whose check is a community rule
            (community.py), held to its limits and fetched in safe mode.
        inferred: The names whose check was worked out from nixpkgs
            (inferred.py). Nobody wrote those to fix, so one that can't run
            only leaves the row to Repology, without a warning.

    Returns:
        {name: why} for the worked-out checks that couldn't run.
    """
    by_name = {row["name"]: row for row in rows}
    # Checks for untracked packages: reported with the lists (listcheck.py).
    # follows has nothing to fetch: follows.py applies it after master.
    wanted = {
        name: check
        for name, check in checks.items()
        if name in by_name and "follows" not in check
    }
    failed: dict[str, str] = {}
    if not wanted:
        return failed
    before = {row["name"]: row for row in previous["packages"]}
    # Those not due keep what they found last time (due).
    quiet = [
        n for n, c in wanted.items() if not due(n, c, by_name[n], before.get(n), now)
    ]
    for name in quiet:
        apply(by_name[name], before[name]["upstream"])
        del wanted[name]
    log.info(
        f"Running {len(wanted)} update checks"
        + (
            f" ({len(quiet)} found nothing new in the last {config.QUIET_DAYS} days)"
            if quiet
            else ""
        )
        + "..."
    )
    if not wanted:
        return failed

    def keep_previous(name, why):
        """Record that name's check couldn't run (why), keeping its last result.

        A worked-out check is only noted in the result. A rule's failure is
        said in the log, and marks the row as not refreshed.
        """
        if name in inferred:
            failed[name] = why
            return
        # Said so for the page, as a community rule is fixed in nixkeeper
        # itself.
        if name in community and not why.startswith("community rule"):
            why = f"community rule: {why}"
        log.warn(f"update check for {name}: {why}")
        old = before.get(name) or {}
        if old.get("upstream"):
            # Kept, but not deciding: the verdict is decided again once the
            # row is marked not refreshed (verdict._update_check).
            record(by_name[name], old["upstream"])
        history.not_refreshed(by_name[name], "upstream", why, old, now)
        verdict.decide(by_name[name])

    def found(name, version, where, what, **extra):
        """Record a check's result for name, or that nothing matched in where."""
        if version is None:
            keep_previous(name, f"nothing in {where} matches {what}")
        else:
            if name in community:
                extra["community"] = True
            elif name in inferred:
                extra["inferred"] = True
            extra["rule"] = fingerprint(checks[name])
            apply(by_name[name], {"version": version, "checkedAt": now, **extra})

    # A community rule beyond its limits is refused, never run.
    for name in sorted(set(wanted) & set(community)):
        if why := community_rules.safety(wanted[name]):
            keep_previous(name, f"community rule refused: {why}")
            del wanted[name]

    github_checks = {n: c for n, c in wanted.items() if "github" in c}
    if github_checks:
        versions = {n: by_name[n].get("nixVersion") for n in github_checks}
        check_github(github_checks, versions, now, keep_previous, found)
    forge_checks = {n: c for n, c in wanted.items() if "gitlab" in c or "forgejo" in c}
    if forge_checks:
        check_forge_tags(forge_checks, keep_previous, found)
    pages = {n: c for n, c in wanted.items() if "url" in c}
    for name in interleaved(pages):
        last = (before.get(name) or {}).get("upstream")
        check_page(name, pages[name], keep_previous, found, name in community, last)
    return failed


def check_github(checks, versions, now, keep_previous, found):
    """Run the GitHub checks: the tags in one request, the branches in another.

    Args:
        checks: The checks, by row name.
        versions: nixpkgs' version of each package, which a branch check
            compares with.
        now: The run's time.
        keep_previous: add_checks' callback for a check that can't run.
        found: add_checks' callback for a result.
    """
    token = github.token()
    if not token:
        for name in checks:
            keep_previous(name, "no GITHUB_TOKEN or gh login")
        return
    tag_checks = {n: c for n, c in checks.items() if "tags" in c}
    branch_checks = {n: c for n, c in checks.items() if "branch" in c}
    if tag_checks:
        check_tags(token, tag_checks, keep_previous, found)
    if branch_checks:
        check_branches(token, branch_checks, versions, now, keep_previous, found)


def check_tags(token, checks, keep_previous, found):
    """Run the checks against a repository's tags.

    GITHUB_REPOS_BATCH repositories go in each request, so a request that
    fails only affects its own.
    """
    repos = sorted({c["github"] for c in checks.values()})
    tags, failed = {}, {}
    for start in range(0, len(repos), config.GITHUB_REPOS_BATCH):
        batch = repos[start : start + config.GITHUB_REPOS_BATCH]
        try:
            tags.update(github.latest_tags(token, batch))
        except (urllib.error.URLError, OSError, ValueError) as e:
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            failed.update(dict.fromkeys(batch, e))
    for name, check in checks.items():
        repo = check["github"]
        if repo in failed:
            keep_previous(name, f"GitHub request failed ({failed[repo]})")
            continue
        if repo not in tags:
            keep_previous(
                name, f"couldn't read the tags of {repo} (renamed or deleted?)"
            )
            continue
        try:
            version = latest(tags[repo], check["tags"])
        except re.error as e:
            keep_previous(name, f"invalid tags pattern ({e})")
            continue
        found(
            name,
            version,
            f"the tags of {repo}",
            check["tags"],
            repo=repo,
            label=f"{repo} tags",
            url=f"https://github.com/{repo}/tags",
        )


# How many of a repository's tags a forge check reads: the newest, by
# version on GitLab, by creation on Forgejo.
FORGE_TAGS = 100


def forge_tags_url(check):
    """Return the API address of a GitLab or Forgejo check's tags, and their page.

    Neither needs a token for a public repository. GitLab answers a renamed
    project's old path with a redirect to it, which http.get follows.

    Returns:
        (the API's URL, the tags' web page).
    """
    if "gitlab" in check:
        host, path = check["gitlab"].split("/", 1)
        project = urllib.parse.quote(path, safe="")
        return (
            f"https://{host}/api/v4/projects/{project}/repository/tags"
            f"?order_by=version&sort=desc&per_page={FORGE_TAGS}",
            f"https://{host}/{path}/-/tags",
        )
    host, path = check["forgejo"].split("/", 1)
    return (
        f"https://{host}/api/v1/repos/{path}/tags?limit={FORGE_TAGS}",
        f"https://{host}/{path}/tags",
    )


def check_forge_tags(checks, keep_previous, found):
    """Run the checks against a repository's tags on a GitLab instance or Forgejo.

    One request a repository, each site asked at most once every
    SITE_PAUSE_SECONDS (http.pace).

    Args:
        checks: The checks, by row name: {"gitlab": "host/path"} or
            {"forgejo": "host/owner/repo"}, with "tags".
        keep_previous: add_checks' callback for a check that can't run.
        found: add_checks' callback for a result.
    """
    tags, failed = {}, {}
    for check in checks.values():
        url, _ = forge_tags_url(check)
        if url in tags or url in failed:
            continue
        try:
            http.pace(url)
            body = http.get(url, accept="application/json")
            tags[url] = None if body is None else [t["name"] for t in json.loads(body)]
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            failed[url] = e
    for name, check in checks.items():
        url, page = forge_tags_url(check)
        repo = check.get("gitlab") or check["forgejo"]
        if url in failed:
            keep_previous(
                name, f"request to {repo.split('/')[0]} failed ({failed[url]})"
            )
            continue
        if tags[url] is None:
            keep_previous(
                name, f"couldn't read the tags of {repo} (renamed or deleted?)"
            )
            continue
        try:
            version = latest(tags[url], check["tags"])
        except re.error as e:
            keep_previous(name, f"invalid tags pattern ({e})")
            continue
        found(
            name,
            version,
            f"the tags of {repo}",
            check["tags"],
            repo=repo,
            label=f"{repo} tags",
            url=page,
        )


def check_branches(token, checks, versions, now, keep_previous, found):
    """Run the checks for unstable versions, against the branch each follows.

    A package is compared with the commits on its branch since the one
    nixpkgs has: it's outdated once one of them has waited long enough, or
    there are enough of them (outdated_after).
    """
    queries = {}
    for name, check in checks.items():
        date = unstable_date(versions.get(name))
        if date is None:
            keep_previous(
                name,
                f"nixpkgs' version {versions.get(name)} isn't an unstable version "
                "(…-unstable-YYYY-MM-DD): use a tags or url check",
            )
            continue
        # Commits from the day after nixpkgs' (its own day is the same version).
        since = datetime.fromisoformat(date).replace(tzinfo=UTC) + timedelta(days=1)
        # Commits old enough to count: up to `days` ago.
        days = outdated_after(check)["days"]
        until = None
        if days is not None:
            until = datetime.fromisoformat(now) - timedelta(days=days)
            if until <= since:
                until = None  # none can have waited that long yet
        queries[name] = (
            check["github"],
            check["branch"],
            since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            until and until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    if not queries:
        return
    # GITHUB_REPOS_BATCH per request: one that fails only affects its own.
    names = list(queries)
    results = {}
    for start in range(0, len(names), config.GITHUB_REPOS_BATCH):
        batch = names[start : start + config.GITHUB_REPOS_BATCH]
        try:
            answers = github.branch_commits(token, [queries[n] for n in batch])
        except (urllib.error.URLError, OSError, ValueError) as e:
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            for name in batch:
                keep_previous(name, f"GitHub request failed ({e})")
            continue
        results.update(zip(batch, answers, strict=True))
    for name, head in results.items():
        repo, branch, _, until = queries[name]
        if head is None:
            keep_previous(
                name, f"couldn't read branch {branch} of {repo} (renamed or deleted?)"
            )
            continue
        limits = outdated_after(checks[name])
        behind, waited = head["since"], head["until"] if until else 0
        found(
            name,
            unstable_version(versions[name], head["committedDate"]),
            f"branch {branch} of {repo}",
            "",
            newer=bool(
                behind
                and (
                    (limits["days"] is not None and waited > 0)
                    or (limits["commits"] is not None and behind >= limits["commits"])
                )
            ),
            behind=behind,
            outdatedAfter=limits,
            repo=repo,
            label=f"{repo} {branch} branch",
            url=f"https://github.com/{repo}/commits/{branch}",
            commit=head["oid"],
        )


def interleaved(pages):
    """Order the page checks so they take turns between sites.

    That's one from each site, then the next from each, and so on, so a
    site with many rules isn't waited on back to back (http.pace).

    Args:
        pages: The page checks, {name: check}.

    Returns:
        The names, in that order.
    """
    by_site = {}
    for name, check in pages.items():
        site = urllib.parse.urlsplit(check["url"]).netloc.lower()
        by_site.setdefault(site, []).append(name)
    order = []
    for turn in range(max(map(len, by_site.values()), default=0)):
        order += [names[turn] for names in by_site.values() if turn < len(names)]
    return order


def check_page(name, check, keep_previous, found, safe=False, last=None):
    """Run a check against a web page, such as a vendor's release notes.

    When the last result read this same page with the same pattern, the
    server is asked to send it only if it changed since (http.get_page).
    When it hasn't, what was found then still holds, without downloading it
    again (the Edge check's page is 1 MB, hourly).

    Args:
        name: The row's name.
        check: The check.
        keep_previous: add_checks' callback for a check that can't run.
        found: add_checks' callback for a result.
        safe: Whether it's a community rule's page (http.get's safe mode).
        last: The row's last result ("upstream"), or None.
    """
    url, pattern = check["url"], check["pattern"]
    last = last or {}
    cached = last.get("page") or {}
    if last.get("url") != url or cached.get("pattern") != pattern:
        cached = None  # read another way: nothing to compare with
    try:
        text, page = http.get_page(url, cached and last.get("version") and cached, safe)
        if text is None:
            keep_previous(name, f"{url} answered 404 (moved?)")
            return
        if text is http.NOT_MODIFIED:
            found(
                name,
                last["version"],
                url,
                pattern,
                label=urllib.parse.urlsplit(url).netloc,
                url=url,
                page=cached,
            )
            return
        version = latest_on_page(text, pattern)
    except http.UnsafeURL as e:
        keep_previous(name, f"community rule refused: {e.reason}")
        return
    except (urllib.error.URLError, OSError) as e:
        keep_previous(name, f"couldn't fetch {url} ({e})")
        return
    except re.error as e:
        keep_previous(name, f"invalid pattern ({e})")
        return
    # What to send next time, and the pattern it goes with.
    extra = {"page": {**page, "pattern": pattern}} if page else {}
    found(
        name,
        version,
        url,
        pattern,
        label=urllib.parse.urlsplit(url).netloc,
        url=url,
        **extra,
    )
