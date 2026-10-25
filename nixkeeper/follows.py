"""Let one package follow another's version and update PRs.

Some packages are updated together with another, to the same version, by
the same PRs (msedgedriver with microsoft-edge). An update check can say
so, instead of looking anywhere itself:

    msedgedriver = { follows = "microsoft-edge"; };

The follower then counts the newest version of the package it follows as
its own (recorded like an update check's result, in row["upstream"] with
"follows"), and that package's update PRs, merged and open, as its own:
their titles name only the package followed, so a search by the
follower's name can't find them.

The package followed must be tracked too, as its row is where all that
comes from, and it can't follow another package itself. The rule is
recorded on the row, so the hourly checks follow along without reading
the lists.
"""

from .sources import upstream

# The update PRs a follower takes from the package it follows.
PR_FIELDS = ("openPR", "masterPR", "stagingPR")


def of(checks):
    """Return {follower: followed} from the update checks."""
    return {
        name: check["follows"]
        for name, check in checks.items()
        if isinstance(check, dict) and isinstance(check.get("follows"), str)
    }


def recorded(rows):
    """Return {follower: followed} as the rows recorded it at the last sync."""
    return {
        row["name"]: row["upstream"]["follows"]
        for row in rows
        if (row.get("upstream") or {}).get("follows")
    }


def pairs(rows, follows):
    """Yield the (follower, followed) rows for each rule with both tracked.

    A package that follows another follower is skipped: there are no chains.
    """
    by_name = {row["name"]: row for row in rows}
    for name, target in sorted(follows.items()):
        row, other = by_name.get(name), by_name.get(target)
        if row and other and target not in follows and target != name:
            yield row, other


def apply_versions(rows, follows, now, community=frozenset()):
    """Give each follower the newest version of the package it follows.

    That's the followed row's refVersion (once master is counted), else its
    nixpkgs version, applied as an update check's result would be.

    Returns:
        The followers' rows it changed.
    """
    changed = []
    for row, other in pairs(rows, follows):
        version = other.get("refVersion") or other.get("nixVersion")
        if not version:
            continue
        found = {"version": version, "checkedAt": now, "follows": other["name"]}
        if row["name"] in community:
            found["community"] = True
        upstream.apply(row, found)
        changed.append(row)
    return changed


def apply_prs(rows, follows):
    """Give each follower the update PRs of the package it follows.

    The same PRs update both. Only the PRs the followed row has are copied.
    """
    for row, other in pairs(rows, follows):
        for field in PR_FIELDS:
            if other.get(field):
                row[field] = other[field]
