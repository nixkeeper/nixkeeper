"""The rows' shards and the summary: what each row is written as.

Each row goes into a shard (rows/<n>.json) by a hash of its name, with its
Repology entries; the summary's entry (and each view's) is a short form of
it. A row's fields that only the last run's data has (elided) are put back
when it's read (restored). load_json and dumps read and write every file.
"""

import json
import math
import re

from .. import config
from ..sources import vulnerabilities_digest

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
    # Repology's own verdict, for the next run to decide from (verdict.py):
    # in the rows only.
    "repologyVerdict",
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
    from ..versions import version_key

    def order(e):
        """Rank an entry: comparable versions first, then the newest first."""
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
        """Hold the key to reverse."""
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


def load_json(path):
    """Read a JSON file."""
    with open(path) as f:
        return json.load(f)
