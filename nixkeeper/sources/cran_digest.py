"""Compare rPackages with CRAN and Bioconductor.

The versions come from the nixkeeper-versions digest's cran.json.gz
(feeds.py). They're what nixpkgs' rPackages are generated from:
generate-r-packages.R reads the same index files, CRAN's as it is that day,
and Bioconductor's for the release nixpkgs pins. The daily sync compares
rPackages' rows with them instead of Repology (apply): outdated or newest
against CRAN, or against the Bioconductor release nixpkgs pins.

A package in none of them is no longer on CRAN (archived: it failed CRAN's
checks, or its maintainer left) or in that Bioconductor release. It's
marked "archived", which Repology can only call "unique". nixpkgs marks
most of those broken already (5,841 of 6,004 on 2026-10-07), so for those
it says why; the others are likely broken too, or due for removal.
"""

import sys

from . import about, feeds

FILE = "cran.json.gz"
PREFIX = "rPackages."
# The digest's indexes, in the order a package is looked for: CRAN, then
# Bioconductor's software, annotation and experiment packages.
INDEXES = ("cran", "bioc", "annotation", "experiment")
# nixpkgs writes a package's dots as underscores (ABC.RAP: ABC_RAP), and
# escapes two names it can't use as they are (generate-r-packages.R's
# escapeName).
ESCAPED = {"r_import": "import", "r_assert": "assert"}
CRAN_URL = "https://cran.r-project.org/package={name}"
BIOC_URL = {
    "bioc": "https://bioconductor.org/packages/{release}/bioc/html/{name}.html",
    "annotation": "https://bioconductor.org/packages/{release}/data/annotation/html/{name}.html",
    "experiment": "https://bioconductor.org/packages/{release}/data/experiment/html/{name}.html",
}


def load(now):
    """Read CRAN's and Bioconductor's versions.

    Returns:
        cran.json.gz's body ({"biocVersion", "cran", "bioc", ...}), or None
        when it can't be used (feeds.load says why); Repology's verdicts
        then stay.
    """
    found = feeds.load(FILE, "cran", "CRAN and Bioconductor", now)
    if found is None:
        return None
    counts = {index: len(found.get(index) or {}) for index in INDEXES}
    print(
        f"CRAN {counts['cran']:,} packages, Bioconductor {found['biocVersion']} "
        f"{counts['bioc'] + counts['annotation'] + counts['experiment']:,}, read "
        f"{found['fetchedAt']}",
        file=sys.stderr,
    )
    about.note(
        "cran", True, at=found["fetchedAt"], biocVersion=found["biocVersion"], **counts
    )
    return found


def package_name(attr):
    """Return the R package of an rPackages attribute (rPackages.ABC_RAP: ABC.RAP)."""
    name = attr[len(PREFIX) :]
    return ESCAPED.get(name) or name.replace("_", ".")


def apply(rows, nixpkgs, found):
    """Compare rPackages' rows with CRAN, else the Bioconductor release nixpkgs pins.

    Each row says what it was compared with ("feed"). A row in none of them
    gets "archived": True, and keeps Repology's status.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute (not needed here).
        found: load's result, or None (then nothing changes).
    """
    if not found:
        return
    release = found["biocVersion"]
    for row in rows:
        attrs = row.get("attrs") or []
        if not attrs or not all(a.startswith(PREFIX) for a in attrs):
            continue
        if not row.get("nixVersion"):
            continue
        name = package_name(attrs[0])
        index = next((i for i in INDEXES if name in (found.get(i) or {})), None)
        if index is None:
            row["archived"] = True
            continue
        if index == "cran":
            label, url = "CRAN", CRAN_URL.format(name=name)
        else:
            label = f"Bioconductor {release}"
            url = BIOC_URL[index].format(release=release, name=name)
        feeds.compare(row, label, found[index][name], url)
