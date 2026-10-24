"""Reading and writing data/, the page's data. Everything that reads the
previous run (history, schedules, notifications, the hourly checks) or
writes a new one goes through here.

The data's format (docs/data.md), format 2: index.json as a small manifest
(format, counts), summary.json with a short entry per row (what the page's
list needs), and the full rows in rows/<n>.json shards (n from a hash of the
name), each row with its Repology entries ("repology").

Format 1 (0.11.0 and before; written beside format 2 until 0.13.0) is still
read, so a sync after upgrading from it keeps the last run's data: index.json
with every row in full ("packages"), and each Repology project's entries in
<dataFile>."""

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
from .naming import SHARD_FILE, shard_of, slug
from .sources import vulnerabilities_digest
from .sources.nixpkgs import available_on

FORMAT = 2
# Rows a shard holds, about: a shard is what a details panel loads.
SHARD_ROWS = 500
# A row's fields only the details panels use, left out of its summary entry.
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
# Of a summary entry's update check, what the list shows (the version,
# whether it's newer, whose check it is).
UPSTREAM_SHOWN = ("community", "inferred", "newer", "version")


def data_file(key):
    """File name for a project's Repology data: names like python:requests
    contain characters that don't belong in file names or URLs."""
    return re.sub(r"[^A-Za-z0-9._+-]", "_", key) + ".json"


def dumps(data):
    """data as compact JSON (no indentation), keys sorted: about a third
    smaller than indented, and the same bytes whenever the data is the same."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def shard_count(rows):
    """How many shards for rows: about SHARD_ROWS a shard, rounded up to a
    power of two (1 for a few hundred, 256 for all of nixpkgs)."""
    return 1 << max(0, math.ceil(math.log2(max(1, rows / SHARD_ROWS))))


def elided(row, run):
    """row as written: its stamps from this run (each build's and its update
    check's "checkedAt", its "countedAt") left out when they're run, the
    index's checkedAt, so a row nothing new happened to keeps its bytes from
    run to run. restored() puts them back."""
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
    """row as elided() wrote it, with its stamps back: each is always there
    when what it dates is (every build and update check has one, and counts
    have theirs), so a missing one was run's."""
    if not run:
        return row
    for build in row.get("builds") or []:
        build.setdefault("checkedAt", run)
    if row.get("upstream"):
        row["upstream"].setdefault("checkedAt", run)
    if "openPRs" in row:
        row.setdefault("countedAt", run)
    return row


# Repology statuses whose versions can't be compared: sorted after the rest
# (comparedRepos in page/logic.js).
UNCOMPARABLE = {"rolling", "ignored", "incorrect", "noscheme", "untrusted"}


def newest_repos(entries, count):
    """Of entries, nixpkgs' own and the newest entry of the newest count other
    repositories, as the details panel orders them (comparedRepos in
    page/logic.js): comparable versions first, newest first."""
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
    """A key that sorts in reverse (newest version first)."""

    def __init__(self, key):
        self.key = key

    def __lt__(self, other):
        return other.key < self.key

    def __eq__(self, other):
        return self.key == other.key


def kept_entries(projects, rows):
    """{dataFile: Repology entries} to write for projects (lookup's) and the
    rows made from them: in full for a project with a row on the lists; for
    the others (with every package, the rest of nixpkgs), only nixpkgs' own
    and those of the newest REPOLOGY_ENTRIES_KEPT other repositories, what
    their details show (the rest are on Repology)."""
    listed = {row["dataFile"] for row in rows if row.get("lists")}
    return {
        p["dataFile"]: p["entries"]
        if p["dataFile"] in listed
        else newest_repos(p["entries"], config.REPOLOGY_ENTRIES_KEPT)
        for p in projects.values()
    }


def summary_entry(row):
    """row's entry in summary.json: what the list, the counts, filters,
    search and sorting need. Builds are reduced to their status and
    platform, the update attempt to its outcome (and why it failed)."""
    entry = {k: v for k, v in row.items() if k not in PANEL_ONLY}
    if (row.get("openPR") or {}).get("facts"):
        # What nixkeeper-prs found of it: the panel's only.
        entry["openPR"] = {k: v for k, v in row["openPR"].items() if k != "facts"}
    if "vulnerabilities" in row:
        # The verdict, worked out once (null: none counted, Repology's
        # flag not used either).
        entry["vuln"] = vulnerabilities_digest.summary(row)
    if "builds" in row:
        entry["builds"] = [
            {"status": b["status"], "system": b["system"]}
            | ({"blockedBy": b["blockedBy"]} if b.get("blockedBy") else {})
            # Why it failed (the list's filter); its lines, the panel's only.
            | ({"failedBecause": b["failedBecause"]} if b.get("failedBecause") else {})
            for b in row["builds"]
        ]
    if row.get("update"):  # null (never tried) and missing (not in nixpkgs) kept
        entry["update"] = {"outcome": row["update"].get("outcome")}
        if because := row["update"].get("failedBecause"):
            entry["update"]["failedBecause"] = because  # the list says why
    if "upstream" in row:
        entry["upstream"] = {
            k: v for k, v in row["upstream"].items() if k in UPSTREAM_SHOWN
        }
    # The bot's queue, for the list's robot: the versions it would update to,
    # whether it runs the package's updateScript, and the day it's expected
    # to try ("by": the list's "auto update in 4 days"; the row has the
    # candidates' sources too).
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


# Days of counts history.json keeps (with every package).
HISTORY_DAYS = 365


def files(index, entries, history=None, fixed=None, events=None):
    """Every file of data/ for index (its rows in "packages") and entries
    (Repology's, by dataFile, put in the rows' shards): {path in data/:
    data}. history: with every
    package, the last run's history.json points (read_history), to which
    this run's counts are added; fixed, the fixes it keeps (read_fixed, with
    this run's: with_fixed); events, what marks the trends (with_events);
    None leaves history.json out (a partial run keeps the one on disk, and
    the manifest its "fixed")."""
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
    del manifest["packages"]  # in the shards
    out = {}
    if index.get("allPackages"):
        # Every package: no summary of them all (too big to load), but views
        # of it, a name index and the counts (views).
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
    """history with the previous run's split counts (SPLIT_COUNTS) on its
    day's point, where that point doesn't have them: the counts were
    recorded combined before, and the previous manifest still has them
    apart (buildFailures: its builds that failed, as the overview's
    newest and longest-standing count them, in older manifests)."""
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
    """history (a list of {"day", counts...}, oldest first) with this run's
    counts of the fully checked rows as the day's point (a second sync the
    same day replaces the first), the last HISTORY_DAYS days."""
    day = (run or "")[:10]
    point = {"day": day, **{k: counts[k] for k in HISTORY_COUNTS}}
    kept = [p for p in history if p.get("day") != day]
    return sorted([*kept, point], key=lambda p: p["day"])[-HISTORY_DAYS:]


# Hydra statuses of a build that didn't succeed: counted as failing builds
# (the manifest's failingBuilds), as zh.fail does; only "failed" makes a
# package fail on the page.
FAILING_BUILDS = {"failed", "dependency", "unfinished"}
# What history.json records each day: the fully checked rows' counts.
HISTORY_COUNTS = (
    "tracked",
    "outdated",
    "failed",
    "buildFailures",
    "updateFailures",
    "vulnerable",
    "broken",
)
# Counts a point didn't have before (the failing ones split, 0.13.0): the
# previous manifest's, for its own day's point (with_split).
SPLIT_COUNTS = ("buildFailures", "updateFailures")


# Days of fixes history.json keeps; days the overview counts them over.
FIXED_DAYS = 30
FIXED_RECENT_DAYS = 7


def read_fixed(out_dir=None):
    """The fixes the last run's history.json keeps, or []."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    try:
        return _load(os.path.join(out_dir, "history.json")).get("fixed") or []
    except (OSError, ValueError, AttributeError):
        return []


def with_fixed(fixed, new, run):
    """fixed (oldest first) with this run's new ones, the last FIXED_DAYS
    days: the same package's same kind of fix once a day (a second sync the
    same day finds it again)."""
    cutoff = _day_before(run, FIXED_DAYS)
    seen, kept = set(), []
    for fix in [*fixed, *new]:
        key = (fix["at"][:10], fix["name"], fix["kind"])
        if fix["at"][:10] > cutoff and key not in seen:
            seen.add(key)
            kept.append(fix)
    return sorted(kept, key=lambda f: (f["at"], f["name"], f["kind"]))


def fixed_summary(fixed, run):
    """The manifest's "fixed": per kind, how many in the last
    FIXED_RECENT_DAYS days and HIGHLIGHTS of them ("newest", as it was
    named when they were): the ones that had lasted longest first (the
    newest are all the last sync's, with a hundred fixes a day), then those
    that don't say since when, the newest first. Each [name, at, from, to]
    (from and to for updates, else null); a fifth, its credit ({"pr",
    "author"?, "mergedBy"?, "likely"?}: history.credit) or null, and a
    sixth, since when it had been failing or outdated, when it has them."""
    cutoff = _day_before(run, FIXED_RECENT_DAYS)
    out = {}
    for kind in ("build", "update", "bot"):
        mine = [f for f in fixed if f["kind"] == kind and f["at"][:10] > cutoff]
        # Newest first, ties by name (a family's first by name stands for it).
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
    """How many seconds fix's problem had lasted when it was fixed; -1 when
    it doesn't say since when."""
    try:
        since = datetime.fromisoformat(fix["since"])
        if since.tzinfo is None:  # a plain day
            since = since.replace(tzinfo=UTC)
        return max(0, (datetime.fromisoformat(fix["at"]) - since).total_seconds())
    except (KeyError, TypeError, ValueError):
        return -1


def _fixed_entry(fix, members=None):
    """A fix as the manifest lists it (fixed_summary), without trailing
    nulls; a seventh, its family's (family_entry), when its family's other
    members were fixed with it."""
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
    """The day (YYYY-MM-DD) days before run's."""
    day = datetime.fromisoformat((run or "1970-01-01")[:10])
    return (day - timedelta(days=days)).date().isoformat()


def read_events(out_dir=None):
    """The trend markers the last run's history.json keeps, or []."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    try:
        return _load(os.path.join(out_dir, "history.json")).get("events") or []
    except (OSError, ValueError, AttributeError):
        return []


def with_events(events, new, run):
    """events with this run's new ones, each once (a staging-next merge by its
    PR, a nixkeeper update by its version, a counting change by its text),
    the last HISTORY_DAYS days,
    oldest first. What marks the trends: a staging-next merge (mass
    rebuilds: failing builds jump for days after), nixkeeper's own updates,
    and changes in how it counts (config.COUNTING_CHANGES)."""
    cutoff = _day_before(run, HISTORY_DAYS)
    kept = {}
    for event in [*events, *new]:
        key = (
            event["kind"],
            event.get("pr") or event.get("version") or event.get("text"),
        )
        if event["day"] > cutoff:
            kept[key] = event  # the newest word on it
    return sorted(kept.values(), key=lambda e: (e["day"], e["kind"]))


def read_history(out_dir=None):
    """The last run's history.json points, or [] if there are none."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    try:
        return _load(os.path.join(out_dir, "history.json")).get("points") or []
    except (OSError, ValueError, AttributeError):
        return []


# The overview's lists (views' highlights), from each row's date.
AGES = {
    "failing": "failingSince",
    "outdated": "outdatedSince",
    "updateFailing": "updateFailingSince",
}
# The card each highlight list goes with: its count is the card's.
HIGHLIGHT_COUNTS = {
    "failing": "buildFailures",
    "outdated": "outdated",
    "updateFailing": "updateFailures",
}
# How many of each the overview shows, newest and oldest.
HIGHLIGHTS = 8


def grouped(items, family, name):
    """items (already in their order) with each family's members after its
    first left out: [(item, members' names)], the names only for a family's
    first (rows.add_families). One update that moves 187 packages is one
    entry, not the whole list."""
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
    """What a list entry says of its family: {"more": the others' count,
    "label": what they're called together, when they share a start}."""
    found = {"more": len(members) - 1}
    if label := rows_module.family_label(members):
        found["label"] = label
    return found


def highlights(found):
    """{"count", "newest", "oldest"} of (since, name, status, family) found:
    how many there are, and the HIGHLIGHTS most recent and longest-standing,
    each [name, since, status] (ties by name), and a fourth when its family
    moves with it ({"more", "label"?}: family_entry), the family's other
    members left out of the list."""

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
    """Whether row's "newest" was compared with nothing: Repology's unique
    (no other repository has a newer version) when no repository outside
    nixpkgs has it at all, and no update check or feed of nixkeeper's own
    knows its releases (python313Packages.pbar2, ~21,300 rows on
    2026-10-23). Not up to date then: not compared (computeStatus)."""
    return (
        row.get("nixStatus") == "unique"
        and bool(row.get("onlyNixpkgs"))
        and not row.get("upstream")
        and not row.get("feed")
    )


def status(row):
    """A row's status as the page's dot shows it (computeStatus and
    hasFailure in page/logic.js), in a letter: f failed, m outdated but
    waiting for the channel, o outdated, u up to date, n not comparable
    (Repology can't say, or doesn't know the package); then v when
    vulnerable (flagged by Repology, or marked insecure by nixpkgs)."""
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


# The systems unbuilt_where looks at: each Linux system apart, Darwin as one.
UNBUILT_KEYS = ("x86_64-linux", "aarch64-linux", "darwin")


def _on_platform(row, key):
    """Whether row is listed for key, a family or a system (the page's
    onPlatform): no restriction ("platforms": null) counts as every one."""
    platforms = row.get("platforms", {})
    if platforms is None:
        return True
    family = key.split("-")[-1]
    if not platforms.get(family):
        return False
    systems = platforms.get("systems")
    return key == family or not systems or key in systems


def _on_system(system, key):
    return system == key if "-" in key else system.endswith("-" + key)


def unbuilt_where(row):
    """The systems row is listed for but Hydra doesn't build it on (the
    page's unbuiltWhere, the struck platform tags): none of its builds there
    exists ("notBuilt", usually as a dependency isn't available there), while
    Hydra builds it elsewhere. [] when Hydra builds it everywhere listed, or
    nowhere (unfree, kept off it)."""
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


# A row's platforms in facets.json, as bits: where it's available
# (sources.nixpkgs.available_on), all three when nixpkgs doesn't restrict it.
FACET_SYSTEMS = (("x86_64-linux", 1), ("aarch64-linux", 2), ("aarch64-darwin", 4))


def facet_entry(row, handles, teams):
    """row's entry in facets.json: its platforms' bits (FACET_SYSTEMS), and
    when it has maintainers or teams, [bits, [maintainers], [teams]?] by
    their place in handles and teams (dicts filled as it goes: {name:
    index}). Most rows have neither, so most entries are one number: all of
    nixpkgs in about 120 KB compressed (2026-10-22)."""
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
    """The overview's "nixpkgs in numbers" (with every package), of what the
    sync has: Hydra's builds of every row ("builds") and of those not built,
    the counts' failingBuilds, each kind: its own failure ("failing"), a
    dependency's ("blocked"), timed out or aborted ("unfinished"); update
    PRs behind upstream ("behind": prs_digest's
    cross_check) and packages outside the sets with no maintainer
    ("unmaintained"). Not how long packages have been outdated:
    outdatedSince only goes back to when nixkeeper began watching every
    package (2026-10-04), so a median of it says nixkeeper's age."""
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
    """With every package: the views the page starts from instead of a
    summary of every row (each {"packages": [summary entries]}, sorted by
    name), added to out, and what the manifest says of them:
      views/attention.json: failing, outdated, flagged vulnerable or with a
        fix to backport (not in a set updated in bulk: those count on their
        set's line)
      views/broken.json: marked broken in nixpkgs (not in such a set)
      views/backport.json: a CVE fixed on nixpkgs master, still affected on
        the newest release branch (backport; not in such a set)
      views/blocked.json: a build of it not tried, as a dependency failed
        (in such sets too, as the overview's blockers count them)
      views/unbuilt.json: listed for a platform Hydra doesn't build it on
        (unbuilt_where; not in such a set)
      views/superseded.json: an open update PR nixpkgs is already past
        (supersededPRs: prs_digest.mark_superseded), in such sets too
      views/maintainer/<handle>.json: a maintainer's (lowercase handle),
        and none.json those with no maintainer (not in such a set)
      views/team/<slug>.json, views/list/<slug>.json, views/set/<name>.json
      names.json: every row's name and status (status), and its set when
        it has one: what a search looks through
      facets.json: the same rows' maintainers, teams and platforms, in the
        same order (facet_entry), for the search's filters
      maintainers.json: every maintainer, as nixpkgs writes the handle,
        with how many packages they have (in such sets too) and how many
        of the fully checked are outdated and failing: [handle, packages,
        outdated, failing], by handle (any case)
    Returns {"counts": {...}, "views": {"attention", "teams", "lists":
    {name: count}, "sets": {name: {"packages", "outdated", "failed",
    "broken"}}}}."""
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
    failing_on = {}  # "linux", "darwin", each system -> packages failing there
    names = []
    # facets.json: beside names, in its order (facet_entry).
    facet_rows, facet_handles, facet_teams = [], {}, {}
    maintainers = {}  # lowercase handle -> [handle, packages, outdated, failing]
    # Since when each fully checked row has been failing, outdated, failing
    # its update attempts: the overview's newest and oldest of each.
    ages = {"failing": [], "outdated": [], "updateFailing": []}
    # Which dependencies stop the most packages' builds (of every row, those
    # in sets too, as zh.fail counts them): {name: [row?, {packages}, builds]}.
    blockers = {}
    # The same on staging-next (branches.apply_staging_next_blocked): what
    # its failing dependencies stop, of packages that build on master.
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
        # Hydra jobs that didn't build, on every platform, of every row
        # (in sets too): failing builds as zh.fail counts them.
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
        # An open update PR nixpkgs is already past (prs_digest
        # .mark_superseded): every one, in sets too, up to date or not.
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
                # No longer on CRAN or in Bioconductor (sources/cran_digest.py);
                # most nixpkgs marks broken already: those it doesn't apart.
                found_set["archived"] = found_set.get("archived", 0) + 1
                if not (row.get("markedBroken") or broken_builds(row)):
                    found_set["archivedUnmarked"] = (
                        found_set.get("archivedUnmarked", 0) + 1
                    )
            found_set["packages"] += 1
            found_set["outdated"] += is_outdated(row)
            if on_branch(row):
                # Of those, already updated on the branch (haskell-updates).
                found_set["onBranch"] = found_set.get("onBranch", 0) + 1
            failed = letter.startswith("f")
            broken = bool(row.get("markedBroken") or broken_builds(row))
            found_set["failed"] += failed
            found_set["broken"] += broken
            # The overview's bar: each package once, at its worst (failing,
            # then broken, then outdated), so its parts never overlap.
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
        # The same by where they fail: each Hydra system, and Linux and
        # Darwin (a package failing on both Linux systems counted once), as
        # the page's platform filter counts them: only where the package is
        # available (not ete's aarch64-darwin, built by ete-unwrapped).
        systems = {
            b["system"]
            for b in failed_builds(row)
            if available_on(row.get("platforms"), b["system"])
        }
        for where in systems | {s.rsplit("-", 1)[-1] for s in systems}:
            failing_on[where] = failing_on.get(where, 0) + 1
        # Only what counts now: the hourly checks recount, but only the daily
        # sync sets and drops these dates, so a change in how nixkeeper counts
        # would otherwise leave the lists apart from the cards for a day.
        now_counts = {
            "failing": bool(failed_builds(row)),
            "outdated": is_outdated(row),
            "updateFailing": bool(row.get("updateFailure")),
        }
        for kind, field in AGES.items():
            # Not an update already merged, waiting for the channel: nothing
            # to do about it (it stays in the card's count).
            if kind == "outdated" and waiting_for_channel(row):
                continue
            if row.get(field) and now_counts[kind]:
                ages[kind].append((row[field], row["name"], letter, row.get("family")))
        if row.get("markedBroken") or broken_builds(row):
            counts["broken"] += 1
            put("views/broken.json", row)
        if unbuilt_where(row):
            put("views/unbuilt.json", row)
        # A fix to backport is the maintainer's to do too, even with
        # nixos-unstable fine (its list tile: Fixes to backport).
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
    # Why things fail, across packages (causes.py): failed builds grouped by
    # the same error, each a view of its packages; the bot's failures by
    # cause.
    groups = causes.build_groups(rows)
    for group in groups:
        out[f"views/cause/{group['key']}.json"] = {
            "packages": [summary_entry(row) for row in group["rows"]],
            **{k: v for k, v in group.items() if k != "rows"},
        }
    # Every group, for the overview's card shown in full (loaded on asking).
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
        # Their counts are the cards' (one counted with no date yet, until the
        # daily sync gives it one, is in the count, not the lists).
        "highlights": {
            kind: {**highlights(found), "count": counts[HIGHLIGHT_COUNTS[kind]]}
            for kind, found in ages.items()
        },
        # The overview's "Blocking the most": how many dependencies stop
        # others' builds, how many packages have a build stopped (the
        # blocked view's: its blockers read or not yet), and the HIGHLIGHTS
        # that stop the most, [name, row?, packages, builds].
        "blockers": {
            "count": len(blockers),
            "packages": len(found.get("views/blocked.json", [])),
            "top": [
                [name, is_row, len(names), builds]
                for name, (is_row, names, builds) in top[:HIGHLIGHTS]
            ],
            # And on staging-next, before its merge into master: how many
            # packages its failing dependencies stop there, the ones
            # stopping the most, and which evaluation.
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
        # The overview's "Why things fail": the biggest groups of failed builds
        # sharing an error (causes.SHOWN; each {"key", "count", "reason",
        # "signature", "line", "title"?, "about"?}), how many groups and
        # packages in all, and the bot's failures by cause.
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
            # (In the file, by name with capitals first, as its keys sort: the
            # page sorts them its way.)
            "teams": dict(sorted(teams.items())),
            "lists": dict(sorted(lists.items())),
            "sets": dict(sorted(sets.items())),
        },
    }


def _write_file(path, text):
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
    """
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    tmp_dir = out_dir + ".tmp"
    restore_interrupted_swap(out_dir)  # its caller holds the lock
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
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
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
    one half-written. Shards past the new shard count, left from a run
    with more rows, are removed.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        out_dir: The data folder (the configured one by default).
    """
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    restore_interrupted_swap(out_dir)  # its caller holds the lock
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
    _remove_extra_shards(out_dir, written["index.json"]["shardCount"])


def _remove_extra_shards(out_dir, count):
    """Remove the shard files numbered count or more.

    Readers only open the shards the manifest's shardCount says, so those
    are never read; removing them keeps the folder as a full write leaves
    it.

    Args:
        out_dir: The data folder.
        count: The number of shards the data now has.
    """
    rows_dir = os.path.join(out_dir, "rows")
    for name in os.listdir(rows_dir) if os.path.isdir(rows_dir) else []:
        # SHARD_FILE matches a shard's path in data/, as the checks see it.
        shard = SHARD_FILE.fullmatch(f"rows/{name}")
        if shard and int(shard.group(1)) >= count:
            os.remove(os.path.join(rows_dir, name))


def _load(path):
    with open(path) as f:
        return json.load(f)


@functools.lru_cache(maxsize=64)
def _cached(path, changed):
    """A data file's JSON, read once while it's unchanged (changed: its
    modification time): entries() reads a shard for each of its rows."""
    return _load(path)


def _shared(path):
    """A data file's JSON from the cache: not to be changed."""
    return _cached(path, os.stat(path).st_mtime_ns)


def load(out_dir=None):
    """The last run's index, with every row in "packages" (without their
    Repology entries: entries()), whichever format it was written in; an
    empty one if there's none or it can't be read."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
    try:
        index = _load(os.path.join(out_dir, "index.json"))
    except (OSError, ValueError):
        return {"packages": []}
    if index.get("format") == FORMAT:
        # The rows from the shards; if one can't be read, index.json's (in
        # data from 0.12.0, written beside format 1), else none.
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
    """Every row's Repology entries from the last run, {name: entries}, each
    shard read once (format 2); {} for format 1 or if one can't be read
    (entries() then reads each row's own file). For the hourly checks, which
    write every shard again: entries() a row at a time would read a shard
    per row, about 126,000 shard reads with every package."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
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
    """row's Repology entries from the last run: from its shard (format 2),
    else its data file (format 1, from 0.11.0 and before). Raises OSError or
    ValueError when neither can be read."""
    out_dir = out_dir or config.OUT_DIR  # the setting now, not at import
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
