"""GitHub releases from nixkeeper-versions' digest (its releases.json.gz):
for every nixpkgs package fetched from a GitHub tag, the newest version
among its repository's tags matching its tag scheme, and its latest
release's, as the update check worked out from its source would find them
(the digest runs nixkeeper's own inferred.github_check), read from GitHub
in bulk instead of a request per package.

Each becomes the row's worked-out check result ("upstream", inferred), so
it adds a newer version Repology hasn't seen and never takes Repology's
verdict away (upstream.apply): measured on 2026-10-09, GitHub and Repology
agree on 86% of 23,009 packages; where only Repology says outdated, a
project moved and its old repository stopped as often as Repology matched
another project.

Not for a package with a rule of its own or the community's (rules win),
nor Coq and Rocq libraries (SKIPPED_SETS), nor where it can't be
trusted: the version its tag scheme was worked out from isn't the
channel's (bumped since the digest's weekly evaluation: a
new tag scheme is possible), or its pick is older than nixpkgs' version
(the scheme matches another series). A package on the lists the digest
read over LISTS_MAX_DAYS ago, or can't answer, gets the sync's own
worked-out check instead, as before."""

import sys
from datetime import datetime, timedelta

from ..versions import is_newer
from . import about, feeds, upstream

FILE = "releases.json.gz"
# A list's package is checked by the sync itself when the digest read its
# repository longer ago than this (the digest reads every one each run,
# every 12 hours; one it couldn't reach waits for the next): the lists'
# packages are checked at least every QUIET_DAYS otherwise.
LISTS_MAX_DAYS = 1
# Sets whose versions follow another package's, not their repository's
# releases alone: Coq and Rocq libraries are released for each version of
# the prover (metarocq 1.5.1-9.2 is for Rocq 9.2, mathcomp 2.6.0 needs a
# newer one), so their newest release waits on nixpkgs' prover. Left to
# Repology (measured 2026-10-09: 88 of 1,733 new outdated, the one family
# in a sample of 50 that wasn't a real update).
SKIPPED_SETS = ("coqPackages.", "rocqPackages.")


def load(now):
    """{attr: entry} of the digest's packages, or None (noting why) when it's
    turned off, not there, too old or can't be read."""
    found = feeds.load(FILE, "releases", "GitHub releases", now)
    if found is None:
        return None
    packages = found.get("packages") or {}
    about.note("releases", True, at=found["fetchedAt"], packages=len(packages))
    print(f"GitHub releases: {len(packages):,} packages", file=sys.stderr)
    return packages


def result(entry):
    """The worked-out check result an entry gives ({"version", "repo",
    "label", "url", "inferred", "checkedAt", "tagged"?}), or None when it has
    no version: its latest release when it matches the tag scheme, else its
    newest matching tag. tagged: a newer matching tag than that release
    (pushed, not released yet)."""
    release, tag = entry.get("release"), entry.get("tag")
    version = release or tag
    if not version:
        return None
    repo = entry["repo"]
    found = {
        "version": version,
        "repo": repo,
        "label": f"{repo} {'releases' if release else 'tags'}",
        "url": f"https://github.com/{repo}/{'releases' if release else 'tags'}",
        "inferred": True,
        "digest": "releases",
    }
    if entry.get("read"):
        found["checkedAt"] = f"{entry['read']}T00:00:00+00:00"
    if release and tag and is_newer(tag, release):
        found["tagged"] = tag
    return found


def apply(rows, digest, rules, now):
    """Give rows without a rule (rules: {name: check}) the digest's result as
    their worked-out check (upstream.apply, inferred: it only adds a newer
    version). Rows not on the lists get it only when it's newer, or tagged,
    or when only nixpkgs packages them (onlyNixpkgs: then it's the one
    thing their version is compared with, else nothing would be: 3,320
    rows on 2026-10-23, python313Packages.pbar2); the rest add nothing to
    them. Returns the names answered: those the sync's own worked-out
    checks needn't run for."""
    if not digest:
        return set()
    today = datetime.fromisoformat(now).date()
    answered = set()
    for row in rows:
        if row["name"] in rules or row["name"].startswith(SKIPPED_SETS):
            continue
        entry = next((digest[a] for a in row.get("attrs") or [] if a in digest), None)
        nix = row.get("nixVersion")
        if not entry or not nix or entry.get("version") != nix:
            continue
        found = result(entry)
        if not found or is_newer(nix, found["version"]):
            continue
        listed = bool(row.get("lists"))
        read = entry.get("read")
        if listed and (
            not read
            or today - datetime.fromisoformat(read).date()
            > timedelta(days=LISTS_MAX_DAYS)
        ):
            continue
        newer = is_newer(found["version"], nix)
        if (
            not listed
            and not newer
            and not found.get("tagged")
            and not row.get("onlyNixpkgs")
        ):
            continue
        upstream.apply(row, found)
        answered.add(row["name"])
    return answered
