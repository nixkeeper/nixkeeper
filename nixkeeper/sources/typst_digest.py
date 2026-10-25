"""Compare typstPackages with Typst Universe's newest versions.

The versions come from the nixkeeper-versions digest's typst.json.gz
(feeds.py). Typst Universe is the source of nixpkgs' typstPackages, which
Repology mostly can't compare: it sees nixpkgs alone ("unique"), or the
versions nixpkgs keeps ("legacy"). So the daily sync compares
typstPackages' rows with Universe instead (apply): a package's latest
attribute (typstPackages.cetz) against Universe's newest version, and the
versioned ones (typstPackages.cetz_0_3_0) as older versions kept beside
it.
"""

import sys

from .. import verdict
from ..shape import Row
from . import about, feeds

FILE = "typst.json.gz"
PREFIX = "typstPackages."
NAME = "Typst Universe"
PACKAGE_URL = "https://typst.app/universe/package/{}"


def load(now):
    """Read Typst Universe's packages.

    Returns:
        {name: {"version", "released"?}} for every package, or None when
        they can't be used (feeds.load says why); Repology's verdicts then
        stay.
    """
    found = feeds.load(FILE, "typst", "Typst Universe's versions", now)
    if found is None:
        return None
    packages = found.get("packages") or {}
    print(
        f"Typst Universe: {len(packages):,} packages, read {found['fetchedAt']}",
        file=sys.stderr,
    )
    about.note("typst", True, at=found["fetchedAt"], packages=len(packages))
    return packages


def apply(rows: list[Row], nixpkgs, packages):
    """Compare typstPackages' rows with Typst Universe.

    The row of a package's latest attribute (typstPackages.cetz) is newest
    or outdated against Universe's newest version. A versioned one
    (typstPackages.cetz_0_3_0) is an older version kept beside it, unless
    it's the same version (a row of its own when Repology doesn't list the
    package): then it's compared too. Each row says what it was compared
    with ("feed"). Packages Universe doesn't have keep Repology's verdict.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        packages: load's result, or None (then nothing changes).
    """
    if not packages:
        return
    for row in rows:
        attrs = row.get("attrs") or []
        if not attrs or not all(a.startswith(PREFIX) for a in attrs):
            continue
        pkg = next((nixpkgs[a] for a in attrs if a in nixpkgs), None)
        name = (pkg or {}).get("pname")
        found = packages.get(name) if name else None
        version = row.get("nixVersion")
        if not name or not found or not version:
            continue
        latest = PREFIX + name
        latest_version = (nixpkgs.get(latest) or {}).get("version")
        if latest not in attrs and latest_version and latest_version != version:
            row["feed"] = {
                "name": NAME,
                "version": found["version"],
                "url": PACKAGE_URL.format(name),
                **({"released": found["released"]} if found.get("released") else {}),
            }
            # Kept beside it, and compared with the feed (verdict._feed).
            row["keptBeside"] = {"attr": latest, "version": latest_version}
            verdict.decide(row)
            continue
        feeds.compare(
            row,
            NAME,
            found["version"],
            PACKAGE_URL.format(name),
            released=found.get("released"),
        )
