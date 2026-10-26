"""What each row says, in the counts, the lists and the filters.

Its status letter (status), the overview's highlights (the newest and
longest-standing), where its builds failed or never ran (unbuilt_where),
its facet entry (facet_entry), and the manifest's counts (numbers).
"""

from datetime import datetime

from .. import rows as rows_module
from ..changes import failures, is_outdated, is_vulnerable, waiting_for_channel
from ..sources.nixpkgs import available_on

# Hydra statuses of a build that didn't succeed. The manifest's failingBuilds
# counts them all, as zh.fail does; only "failed" makes a package fail on
# the page.
FAILING_BUILDS = {"failed", "dependency", "unfinished"}


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
        """Return when an entry's problem began, as a timestamp."""
        return datetime.fromisoformat(f[0]).timestamp()

    def pick(chosen):
        """Format the first HIGHLIGHTS of chosen, each family once."""
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
    page/status.js do: f failing, m outdated but the update is waiting for
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
    page/status.js). A platform counts when every build of the row there is
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
