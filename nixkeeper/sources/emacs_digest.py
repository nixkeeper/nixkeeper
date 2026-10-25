"""Compare emacsPackages with the Emacs package archives' newest versions.

The versions come from the nixkeeper-versions digest's emacs.json.gz
(feeds.py). The archives are what nixpkgs' emacsPackages are made from,
which Repology mostly can't compare: MELPA's versions are dates, which it
calls "untrusted".

nixpkgs lays the archives over each other, a later one winning
(pkgs/top-level/emacs-packages.nix): GNU ELPA, NonGNU ELPA, MELPA Stable,
MELPA, then its hand-written packages. So a row of emacsPackages is
compared (apply) with:

1. MELPA, when its version is MELPA's: a build's date and time
   (20251005.508);
2. else the first of MELPA Stable, NonGNU ELPA and GNU ELPA that has the
   package, in nixpkgs' order;
3. nothing, keeping Repology's verdict, for the hand-written packages
   (manual-packages), the devel archives' versions (0.0.20260424.102016)
   and packages no archive has.
"""

import re
import sys

from . import about, feeds

FILE = "emacs.json.gz"
PREFIX = "emacsPackages."
# Each archive nixkeeper-versions reads: its name, and a package's page.
ARCHIVES = {
    "melpa": ("MELPA", "https://melpa.org/#/{}"),
    "melpaStable": ("MELPA Stable", "https://stable.melpa.org/#/{}"),
    "nongnu": ("NonGNU ELPA", "https://elpa.nongnu.org/nongnu/{}.html"),
    "gnu": ("GNU ELPA", "https://elpa.gnu.org/packages/{}.html"),
}
# Where a version that isn't MELPA's is looked for, in nixpkgs' order.
RELEASES = ("melpaStable", "nongnu", "gnu")
# A MELPA version: a build's date and time (20251005.508).
MELPA_VERSION = re.compile(r"\d{8}\.\d+")
# The devel archives' versions end in a date and time (0.0.20260424.102016):
# not comparable with the release archives'.
DEVEL_VERSION = re.compile(r".+\.\d{8}\.\d+")
# nixpkgs' hand-written Emacs packages, by where they're defined.
MANUAL = "elisp-packages/manual-packages"


def load(now):
    """Read the archives' versions.

    Returns:
        {archive: {name: version}} for the archives in ARCHIVES, or None
        when they can't be used (feeds.load says why); Repology's verdicts
        then stay.
    """
    found = feeds.load(FILE, "emacs", "Emacs archives' versions", now)
    if found is None:
        return None
    archives = found.get("archives") or {}
    counts = {archive: len(archives.get(archive) or {}) for archive in ARCHIVES}
    print(
        "Emacs archives: "
        + ", ".join(f"{ARCHIVES[a][0]} {n:,}" for a, n in counts.items())
        + f" packages, read {found['fetchedAt']}",
        file=sys.stderr,
    )
    about.note("emacs", True, at=found["fetchedAt"], **counts)
    return archives


def apply(rows, nixpkgs, archives):
    """Compare emacsPackages' rows with the archive each comes from.

    The archive is chosen by the module's rules. Each row is newest or
    outdated against its newest version there, and says so ("feed"). Rows
    no rule applies to keep Repology's verdict.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        archives: load's result, or None (then nothing changes).
    """
    if not archives:
        return
    for row in rows:
        attrs = row.get("attrs") or []
        if not attrs or not all(a.startswith(PREFIX) for a in attrs):
            continue
        version = row.get("nixVersion") or ""
        pkg = next((nixpkgs[a] for a in attrs if a in nixpkgs), {})
        if not version or MANUAL in ((pkg.get("meta") or {}).get("position") or ""):
            continue
        name = attrs[0][len(PREFIX) :].strip('"')
        if MELPA_VERSION.fullmatch(version):
            archive = "melpa" if name in (archives.get("melpa") or {}) else None
        elif DEVEL_VERSION.fullmatch(version):
            archive = None
        else:
            archive = next(
                (a for a in RELEASES if name in (archives.get(a) or {})), None
            )
        if not archive:
            continue
        label, url = ARCHIVES[archive]
        feeds.compare(
            row,
            label,
            archives[archive][name],
            url.format(name),
            dated=archive == "melpa",
        )
