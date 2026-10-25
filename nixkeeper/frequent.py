"""Run the frequent update checks, about hourly.

The frequent checks are the update checks marked `frequent = true` in
package-lists/update-checks.nix, for packages where a new release matters
within hours (browsers, for their security fixes). This touches only those
packages: their Repology data (so the comparison uses nixpkgs' current
version) and their update check. Run it with `nixkeeper frequent-check`,
or `nix run .#frequent-check` from a checkout.
"""

import sys
import urllib.error
from datetime import UTC, datetime

from . import community, follows, history, partial, rows
from .changes import count_master
from .sources import nixpkgs as nixpkgs_source
from .sources import repology, upstream

# Fields a run sets from scratch, so a copy of the last run's row mustn't
# keep them: each is set again below if it still applies.
REFRESHED = ("upstream", "outdatedSince")


def refresh_repology(row, previous, now):
    """Update row's nixpkgs version and status from Repology.

    A lookup that fails leaves the row's data as it was, marked as not
    refreshed, as in a full sync.

    Returns:
        The project's entries, to write to its data file, or None when the
        lookup failed or found nothing.
    """
    try:
        project, entries = repology.project_by_name(row["project"])
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(
            f"::warning::{row['name']}: Repology lookup failed ({e})", file=sys.stderr
        )
        row["staleSince"] = row.get("staleSince") or previous.get("checkedAt") or now
        return None
    if project is None:
        return None  # renamed on Repology: the daily sync will sort it out
    proj = {
        "name": row["name"],
        "project": project,
        "attrs": row["attrs"],
        "entries": entries,
        "dataFile": row["dataFile"],
    }
    # nixpkgs isn't loaded ({}): platforms and homepage stay as they were.
    fresh = next(
        (r for r in rows.project_rows(proj, {}) if r["name"] == row["name"]), None
    )
    if fresh is None:
        return None
    # The version the daily sync took from the channel's index, where Repology
    # hadn't caught up (rows.channel_versions): this run doesn't read the
    # index, so it's held against Repology's fresh one the same way (the
    # channel only moves on between daily syncs as far as this run knows).
    channel = row.get("nixVersion")
    for key in ("nixVersion", "nixStatus", "nixVulnerable", "refVersion", "repoCount"):
        row[key] = fresh[key]
    row.pop("repologyVersion", None)
    if channel:
        rows.channel_versions([row], {a: {"version": channel} for a in row["attrs"]})
    # Repology's verdict is this fresh one now, for the check to decide
    # against (upstream.apply); without a refresh, the one it kept stays.
    row.pop("repologySaid", None)
    row.pop("staleSince", None)
    row["repologyCheckedAt"] = now
    return entries


def main():
    """Run the frequent check, and publish what changed."""
    now = datetime.now(UTC).isoformat()
    previous, packages = partial.load()
    # Your own checks and, if the lists opt in, the community's (community.py).
    merged, from_community = community.merge(
        nixpkgs_source.read_lists(), [row["name"] for row in packages]
    )
    checks = {name: check for name, check in merged.items() if check.get("frequent")}
    by_name = {row["name"]: row for row in packages}
    selected = [by_name[name] for name in checks if name in by_name]
    if not selected:
        print("No frequent update checks for tracked packages.", file=sys.stderr)
        return
    print(
        f"Frequent check: {', '.join(row['name'] for row in selected)}",
        file=sys.stderr,
    )
    data_files = {}
    for row in selected:
        for key in REFRESHED:
            row.pop(key, None)
        stale = row.get("notRefreshed") or {}
        stale.pop("upstream", None)
        if not stale:
            row.pop("notRefreshed", None)
        if row.get("project"):
            entries = refresh_repology(row, previous, now)
            if entries is not None:
                data_files[row["dataFile"]] = entries
    upstream.add_checks(selected, checks, previous, now, from_community)
    # Repology's refVersion is fresh again: count master (as the sync does).
    for row in selected:
        count_master(row)
    # Packages that follow one of these (follows.py) get its new version too.
    refreshed = {row["name"] for row in selected}
    following = {
        name: target
        for name, target in follows.recorded(packages).items()
        if target in refreshed
    }
    followers = [by_name[name] for name in following if name in by_name]
    for row in followers:
        row.pop("outdatedSince", None)  # set again below, as for the others
    follows.apply_versions(packages, following, now, from_community)
    history.add_outdated_since([*selected, *followers], previous, now)
    partial.publish(previous, packages, now, data_files)


if __name__ == "__main__":
    main()
