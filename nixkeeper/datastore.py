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
import math
import os
import re
import shutil
import sys
import traceback
from datetime import UTC, datetime, timedelta

from . import causes, config, shape
from . import rows as rows_module
from .changes import (
    broken_builds,
    failed_builds,
    failures,
    is_outdated,
    is_vulnerable,
    on_branch,
    waiting_for_channel,
)
from .naming import shard_of, slug
from .sources import vulnerabilities_digest
from .sources.nixpkgs import available_on

FORMAT = 2
# About how many rows a shard holds. A shard is what the page loads to show
# a package's details panel.
SHARD_ROWS = 500
# A row's fields that only the details panel uses: they're left out of the
# row's summary entry.
PANEL_ONLY = (
    "dataFile",
    "feed",
    "buildFixPR",
    "buildCausePR",
    "recentFixes",
    "fixPRs",
    "issueChecks",
    "otherPRs",
    "vulnerabilities",
    "homepage",
    "repoCount",
    "repologyCheckedAt",
    "source",
)
# The fields of a row's update check ("upstream") that its summary entry
# keeps: what the list shows (the version, whether it's newer, and whose
# check it is).
UPSTREAM_SHOWN = ("community", "inferred", "newer", "version")


def data_file(key):
    """Return the file name for a Repology project's data.

    Project names such as python:requests contain characters that don't
    belong in file names or URLs; each of them becomes an underscore.
    """
    return re.sub(r"[^A-Za-z0-9._+-]", "_", key) + ".json"


def dumps(data):
    """Format data as compact JSON, with its keys sorted.

    Without indentation the files are about a third smaller, and with the
    keys sorted, the same data always gives the same bytes.
    """
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def shard_count(rows):
    """Return how many shards to split the rows into.

    About SHARD_ROWS rows a shard, rounded up to a power of two: 1 for a few
    hundred rows, 256 for all of nixpkgs.

    Args:
        rows: The number of rows.
    """
    return 1 << max(0, math.ceil(math.log2(max(1, rows / SHARD_ROWS))))


def elided(row, run):
    """Return row without the timestamps that only repeat the run's time.

    A row's "countedAt", and the "checkedAt" of its update check and of each
    of its builds, are left out when they equal run. A row that nothing new
    happened to then keeps the same bytes from one run to the next.
    restored() puts the timestamps back when the data is read.

    Args:
        row: The row. It isn't changed.
        run: The run's time, the index's "checkedAt". When it's empty, row
            is returned as it is.

    Returns:
        The row as it's written.
    """
    if not run:
        return row
    row = dict(row)
    if row.get("countedAt") == run:
        del row["countedAt"]
    if (row.get("upstream") or {}).get("checkedAt") == run:
        row["upstream"] = {k: v for k, v in row["upstream"].items() if k != "checkedAt"}
    if "builds" in row:
        row["builds"] = [
            {k: v for k, v in b.items() if k != "checkedAt"}
            if b.get("checkedAt") == run
            else b
            for b in row["builds"]
        ]
    return row


def restored(row, run):
    """Put back the timestamps elided() left out of row.

    Every build and update check has a "checkedAt", and a row with counts
    ("openPRs") has a "countedAt", so a missing one was left out because
    it equalled run.

    Args:
        row: The row as read from its shard. It's changed in place.
        run: The time of the run that wrote it, the index's "checkedAt".
            When it's empty, nothing is changed.

    Returns:
        row.
    """
    if not run:
        return row
    for build in row.get("builds") or []:
        build.setdefault("checkedAt", run)
    if row.get("upstream"):
        row["upstream"].setdefault("checkedAt", run)
    if "openPRs" in row:
        row.setdefault("countedAt", run)
    return row


# Repology statuses whose versions can't be compared with others. They sort
# after the rest, as comparedRepos in page/logic.js does.
UNCOMPARABLE = {"rolling", "ignored", "incorrect", "noscheme", "untrusted"}


def newest_repos(entries, count):
    """Pick the Repology entries a details panel shows.

    nixpkgs' own entries are kept, and of the other repositories, the count
    with the newest versions, one entry each (its newest). They're ranked as
    the panel orders them (comparedRepos in page/logic.js): comparable
    versions first, then the newest version first, then by repository.

    Args:
        entries: A project's Repology entries.
        count: How many other repositories to keep.

    Returns:
        nixpkgs' entries, then the kept ones in that order.
    """
    from .versions import version_key

    def order(e):
        return (
            e.get("status") in UNCOMPARABLE,
            _Reversed(version_key(e.get("version") or "")),
        )

    best = {}
    for e in entries:
        repo = e.get("repo")
        if repo == config.NIX_REPO:
            continue
        if repo not in best or order(e) < order(best[repo]):
            best[repo] = e
    kept = sorted(best.values(), key=lambda e: (*order(e), e.get("repo") or ""))
    return [e for e in entries if e.get("repo") == config.NIX_REPO] + kept[:count]


class _Reversed:
    """A sort key that orders in reverse, so the newest version comes first."""

    def __init__(self, key):
        self.key = key

    def __lt__(self, other):
        return other.key < self.key

    def __eq__(self, other):
        return self.key == other.key


def kept_entries(projects, rows):
    """Choose the Repology entries to write for each project.

    A project with a row on the package lists keeps all its entries. Every
    other project (with every package, the rest of nixpkgs) keeps only
    nixpkgs' own entries and those of the REPOLOGY_ENTRIES_KEPT other
    repositories with the newest versions: what its details panel shows.
    The rest can be seen on Repology.

    Args:
        projects: The Repology projects looked up (by lookup), each with
            "dataFile" and "entries".
        rows: The rows made from them.

    Returns:
        {dataFile: entries}.
    """
    listed = {row["dataFile"] for row in rows if row.get("lists")}
    return {
        p["dataFile"]: p["entries"]
        if p["dataFile"] in listed
        else newest_repos(p["entries"], config.REPOLOGY_ENTRIES_KEPT)
        for p in projects.values()
    }


def summary_entry(row):
    """Make row's entry in summary.json and in the views.

    The entry keeps what the list, the counts, the filters, the search and
    sorting need, and leaves out the fields only the details panel uses
    (PANEL_ONLY). Builds are reduced to their status and system, the update
    attempt to its outcome and why it failed, and the update check to
    UPSTREAM_SHOWN.

    Args:
        row: The row, as written.

    Returns:
        The entry, a new dict.
    """
    entry = {k: v for k, v in row.items() if k not in PANEL_ONLY}
    if (row.get("openPR") or {}).get("facts"):
        # What nixkeeper-prs found about the PR is only shown in the panel.
        entry["openPR"] = {k: v for k, v in row["openPR"].items() if k != "facts"}
    if "vulnerabilities" in row:
        # The vulnerability verdict, worked out once here rather than by
        # the page. None means no vulnerability counted, and Repology's flag
        # isn't used either.
        entry["vuln"] = vulnerabilities_digest.summary(row)
    if "builds" in row:
        entry["builds"] = [
            {"status": b["status"], "system": b["system"]}
            | ({"blockedBy": b["blockedBy"]} if b.get("blockedBy") else {})
            # Why it failed, for the list's filter; the log lines are only
            # in the panel.
            | ({"failedBecause": b["failedBecause"]} if b.get("failedBecause") else {})
            for b in row["builds"]
        ]
    # null (never tried) and a missing "update" (not in nixpkgs) stay as they
    # are.
    if row.get("update"):
        entry["update"] = {"outcome": row["update"].get("outcome")}
        if because := row["update"].get("failedBecause"):
            entry["update"]["failedBecause"] = because  # the list shows why
    if "upstream" in row:
        entry["upstream"] = {
            k: v for k, v in row["upstream"].items() if k in UPSTREAM_SHOWN
        }
    # The update bot's queue, for the list's robot icon: the versions it
    # would update to, whether it runs the package's updateScript, and the
    # day it's expected to try ("by", shown as "auto update in 4 days"). The
    # row also has where each version was found; the entry leaves that out.
    queued = row.get("queued") or {}
    entry.pop("queued", None)
    to = list(dict.fromkeys(c[0] for c in queued.get("candidates", [])))
    if to or queued.get("script"):
        entry["queued"] = {
            **({"to": to} if to else {}),
            **({"script": True} if queued.get("script") else {}),
            **({"by": queued["by"]} if queued.get("by") else {}),
        }
    return entry


# How many days of counts history.json keeps (with every package).
HISTORY_DAYS = 365


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
        (elided(row, run) for row in index["packages"]), key=lambda row: row["name"]
    )
    count = shard_count(len(rows))
    shards = [[] for _ in range(count)]
    for row in rows:
        full = dict(row)
        if found := entries.get(row.get("dataFile")):
            full["repology"] = found
        shards[shard_of(row["name"], count)].append(full)
    manifest = {
        **index,
        "format": FORMAT,
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
                "points": with_point(history, run, manifest["counts"]),
                "fixed": fixed or [],
                "events": events or [],
            }
            manifest["fixed"] = fixed_summary(fixed or [], run)
    else:
        out["summary.json"] = {"packages": [summary_entry(row) for row in rows]}
    out["index.json"] = manifest
    for n, shard in enumerate(shards):
        out[f"rows/{n}.json"] = {"packages": shard}
    return out


def with_split(history, previous):
    """Add the previous run's split failure counts to its day's point.

    The failures were recorded as one count before 0.13.0, and as two
    after (SPLIT_COUNTS). The previous manifest has them apart, so its
    day's point gets them where it doesn't have them yet. Older manifests
    have no buildFailures count; the count of the overview's failing
    highlights stands for it.

    Args:
        history: The history points, oldest first.
        previous: The previous run's manifest.

    Returns:
        history, with that day's point completed, or as it was when the
        manifest lacks either count.
    """
    run = previous.get("checkedAt") or ""
    counts = previous.get("counts") or {}
    found = {
        "buildFailures": counts.get("buildFailures")
        if "buildFailures" in counts
        else ((previous.get("highlights") or {}).get("failing") or {}).get("count"),
        "updateFailures": counts.get("updateFailures"),
    }
    if not run or any(v is None for v in found.values()):
        return history
    return [{**found, **p} if p.get("day") == run[:10] else p for p in history]


def with_point(history, run, counts):
    """Record this run's counts as its day's point in the history.

    A second sync on the same day replaces the first one's point. Only the
    last HISTORY_DAYS days are kept.

    Args:
        history: The points, each {"day", counts...}, oldest first.
        run: The run's time.
        counts: The manifest's counts, of the fully checked rows. The ones
            in HISTORY_COUNTS are recorded.

    Returns:
        The points, oldest first.
    """
    day = (run or "")[:10]
    point = {"day": day, **{k: counts[k] for k in HISTORY_COUNTS}}
    kept = [p for p in history if p.get("day") != day]
    return sorted([*kept, point], key=lambda p: p["day"])[-HISTORY_DAYS:]


# Hydra statuses of a build that didn't succeed. The manifest's failingBuilds
# counts them all, as zh.fail does; only "failed" makes a package fail on
# the page.
FAILING_BUILDS = {"failed", "dependency", "unfinished"}
# The counts history.json records each day, of the fully checked rows.
HISTORY_COUNTS = (
    "tracked",
    "outdated",
    "failed",
    "buildFailures",
    "updateFailures",
    "vulnerable",
    "broken",
)
# The counts a history point didn't have before 0.13.0, when the failures
# were split in two. with_split takes them from the previous manifest for
# its own day's point.
SPLIT_COUNTS = ("buildFailures", "updateFailures")


# How many days of fixes history.json keeps, and how many days the
# overview counts them over.
FIXED_DAYS = 30
FIXED_RECENT_DAYS = 7


def read_fixed(out_dir=None):
    """Return the fixes kept in the last run's history.json, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return _load(os.path.join(out_dir, "history.json")).get("fixed") or []
    except (OSError, ValueError, AttributeError):
        return []


def with_fixed(fixed, new, run):
    """Add this run's fixes to the kept ones.

    A package's fix of one kind is kept once a day, as a second sync on the
    same day finds it again. Only the last FIXED_DAYS days are kept.

    Args:
        fixed: The kept fixes, oldest first.
        new: This run's fixes.
        run: The run's time.

    Returns:
        The fixes, oldest first.
    """
    cutoff = _day_before(run, FIXED_DAYS)
    seen, kept = set(), []
    for fix in [*fixed, *new]:
        key = (fix["at"][:10], fix["name"], fix["kind"])
        if fix["at"][:10] > cutoff and key not in seen:
            seen.add(key)
            kept.append(fix)
    return sorted(kept, key=lambda f: (f["at"], f["name"], f["kind"]))


def fixed_summary(fixed, run):
    """Summarize the recent fixes, for the manifest's "fixed".

    For each kind of fix (build, update, bot), count the fixes of the last
    FIXED_RECENT_DAYS days and pick HIGHLIGHTS of them to show. The list is
    called "newest" from when it held the newest ones; it now holds the
    fixes whose problem had lasted longest first (with about a hundred
    fixes a day, the newest are all the last sync's), then those that don't
    say since when, newest first. A family is listed once, as its first
    member.

    Args:
        fixed: The kept fixes.
        run: The run's time.

    Returns:
        {"days": FIXED_RECENT_DAYS, and for each kind: {"count", "newest"}},
        each fix in "newest" as _fixed_entry formats it.
    """
    cutoff = _day_before(run, FIXED_RECENT_DAYS)
    out = {}
    for kind in ("build", "update", "bot"):
        mine = [f for f in fixed if f["kind"] == kind and f["at"][:10] > cutoff]
        # Newest first, ties by name. The sort by how long the problem
        # lasted, below, keeps this order among equals.
        newest = sorted(
            sorted(mine, key=lambda f: f["name"]), key=lambda f: f["at"], reverse=True
        )
        shown = grouped(
            sorted(newest, key=_lasted, reverse=True),
            lambda f: f.get("family"),
            lambda f: f["name"],
        )[:HIGHLIGHTS]
        out[kind] = {
            "count": len(mine),
            "newest": [_fixed_entry(f, members) for f, members in shown],
        }
    return {"days": FIXED_RECENT_DAYS, **out}


def _lasted(fix):
    """Return how long fix's problem had lasted, in seconds.

    Returns:
        The seconds from when the problem began to when it was fixed, or -1
        when the fix doesn't say when it began.
    """
    try:
        since = datetime.fromisoformat(fix["since"])
        if since.tzinfo is None:  # a day without a time: midnight UTC
            since = since.replace(tzinfo=UTC)
        return max(0, (datetime.fromisoformat(fix["at"]) - since).total_seconds())
    except (KeyError, TypeError, ValueError):
        return -1


def _fixed_entry(fix, members=None):
    """Format a fix as the manifest lists it (see fixed_summary).

    Args:
        fix: The fix.
        members: For a family's first fix, the names of the family's
            members fixed with it; None otherwise.

    Returns:
        [name, at, from, to, credit, since, family], without trailing nulls
        (but always the first four). from and to are an update's versions,
        else null; credit is {"pr", "author"?, "mergedBy"?, "likely"?}
        (history.credit) or null; since is when the problem began; family
        is family_entry's, when other members of its family were fixed
        with it.
    """
    credit = {k: fix[k] for k in ("pr", "author", "mergedBy", "likely") if k in fix}
    entry = [
        fix["name"],
        fix["at"],
        fix.get("from"),
        fix.get("to"),
        credit if fix.get("pr") else None,
        fix.get("since"),
        family_entry(members) if members else None,
    ]
    while len(entry) > 4 and entry[-1] is None:
        entry.pop()
    return entry


def _day_before(run, days):
    """Return the day (YYYY-MM-DD) that is days before run's day."""
    day = datetime.fromisoformat((run or "1970-01-01")[:10])
    return (day - timedelta(days=days)).date().isoformat()


def read_events(out_dir=None):
    """Return the trend markers kept in the last run's history.json, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return _load(os.path.join(out_dir, "history.json")).get("events") or []
    except (OSError, ValueError, AttributeError):
        return []


def with_events(events, new, run):
    """Add this run's trend markers to the kept ones.

    The markers are what the trend charts mark: staging-next merges (mass
    rebuilds, after which failing builds jump for days), nixkeeper's own
    updates, and changes in how it counts (config.COUNTING_CHANGES). Each
    is kept once: a merge by its PR, an update by its version, a counting
    change by its text. Only the last HISTORY_DAYS days are kept.

    Args:
        events: The kept markers.
        new: This run's markers.
        run: The run's time.

    Returns:
        The markers, oldest first.
    """
    cutoff = _day_before(run, HISTORY_DAYS)
    kept = {}
    for event in [*events, *new]:
        key = (
            event["kind"],
            event.get("pr") or event.get("version") or event.get("text"),
        )
        if event["day"] > cutoff:
            kept[key] = event  # a later copy replaces an earlier one
    return sorted(kept.values(), key=lambda e: (e["day"], e["kind"]))


def read_history(out_dir=None):
    """Return the last run's history.json points, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return _load(os.path.join(out_dir, "history.json")).get("points") or []
    except (OSError, ValueError, AttributeError):
        return []


# The overview's lists of the newest and oldest problems (the highlights in
# views()), each with the row field that says since when.
AGES = {
    "failing": "failingSince",
    "outdated": "outdatedSince",
    "updateFailing": "updateFailingSince",
}
# The overview card each highlight list belongs to; the list's count is the
# card's.
HIGHLIGHT_COUNTS = {
    "failing": "buildFailures",
    "outdated": "outdated",
    "updateFailing": "updateFailures",
}
# How many entries each overview list shows.
HIGHLIGHTS = 8


def grouped(items, family, name):
    """Collapse each family in a list to its first member.

    A family (rows.add_families) is packages that move together: one update
    that moves 187 packages should be one entry, not the whole list.

    Args:
        items: The items, already in their order.
        family: Returns an item's family, or None.
        name: Returns an item's name.

    Returns:
        [(item, members)], in the same order, without each family's later
        members. members is the names of the family's members for a
        family's first item, when it has more than one; otherwise None.
    """
    names = {}
    for item in items:
        if family(item):
            names.setdefault(family(item), []).append(name(item))
    out, seen = [], set()
    for item in items:
        key = family(item)
        if key in seen:
            continue
        if key:
            seen.add(key)
        out.append((item, names[key] if key and len(names[key]) > 1 else None))
    return out


def family_entry(members):
    """Describe the family a list entry stands for.

    Args:
        members: The names of the family's members, the entry's own
            included.

    Returns:
        {"more": how many others there are}, and "label", what they're
        called together (rows.family_label), when there is one.
    """
    found = {"more": len(members) - 1}
    if label := rows_module.family_label(members):
        found["label"] = label
    return found


def highlights(found):
    """Pick the overview's newest and longest-standing problems of one kind.

    Args:
        found: (since, name, status, family) for each row with the problem.

    Returns:
        {"count", "newest", "oldest"}: how many there are, and the
        HIGHLIGHTS most recent and longest-standing, ties by name. Each is
        [name, since, status], with family_entry's as a fourth item when
        the entry stands for its family; the family's other members are
        left out of the list.
    """

    def since(f):
        return datetime.fromisoformat(f[0]).timestamp()

    def pick(chosen):
        picked = grouped(chosen, lambda f: f[3], lambda f: f[1])[:HIGHLIGHTS]
        return [
            [name, at, letter, *([family_entry(members)] if members else [])]
            for (at, name, letter, _), members in picked
        ]

    return {
        "count": len(found),
        "newest": pick(sorted(found, key=lambda f: (-since(f), f[1]))),
        "oldest": pick(sorted(found, key=lambda f: (since(f), f[1]))),
    }


def nothing_compared(row):
    """Return whether row's version was compared with nothing.

    Repology calls a version "unique" when no other repository has a newer
    one, which includes when no repository outside nixpkgs has the package
    at all. When no update check or release feed of nixkeeper's own knows
    its releases either, the version was compared with nothing
    (python313Packages.pbar2, one of about 21,300 such rows on 2026-10-23).
    The page then shows it as not compared rather than up to date
    (computeStatus).
    """
    return (
        row.get("nixStatus") == "unique"
        and bool(row.get("onlyNixpkgs"))
        and not row.get("upstream")
        and not row.get("feed")
    )


def status(row):
    """Return a row's status as the page's dot shows it, in letters.

    The first letter is worked out as computeStatus and hasFailure in
    page/logic.js do: f failing, m outdated but the update is waiting for
    the channel, o outdated, u up to date, n not comparable (Repology can't
    say, or doesn't know the package). A v follows when the package is
    vulnerable (flagged by Repology, or marked insecure by nixpkgs).
    """
    if failures(row):
        letter = "f"
    elif waiting_for_channel(row):
        letter = "m"
    elif is_outdated(row):
        letter = "o"
    elif row.get("nixStatus") in ("newest", "unique", "devel") and not nothing_compared(
        row
    ):
        letter = "u"
    else:
        letter = "n"
    return letter + ("v" if is_vulnerable(row) else "")


# The platforms unbuilt_where looks at: each Linux system on its own, and
# Darwin as one.
UNBUILT_KEYS = ("x86_64-linux", "aarch64-linux", "darwin")


def _on_platform(row, key):
    """Return whether row is listed for key, as the page's onPlatform does.

    key is a family ("linux") or a system ("x86_64-linux"). A row without a
    restriction ("platforms": null) is listed for every one.
    """
    platforms = row.get("platforms", {})
    if platforms is None:
        return True
    family = key.split("-")[-1]
    if not platforms.get(family):
        return False
    systems = platforms.get("systems")
    return key == family or not systems or key in systems


def _on_system(system, key):
    """Return whether a build's system matches key.

    key is the same system ("x86_64-linux"), or a family ("linux") the
    system is one of.
    """
    return system == key if "-" in key else system.endswith("-" + key)


def unbuilt_where(row):
    """Return the platforms row is listed for but Hydra doesn't build it on.

    These are the page's struck platform tags (unbuiltWhere in
    page/logic.js). A platform counts when every build of the row there is
    "notBuilt", usually because a dependency isn't available there, while
    Hydra builds the row elsewhere.

    Returns:
        The platforms (of UNBUILT_KEYS). [] when Hydra builds the row
        everywhere it's listed, or nowhere (an unfree package, kept off
        Hydra).
    """
    builds = row.get("builds") or []
    found = []
    for key in UNBUILT_KEYS:
        here = [b for b in builds if _on_system(b["system"], key)]
        if (
            here
            and _on_platform(row, key)
            and all(b["status"] == "notBuilt" for b in here)
            and any(
                b["status"] != "notBuilt"
                for b in builds
                if not _on_system(b["system"], key)
            )
        ):
            found.append(key)
    return found


# The bits for a row's platforms in facets.json: where it's available
# (sources.nixpkgs.available_on). All three are set when nixpkgs doesn't
# restrict it.
FACET_SYSTEMS = (("x86_64-linux", 1), ("aarch64-linux", 2), ("aarch64-darwin", 4))


def facet_entry(row, handles, teams):
    """Make row's entry in facets.json.

    Args:
        row: The row.
        handles: {maintainer handle: index}, filled in as rows are added.
        teams: {team: index}, filled in the same way.

    Returns:
        The bits of the platforms the row is available on (FACET_SYSTEMS),
        when it has no maintainers or teams. Otherwise [bits, [maintainers'
        indexes]], with [teams' indexes] third when it has teams. Most rows
        have neither, so most entries are one number: all of nixpkgs takes
        about 120 KB compressed (2026-10-22).
    """
    bits = sum(
        bit
        for system, bit in FACET_SYSTEMS
        if available_on(row.get("platforms"), system)
    )
    people = [handles.setdefault(h, len(handles)) for h in row.get("maintainers") or []]
    groups = [teams.setdefault(t, len(teams)) for t in row.get("teams") or []]
    if groups:
        return [bits, people, groups]
    return [bits, people] if people else bits


def numbers(rows):
    """Count the overview's "nixpkgs in numbers" (with every package).

    How long packages have been outdated isn't among them: outdatedSince
    only goes back to when nixkeeper began watching every package
    (2026-10-04), so a median of it would measure nixkeeper's age.

    Returns:
        "builds": Hydra's builds of every row, those not built left out.
        "failing", "blocked", "unfinished": of those, the builds that
        failed themselves, whose dependency failed, and that timed out or
        were aborted (the counts' failingBuilds, by kind).
        "behind": update PRs behind upstream (prs_digest.cross_check).
        "unmaintained": packages outside the sets with no maintainer.
    """
    builds = failing = blocked = unfinished = behind = unmaintained = 0
    for row in rows:
        for b in row.get("builds") or []:
            if b["status"] != "notBuilt":
                builds += 1
                failing += b["status"] == "failed"
                blocked += b["status"] == "dependency"
                unfinished += b["status"] == "unfinished"
        if ((row.get("openPR") or {}).get("facts") or {}).get("behind"):
            behind += 1
        if not row.get("set") and row.get("maintainers") == []:
            unmaintained += 1
    return {
        "builds": builds,
        "failing": failing,
        "blocked": blocked,
        "unfinished": unfinished,
        "behind": behind,
        "unmaintained": unmaintained,
    }


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
    found = {}

    def put(path, row):
        found.setdefault(path, []).append(row)

    counts = dict.fromkeys(
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
    teams, lists, sets = {}, {}, {}
    failing_on = {}  # {"linux", "darwin" or a system: packages failing there}
    names = []
    # facets.json's rows, in the same order as names (facet_entry).
    facet_rows, facet_handles, facet_teams = [], {}, {}
    maintainers = {}  # {lowercase handle: [handle, packages, outdated, failing]}
    # Since when each fully checked row has been failing, outdated, or
    # failing its update attempts: the overview's newest and oldest of each.
    ages = {"failing": [], "outdated": [], "updateFailing": []}
    # The dependencies that stop other packages' builds, counted over every
    # row (sets included, as zh.fail counts them): {name: [whether it has a
    # row, {packages}, builds]}.
    blockers = {}
    # The same on staging-next (branches.apply_staging_next_blocked): what
    # its failing dependencies stop, of the packages that build on master.
    staging_blockers, staging_blocked, staging_info = {}, 0, {}
    for row in rows:
        letter = status(row)
        if sn := row.get("stagingNextBlockedBy"):
            staging_blocked += 1
            staging_info = {k: sn[k] for k in ("eval", "evaluatedAt") if k in sn}
            for b in sn["builds"]:
                for blocker in b["by"]:
                    stops = staging_blockers.setdefault(
                        blocker["name"], [bool(blocker.get("row")), set(), 0]
                    )
                    stops[1].add(row["name"])
                    stops[2] += 1
        for b in row.get("builds") or []:
            if b["status"] != "dependency":
                continue
            if found.get("views/blocked.json", [None])[-1] is not row:
                put("views/blocked.json", row)
            for blocker in b.get("blockedBy") or []:
                stops = blockers.setdefault(
                    blocker["name"], [bool(blocker.get("row")), set(), 0]
                )
                stops[1].add(row["name"])
                stops[2] += 1
        # Hydra jobs that didn't succeed, on every platform and of every row
        # (sets included): failing builds as zh.fail counts them.
        counts["failingBuilds"] += sum(
            b["status"] in FAILING_BUILDS for b in row.get("builds") or []
        )
        names.append(
            [row["name"], letter, row["set"]]
            if row.get("set")
            else [row["name"], letter]
        )
        facet_rows.append(facet_entry(row, facet_handles, facet_teams))
        for handle in row.get("maintainers") or []:
            put(f"views/maintainer/{handle.lower()}.json", row)
            mine = maintainers.setdefault(handle.lower(), [handle, 0, 0, 0])
            mine[1] += 1
            if not row.get("set"):
                mine[2] += is_outdated(row)
                mine[3] += letter.startswith("f")
        for team in row.get("teams") or []:
            put(f"views/team/{slug(team)}.json", row)
            teams[team] = teams.get(team, 0) + 1
        for name in row.get("lists") or []:
            put(f"views/list/{slug(name)}.json", row)
            lists[name] = lists.get(name, 0) + 1
        # An open update PR that nixpkgs is already past
        # (prs_digest.mark_superseded): every such row, sets included, up
        # to date or not.
        if row.get("supersededPRs"):
            put("views/superseded.json", row)
        if row.get("set"):
            put(f"views/set/{row['set']}.json", row)
            found_set = sets.setdefault(
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
                    found_set["archivedUnmarked"] = (
                        found_set.get("archivedUnmarked", 0) + 1
                    )
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
            # (failing, then broken, then outdated), so its parts never
            # overlap.
            if failed:
                found_set["bar"]["failed"] += 1
            elif broken:
                found_set["bar"]["broken"] += 1
            elif is_outdated(row):
                found_set["bar"]["outdated"] += 1
            counts["inSets"] += 1
            continue
        if row.get("maintainers") == []:
            put("views/maintainer/none.json", row)
        counts["tracked"] += 1
        counts["failed"] += letter.startswith("f")
        counts["waiting"] += letter.startswith("m")
        counts["outdated"] += is_outdated(row)
        counts["vulnerable"] += letter.endswith("v")
        if row.get("backport"):
            counts["backport"] += 1
            put("views/backport.json", row)
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
            failing_on[where] = failing_on.get(where, 0) + 1
        # Only rows that count now are listed. The hourly checks recount,
        # but only the daily sync sets and clears these dates, so after a
        # change in how nixkeeper counts, the lists would otherwise disagree
        # with the cards for a day.
        now_counts = {
            "failing": bool(failed_builds(row)),
            "outdated": is_outdated(row),
            "updateFailing": bool(row.get("updateFailure")),
        }
        for kind, field in AGES.items():
            # An update already merged and waiting for the channel needs no
            # action, so it's left out of the list (but not the card's count).
            if kind == "outdated" and waiting_for_channel(row):
                continue
            if row.get(field) and now_counts[kind]:
                ages[kind].append((row[field], row["name"], letter, row.get("family")))
        if row.get("markedBroken") or broken_builds(row):
            counts["broken"] += 1
            put("views/broken.json", row)
        if unbuilt_where(row):
            put("views/unbuilt.json", row)
        # A fix to backport is for the maintainer to do too, even when
        # nixos-unstable is fine (the list's tile: Fixes to backport).
        if letter[0] in "fmo" or letter.endswith("v") or row.get("backport"):
            put("views/attention.json", row)
    for path, members in found.items():
        out[path] = {"packages": [summary_entry(row) for row in members]}
    out["names.json"] = {"names": names}
    out["facets.json"] = {
        "handles": list(facet_handles),
        "teams": list(facet_teams),
        "rows": facet_rows,
    }
    out["maintainers.json"] = {
        "maintainers": [maintainers[key] for key in sorted(maintainers)]
    }
    # Why things fail across packages (causes.py): failed builds grouped by
    # their error, each group a view of its packages.
    groups = causes.build_groups(rows)
    for group in groups:
        out[f"views/cause/{group['key']}.json"] = {
            "packages": [summary_entry(row) for row in group["rows"]],
            **{k: v for k, v in group.items() if k != "rows"},
        }
    # Every group, for the overview's card when it's expanded (loaded only
    # then).
    if groups:
        out["views/causes.json"] = {
            "groups": [{k: v for k, v in g.items() if k != "rows"} for g in groups]
        }
    top = sorted(blockers.items(), key=lambda kv: (-len(kv[1][1]), -kv[1][2], kv[0]))
    staging_top = sorted(
        staging_blockers.items(), key=lambda kv: (-len(kv[1][1]), -kv[1][2], kv[0])
    )
    return {
        "counts": {**counts, "buildFailuresOn": dict(sorted(failing_on.items()))},
        # The lists' counts are the cards'. A row counted before the daily
        # sync gives it a date is in the count, but not in the lists.
        "highlights": {
            kind: {**highlights(found), "count": counts[HIGHLIGHT_COUNTS[kind]]}
            for kind, found in ages.items()
        },
        # The overview's "Blocking the most": how many dependencies stop
        # other packages' builds, how many packages have a build stopped
        # (the blocked view's size, whether its blockers are known yet or
        # not), and the HIGHLIGHTS that stop the most, each [name, whether
        # it has a row, packages, builds].
        "blockers": {
            "count": len(blockers),
            "packages": len(found.get("views/blocked.json", [])),
            "top": [
                [name, is_row, len(names), builds]
                for name, (is_row, names, builds) in top[:HIGHLIGHTS]
            ],
            # The same on staging-next, before it's merged into master: how
            # many packages its failing dependencies stop there, the ones
            # that stop the most, and which evaluation this is.
            **(
                {
                    "stagingNext": {
                        **staging_info,
                        "count": len(staging_blockers),
                        "packages": staging_blocked,
                        "top": [
                            [name, is_row, len(names), builds]
                            for name, (is_row, names, builds) in staging_top[
                                :HIGHLIGHTS
                            ]
                        ],
                    }
                }
                if staging_blockers
                else {}
            ),
        },
        # The overview's "Why things fail": the biggest groups of failed
        # builds sharing an error (causes.SHOWN of them, each {"key",
        # "count", "reason", "signature", "line", "title"?, "about"?}), how
        # many groups and packages there are in all, and the update bot's
        # failures by cause.
        "causes": {
            "builds": [
                {k: v for k, v in group.items() if k != "rows"}
                for group in groups[: causes.SHOWN]
            ],
            "groups": len(groups),
            "packages": len({row["name"] for g in groups for row in g["rows"]}),
            "bot": causes.bot_causes(rows),
        },
        "views": {
            "attention": len(found.get("views/attention.json", [])),
            "broken": len(found.get("views/broken.json", [])),
            "blocked": len(found.get("views/blocked.json", [])),
            "backport": len(found.get("views/backport.json", [])),
            "unbuilt": len(found.get("views/unbuilt.json", [])),
            "superseded": len(found.get("views/superseded.json", [])),
            # Sorted with capitals first, as Python sorts strings; the page
            # sorts them its own way.
            "teams": dict(sorted(teams.items())),
            "lists": dict(sorted(lists.items())),
            "sets": dict(sorted(sets.items())),
        },
    }


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
        print(f"Data shape: the check itself failed at {where}: {e!r}", file=sys.stderr)


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
        _write_file(os.path.join(tmp_dir, name), dumps(data))
    for name, data in (kept or {}).items():
        if data is not None:
            _write_file(os.path.join(tmp_dir, name), dumps(data))
    _swap_in(tmp_dir, out_dir)


def _swap_in(new_dir, out_dir):
    """Replace the data folder with a new one.

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

    Only to be called with the data folder's lock held (lock.held calls it):
    it moves folders, and another run in the middle of _swap_in would then
    see them change under it.

    A run that died between _swap_in's two renames leaves no data folder
    and the last data in <out_dir>.old: that data is moved back, so the run
    that follows reads it as the previous run's. A run that died after
    both renames leaves the data folder and a stale <out_dir>.old: the old
    folder is removed.

    Args:
        out_dir: The data folder (the configured one by default).
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
        text = dumps(data)
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


def _load(path):
    """Read a JSON file."""
    with open(path) as f:
        return json.load(f)


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
    return _load(path)


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
        index = _load(os.path.join(out_dir, "index.json"))
    except (OSError, ValueError):
        return {"packages": []}
    if index.get("format") == FORMAT:
        # The rows come from the shards. If one can't be read, the rows in
        # index.json are kept (data from 0.12.0 has them, written beside
        # format 1), else there are none.
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            index["packages"] = sorted(
                (
                    {k: v for k, v in row.items() if k != "repology"}
                    for n in range(index["shardCount"])
                    for row in _load(os.path.join(out_dir, f"rows/{n}.json"))[
                        "packages"
                    ]
                ),
                key=lambda row: row["name"],
            )
    index.setdefault("packages", [])
    for row in index["packages"]:
        restored(row, index.get("checkedAt"))
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
        index = _load(os.path.join(out_dir, "index.json"))
        if index.get("format") != FORMAT:
            return {}
        return {
            full["name"]: full.get("repology") or []
            for n in range(index["shardCount"])
            for full in _load(os.path.join(out_dir, f"rows/{n}.json"))["packages"]
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
        if index.get("format") == FORMAT:
            n = shard_of(row["name"], index["shardCount"])
            for full in _shared(os.path.join(out_dir, f"rows/{n}.json"))["packages"]:
                if full["name"] == row["name"]:
                    return copy.deepcopy(full.get("repology") or [])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    path = os.path.join(out_dir, row.get("dataFile") or f"{row['project']}.json")
    with open(path) as f:
        return json.load(f)
