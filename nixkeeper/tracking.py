"""Which packages to track, from the package lists and the nixpkgs index, and
which list each is on."""

from . import config
from .naming import slug

# The list of packages tracked through meta.maintainers; the other lists are
# named in package-lists/default.nix.
MAINTAINED = "maintained"


def extra_lists(lists):
    """{list name: entries} from extraPackages: named lists (an attrset), or a
    plain list, which counts as the list "extra"."""
    extra = lists.get("extraPackages") or {}
    return {"extra": extra} if isinstance(extra, list) else extra


def maintained(lists, nixpkgs):
    """Attributes whose meta.maintainers include one of the handles, sorted."""
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
    """pname -> top-level attributes. Bare pnames only match top-level
    packages: "heroic" shouldn't pull in typstPackages.heroic."""
    index = {}
    for attr, p in nixpkgs.items():
        if "." not in attr:
            index.setdefault(p.get("pname"), []).append(attr)
    return index


def extra_attrs(name, nixpkgs, pnames):
    """What an extra entry tracks: an exact attribute name just that package
    (_1password-gui without its -beta, which shares the pname "1password");
    else every top-level package with that pname."""
    return [name] if name in nixpkgs else sorted(pnames.get(name, []))


def tracked_packages(lists, nixpkgs):
    """name -> (nixpkgs attrs to look up, Repology project name to try if none
    of them resolve). Maintained packages go one attr at a time: with nested
    sets a pname can mean unrelated packages (foo, python313Packages.foo)."""
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
    """Which lists each attribute is on (or, for an entry not in nixpkgs, the
    entry's name): {name: [list names]}."""
    found = {attr: [MAINTAINED] for attr in maintained(lists, nixpkgs)}
    pnames = by_pname(nixpkgs)
    for list_name, entries in extra_lists(lists).items():
        for name in entries:
            for key in extra_attrs(name, nixpkgs, pnames) or [name]:
                if list_name not in found.setdefault(key, []):
                    found[key].append(list_name)
    return found


def add_lists(rows, names):
    """Give each row the lists it's on ("lists"): those of its attributes, or
    of its own name when it's not in nixpkgs. "maintained" first, then the
    named lists alphabetically."""
    for row in rows:
        on = {n for key in [*row["attrs"], row["name"]] for n in names.get(key, [])}
        row["lists"] = sorted(on, key=lambda n: (n != MAINTAINED, n))


def add_list_teams(rows, nixpkgs):
    """A named list called as a nixpkgs team is (its name as a file name:
    gaming for Gaming, as naming.slug has it) joins that team: its
    packages count as the team's too, on the team's page (?team=Gaming), in
    its counts and in the team filter, beside those nixpkgs lists under the
    team (meta.teams). For packages a team looks after that nixpkgs doesn't
    list it on. Those a list adds are also in "teamsByList", so the page
    can say where the team came from; a package both ways stays nixpkgs'."""
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
    """With every package tracked (config.all_packages): name -> (attrs,
    fallback), as tracked_packages, for each nixpkgs attribute the lists
    (listed, tracked_packages') don't already cover. One attribute each:
    those of one Repology project come together as one row anyway (lookup),
    so python313Packages.requests and python314Packages.requests share one."""
    covered = {a for attrs, _ in listed.values() for a in attrs}
    return {
        attr: ([attr], p.get("pname") or attr)
        for attr, p in nixpkgs.items()
        if attr not in covered and attr not in listed
    }


def in_set(attrs, names):
    """The attribute set of names (its first part: rPackages) all of attrs
    are in, or None."""
    sets = {a.split(".", 1)[0] if "." in a else None for a in attrs}
    if len(sets) == 1 and (name := sets.pop()) in names:
        return name
    return None


def add_sets(rows):
    """With every package: give the rows of the sets updated in bulk
    (config.SET_PROFILES) that no list has their set ("set": rPackages),
    and mark those of sets that aren't versioned software
    (config.UNVERSIONED_SETS: "unversioned"). A list's own packages keep
    the full checks, set or not."""
    for row in rows:
        if not row.get("lists") and (name := in_set(row["attrs"], config.SET_PROFILES)):
            row["set"] = name
        if in_set(row["attrs"], config.UNVERSIONED_SETS):
            row["unversioned"] = True
