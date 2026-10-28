"""The views, counts and lists the overview reads, with every package.

views() builds them in one pass over the rows: one collector per output,
each with add(row, letter) and result().
"""

from typing import NamedTuple

from .. import causes
from ..changes import (
    broken_builds,
    failed_builds,
    is_outdated,
    on_branch,
    waiting_for_channel,
)
from ..naming import slug
from ..sources.nixpkgs import available_on
from . import facts, shards


def views(rows, out):
    """Build the files the page starts from with every package.

    With every package, the page loads these instead of a summary of every
    row. Each view is {"packages": [summary entries]}, sorted by name.
    Packages in a set updated in bulk (such as the Haskell or R sets) are
    counted on their set's line, so most views leave them out; the views
    that include them say so.

    - views/attention.json: failing, outdated, flagged vulnerable, or with
      a fix to backport.
    - views/broken.json: marked broken in nixpkgs.
    - views/backport.json: a CVE fixed on nixpkgs master that still
      affects the newest release branch.
    - views/blocked.json: a build not tried because a dependency failed.
      Sets included, as the overview's blockers count them.
    - views/upstream.json: its GitHub repository is gone, archived, renamed
      or moved (releases_digest.mark_repos), sets included.
    - views/unbuilt.json: listed for a platform Hydra doesn't build it on
      (unbuilt_where).
    - views/superseded.json: an open update PR that nixpkgs is already past
      (supersededPRs, from prs_digest.mark_superseded). Sets included.
    - views/maintainer/<handle>.json: a maintainer's packages, by lowercase
      handle, sets included; views/maintainer/none.json: those with no
      maintainer, sets left out.
    - views/team/<slug>.json, views/list/<slug>.json: a team's and a
      package list's packages, sets included.
    - views/set/<name>.json: a set's packages.
    - views/cause/<key>.json: failed builds that share an error
      (causes.build_groups), with views/causes.json listing every group.
    - names.json: every row's name and status (status()), and its set when
      it has one: what a search looks through.
    - facets.json: the same rows' maintainers, teams and platforms, in the
      same order (facet_entry), for the search's filters.
    - maintainers.json: every maintainer, with the handle as nixpkgs writes
      it, as [handle, packages, outdated, failing], sorted by lowercase
      handle. packages counts sets too; outdated and failing count only
      the fully checked rows.

    Args:
        rows: Every row, as written, sorted by name.
        out: The files being built, {path: data}; the files above are
            added to it.

    Returns:
        What the manifest says of them: {"counts", "highlights",
        "blockers", "causes", "views"}. "views" has each view's size, the
        teams' and lists' sizes ({name: count}), and each set's counts
        ({name: {"packages", "outdated", "failed", "broken", ...}}).
    """
    # Every collector sees every row. A new output is a new collector, in
    # _Collectors.
    collectors = _Collectors.new()
    for row in rows:
        letter = facts.status(row)
        for collector in collectors:
            collector.add(row, letter)
    files, view_sizes = collectors.view_files.result()
    out.update(files)
    out["names.json"] = collectors.names.result()
    out["facets.json"] = collectors.facets.result()
    out["maintainers.json"] = collectors.maintainers.result()
    counted = collectors.counts.result()
    return {
        "counts": counted,
        "highlights": collectors.ages.result(counted),
        # The overview's "Blocking the most", on master and, before it's
        # merged into master, on staging-next.
        "blockers": {
            **collectors.blockers.result(),
            **(
                {"stagingNext": collectors.staging.result()}
                if collectors.staging.stops
                else {}
            ),
        },
        "causes": _causes(rows, out),
        "views": {**view_sizes, "sets": collectors.sets.result()},
    }


def _causes(rows, out):
    """Group the failed builds that share an error, for "Why things fail".

    Each group is a view of its packages (views/cause/<key>.json), and
    views/causes.json lists every group, for the overview's card when it's
    expanded (loaded only then). Both are added to out.

    Returns:
        The manifest's "causes": the biggest groups (causes.SHOWN of them,
        each {"key", "count", "reason", "signature", "line", "title"?,
        "about"?}), how many groups and packages there are in all, and the
        update bot's failures by cause.
    """
    groups = causes.build_groups(rows)
    for group in groups:
        out[f"views/cause/{group['key']}.json"] = {
            "packages": [shards.summary_entry(row) for row in group["rows"]],
            **{k: v for k, v in group.items() if k != "rows"},
        }
    if groups:
        out["views/causes.json"] = {
            "groups": [{k: v for k, v in g.items() if k != "rows"} for g in groups]
        }
    return {
        "builds": [
            {k: v for k, v in group.items() if k != "rows"}
            for group in groups[: causes.SHOWN]
        ],
        "groups": len(groups),
        "packages": len({row["name"] for g in groups for row in g["rows"]}),
        "bot": causes.bot_causes(rows),
    }


# The collectors views() fills in one pass over the rows: each one output,
# with add(row, letter) for each row (letter: status(row)), and result()
# once every row is added (_Ages' also takes the counts, for its cards). A
# row in a set updated in bulk reaches every collector; each decides for
# itself whether that row counts.


class _Views:
    """Collect the views (views/*.json) each row is in.

    Also counts the teams' and lists' packages, for the manifest.
    """

    def __init__(self):
        """Start with no views."""
        self.files = {}  # {path: [rows]}, each in the order rows come
        self.teams, self.lists = {}, {}

    def put(self, path, row):
        """Add row to the view at path."""
        self.files.setdefault(path, []).append(row)

    def add(self, row, letter):
        """Add row to every view it's in."""
        if any(b["status"] == "dependency" for b in row.get("builds") or []):
            self.put("views/blocked.json", row)
        for handle in row.get("maintainers") or []:
            self.put(f"views/maintainer/{handle.lower()}.json", row)
        for team in row.get("teams") or []:
            self.put(f"views/team/{slug(team)}.json", row)
            self.teams[team] = self.teams.get(team, 0) + 1
        for name in row.get("lists") or []:
            self.put(f"views/list/{slug(name)}.json", row)
            self.lists[name] = self.lists.get(name, 0) + 1
        # An open update PR that nixpkgs is already past
        # (prs_digest.mark_superseded): every such row, sets included, up
        # to date or not.
        if row.get("supersededPRs"):
            self.put("views/superseded.json", row)
        # Its GitHub repository gone, archived, renamed or moved: every
        # such row, sets included.
        if row.get("upstreamRepo"):
            self.put("views/upstream.json", row)
        if row.get("set"):
            # A set's packages are counted on its set's line: none of the
            # views below.
            self.put(f"views/set/{row['set']}.json", row)
            return
        if row.get("maintainers") == []:
            self.put("views/maintainer/none.json", row)
        if row.get("backport"):
            self.put("views/backport.json", row)
        if row.get("markedBroken") or broken_builds(row):
            self.put("views/broken.json", row)
        if facts.unbuilt_where(row):
            self.put("views/unbuilt.json", row)
        # A fix to backport is for the maintainer to do too, even when
        # nixos-unstable is fine (the list's tile: Fixes to backport).
        if letter[0] in "fmo" or letter.endswith("v") or row.get("backport"):
            self.put("views/attention.json", row)

    def result(self):
        """Return the views, and their sizes for the manifest.

        Returns:
            ({path: {"packages": [summary entries]}}, {"attention",
            "broken", "blocked", "backport", "unbuilt", "superseded",
            "upstream": each view's size, "teams", "lists": {name: packages}}).
        """
        files = {
            path: {"packages": [shards.summary_entry(row) for row in members]}
            for path, members in self.files.items()
        }
        sizes = {
            name: len(self.files.get(f"views/{name}.json", []))
            for name in (
                "attention",
                "broken",
                "blocked",
                "backport",
                "unbuilt",
                "superseded",
                "upstream",
            )
        }
        # Sorted with capitals first, as Python sorts strings; the page
        # sorts them its own way.
        sizes["teams"] = dict(sorted(self.teams.items()))
        sizes["lists"] = dict(sorted(self.lists.items()))
        return files, sizes


class _Counts:
    """Collect the manifest's counts.

    Most count the fully checked rows only; failingBuilds and inSets count
    the rows in sets too.
    """

    def __init__(self):
        """Start every count at 0."""
        self.counts = dict.fromkeys(
            (
                "broken",
                "failingBuilds",
                "tracked",
                "outdated",
                "failed",
                "vulnerable",
                "backport",
                "updateFailures",
                "buildFailures",
                "waiting",
                "inSets",
            ),
            0,
        )
        self.failing_on = {}  # {"linux", "darwin" or a system: packages failing there}

    def add(self, row, letter):
        """Count row."""
        counts = self.counts
        # Hydra jobs that didn't succeed, on every platform and of every row
        # (sets included): failing builds as zh.fail counts them.
        counts["failingBuilds"] += sum(
            b["status"] in facts.FAILING_BUILDS for b in row.get("builds") or []
        )
        if row.get("set"):
            counts["inSets"] += 1
            return
        counts["tracked"] += 1
        counts["failed"] += letter.startswith("f")
        counts["waiting"] += letter.startswith("m")
        counts["outdated"] += is_outdated(row)
        counts["vulnerable"] += letter.endswith("v")
        counts["backport"] += bool(row.get("backport"))
        counts["updateFailures"] += bool(row.get("updateFailure"))
        counts["buildFailures"] += bool(failed_builds(row))
        # The same by where the builds fail: each Hydra system, and Linux
        # and Darwin (a package failing on both Linux systems is counted
        # once for Linux), as the page's platform filter counts them. Only
        # where the package is available counts: ete's failing
        # aarch64-darwin build doesn't, as ete isn't available there.
        systems = {
            b["system"]
            for b in failed_builds(row)
            if available_on(row.get("platforms"), b["system"])
        }
        for where in systems | {s.rsplit("-", 1)[-1] for s in systems}:
            self.failing_on[where] = self.failing_on.get(where, 0) + 1
        counts["broken"] += bool(row.get("markedBroken") or broken_builds(row))

    def result(self):
        """Return the counts, with buildFailuresOn: the failures by platform."""
        return {**self.counts, "buildFailuresOn": dict(sorted(self.failing_on.items()))}


class _Names:
    """Collect names.json: every row's name and status, and its set."""

    def __init__(self):
        """Start with no names."""
        self.names = []

    def add(self, row, letter):
        """Add row's name, status and set, when it has one."""
        self.names.append(
            [row["name"], letter, row["set"]]
            if row.get("set")
            else [row["name"], letter]
        )

    def result(self):
        """Return names.json."""
        return {"names": self.names}


class _Facets:
    """Collect facets.json: each row's platforms, maintainers and teams.

    The rows come in the same order as names.json's (facet_entry).
    """

    def __init__(self):
        """Start with no rows."""
        self.rows, self.handles, self.teams = [], {}, {}

    def add(self, row, letter):
        """Add row's entry."""
        self.rows.append(facts.facet_entry(row, self.handles, self.teams))

    def result(self):
        """Return facets.json."""
        return {
            "handles": list(self.handles),
            "teams": list(self.teams),
            "rows": self.rows,
        }


class _Maintainers:
    """Collect maintainers.json: each maintainer's packages, outdated and failing.

    packages counts the rows in sets too; outdated and failing count only the
    fully checked rows.
    """

    def __init__(self):
        """Start with no maintainers."""
        self.found = {}  # {lowercase handle: [handle, packages, outdated, failing]}

    def add(self, row, letter):
        """Count row for each of its maintainers."""
        for handle in row.get("maintainers") or []:
            mine = self.found.setdefault(handle.lower(), [handle, 0, 0, 0])
            mine[1] += 1
            if not row.get("set"):
                mine[2] += is_outdated(row)
                mine[3] += letter.startswith("f")

    def result(self):
        """Return maintainers.json, sorted by lowercase handle."""
        return {"maintainers": [self.found[key] for key in sorted(self.found)]}


class _Ages:
    """Collect since when each fully checked row has had each problem.

    That's failing, outdated, or failing its update attempts: the overview's
    newest and oldest of each (highlights).
    """

    def __init__(self):
        """Start with no problems."""
        self.ages = {"failing": [], "outdated": [], "updateFailing": []}

    def add(self, row, letter):
        """Add row's problems that count now, with since when it has had them."""
        if row.get("set"):
            return
        # Only rows that count now are listed. The hourly checks recount,
        # but only the daily sync sets and clears these dates, so after a
        # change in how nixkeeper counts, the lists would otherwise disagree
        # with the cards for a day.
        now_counts = {
            "failing": bool(failed_builds(row)),
            "outdated": is_outdated(row),
            "updateFailing": bool(row.get("updateFailure")),
        }
        for kind, field in facts.AGES.items():
            # An update already merged and waiting for the channel needs no
            # action, so it's left out of the list (but not the card's count).
            if kind == "outdated" and waiting_for_channel(row):
                continue
            if row.get(field) and now_counts[kind]:
                self.ages[kind].append(
                    (row[field], row["name"], letter, row.get("family"))
                )

    def result(self, counts):
        """Return the overview's highlights of each kind.

        Args:
            counts: The manifest's counts. Each list's count is its card's:
                a row counted before the daily sync gives it a date is in
                the count, but not in the list.
        """
        return {
            kind: {
                **facts.highlights(found),
                "count": counts[facts.HIGHLIGHT_COUNTS[kind]],
            }
            for kind, found in self.ages.items()
        }


class _Blockers:
    """Collect the dependencies that stop other packages' builds on master.

    Every row counts, sets included, as zh.fail counts them.
    """

    def __init__(self):
        """Start with no blockers."""
        self.stops = {}  # {name: [whether it has a row, {packages}, builds]}
        self.packages = 0  # the packages with a build stopped

    def stop(self, blocker, package):
        """Note that blocker stops one of package's builds."""
        stops = self.stops.setdefault(
            blocker["name"], [bool(blocker.get("row")), set(), 0]
        )
        stops[1].add(package)
        stops[2] += 1

    def add(self, row, letter):
        """Note what stops row's builds that a dependency's failure stopped.

        A row with such a build counts as stopped whether or not its
        blockers are known yet (the blocked view's).
        """
        stopped = [b for b in row.get("builds") or [] if b["status"] == "dependency"]
        self.packages += bool(stopped)
        for build in stopped:
            for blocker in build.get("blockedBy") or []:
                self.stop(blocker, row["name"])

    def top(self):
        """Return the HIGHLIGHTS that stop the most, [name, row?, packages, builds]."""
        ranked = sorted(
            self.stops.items(), key=lambda kv: (-len(kv[1][1]), -kv[1][2], kv[0])
        )
        return [
            [name, is_row, len(names), builds]
            for name, (is_row, names, builds) in ranked[: facts.HIGHLIGHTS]
        ]

    def result(self):
        """Return how many dependencies stop builds, how many packages, and the top."""
        return {"count": len(self.stops), "packages": self.packages, "top": self.top()}


class _StagingNextBlockers(_Blockers):
    """Collect what staging-next's failing dependencies stop there.

    That's of the packages that build on master
    (branches.apply_staging_next_blocked): a forecast for staging-next's
    merge into master.
    """

    def __init__(self):
        """Start with no blockers, and no evaluation."""
        super().__init__()
        self.info = {}  # which evaluation of staging-next, and when

    def add(self, row, letter):
        """Note what stops row's builds on staging-next."""
        if not (found := row.get("stagingNextBlockedBy")):
            return
        self.packages += 1
        self.info = {k: found[k] for k in ("eval", "evaluatedAt") if k in found}
        for build in found["builds"]:
            for blocker in build["by"]:
                self.stop(blocker, row["name"])

    def result(self):
        """Return the same as _Blockers, with which evaluation this is."""
        return {**self.info, **super().result()}


class _Sets:
    """Collect each set's counts, for the overview's line on it."""

    def __init__(self):
        """Start with no sets."""
        self.sets = {}

    def add(self, row, letter):
        """Count row on its set's line, when it's in a set."""
        if not row.get("set"):
            return
        found_set = self.sets.setdefault(
            row["set"],
            {
                "packages": 0,
                "outdated": 0,
                "failed": 0,
                "broken": 0,
                "bar": {"failed": 0, "broken": 0, "outdated": 0},
            },
        )
        if row.get("archived"):
            # No longer on CRAN or in Bioconductor (sources/cran_digest.py).
            # nixpkgs already marks most of them broken; the others are
            # counted apart.
            found_set["archived"] = found_set.get("archived", 0) + 1
            if not (row.get("markedBroken") or broken_builds(row)):
                found_set["archivedUnmarked"] = found_set.get("archivedUnmarked", 0) + 1
        found_set["packages"] += 1
        found_set["outdated"] += is_outdated(row)
        if on_branch(row):
            # Already updated on the set's branch (haskell-updates).
            found_set["onBranch"] = found_set.get("onBranch", 0) + 1
        failed = letter.startswith("f")
        broken = bool(row.get("markedBroken") or broken_builds(row))
        found_set["failed"] += failed
        found_set["broken"] += broken
        # The overview's bar counts each package once, at its worst
        # (failing, then broken, then outdated), so its parts never overlap.
        if failed:
            found_set["bar"]["failed"] += 1
        elif broken:
            found_set["bar"]["broken"] += 1
        elif is_outdated(row):
            found_set["bar"]["outdated"] += 1

    def result(self):
        """Return each set's counts, by set."""
        return dict(sorted(self.sets.items()))


class _Collectors(NamedTuple):
    """views()' collectors, one per output, each under its own name.

    They're made by keyword (new), so a name can't end up holding another
    collector; a test checks each against its annotation.
    """

    view_files: _Views
    counts: _Counts
    names: _Names
    facets: _Facets
    maintainers: _Maintainers
    ages: _Ages
    blockers: _Blockers
    staging: _StagingNextBlockers
    sets: _Sets

    @classmethod
    def new(cls):
        """Make each collector afresh, under its name."""
        return cls(**{name: kind() for name, kind in cls.__annotations__.items()})
