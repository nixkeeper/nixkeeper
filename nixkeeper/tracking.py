"""Decide which packages to track, and which lists each is on.

The packages come from the package lists (package-lists/) and the nixpkgs
package index.
"""

from . import config
from .naming import slug

# The list of packages tracked through meta.maintainers. The other lists are
# named in package-lists/default.nix.
MAINTAINED = "maintained"


def extra_lists(lists):
    """Return the extra package lists, as {list name: entries}.

    extraPackages is either named lists (an attrset), or a plain list,
    which counts as the list "extra".
    """
    extra = lists.get("extraPackages") or {}
    return {"extra": extra} if isinstance(extra, list) else extra


def maintained(lists, nixpkgs):
    """Return the attributes maintained by one of the lists' handles, sorted.

    The maintainers are read from each package's meta.maintainers.
    """
    handles = {h.lower() for h in lists["maintainers"]}
    return [
        attr
        for attr, p in sorted(nixpkgs.items())
        if any(
            isinstance(m, dict) and (m.get("github") or "").lower() in handles
            for m in p["meta"].get("maintainers") or []
        )
    ]


def by_pname(nixpkgs):
    """Index the top-level attributes by pname.

    Only top-level packages are indexed, as a bare pname should only match
    those: "heroic" shouldn't pull in typstPackages.heroic.

    Returns:
        {pname: [attributes]}.
    """
    index = {}
    for attr, p in nixpkgs.items():
        if "." not in attr:
            index.setdefault(p.get("pname"), []).append(attr)
    return index


def extra_attrs(name, nixpkgs, pnames):
    """Return the attributes an extra list's entry tracks.

    An exact attribute name tracks just that package (_1password-gui,
    without _1password-gui-beta, which shares the pname "1password"). Any
    other name tracks every top-level package with that pname.
    """
    return [name] if name in nixpkgs else sorted(pnames.get(name, []))


def tracked_packages(lists, nixpkgs):
    """Return every package the lists track.

    Maintained packages are tracked one attribute at a time: with nested
    sets, a pname can mean unrelated packages (foo, python313Packages.foo).

    Returns:
        {name: (the nixpkgs attributes to look up, the Repology project name
        to try when none of them resolves)}.
    """
    wanted = {
        attr: ([attr], nixpkgs[attr].get("pname") or attr)
        for attr in maintained(lists, nixpkgs)
    }
    pnames = by_pname(nixpkgs)
    entries = {e for es in extra_lists(lists).values() for e in es}
    for name in sorted(entries):
        attrs = extra_attrs(name, nixpkgs, pnames)
        # Not in nixpkgs: tracked anyway, as a "not in nixpkgs" row, and
        # reported with the lists (listcheck.py).
        wanted.setdefault(name, (attrs, name))
    return wanted


def list_names(lists, nixpkgs):
    """Return which lists each attribute is on.

    Returns:
        {attribute, or an entry's own name when it's not in nixpkgs: [list
        names]}.
    """
    found = {attr: [MAINTAINED] for attr in maintained(lists, nixpkgs)}
    pnames = by_pname(nixpkgs)
    for list_name, entries in extra_lists(lists).items():
        for name in entries:
            for key in extra_attrs(name, nixpkgs, pnames) or [name]:
                if list_name not in found.setdefault(key, []):
                    found[key].append(list_name)
    return found


def add_lists(rows, names):
    """Give each row the lists it's on ("lists").

    Those are its attributes' lists, or its own name's when it's not in
    nixpkgs: "maintained" first, then the named lists in alphabetical order.
    """
    for row in rows:
        on = {n for key in [*row["attrs"], row["name"]] for n in names.get(key, [])}
        row["lists"] = sorted(on, key=lambda n: (n != MAINTAINED, n))


def add_list_teams(rows, nixpkgs):
    """Add a nixpkgs team to the rows of a list named after it.

    A named list with a team's name (compared as file names, as
    naming.slug makes them: gaming for Gaming) joins that team. Its
    packages count as the team's too: on the team's page (?team=Gaming), in
    its counts and in the team filter, beside those nixpkgs lists under the
    team (meta.teams). That's for packages a team looks after that nixpkgs
    doesn't list it on. Teams a list adds are also in "teamsByList", so the
    page can say where the team came from; a package on the team both ways
    counts as nixpkgs'.
    """
    teams = {}
    for pkg in nixpkgs.values():
        for team in (pkg.get("meta") or {}).get("teams") or []:
            name = team.get("shortName") if isinstance(team, dict) else None
            if isinstance(name, str) and name:
                teams.setdefault(slug(name), name)
    for row in rows:
        for list_name in row.get("lists") or []:
            team = teams.get(slug(list_name))
            if team and team not in (row.get("teams") or []):
                row.setdefault("teams", []).append(team)
                row.setdefault("teamsByList", []).append(team)


def every_package(nixpkgs, listed):
    """Return the packages to track beyond the lists', with every package.

    With every package tracked (config.all_packages), each nixpkgs attribute
    the lists don't already cover is tracked too, one attribute each: the
    attributes of one Repology project come together as one row anyway
    (lookup), so python313Packages.requests and python314Packages.requests
    share one.

    Args:
        nixpkgs: The package index, by attribute.
        listed: tracked_packages' result.

    Returns:
        {name: (attributes, fallback)}, as tracked_packages returns them.
    """
    covered = {a for attrs, _ in listed.values() for a in attrs}
    return {
        attr: ([attr], p.get("pname") or attr)
        for attr, p in nixpkgs.items()
        if attr not in covered and attr not in listed
    }


def in_set(attrs, names):
    """Return the set, of names, that all of attrs are in, or None.

    An attribute's set is its first part, such as rPackages.
    """
    sets = {a.split(".", 1)[0] if "." in a else None for a in attrs}
    if len(sets) == 1 and (name := sets.pop()) in names:
        return name
    return None


def add_sets(rows):
    """Mark the rows of the sets updated in bulk, with every package.

    A row of a set in config.SET_PROFILES that no list has gets "set"
    (rPackages, say); a list's own packages keep the full checks, set or
    not. A row of a set that isn't versioned software
    (config.UNVERSIONED_SETS) gets "unversioned".
    """
    for row in rows:
        if not row.get("lists") and (name := in_set(row["attrs"], config.SET_PROFILES)):
            row["set"] = name
        if in_set(row["attrs"], config.UNVERSIONED_SETS):
            row["unversioned"] = True
