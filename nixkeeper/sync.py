"""Run one sync: gather every source's data on the tracked packages, and write it.

`main` calls one function per phase, in order:

1. start: read the channel's package index, the package lists and the last
   sync's data, and decide which packages to track.
2. repology: look the packages up on Repology and make a row for each.
3. own_sources_and_lists: add versions from sources Repology doesn't cover,
   and each row's lists, teams and set.
4. update_checks: apply the up-to-date rules and run the update checks.
5. builds: add Hydra's builds (asked in the background since the start, as
   Hydra is the slowest source), master's versions and the follows.
6. update_bot: add the update bot's (nixpkgs-update's) attempts.
7. github_and_staging: add the PR and issue counts, the update PRs, and how
   staging-next builds.
8. vulnerabilities_and_fixes: add the CVEs, and what was fixed since.
9. write: write the data folder.
10. notify_changes: update the status issues.

Each phase's time is in the log at the end (timing.py). Run with
`nixkeeper sync` (cli.py), or `nix run .#sync` from a checkout.
"""

import dataclasses
import sys
import time
from datetime import UTC, datetime, timedelta

from . import (
    background,
    community,
    config,
    datastore,
    follows,
    history,
    inferred,
    listcheck,
    lookup,
    notify,
    rows,
    scale,
    timing,
    tracking,
    uptodate,
    verdict,
    version,
)
from .changes import is_outdated
from .sources import (
    about,
    branches,
    cran_digest,
    emacs_digest,
    github,
    github_bulk,
    hydra,
    hydra_digest,
    nixpkgs_update,
    prs_digest,
    releases_digest,
    stackage_digest,
    typst_digest,
    updates_digest,
    upstream,
    versions_digest,
    vulnerabilities_digest,
)
from .sources import nixpkgs as nixpkgs_source

# The sources whose packages are compared with them instead of Repology:
# Typst Universe, the Emacs archives, Stackage LTS, CRAN and Bioconductor
# (sources/feeds.py).
FEEDS = (typst_digest, emacs_digest, stackage_digest, cran_digest)


def ask_hydra(attrs, nixpkgs, revision, previous, now, bulk=frozenset()):
    """Collect Hydra's build results for the tracked attributes.

    Runs in the background from the start of the sync (main), as Hydra is
    the slowest source. The jobs nixkeeper-hydra's digest can answer are
    taken from it (hydra_digest); the other jobs that are due for a check
    are asked of Hydra itself, and all of them when the digest is out of
    date.

    Args:
        attrs: The nixpkgs attributes to collect builds for.
        nixpkgs: The channel's package index.
        revision: The channel's commit.
        previous: The last sync's data.
        now: This run's time (ISO 8601).
        bulk: The attributes only the digest answers (with every package,
            those not on the lists). Their meta.broken comes from the
            package index, for x86_64-linux, rather than being evaluated.

    Returns:
        (broken, fetched), for hydra.add_builds: broken maps an attribute
        nixpkgs marks broken to its systems; fetched maps a job to Hydra's
        answer.
    """
    started = time.monotonic()
    deep = [a for a in attrs if a not in bulk]
    broken = nixpkgs_source.broken(deep, revision) if deep else {}
    for attr in bulk:
        if nixpkgs[attr]["meta"].get("broken"):
            broken.setdefault(attr, ["x86_64-linux"])
    found, ask = {}, []
    digest = hydra_digest.load(now)
    before = hydra.last_run(previous)[0]
    if digest is not None:
        found, ask = hydra_digest.answers(
            digest, hydra.jobs(deep, nixpkgs), broken, before
        )
    if bulk:
        found.update(
            hydra_digest.bulk_answers(
                digest, hydra.jobs(sorted(bulk), nixpkgs), broken, before
            )
        )
    due = hydra.due_jobs(deep, nixpkgs, previous, now, broken)
    jobs = ask + [j for j in due if j not in found and j not in ask]
    print(
        f"Hydra, in the background: {len(found):,} jobs from the digest, "
        f"{len(jobs)} to ask Hydra about...",
        file=sys.stderr,
    )
    # Hydra's own answers don't say which dependency failed; the digest
    # does, for the same build.
    fetched = {**found, **hydra_digest.with_blockers(hydra.fetch(jobs, broken), digest)}
    minutes = (time.monotonic() - started) / 60
    print(f"Hydra, in the background: done in {minutes:.0f} min", file=sys.stderr)
    return broken, fetched


def trend_events(previous, now, known=None):
    """List the events this run adds to the overview's trends.

    These are staging-next merges into master in the last month (asked again
    every day, and kept once each), nixkeeper itself being updated since the
    last sync, and a change in how nixkeeper counts (on the first day it ran
    with it).

    Args:
        previous: The last sync's data.
        now: This run's time (ISO 8601).
        known: The events kept so far (datastore.read_events); read here
            when not given.

    Returns:
        The new events, as datastore.with_events takes them.
    """
    since = (datetime.fromisoformat(now) - timedelta(days=30)).date().isoformat()
    events = github.staging_next_merges(github.token(), since) or []
    if previous.get("version") and previous["version"] != version():
        events.append(
            {
                "day": now[:10],
                "kind": "nixkeeper",
                "version": version(),
                "from": previous["version"],
            }
        )
    # A change in how nixkeeper counts is marked on the first day it ran:
    # the last sync's day if that sync came after the change was merged (an
    # instance running main), otherwise this run's.
    texts = {
        e.get("text") for e in (datastore.read_events() if known is None else known)
    }
    last = previous.get("checkedAt") or ""
    for change in config.COUNTING_CHANGES:
        if change["text"] in texts:
            continue
        ran = last if last and last >= change["merged"] else now
        events.append({"day": ran[:10], "kind": "counting", "text": change["text"]})
    return events


@dataclasses.dataclass(frozen=True)
class Run:
    """What a sync works from, made once by start and not changed after.

    Attributes:
        now: This run's time (ISO 8601).
        nixpkgs: The channel's package index.
        lists: The package lists.
        previous: The last sync's data.
        revision: The channel's commit, or the branch's name when it
            couldn't be read.
        everything: Whether the instance tracks every package (the community
            instance) rather than only the lists'. The others are then read
            in bulk only, from the digests and the listings.
        listed: The lists' packages (tracking.tracked_packages).
        bulk: With every package, the others; otherwise empty.
        tracked: The nixpkgs attributes of both, sorted.
        bulk_attrs: The attributes of the others, which only the digests
            answer.
    """

    now: str
    nixpkgs: dict
    lists: dict
    previous: dict
    revision: str
    everything: bool
    listed: dict
    bulk: dict
    tracked: list
    bulk_attrs: set


@dataclasses.dataclass(frozen=True)
class Scope:
    """Which rows each phase covers, worked out once the rows exist (scope_of).

    Attributes:
        names: Every row's name.
        on_lists: The rows on the lists: every row, unless the instance
            tracks every package.
        in_bulk: With every package, the names of the rows not on the
            lists; otherwise empty.
        shown: The rows not in a set updated in bulk (config.SET_PROFILES):
            those the page shows one by one.
    """

    names: list
    on_lists: list
    in_bulk: set
    shown: list


def main():
    """Run one sync, phase by phase, and log how long each phase took."""
    phases = timing.Phases()
    run = start()
    phases.lap("nixpkgs: the index, the lists, the channel")
    # Hydra is the slowest source (a request or more per package and
    # platform), so it's asked in the background from here while the other
    # sources are asked. Each server still gets one request at a time: only
    # the waiting overlaps. Its answers are added to the rows in builds().
    hydra_answers = background.Background(
        ask_hydra,
        run.tracked,
        run.nixpkgs,
        run.revision,
        run.previous,
        run.now,
        run.bulk_attrs,
    )
    projects, index_rows = repology(run)
    phases.lap("Repology")
    scope = own_sources_and_lists(run, index_rows)
    phases.lap("versions' own sources, branches, lists")
    problems, checks, from_community = update_checks(run, scope, index_rows)
    phases.lap("update checks")
    if not hydra_answers.done():
        print("Waiting for Hydra's answers...", file=sys.stderr)
    broken, fetched = hydra_answers.result()
    phases.lap("waiting for Hydra")
    # The packages updated together with another (the checks' "follows").
    following = follows.of(checks)
    builds(run, index_rows, broken, fetched, following, from_community)
    phases.lap("builds, master, follows")
    update_bot(run, scope, index_rows)
    phases.lap("update bot")
    prs = github_and_staging(run, scope, index_rows, following)
    phases.lap("GitHub, staging and staging-next")
    found_fixes = vulnerabilities_and_fixes(run, scope, index_rows, prs)
    phases.lap("vulnerabilities, fixes, families")
    write(run, projects, index_rows, problems, prs, found_fixes)
    phases.lap("writing data/")
    notify_changes(run, scope, index_rows)
    phases.lap("notifications")
    phases.report()


def start():
    """Read what the sync works from, and decide which packages it tracks.

    Returns:
        The Run every later phase reads from.

    Raises:
        Problem: The lists track more packages than the limit
            (scale.check), which the message explains.
    """
    now = datetime.now(UTC).isoformat()
    nixpkgs = nixpkgs_source.load_index()
    lists = nixpkgs_source.read_lists()
    listed = tracking.tracked_packages(lists, nixpkgs)
    previous = history.load_previous_run()
    # Says how long the sync should take (new packages cost the most), and
    # stops it if the lists track more packages than the limit.
    scale.check(lists, len(listed), history.new_packages(previous, listed))
    everything = config.all_packages()
    bulk = tracking.every_package(nixpkgs, listed) if everything else {}
    if everything:
        print(
            f"Every package: {len(listed):,} from the lists, {len(bulk):,} more "
            "read in bulk only",
            file=sys.stderr,
        )
    wanted = {**bulk, **listed}
    # Clear the sources noted so far, so only this run's are reported (a test
    # in the same process may have run a sync before).
    about.taken()
    revision = nixpkgs_source.channel_revision()
    # nixpkgs' evaluations (meta.broken, sources, patches) are reused from
    # the last sync while the channel's commit hasn't moved.
    if kept := nixpkgs_source.keep_answers():
        print(f"nixpkgs evaluations: {kept:,} answers kept", file=sys.stderr)
    # When the channel's commit couldn't be read, links use the branch.
    if revision == config.NIXPKGS_BRANCH:
        about.note("nixpkgs", False, "the channel's revision couldn't be read")
    else:
        about.note("nixpkgs", True, revision=revision)
    return Run(
        now=now,
        nixpkgs=nixpkgs,
        lists=lists,
        previous=previous,
        revision=revision,
        everything=everything,
        listed=listed,
        bulk=bulk,
        tracked=sorted(
            {a for attrs, _ in wanted.values() for a in attrs if a in nixpkgs}
        ),
        bulk_attrs={a for attrs, _ in bulk.values() for a in attrs if a in nixpkgs},
    )


def repology(run):
    """Look the tracked packages up on Repology, and make a row for each.

    nixkeeper-versions' digest answers first (versions_digest); Repology
    itself is asked for what it doesn't have.

    Returns:
        (projects, rows): Repology's projects by package, and the rows.
    """
    digest = versions_digest.load(run.tracked, run.now)
    projects = lookup.collect_projects(
        {**run.bulk, **run.listed},
        run.previous,
        nixpkgs=run.nixpkgs,
        now=run.now,
        digest=digest,
        bulk=set(run.bulk),
    )
    return projects, rows.build_rows(projects, run.nixpkgs)


def own_sources_and_lists(run, index_rows):
    """Add what doesn't come from Repology, then work out the run's Scope.

    That's the versions from the channel and from other sources, what a
    branch updating a set before master has, and each row's lists, teams
    and set.

    Returns:
        The run's Scope.
    """
    # The channel's own versions, for the packages Repology hasn't read
    # since the channel moved.
    if ahead := rows.channel_versions(index_rows, run.nixpkgs):
        print(
            f"nixos-unstable ahead of Repology: {len(ahead):,} packages",
            file=sys.stderr,
        )
    # Typst, Emacs, Stackage-pinned Haskell and R packages are compared with
    # their own sources instead of Repology (FEEDS).
    for feed in FEEDS:
        if any(a.startswith(feed.PREFIX) for a in run.tracked):
            feed.apply(index_rows, run.nixpkgs, feed.load(run.now))
    # What a branch that updates a set before master has (haskell-updates).
    for branch in branches.wanted(run.tracked):
        branches.apply(index_rows, branch, branches.load(branch, run.now))
    tracking.add_lists(index_rows, tracking.list_names(run.lists, run.nixpkgs))
    # A list named like a team (gaming for Gaming) adds its packages to the
    # team.
    tracking.add_list_teams(index_rows, run.nixpkgs)
    if run.everything:
        tracking.add_sets(index_rows)
    return scope_of(run, index_rows)


def scope_of(run, index_rows):
    """Work out which rows each phase covers.

    Call it after the rows' sets are added (tracking.add_sets), as shown
    depends on them.

    Returns:
        The run's Scope.
    """
    return Scope(
        names=[row["name"] for row in index_rows],
        on_lists=[row for row in index_rows if row["lists"]]
        if run.everything
        else index_rows,
        in_bulk={row["name"] for row in index_rows if not row["lists"]}
        if run.everything
        else set(),
        shown=[row for row in index_rows if not row.get("set")],
    )


def update_checks(run, scope, index_rows):
    """Apply the up-to-date rules, check the lists, and run the update checks.

    The update checks are the lists' own, the community's, and those worked
    out from nixpkgs' sources (inferred.py). The rows also get links to
    their source in nixpkgs.

    Returns:
        (problems, checks, from_community): the lists' problems, every
        update check by package, and the names of the packages whose check
        is the community's.
    """
    # The up-to-date rules correct Repology's verdict for a version. They go
    # first: the update checks and master can still make a row outdated.
    up_to_date, up_to_date_community = community.merge_up_to_date(
        run.lists, scope.names
    )
    uptodate.apply(index_rows, up_to_date, up_to_date_community)

    problems = listcheck.problems(
        run.lists, run.nixpkgs, scope.names, len(scope.on_lists)
    )
    listcheck.report(problems)
    rows.add_source_links(index_rows, run.nixpkgs, run.revision)
    checks, from_community = community.merge(run.lists, scope.names)
    # Packages without a rule get a check worked out from nixpkgs' sources
    # (inferred.py). For the packages whose GitHub releases are in
    # nixkeeper-versions' digest, the digest answers in bulk
    # (releases_digest); the sync works out its own check only for the
    # lists' other packages. They run with the rest, and are compared with
    # Repology in the log, before master or the follows change the rows.
    answered_by_releases = (
        releases_digest.apply(
            index_rows, releases_digest.load(run.now), checks, run.now
        )
        if inferred.enabled(run.lists)
        else set()
    )
    worked = inferred.work_out(
        run.lists,
        [row for row in scope.on_lists if row["name"] not in answered_by_releases],
        checks,
        run.revision,
    )
    to_run = worked.to_run(checks) if worked else {}
    checks_failed = upstream.add_checks(
        index_rows,
        {**to_run, **checks},
        run.previous,
        run.now,
        from_community,
        set(to_run),
    )
    if worked:
        inferred.report(worked, scope.on_lists, checks, checks_failed)
    return problems, checks, from_community


def builds(run, index_rows, broken, fetched, following, from_community):
    """Add Hydra's builds, master's versions and the follows' versions.

    Then each row's "outdated since" is worked out, as all three can make a
    row outdated.

    Args:
        run: The run's Run.
        index_rows: The rows.
        broken: What ask_hydra returned for the attributes marked broken.
        fetched: What ask_hydra returned for the jobs.
        following: The packages updated together with another
            ({follower: followed}, follows.of).
        from_community: The names of the packages whose check is the
            community's.
    """
    hydra.add_builds(index_rows, run.nixpkgs, run.previous, run.now, broken, fetched)
    # Name the dependency that stopped a build as its row is named, so the
    # page can link to it.
    rows.name_blockers(index_rows)
    # Master can make a row outdated by having a newer version than the
    # channel (verdict._master): decided again once Hydra has said what
    # master has, before "outdated since".
    for row in index_rows:
        verdict.decide(row)
    # A package updated together with another gets that one's newest
    # version, once master is counted for it.
    follows.apply_versions(index_rows, following, run.now, from_community)
    history.add_outdated_since(index_rows, run.previous, run.now)


def update_bot(run, scope, index_rows):
    """Add the update bot's (nixpkgs-update's) attempts, and its queue.

    The attempts come from nixkeeper-updates' digest first. The queue says
    when the bot will try each package again, and what it would update to.
    """
    ignored, ignored_by_community = community.merge_ignores(run.lists, scope.names)
    nixpkgs_update.add_attempts(
        index_rows,
        run.nixpkgs,
        run.previous,
        run.now,
        ignored,
        ignored_by_community,
        scope.in_bulk,
        updates_digest.load(run.now),
    )
    nixpkgs_update.add_queue(
        index_rows, run.nixpkgs, updates_digest.load_queue(run.now)
    )


def github_and_staging(run, scope, index_rows, following):
    """Add the PR and issue counts, the update PRs, and how staging-next builds.

    The update PRs are those open, those merged into master, and those
    merged into staging or staging-next. Most of this comes from
    nixkeeper-prs' digest.

    Args:
        run: The run's Run.
        scope: The run's Scope.
        index_rows: The rows.
        following: The packages updated together with another: theirs are
            the same PRs.

    Returns:
        nixkeeper-prs' digest, which the later phases read too; empty when
        it couldn't be loaded.
    """
    # The open PR and issue counts, and the open update PRs, come from one
    # listing of all of nixpkgs' open ones (github_bulk): the digest's, or
    # else one made here. Failing both, they're searched per package, for
    # the lists' packages only. The rows of sets updated in bulk don't get
    # them, as their sets are updated as a whole.
    prs = prs_digest.load(run.now, run.revision) or {}
    shown = scope.shown
    if prs.get("open") and github_bulk.add_counts(shown, run.now, prs["open"]):
        # What the digest found of each package's PRs and issues, for its
        # panel.
        prs_digest.add_facts(shown, prs)
    elif github_bulk.add_counts(shown, run.now):
        about.note("github", True)  # the listing was made here
    else:
        about.note(
            "github", False, "no token, or the listing failed: searched per package"
        )
        github.add_counts(scope.on_lists, run.previous, run.now)
    outdated = [row for row in shown if is_outdated(row)]
    # The update PRs merged into master but not in the channel yet, from the
    # digest or else searched for.
    if not github_bulk.add_master_prs(
        outdated, run.revision, run.now, prs.get("merged")
    ):
        github.add_update_prs(
            [row for row in outdated if row["name"] not in scope.in_bulk],
            open_prs=False,
            merged_since=github_bulk.merged_since(run.revision),
        )
    # The update PRs merged into staging or staging-next, on their way to
    # master. Only the digest has them: it knows which branch each is on.
    prs_digest.add_staging_prs(outdated, prs.get("staging"))
    # How the updates on staging-next build there, from Hydra's evaluation
    # of it.
    cycles = (prs.get("staging") or {}).get("stagingNext") or {}
    staging_next = branches.current_staging_next(
        branches.load_staging_next(run.now), cycles.get("lastMerged")
    )
    branches.apply_staging_next(outdated, staging_next)
    # What staging-next breaks: packages that build on master but fail their
    # own build there. It's a forecast, shown in their panel and a filter.
    branches.apply_staging_next_breaks(shown, staging_next, cycles.get("open"))
    # Which dependency failing on staging-next stops which packages there.
    branches.apply_staging_next_blocked(index_rows, staging_next)
    # A package updated together with another has the same PRs.
    follows.apply_prs(index_rows, following)
    # An outdated package with no newer version named takes the newest its
    # update PRs bring (verdict._update_prs).
    for row in outdated:
        verdict.decide(row)
    nixpkgs_update.recheck_superseded(outdated)
    return prs


def vulnerabilities_and_fixes(run, scope, index_rows, prs):
    """Add the CVEs, what was fixed since the last sync, and the families.

    Also works out since when each row's builds and update attempts have
    been failing, the PRs that likely fix a build or patch a CVE, and marks
    the update PRs behind upstream and those for a vulnerable package.

    Args:
        run: The run's Run.
        scope: The run's Scope.
        index_rows: The rows.
        prs: nixkeeper-prs' digest, as github_and_staging returned it.

    Returns:
        What this sync found fixed since the last (history.fixes).
    """
    # Since when builds and update attempts have been failing, carried over
    # from the last sync.
    history.add_failing_since(index_rows, run.previous, run.now)
    # A PR merged since a build began failing, which touched the package, is
    # likely its fix; it's credited once Hydra builds it (history.fixes).
    if prs.get("merged") is not None:
        prs_digest.build_fix_prs(scope.shown, prs["merged"], run.previous)
    # Each package's CVEs and advisories, with nixkeeper's verdicts.
    vulnerabilities_digest.add(
        index_rows, vulnerabilities_digest.load(run.now), run.revision
    )
    # The open PRs patching them.
    if prs.get("raw") is not None:
        prs_digest.add_cve_prs(index_rows, prs["raw"])
    # What this sync finds fixed since the last, with who fixed it when the
    # PR is known. Each package keeps its fixes for a month, for its panel.
    found_fixes = history.fixes(index_rows, run.previous, run.now)
    # Mark the update PRs behind upstream, and those for a vulnerable
    # package; this needs the versions and vulnerabilities added first.
    prs_digest.cross_check(index_rows)
    # The CVE issues nixkeeper finds fixed: candidates to close.
    if prs.get("open"):
        prs_digest.add_cve_issues(index_rows, prs["open"][1])
    history.add_recent_fixes(index_rows, run.previous, found_fixes, run.now)
    # Packages that one update moves together (the same package file,
    # version and homepage) form a family: one entry in the overview's lists,
    # and one fix in the next sync's fixes.
    rows.add_families(index_rows)
    return found_fixes


def write(run, projects, index_rows, problems, prs, found_fixes):
    """Write the data folder: the manifest, the rows, and what's kept.

    With every package, also what only that instance writes
    (every_package_outputs).
    """
    # version is the nixkeeper that made this data, for the page's footer.
    index = {
        "checkedAt": run.now,
        "packages": index_rows,
        "version": version(),
        # The rows can be decided again by the hourly checks (verdict.py).
        "verdicts": verdict.FORMAT,
    }
    if run.everything:
        index["allPackages"] = True
        # What updates each set updated in bulk, said once here rather than
        # on each of its rows.
        index["profiles"] = config.SET_PROFILES
    if problems:
        index["listProblems"] = problems
    if page := listcheck.page_settings(run.lists):
        index["page"] = page  # the page's default theme
    # Where the data is from: each source's time, used or not, for the
    # page's "checked" panel. Hydra noted its own in the background, which
    # has finished by now.
    index["sources"] = about.taken()
    merge, history_points, fixed, events = (
        every_package_outputs(run, index_rows, index, prs, found_fixes)
        if run.everything
        else (None, None, None, None)
    )
    datastore.write(
        index,
        datastore.kept_entries(projects, index_rows),
        history=history_points,
        fixed=fixed,
        events=events,
        kept=kept_files(run, merge),
    )
    nixpkgs_source.stop_keeping()


def kept_files(run, merge):
    """List what the daily sync keeps for its next run, besides the data.

    A file kept under rows/ or views/ must be in datastore.SYNC_ONLY, or the
    hourly checks would delete it; a test checks every one here is.

    Args:
        run: The run's Run.
        merge: The PRs maintainers can merge with the merge bot, or None
            (with every package only).

    Returns:
        {path in data/: data}, with None for a file to leave out.
    """
    return {
        nixpkgs_source.EVALUATIONS: nixpkgs_source.kept_answers(),
        # The maintainer and team views' "You can merge these".
        datastore.MERGE_VIEW: {"checkedAt": run.now, "prs": merge}
        if merge is not None
        else None,
    }


def every_package_outputs(run, index_rows, index, prs, found_fixes):
    """Work out what only an instance tracking every package writes.

    Adds to the manifest the PRs maintainers can merge, the PRs to close,
    and "nixpkgs in numbers".

    Args:
        run: The run's Run.
        index_rows: The rows.
        index: The manifest, changed in place.
        prs: nixkeeper-prs' digest.
        found_fixes: What this sync found fixed.

    Returns:
        (merge, history, fixed, events) for datastore.write: the PRs
        maintainers can merge, the counts' history, the fixes to keep, and
        the trends' events.
    """
    # The PRs maintainers can merge with the merge bot: "You can merge
    # these" on a maintainer's or team's page, and their count in the
    # overview's numbers.
    merge = (
        prs_digest.mergeable(prs["raw"], index_rows)
        if prs.get("raw") is not None
        else None
    )
    if merge is not None:
        index["merge"] = prs_digest.merge_summary(merge, run.now)
    # The update PRs nixpkgs is already past: "Can be closed", the list's
    # filter (marked on the rows), and the overview's count.
    if close := prs_digest.mark_superseded(prs.get("raw"), index_rows):
        index["close"] = close
    # The overview's "nixpkgs in numbers".
    index["numbers"] = datastore.numbers(index_rows)
    # The counts' history carries over, one point a day, and so do the last
    # month's fixes. If the previous day's point was recorded without the
    # split failing counts, they're taken from the last manifest.
    events = datastore.read_events()
    return (
        merge,
        datastore.with_split(datastore.read_history(), run.previous),
        datastore.with_fixed(datastore.read_fixed(), found_fixes, run.now),
        datastore.with_events(
            events, trend_events(run.previous, run.now, events), run.now
        ),
    )


def notify_changes(run, scope, index_rows):
    """Update the status issues with what changed since the last sync.

    The lists' issue covers the lists' own packages (with every package,
    only those); each subscriber's issue covers theirs.
    """
    notify.notify(
        {
            **run.previous,
            "packages": [r for r in run.previous["packages"] if r.get("lists")],
        }
        if run.everything
        else run.previous,
        scope.on_lists,
        run.now,
        # The subscribers' issues (notifications/) take their packages from
        # every row.
        everyone=index_rows,
        everyone_before=run.previous,
        lists=run.lists,
    )
