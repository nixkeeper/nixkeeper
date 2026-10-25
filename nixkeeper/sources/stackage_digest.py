"""Compare the haskellPackages pinned to Stackage LTS with that series.

nixpkgs pins about 3,400 of its haskellPackages to a Stackage LTS series
(configuration-hackage2nix/stackage.yaml). For those, the version to be at
is the newest of that series, not Hackage's newest, which Stackage holds
back until its next series. The series' versions come from the
nixkeeper-versions digest's stackage.json.gz (feeds.py).

The daily sync compares those rows with the series instead of Repology,
which knows only Hackage's newest: outdated when behind the series' newest
snapshot (nixpkgs moves to it with the next haskell-updates merge), newest
when at it, whatever Hackage has. The rest of haskellPackages keep
Repology's verdict (Hackage's newest).
"""

import sys

from ..versions import version_key
from . import about, feeds

FILE = "stackage.json.gz"
PREFIX = "haskellPackages."
PACKAGE_URL = "https://www.stackage.org/{snapshot}/package/{name}"


def load(now):
    """Read Stackage LTS's versions.

    Returns:
        stackage.json.gz's {"series", "nixpkgs", "snapshot", "versions"},
        or None when it can't be used (feeds.load says why); Repology's
        verdicts then stay.
    """
    found = feeds.load(FILE, "stackage", "Stackage LTS", now)
    if found is None:
        return None
    print(
        f"Stackage: nixpkgs follows {found['nixpkgs']}, {found['snapshot']} is the "
        f"newest; {len(found['versions']):,} packages, read {found['fetchedAt']}",
        file=sys.stderr,
    )
    about.note(
        "stackage",
        True,
        at=found["fetchedAt"],
        snapshot=found["snapshot"],
        nixpkgs=found["nixpkgs"],
        packages=len(found["versions"]),
    )
    return found


def series_name(series):
    """Name a Stackage series as the page shows it: lts-24 is "Stackage LTS 24"."""
    return "Stackage " + series.replace("lts-", "LTS ")


def apply(rows, nixpkgs, found):
    """Compare the rows of the haskellPackages nixpkgs pins with the series.

    Each is outdated or newest against its version in the series' newest
    snapshot, and says so ("feed"), with the snapshot nixpkgs follows, and
    Hackage's newer version when Stackage holds the package back
    ("heldBack").

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        found: load's result, or None (then nothing changes).
    """
    if not found:
        return
    versions = found.get("versions") or {}
    for row in rows:
        attrs = row.get("attrs") or []
        if not attrs or not all(a.startswith(PREFIX) for a in attrs):
            continue
        name = attrs[0][len(PREFIX) :]
        version = versions.get(name)
        if not version or not row.get("nixVersion"):
            continue
        # Repology's newest is Hackage's: the package is held back when it's
        # past the series' version.
        hackage = row.get("refVersion")
        held = hackage and version_key(hackage) > version_key(version)
        feeds.compare(
            row,
            series_name(found["series"]),
            version,
            PACKAGE_URL.format(snapshot=found["snapshot"], name=name),
            snapshot=found["snapshot"],
            followed=found["nixpkgs"],
            **({"heldBack": hackage} if held else {}),
        )
