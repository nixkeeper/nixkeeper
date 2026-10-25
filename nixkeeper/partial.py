"""Load and publish the data for the hourly checks.

The hourly checks (frequent.py, prcheck.py) each start from the last
published data, change a few rows, and publish only if something changed.
Most hours nothing does, so nothing is written, committed or posted.
"""

import copy

from . import config, datastore, history, log, notify, verdict
from .errors import Problem


def load():
    """Load the last published data, and a copy of its rows to change.

    Returns:
        (the last published index, a deep copy of its rows), or None when
        its rows can't be decided again (verdict.decidable): written by an
        older nixkeeper, they wait for a full sync with this one.

    Raises:
        Problem: There's no published data: the daily sync has to have
            run once.
    """
    previous = history.load_previous_run()
    if not previous["packages"]:
        raise Problem(
            f"No previous run in {config.data_dir()}: run the full sync first "
            "(nixkeeper sync; from a checkout, nix run .#sync)."
        )
    if not verdict.decidable(previous):
        log.notice(
            "The data was written by an older nixkeeper "
            f"({previous.get('version') or 'unknown'}), before its rows kept "
            "Repology's verdict: nothing is published until a full sync with "
            "this one."
        )
        return None
    return previous, copy.deepcopy(previous["packages"])


def meaningful(packages):
    """Return packages without what changes every run anyway.

    That's when an update check last succeeded and its rule's fingerprint,
    and when Repology was asked. What's left tells whether anything worth
    publishing changed.
    """
    packages = copy.deepcopy(packages)
    for row in packages:
        (row.get("upstream") or {}).pop("checkedAt", None)
        (row.get("upstream") or {}).pop("rule", None)
        row.pop("repologyCheckedAt", None)
    return packages


def publish(previous, packages, now, data_files=None):
    """Write the changed rows and notify, if anything changed.

    checkedAt stays the daily sync's: the page's staleness warning, and
    every source these checks don't touch, go by it.

    Args:
        previous: The last published index.
        packages: The rows, as changed.
        now: The run's time.
        data_files: Repology entries by dataFile, for the rows refreshed.

    Returns:
        Whether it wrote.
    """
    if meaningful(packages) == meaningful(previous["packages"]):
        log.info("Nothing changed.")
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
    log.info("Changes written.")
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
