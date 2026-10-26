"""Read and write data/, the page's data folder.

Everything that reads the last run's data (history, schedules,
notifications, the hourly checks) or writes a new run's goes through this
module.

The data is in format 2, described in docs/data.md:

- index.json: a small manifest (the format, the counts, ...).
- summary.json: a short entry per row, what the page's list needs. With
  every package there's no summary; views/ and names.json take its place
  (views()).
- rows/<n>.json: the full rows, split into shards by a hash of the
  package's name. Each row carries its Repology entries in "repology".

Format 1 (0.11.0 and before; written beside format 2 until 0.13.0) is still
read, so the first sync after upgrading keeps the last run's data. In
format 1, index.json held every row in full in "packages", and each
Repology project's entries were in a file of their own, named by the row's
"dataFile".
"""

import contextlib
import copy
import functools
import json
import os
import shutil
import traceback
from typing import NamedTuple

from .. import causes, config, log, shape
from ..changes import (
    broken_builds,
    failed_builds,
    is_outdated,
    on_branch,
    waiting_for_channel,
)
from ..naming import shard_of, slug
from ..sources.nixpkgs import available_on
from . import facts, shards, trends
from .facts import highlights, nothing_compared, numbers, status, unbuilt_where
from .shards import (
    PANEL_ONLY,
    data_file,
    kept_entries,
    newest_repos,
    shard_count,
    summary_entry,
)
from .trends import (
    fixed_summary,
    read_events,
    read_fixed,
    read_history,
    with_events,
    with_fixed,
    with_split,
)

__all__ = [
    "check_kept",
    "data_file",
    "entries",
    "files",
    "fixed_summary",
    "highlights",
    "kept_entries",
    "load",
    "MERGE_VIEW",
    "newest_repos",
    "nothing_compared",
    "numbers",
    "PANEL_ONLY",
    "read_events",
    "read_fixed",
    "read_history",
    "restore_interrupted_swap",
    "saved_entries",
    "shard_count",
    "status",
    "summary_entry",
    "swap_in",
    "SYNC_ONLY",
    "unbuilt_where",
    "update",
    "views",
    "with_events",
    "with_fixed",
    "with_split",
    "write",
]


def files(index, entries, history=None, fixed=None, events=None):
    """Build every file of the data folder.

    The rows go into the shards, each with its Repology entries. With every
    package, the page starts from views (views()) rather than a summary of
    every row, and history.json gets this run's counts; otherwise
    summary.json lists every row.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        history: With every package, the last run's history.json points
            (read_history), to which this run's counts are added. None
            leaves history.json out, for a partial run: the file on disk
            stays, and the manifest keeps the "fixed" it already has.
        fixed: The fixes to keep (read_fixed's, with this run's added by
            with_fixed).
        events: What marks the trends (with_events).

    Returns:
        {path in the data folder: data}.
    """
    run = index.get("checkedAt")
    rows = sorted(
        (shards.elided(row, run) for row in index["packages"]),
        key=lambda row: row["name"],
    )
    count = shards.shard_count(len(rows))
    by_shard = [[] for _ in range(count)]
    for row in rows:
        full = dict(row)
        if found := entries.get(row.get("dataFile")):
            full["repology"] = found
        by_shard[shard_of(row["name"], count)].append(full)
    manifest = {
        **index,
        "format": shards.FORMAT,
        "packageCount": len(rows),
        "shardCount": count,
    }
    del manifest["packages"]  # the rows are in the shards
    out = {}
    if index.get("allPackages"):
        # With every package, a summary of them all would be too big to
        # load: the page starts from the views, the name index and the
        # counts instead (views()).
        manifest.update(views(rows, out))
        if history is not None:
            out["history.json"] = {
                "points": trends.with_point(history, run, manifest["counts"]),
                "fixed": fixed or [],
                "events": events or [],
            }
            manifest["fixed"] = trends.fixed_summary(fixed or [], run)
    else:
        out["summary.json"] = {"packages": [shards.summary_entry(row) for row in rows]}
    out["index.json"] = manifest
    for n, shard in enumerate(by_shard):
        out[f"rows/{n}.json"] = {"packages": shard}
    return out


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
            "broken", "blocked", "backport", "unbuilt", "superseded": each
            view's size, "teams", "lists": {name: packages}}).
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


def _write_file(path, text):
    """Write text to path, through a temporary file.

    The file is replaced in one step, so a failed write never leaves it
    half-written.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _check_shape(written):
    """Report what in the data doesn't match its description (shape.py).

    The check only reports for now, so it must never stop a write: should
    the check itself fail, that failure is logged too, and the write goes on.

    Args:
        written: The data about to be written, as files builds it.
    """
    try:
        shape.report(shape.problems(written))
    except Exception as e:  # reporting only: never stop a write
        # Where in shape.py it broke, to find the bug without running it
        # again: the innermost frame may be in a library it called.
        frames = traceback.extract_tb(e.__traceback__)
        frame = next(
            (f for f in reversed(frames) if os.path.basename(f.filename) == "shape.py"),
            frames[-1],
        )
        where = f"{os.path.basename(frame.filename)}:{frame.lineno}"
        log.warn(f"Data shape: the check itself failed at {where}: {e!r}")


def write(
    index, entries, out_dir=None, history=None, fixed=None, events=None, kept=None
):
    """Write the whole data folder for a sync, replacing the last one.

    The new data is built in a folder of its own and only then swapped in,
    so packages removed since the last sync disappear, and a run that
    fails before the swap leaves the last data as it was.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        out_dir: The data folder (the configured one by default).
        history: The counts' history so far (read_history), with every
            package; None leaves history.json out.
        fixed: The fixes to keep (with_fixed).
        events: What marks the trends (with_events).
        kept: Files written as they are, {path: data}, what the sync keeps
            for its next run (nixpkgs' evaluations, views/merge.json); None
            for a file leaves it out.

    Raises:
        ValueError: A kept file is under rows/ or views/ but not in
            SYNC_ONLY, before anything is written.
    """
    check_kept(kept)
    out_dir = config.data_dir(out_dir)
    tmp_dir = out_dir + ".tmp"
    # Also done by lock.held; repeated here for callers, such as tests,
    # that write without the lock.
    restore_interrupted_swap(out_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)  # leftover from a failed run
    os.makedirs(tmp_dir)
    written = files(index, entries, history, fixed, events)
    _check_shape(written)
    for name, data in written.items():
        _write_file(os.path.join(tmp_dir, name), shards.dumps(data))
    for name, data in (kept or {}).items():
        if data is not None:
            _write_file(os.path.join(tmp_dir, name), shards.dumps(data))
    swap_in(tmp_dir, out_dir)


def swap_in(new_dir, out_dir):
    """Replace a data folder with a new one.

    The old folder is moved aside before the new one is moved in, rather
    than deleted first: the data is then missing only between two renames,
    not while a whole folder is deleted, and a run that dies between them
    leaves the old data in <out_dir>.old, which restore_interrupted_swap
    puts back.

    Args:
        new_dir: The new data folder, complete.
        out_dir: The data folder it replaces.
    """
    old_dir = out_dir + ".old"
    shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.exists(out_dir):
        os.rename(out_dir, old_dir)
    os.rename(new_dir, out_dir)
    shutil.rmtree(old_dir, ignore_errors=True)


def restore_interrupted_swap(out_dir=None):
    """Tidy up after a swap that a run didn't finish.

    Only to be called when nothing else can be writing the folder: for the
    data folder, with its lock held (lock.held calls it). It moves folders,
    and another run in the middle of swap_in would see them change under
    it.

    A run that died between swap_in's two renames leaves no data folder
    and the last data in <out_dir>.old: that data is moved back, so the run
    that follows reads it as the previous run's. A run that died after
    both renames leaves the data folder and a stale <out_dir>.old: the old
    folder is removed.

    Args:
        out_dir: The folder swap_in replaces (the configured data folder by
            default).
    """
    out_dir = config.data_dir(out_dir)
    old_dir = out_dir + ".old"
    if not os.path.isdir(old_dir):
        return
    if os.path.exists(out_dir):
        shutil.rmtree(old_dir, ignore_errors=True)
    else:
        os.rename(old_dir, out_dir)


def update(index, entries, out_dir=None):
    """Rewrite the data folder in place, for a partial run.

    The hourly checks change a few rows: only the files whose content
    changed are written, each written aside first so a failure never leaves
    one half-written. The shards and views this run no longer writes, left
    from a run with more rows or a view that has emptied since, are
    removed, so the folder holds what a full write would leave.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        out_dir: The data folder (the configured one by default).
    """
    out_dir = config.data_dir(out_dir)
    # Also done by lock.held; repeated here for callers, such as tests,
    # that write without the lock.
    restore_interrupted_swap(out_dir)
    written = files(index, entries)
    _check_shape(written)
    for name, data in written.items():
        path = os.path.join(out_dir, name)
        text = shards.dumps(data)
        try:
            with open(path) as f:
                if f.read() == text:
                    continue
        except OSError:
            pass
        _write_file(path, text)
    _remove_files_no_longer_written(out_dir, written)


# The view of the PRs maintainers can merge. Only the daily sync writes it,
# as one of write's kept files, so a partial run leaves it in place.
MERGE_VIEW = "views/merge.json"
# Every file the daily sync keeps under rows/ or views/ (write's kept
# files): the only files there that a partial run leaves although it doesn't
# write them. check_kept refuses a kept file there that isn't listed, so a
# new one can't be deleted by every hourly check without anyone noticing.
SYNC_ONLY = frozenset({MERGE_VIEW})
# The folders a partial run tidies: everything in them is written by
# files().
GENERATED_FOLDERS = ("rows", "views")


def check_kept(kept):
    """Refuse a kept file in the generated folders that SYNC_ONLY doesn't list.

    This raises, unlike the shape check (shape.py), which only reports: an
    unlisted kept file is a mistake in nixkeeper's code, caught before any
    data is lost, not a problem in the data.

    Args:
        kept: write's kept files, {path: data}.

    Raises:
        ValueError: A kept file under rows/ or views/ isn't in SYNC_ONLY:
            the next partial run would delete it.
    """
    for path in kept or {}:
        if path.split("/")[0] in GENERATED_FOLDERS and path not in SYNC_ONLY:
            raise ValueError(
                f"{path} is kept by the sync but isn't in datastore.SYNC_ONLY: "
                "the hourly checks would delete it. Add it there."
            )


def _remove_files_no_longer_written(out_dir, written):
    """Remove the files under rows/ and views/ a partial run no longer writes.

    A view with no rows isn't written, so a view that has emptied since the
    last sync would otherwise keep its old rows on disk while the manifest
    says 0; and a shard past the shard count would stay when there are
    fewer rows. A leftover <file>.tmp, from a write that died, goes too.
    The files in SYNC_ONLY, which only the daily sync writes, are kept, and
    so is everything outside those folders (evaluations.json, history.json).
    Folders left empty are removed, except rows/ and views/ themselves, as
    a full write wouldn't make them.

    Args:
        out_dir: The data folder.
        written: The files this run wrote, as files builds them.
    """
    for folder in GENERATED_FOLDERS:
        top = os.path.join(out_dir, folder)
        # Bottom up, so a folder is seen after its files are removed.
        for root, _, names in os.walk(top, topdown=False):
            for name in names:
                path = os.path.relpath(os.path.join(root, name), out_dir)
                if path not in written and path not in SYNC_ONLY:
                    os.remove(os.path.join(root, name))
            if root != top and not os.listdir(root):
                os.rmdir(root)


@functools.lru_cache(maxsize=64)
def _cached(path, changed):
    """Read a data file's JSON, once while the file is unchanged.

    entries() reads a row's shard for each row it's asked about, so without
    the cache a shard would be read again for each of its rows.

    Args:
        path: The file.
        changed: Its modification time, part of the cache's key, so a file
            that was written again is read again.
    """
    return shards.read_json(path)


def _shared(path):
    """Read a data file's JSON through the cache.

    The result is shared with every other caller, so it must not be
    changed.
    """
    return _cached(path, os.stat(path).st_mtime_ns)


def load(out_dir=None):
    """Read the last run's index, with every row in "packages".

    The rows come without their Repology entries (entries() reads those).
    Both formats are read.

    Returns:
        The index, or {"packages": []} when there's none or it can't be
        read.
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = shards.read_json(os.path.join(out_dir, "index.json"))
    except (OSError, ValueError):
        return {"packages": []}
    if index.get("format") == shards.FORMAT:
        # The rows come from the shards. If one can't be read, the rows in
        # index.json are kept (data from 0.12.0 has them, written beside
        # format 1), else there are none.
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            index["packages"] = sorted(
                (
                    {k: v for k, v in row.items() if k != "repology"}
                    for n in range(index["shardCount"])
                    for row in shards.read_json(
                        os.path.join(out_dir, f"rows/{n}.json")
                    )["packages"]
                ),
                key=lambda row: row["name"],
            )
    index.setdefault("packages", [])
    for row in index["packages"]:
        shards.restored(row, index.get("checkedAt"))
    return index


def saved_entries(out_dir=None):
    """Read every row's Repology entries from the last run, each shard once.

    This is for the hourly checks, which write every shard again: calling
    entries() for each row would read a shard per row, about 126,000 shard
    reads with every package.

    Returns:
        {name: entries}, or {} for format 1 or when a file can't be read
        (entries() then reads each row's own file).
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = shards.read_json(os.path.join(out_dir, "index.json"))
        if index.get("format") != shards.FORMAT:
            return {}
        return {
            full["name"]: full.get("repology") or []
            for n in range(index["shardCount"])
            for full in shards.read_json(os.path.join(out_dir, f"rows/{n}.json"))[
                "packages"
            ]
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def entries(row, out_dir=None):
    """Read row's Repology entries from the last run.

    They're read from the row's shard (format 2), else from its own data
    file (format 1, 0.11.0 and before).

    Raises:
        OSError, ValueError: Neither can be read.
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = _shared(os.path.join(out_dir, "index.json"))
        if index.get("format") == shards.FORMAT:
            n = shard_of(row["name"], index["shardCount"])
            for full in _shared(os.path.join(out_dir, f"rows/{n}.json"))["packages"]:
                if full["name"] == row["name"]:
                    return copy.deepcopy(full.get("repology") or [])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    path = os.path.join(out_dir, row.get("dataFile") or f"{row['project']}.json")
    with open(path) as f:
        return json.load(f)
