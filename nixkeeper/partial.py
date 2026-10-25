"""Shared by the hourly checks (frequent.py, prcheck.py): each starts from the
last published data, changes a few rows, and publishes only if something
changed. Most hours nothing does, so nothing is written, committed or posted."""

import copy
import sys

from . import config, datastore, history, notify


def load():
    """(the last published index, a copy of its rows to change). Exits if
    there's none: the daily sync has to have run once."""
    previous = history.load_previous_run()
    if not previous["packages"]:
        sys.exit(
            f"No previous run in {config.data_dir()}: run the full sync first "
            "(nixkeeper sync; from a checkout, nix run .#sync)."
        )
    return previous, copy.deepcopy(previous["packages"])


def meaningful(packages):
    """packages without what changes every run anyway (when an update check
    last succeeded and its rule's fingerprint, when Repology was asked), to
    tell whether anything worth publishing changed."""
    packages = copy.deepcopy(packages)
    for row in packages:
        (row.get("upstream") or {}).pop("checkedAt", None)
        (row.get("upstream") or {}).pop("rule", None)
        row.pop("repologyCheckedAt", None)
    return packages


def publish(previous, packages, now, data_files=None):
    """Write packages (and data_files: Repology entries by dataFile, for the
    rows refreshed) and notify, if anything changed.
    checkedAt stays the daily sync's: the page's staleness warning, and every
    source these checks don't touch, go by it. Returns whether it wrote."""
    if meaningful(packages) == meaningful(previous["packages"]):
        print("Nothing changed.", file=sys.stderr)
        return False
    # Every row's entries, for the shards: the last run's, or refreshed.
    saved = datastore.saved_entries()
    entries = {}
    for row in packages:
        if row.get("dataFile") and row["dataFile"] not in entries:
            if row["name"] in saved:
                entries[row["dataFile"]] = saved[row["name"]]
                continue
            try:
                entries[row["dataFile"]] = datastore.entries(row)
            except (OSError, ValueError):
                entries[row["dataFile"]] = []
    datastore.update(
        {**previous, "packages": packages}, {**entries, **(data_files or {})}
    )
    print("Changes written.", file=sys.stderr)
    # The instance's own issue: what changed for the lists' packages (with
    # every package, the lists' own only); the subscribers' (notifications/):
    # theirs among every row, and only theirs that newly need attention (the
    # daily sync rewrites them all).
    lists_only = previous.get("allPackages")
    notify.notify(
        {**previous, "packages": [r for r in previous["packages"] if r.get("lists")]}
        if lists_only
        else previous,
        [r for r in packages if r.get("lists")] if lists_only else packages,
        now,
        everyone=packages,
        everyone_before=previous,
        news_only=True,
    )
    return True
