"""One sync: nixpkgs index + package lists -> tracked packages -> Repology ->
rows -> update checks -> meta.broken + Hydra builds -> nixpkgs-update logs ->
GitHub counts and update PRs -> data/ -> status issue. Hydra, the slowest,
is asked in the background from the start (background.py). `nixkeeper sync`
(nixkeeper/cli.py); from a checkout, `nix run .#sync`."""

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
    version,
)
from .changes import count_master, count_prs, is_outdated
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


def ask_hydra(attrs, nixpkgs, revision, previous, now, bulk=frozenset()):
    """Hydra's answers for attrs: (where nixpkgs marks them broken, answers
    by job), for hydra.add_builds. From nixkeeper-hydra's digest for the jobs
    it can answer (hydra_digest), and from Hydra itself for the rest that
    are due, or for all of them when the digest isn't current. bulk: attrs
    (with every package, those not on the lists) that only the digest
    answers, and whose meta.broken is the package index's (x86_64-linux),
    not evaluated. Run in the background (main)."""
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
    # Hydra doesn't say which dependency failed: the digest's, for the same build.
    fetched = {**found, **hydra_digest.with_blockers(hydra.fetch(jobs, broken), digest)}
    minutes = (time.monotonic() - started) / 60
    print(f"Hydra, in the background: done in {minutes:.0f} min", file=sys.stderr)
    return broken, fetched


def trend_events(previous, now, known=None):
    """What marks the overview's trends from this run: staging-next merged
    into master in the last month (asked again daily, kept once each), and
    nixkeeper itself updated since the last sync. known: the events kept
    so far (datastore.read_events, read here if not given)."""
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
    # A change in how nixkeeper counts: on the first day it ran with it. The
    # last sync did if it came after the change was merged (an instance
    # running main); else this one is the first.
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
    """What a sync works from, made once (start): its time, the channel's
    package index and revision, the lists, the last run's data, and which
    packages it tracks."""

    now: str
    nixpkgs: dict
    lists: dict
    previous: dict
    revision: str
    # With every package (the community instance): the rest of nixpkgs
    # too, read in bulk only (the digests, the listings), nothing per package.
    everything: bool
    listed: dict  # the lists' packages (tracking.tracked_packages)
    bulk: dict  # with every package, the others
    tracked: list  # the nixpkgs attributes of both, sorted
    bulk_attrs: set  # those of the others: only the digests answer them


@dataclasses.dataclass(frozen=True)
class Scope:
    """Which rows each step covers, once the rows exist (scope_of)."""

    names: list  # every row's
    on_lists: list  # the lists' rows: every row, unless every package
    in_bulk: set  # with every package, the names of the others' rows
    shown: list  # the rows not in a set updated in bulk (config.SET_PROFILES)


def main():
    phases = timing.Phases()
    run = start()
    phases.lap("nixpkgs: the index, the lists, the channel")
    # Hydra is the slowest source (a request or more per package and
    # platform): asked from here, in the background, while the others are.
    # Each server is still asked one request at a time; only the waiting
    # overlaps. Its answers are put together with the rest in builds().
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
    following = builds(run, index_rows, broken, fetched, checks, from_community)
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
    """The run's Run: what the channel, the lists and the last run say.
    Refuses (scale.check) a run past the size limit."""
    now = datetime.now(UTC).isoformat()
    nixpkgs = nixpkgs_source.load_index()
    lists = nixpkgs_source.read_lists()
    listed = tracking.tracked_packages(lists, nixpkgs)
    previous = history.load_previous_run()
    # How long it'll take (new packages cost the most); refuses past the limit.
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
    about.taken()  # a run's sources only (a test may have run one before)
    revision = nixpkgs_source.channel_revision()
    # nixpkgs' evaluations (meta.broken, sources, patches): the last sync's
    # answers reused while the channel's commit hasn't moved.
    if kept := nixpkgs_source.keep_answers():
        print(f"nixpkgs evaluations: {kept:,} answers kept", file=sys.stderr)
    if revision == config.NIXPKGS_BRANCH:  # not fetched: links use the branch
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
    """Repology's projects for the tracked packages, from nixkeeper-versions'
    digest first (versions_digest), and the rows made of them."""
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
    """The versions Repology isn't the source for, the branches updating a
    set before master, and each row's lists, teams and set: then the
    run's Scope."""
    # The channel's own versions, where Repology hasn't caught up with it yet.
    if ahead := rows.channel_versions(index_rows, run.nixpkgs):
        print(
            f"nixos-unstable ahead of Repology: {len(ahead):,} packages",
            file=sys.stderr,
        )
    # Typst, Emacs, Stackage-pinned Haskell and R packages: compared with
    # their own sources instead (Typst Universe, the Emacs archives, Stackage
    # LTS, CRAN and Bioconductor; sources/feeds.py).
    for feed in (typst_digest, emacs_digest, stackage_digest, cran_digest):
        if any(a.startswith(feed.PREFIX) for a in run.tracked):
            feed.apply(index_rows, run.nixpkgs, feed.load(run.now))
    # What a branch updating a set before master has (haskell-updates).
    for branch in branches.wanted(run.tracked):
        branches.apply(index_rows, branch, branches.load(branch, run.now))
    tracking.add_lists(index_rows, tracking.list_names(run.lists, run.nixpkgs))
    # A list called as a team (gaming, Gaming) adds its packages to the team.
    tracking.add_list_teams(index_rows, run.nixpkgs)
    if run.everything:
        tracking.add_sets(index_rows)
    return scope_of(run, index_rows)


def scope_of(run, index_rows):
    """Which rows each step covers: with every package, the lists' rows
    apart from the rest (read in bulk only), and the rows of sets updated
    in bulk (their set, tracking.add_sets) apart from those shown alone."""
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
    """The up-to-date rules, the lists' problems, nixpkgs' source links and
    the update checks (the lists', the community's, the worked-out ones):
    (the lists' problems, the checks, which of them are the community's)."""
    # Repology's verdicts that are wrong for a version (up-to-date rules):
    # before the update checks and master, which can still make it outdated.
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
    # Checks worked out from nixpkgs' sources, for packages without a rule
    # (inferred.py): run with the rest, then compared with Repology (logged),
    # before master or follows change the rows.
    # GitHub releases from nixkeeper-versions' digest (releases_digest): the
    # worked-out check of every package it knows, read in bulk; the sync
    # works out its own only for the lists' packages it doesn't answer.
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


def builds(run, index_rows, broken, fetched, checks, from_community):
    """Hydra's builds, master's versions and the packages updated together
    (follows), and since when each row has been outdated: the follows."""
    hydra.add_builds(index_rows, run.nixpkgs, run.previous, run.now, broken, fetched)
    # Which dependency stopped a build, as the rows are named (to link them).
    rows.name_blockers(index_rows)
    # After the update checks and Hydra, before outdated-since: each can make
    # a row outdated (master, by having a newer version than the channel).
    for row in index_rows:
        count_master(row)
    # Packages updated together with another (follows): its newest version,
    # once master is counted for it, is theirs too.
    following = follows.of(checks)
    follows.apply_versions(index_rows, following, run.now, from_community)
    history.add_outdated_since(index_rows, run.previous, run.now)
    return following


def update_bot(run, scope, index_rows):
    """nixpkgs-update's attempts, from nixkeeper-updates' digest first, and
    when it will try each package again."""
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
    # When the bot will try each package again, and what it would update to.
    nixpkgs_update.add_queue(
        index_rows, run.nixpkgs, updates_digest.load_queue(run.now)
    )


def github_and_staging(run, scope, index_rows, following):
    """Open PR and issue counts, update PRs (open, merged into master,
    into staging or staging-next), and how staging-next builds: nixkeeper-
    prs' digest, which the later steps read too ({} without it)."""
    # Open PR/issue counts and open update PRs: from one listing of all of
    # nixpkgs' open ones (github_bulk: nixkeeper-prs' digest's, else listed
    # here), else searched per package (the lists' only). Not for the rows
    # of sets updated in bulk: their sets are updated as a whole.
    prs = prs_digest.load(run.now, run.revision) or {}
    shown = scope.shown
    if prs.get("open") and github_bulk.add_counts(shown, run.now, prs["open"]):
        # What the digest found of each package's PRs and issues (its panel).
        prs_digest.add_facts(shown, prs)
    elif github_bulk.add_counts(shown, run.now):
        about.note("github", True)  # listed during the sync
    else:
        about.note(
            "github", False, "no token, or the listing failed: searched per package"
        )
        github.add_counts(scope.on_lists, run.previous, run.now)
    outdated = [row for row in shown if is_outdated(row)]
    # Update PRs merged into master, not in the channel yet: likewise.
    if not github_bulk.add_master_prs(
        outdated, run.revision, run.now, prs.get("merged")
    ):
        github.add_update_prs(
            [row for row in outdated if row["name"] not in scope.in_bulk],
            open_prs=False,
            merged_since=github_bulk.merged_since(run.revision),
        )
    # Update PRs merged into staging or staging-next: on their way to master,
    # the digest's only (it knows where each is).
    prs_digest.add_staging_prs(outdated, prs.get("staging"))
    # And how those on staging-next build there (Hydra's evaluation of it).
    cycles = (prs.get("staging") or {}).get("stagingNext") or {}
    staging_next = branches.current_staging_next(
        branches.load_staging_next(run.now), cycles.get("lastMerged")
    )
    branches.apply_staging_next(outdated, staging_next)
    # And what staging-next breaks: packages that build on master, failing
    # there themselves (a forecast, for their panel and a filter).
    branches.apply_staging_next_breaks(shown, staging_next, cycles.get("open"))
    # And who stops whom there: a dependency failing on staging-next.
    branches.apply_staging_next_blocked(index_rows, staging_next)
    # Outdated with no newer version named: the newest its update PRs bring.
    for row in outdated:
        count_prs(row)
    follows.apply_prs(index_rows, following)  # theirs are the same PRs
    nixpkgs_update.recheck_superseded(outdated)
    return prs


def vulnerabilities_and_fixes(run, scope, index_rows, prs):
    """Since when builds and attempts have been failing, the CVEs and their
    patches, what this sync finds fixed, the PRs' cross-checks, and the
    families: what was found fixed (history.fixes)."""
    # Since when builds and update attempts have been failing (carried over).
    history.add_failing_since(index_rows, run.previous, run.now)
    # A PR merged since a build began failing that touched it: likely its
    # fix (credited when Hydra builds it: history.fixes).
    if prs.get("merged") is not None:
        prs_digest.build_fix_prs(scope.shown, prs["merged"], run.previous)
    # The CVEs and advisories of each package, with their verdicts.
    vulnerabilities_digest.add(
        index_rows, vulnerabilities_digest.load(run.now), run.revision
    )
    # And the open PRs patching them.
    if prs.get("raw") is not None:
        prs_digest.add_cve_prs(index_rows, prs["raw"])
    # What this sync finds fixed since the last (with who, when a PR is
    # known), kept on each package a month too, for its panel.
    found_fixes = history.fixes(index_rows, run.previous, run.now)
    # An update PR behind upstream, or for a vulnerable package: once the
    # versions and vulnerabilities are in (prs_digest.cross_check).
    prs_digest.cross_check(index_rows)
    # And CVE issues nixkeeper finds fixed: candidates to close.
    if prs.get("open"):
        prs_digest.add_cve_issues(index_rows, prs["open"][1])
    history.add_recent_fixes(index_rows, run.previous, found_fixes, run.now)
    # Packages one update moves together (one package file, version and
    # homepage): one entry in the overview's lists, and their fixes, next
    # sync, one too.
    rows.add_families(index_rows)
    return found_fixes


def write(run, projects, index_rows, problems, prs, found_fixes):
    """data/: the manifest, the rows, and with every package what only it
    has (every_package_outputs)."""
    # version: the nixkeeper that made this data, for the page's footer.
    index = {"checkedAt": run.now, "packages": index_rows, "version": version()}
    if run.everything:
        index["allPackages"] = True
        # What updates each set updated in bulk: once here, not on its rows.
        index["profiles"] = config.SET_PROFILES
    if problems:
        index["listProblems"] = problems
    if page := listcheck.page_settings(run.lists):
        index["page"] = page  # the page's default theme
    # Where the data is from: each digest's time, used or not (the page's
    # "checked" panel). Hydra's is noted in the background: done by now.
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
    """With every package, what only it has: in index, the PRs maintainers
    can merge, those to close and "nixpkgs in numbers"; and for
    datastore.write, (the mergeable PRs, the counts' history, what was
    fixed, the trends' events)."""
    # The PRs maintainers can merge with the merge bot: the maintainer and
    # team views' "You can merge these", and their count in the overview's
    # numbers.
    merge = (
        prs_digest.mergeable(prs["raw"], index_rows)
        if prs.get("raw") is not None
        else None
    )
    if merge is not None:
        index["merge"] = prs_digest.merge_summary(merge, run.now)
    # Update PRs nixpkgs is already past: "Can be closed" and the list's
    # filter (on the rows), and the overview's count.
    if close := prs_digest.mark_superseded(prs.get("raw"), index_rows):
        index["close"] = close
    # The overview's "nixpkgs in numbers".
    index["numbers"] = datastore.numbers(index_rows)
    # The counts' history carries over, a point a day, and what was fixed,
    # the last month's. The day before's point gets its split failing
    # counts from the last manifest, if it was recorded without them.
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
    """The status issues: what changed since the last run, for the lists'
    own packages (with every package, only theirs), and the subscribers'."""
    notify.notify(
        {
            **run.previous,
            "packages": [r for r in run.previous["packages"] if r.get("lists")],
        }
        if run.everything
        else run.previous,
        scope.on_lists,
        run.now,
        # The subscribers' issues (notifications/): theirs among every row.
        everyone=index_rows,
        everyone_before=run.previous,
        lists=run.lists,
    )
