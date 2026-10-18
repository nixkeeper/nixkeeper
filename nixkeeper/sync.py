"""One sync: nixpkgs index + package lists -> tracked packages -> Repology ->
rows -> update checks -> meta.broken + Hydra builds -> nixpkgs-update logs ->
GitHub counts and update PRs -> data/ -> status issue. Hydra, the slowest,
is asked in the background from the start (background.py). `nixkeeper sync`
(nixkeeper/cli.py); from a checkout, `nix run .#sync`."""

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


def trend_events(previous, now):
    """What marks the overview's trends from this run: staging-next merged
    into master in the last month (asked again daily, kept once each), and
    nixkeeper itself updated since the last sync."""
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
    known = {e.get("text") for e in datastore.read_events()}
    last = previous.get("checkedAt") or ""
    for change in config.COUNTING_CHANGES:
        if change["text"] in known:
            continue
        ran = last if last and last >= change["merged"] else now
        events.append({"day": ran[:10], "kind": "counting", "text": change["text"]})
    return events


def main():
    now = datetime.now(UTC).isoformat()
    nixpkgs = nixpkgs_source.load_index()
    lists = nixpkgs_source.read_lists()
    listed = tracking.tracked_packages(lists, nixpkgs)
    previous = history.load_previous_run()
    # How long it'll take (new packages cost the most); refuses past the limit.
    scale.check(lists, len(listed), history.new_packages(previous, listed))
    # With every package (the community instance), the rest of nixpkgs too:
    # read in bulk only (the digests, the listings), nothing per package.
    everything = config.all_packages()
    bulk = tracking.every_package(nixpkgs, listed) if everything else {}
    if everything:
        print(
            f"Every package: {len(listed):,} from the lists, {len(bulk):,} more "
            "read in bulk only",
            file=sys.stderr,
        )
    wanted = {**bulk, **listed}
    bulk_attrs = {a for attrs, _ in bulk.values() for a in attrs if a in nixpkgs}
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
    # Hydra is the slowest source (a request or more per package and
    # platform): asked from here, in the background, while the others are.
    # Each server is still asked one request at a time; only the waiting
    # overlaps. Its answers are put together with the rest further down.
    tracked = sorted({a for attrs, _ in wanted.values() for a in attrs if a in nixpkgs})
    hydra_answers = background.Background(
        ask_hydra, tracked, nixpkgs, revision, previous, now, bulk_attrs
    )
    # Repology, from nixkeeper-versions' digest first (versions_digest).
    digest = versions_digest.load(tracked, now)
    projects = lookup.collect_projects(
        wanted, previous, nixpkgs=nixpkgs, now=now, digest=digest, bulk=set(bulk)
    )
    index_rows = rows.build_rows(projects, nixpkgs)
    # The channel's own versions, where Repology hasn't caught up with it yet.
    if ahead := rows.channel_versions(index_rows, nixpkgs):
        print(
            f"nixos-unstable ahead of Repology: {len(ahead):,} packages",
            file=sys.stderr,
        )
    # Typst, Emacs, Stackage-pinned Haskell and R packages: compared with
    # their own sources instead (Typst Universe, the Emacs archives, Stackage
    # LTS, CRAN and Bioconductor; sources/feeds.py).
    for feed in (typst_digest, emacs_digest, stackage_digest, cran_digest):
        if any(a.startswith(feed.PREFIX) for a in tracked):
            feed.apply(index_rows, nixpkgs, feed.load(now))
    # What a branch updating a set before master has (haskell-updates).
    for branch in branches.wanted(tracked):
        branches.apply(index_rows, branch, branches.load(branch, now))
    tracking.add_lists(index_rows, tracking.list_names(lists, nixpkgs))
    # A list called as a team (gaming, Gaming) adds its packages to the team.
    tracking.add_list_teams(index_rows, nixpkgs)
    # The lists' rows (all of them, unless every package is tracked): the
    # rest are read in bulk only, and the rows of sets updated in bulk have
    # their set (config.SET_PROFILES).
    on_lists = [row for row in index_rows if row["lists"]] if everything else index_rows
    in_bulk = (
        {row["name"] for row in index_rows if not row["lists"]} if everything else set()
    )
    if everything:
        tracking.add_sets(index_rows)
    shown = [row for row in index_rows if not row.get("set")]

    # Repology's verdicts that are wrong for a version (up-to-date rules):
    # before the update checks and master, which can still make it outdated.
    up_to_date, up_to_date_community = community.merge_up_to_date(
        lists, [row["name"] for row in index_rows]
    )
    uptodate.apply(index_rows, up_to_date, up_to_date_community)

    problems = listcheck.problems(
        lists, nixpkgs, [row["name"] for row in index_rows], len(on_lists)
    )
    listcheck.report(problems)
    rows.add_source_links(index_rows, nixpkgs, revision)
    checks, from_community = community.merge(lists, [row["name"] for row in index_rows])
    # Checks worked out from nixpkgs' sources, for packages without a rule
    # (inferred.py): run with the rest, then compared with Repology (logged),
    # before master or follows change the rows.
    # GitHub releases from nixkeeper-versions' digest (releases_digest): the
    # worked-out check of every package it knows, read in bulk; the sync
    # works out its own only for the lists' packages it doesn't answer.
    answered = (
        releases_digest.apply(index_rows, releases_digest.load(now), checks, now)
        if inferred.enabled(lists)
        else set()
    )
    worked = inferred.work_out(
        lists,
        [row for row in on_lists if row["name"] not in answered],
        checks,
        revision,
    )
    to_run = worked.to_run(checks) if worked else {}
    failed = upstream.add_checks(
        index_rows, {**to_run, **checks}, previous, now, from_community, set(to_run)
    )
    if worked:
        inferred.report(worked, on_lists, checks, failed)
    if not hydra_answers.done():
        print("Waiting for Hydra's answers...", file=sys.stderr)
    broken, fetched = hydra_answers.result()
    hydra.add_builds(index_rows, nixpkgs, previous, now, broken, fetched)
    # Which dependency stopped a build, as the rows are named (to link them).
    rows.name_blockers(index_rows)
    # After the update checks and Hydra, before outdated-since: each can make
    # a row outdated (master, by having a newer version than the channel).
    for row in index_rows:
        count_master(row)
    # Packages updated together with another (follows): its newest version,
    # once master is counted for it, is theirs too.
    following = follows.of(checks)
    follows.apply_versions(index_rows, following, now, from_community)
    history.add_outdated_since(index_rows, previous, now)
    ignored, ignored_by_community = community.merge_ignores(
        lists, [row["name"] for row in index_rows]
    )
    # nixpkgs-update's attempts, from nixkeeper-updates' digest first.
    nixpkgs_update.add_attempts(
        index_rows,
        nixpkgs,
        previous,
        now,
        ignored,
        ignored_by_community,
        in_bulk,
        updates_digest.load(now),
    )
    # When the bot will try each package again, and what it would update to.
    nixpkgs_update.add_queue(index_rows, nixpkgs, updates_digest.load_queue(now))
    # Open PR/issue counts and open update PRs: from one listing of all of
    # nixpkgs' open ones (github_bulk: nixkeeper-prs' digest's, else listed
    # here), else searched per package (the lists' only). Not for the rows
    # of sets updated in bulk: their sets are updated as a whole.
    digest = prs_digest.load(now, revision) or {}
    if digest.get("open") and github_bulk.add_counts(shown, now, digest["open"]):
        # What the digest found of each package's PRs and issues (its panel).
        prs_digest.add_facts(shown, digest)
    elif github_bulk.add_counts(shown, now):
        about.note("github", True)  # listed during the sync
    else:
        about.note(
            "github", False, "no token, or the listing failed: searched per package"
        )
        github.add_counts(on_lists, previous, now)
    outdated = [row for row in shown if is_outdated(row)]
    # Update PRs merged into master, not in the channel yet: likewise.
    if not github_bulk.add_master_prs(outdated, revision, now, digest.get("merged")):
        github.add_update_prs(
            [row for row in outdated if row["name"] not in in_bulk],
            open_prs=False,
            merged_since=github_bulk.merged_since(revision),
        )
    # Update PRs merged into staging or staging-next: on their way to master,
    # the digest's only (it knows where each is).
    prs_digest.add_staging_prs(outdated, digest.get("staging"))
    # And how those on staging-next build there (Hydra's evaluation of it).
    cycles = (digest.get("staging") or {}).get("stagingNext") or {}
    staging_next = branches.current_staging_next(
        branches.load_staging_next(now), cycles.get("lastMerged")
    )
    branches.apply_staging_next(outdated, staging_next)
    # And what staging-next breaks: packages that build on master, failing
    # there themselves (a forecast, for their panel and a filter).
    cycle = cycles.get("open")
    branches.apply_staging_next_breaks(shown, staging_next, cycle)
    # And who stops whom there: a dependency failing on staging-next.
    branches.apply_staging_next_blocked(index_rows, staging_next)
    # Outdated with no newer version named: the newest its update PRs bring.
    for row in outdated:
        count_prs(row)
    follows.apply_prs(index_rows, following)  # theirs are the same PRs
    nixpkgs_update.recheck_superseded(outdated)
    # Since when builds and update attempts have been failing (carried over).
    history.add_failing_since(index_rows, previous, now)
    # A PR merged since a build began failing that touched it: likely its
    # fix (credited when Hydra builds it: history.fixes).
    if digest.get("merged") is not None:
        prs_digest.build_fix_prs(shown, digest["merged"], previous)
    # The CVEs and advisories of each package, with their verdicts.
    vulnerabilities_digest.add(index_rows, vulnerabilities_digest.load(now), revision)
    # What this sync finds fixed since the last (with who, when a PR is
    # known), kept on each package a month too, for its panel.
    found_fixes = history.fixes(index_rows, previous, now)
    # An update PR behind upstream, or for a vulnerable package: once the
    # versions and vulnerabilities are in (prs_digest.cross_check).
    prs_digest.cross_check(index_rows)
    history.add_recent_fixes(index_rows, previous, found_fixes, now)
    # Packages one update moves together (one package file, version and
    # homepage): one entry in the overview's lists, and their fixes, next
    # sync, one too.
    rows.add_families(index_rows)
    # version: the nixkeeper that made this data, for the page's footer.
    index = {"checkedAt": now, "packages": index_rows, "version": version()}
    if everything:
        index["allPackages"] = True
        # What updates each set updated in bulk: once here, not on its rows.
        index["profiles"] = config.SET_PROFILES
    if problems:
        index["listProblems"] = problems
    if page := listcheck.page_settings(lists):
        index["page"] = page  # the page's default theme
    # Where the data is from: each digest's time, used or not (the page's
    # "checked" panel). Hydra's is noted in the background: done by now.
    index["sources"] = about.taken()
    datastore.write(
        index,
        datastore.kept_entries(projects, index_rows),
        # With every package, the counts' history carries over, a point a day,
        # and what was fixed, the last month's.
        # The day before's point gets its split failing counts from the last
        # manifest, if it was recorded without them.
        history=datastore.with_split(datastore.read_history(), previous)
        if everything
        else None,
        fixed=datastore.with_fixed(datastore.read_fixed(), found_fixes, now)
        if everything
        else None,
        events=datastore.with_events(
            datastore.read_events(), trend_events(previous, now), now
        )
        if everything
        else None,
        kept={
            nixpkgs_source.EVALUATIONS: nixpkgs_source.kept_answers(),
            # The PRs maintainers can merge with the merge bot: the
            # maintainer and team views' "You can merge these" (every
            # package's PRs: with every package only).
            "views/merge.json": {
                "checkedAt": now,
                "prs": prs_digest.mergeable(digest["raw"], index_rows),
            }
            if everything and digest.get("raw") is not None
            else None,
        },
    )
    nixpkgs_source.stop_keeping()
    # With every package, what changed for the lists' own packages only.
    notify.notify(
        {**previous, "packages": [r for r in previous["packages"] if r.get("lists")]}
        if everything
        else previous,
        on_lists,
        now,
        # The subscribers' issues (notifications/): theirs among every row.
        everyone=index_rows,
        everyone_before=previous,
        lists=lists,
    )
