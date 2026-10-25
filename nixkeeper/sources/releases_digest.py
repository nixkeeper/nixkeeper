"""Read GitHub releases from the nixkeeper-versions digest.

The digest's releases.json.gz has, for every nixpkgs package fetched from a
GitHub tag, the newest version among its repository's tags matching its
tag scheme, and its latest release's. That's what the update check worked
out from the package's source would find (the digest runs nixkeeper's own
inferred.github_check), read from GitHub in bulk instead of a request per
package.

Each becomes the row's worked-out check result ("upstream", inferred), so
it adds a newer version Repology hasn't seen, and never takes Repology's
verdict away (upstream.apply). Measured on 2026-10-09, GitHub and Repology
agree on 86% of 23,009 packages; where only Repology says outdated, a
project had moved and its old repository stopped as often as Repology
matched another project.

It isn't used:

- for a package with a rule of its own or the community's (rules win);
- for Coq and Rocq libraries (SKIPPED_SETS);
- where it can't be trusted: the version its tag scheme was worked out
  from isn't the channel's (bumped since the digest's weekly evaluation,
  so a new tag scheme is possible), or its pick is older than nixpkgs'
  version (the scheme matches another series).

A package on the lists that the digest read over LISTS_MAX_DAYS ago, or
that it can't answer, gets the sync's own worked-out check instead, as
before.
"""

from datetime import datetime, timedelta

from .. import log
from ..shape import Row
from ..versions import is_newer
from . import about, feeds, upstream

FILE = "releases.json.gz"
# A list's package is checked by the sync itself when the digest read its
# repository longer ago than this many days. The digest reads every one
# each run, every 12 hours; one it couldn't reach waits for the next run.
LISTS_MAX_DAYS = 1
# Sets whose versions follow another package's, not their repository's
# releases alone: Coq and Rocq libraries are released for each version of
# the prover (metarocq 1.5.1-9.2 is for Rocq 9.2, mathcomp 2.6.0 needs a
# newer one), so their newest release waits on nixpkgs' prover. Left to
# Repology (measured 2026-10-09: 88 of 1,733 new outdated, the one family
# in a sample of 50 that wasn't a real update).
SKIPPED_SETS = ("coqPackages.", "rocqPackages.")


def load(now):
    """Read the digest's packages.

    Returns:
        {attr: entry}, or None when the digest is turned off, missing, too
        old or can't be read (feeds.load notes why).
    """
    found = feeds.load(FILE, "releases", "GitHub releases", now)
    if found is None:
        return None
    packages = found.get("packages") or {}
    about.note("releases", True, at=found["fetchedAt"], packages=len(packages))
    log.info(f"GitHub releases: {len(packages):,} packages")
    return packages


def result(entry):
    """Return the worked-out check result an entry gives, or None.

    The version is the latest release's when it matches the tag scheme,
    else the newest matching tag's. "tagged" is a newer matching tag than
    that release: pushed, but not released yet.

    Returns:
        {"version", "repo", "label", "url", "inferred", "digest",
        "checkedAt"?, "tagged"?}, or None when the entry has no version.
    """
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


def apply(rows: list[Row], digest, rules, now):
    """Give rows without a rule the digest's result as their worked-out check.

    It's applied by upstream.apply as inferred, so it only adds a newer
    version. Rows not on the lists get it only when it's newer, or tagged,
    or when only nixpkgs packages them (onlyNixpkgs): it's then the one
    thing their version is compared with, else nothing would be (3,320 rows
    on 2026-10-23, such as python313Packages.pbar2). For the other rows it
    would add nothing.

    Args:
        rows: The rows, changed in place.
        digest: load's result, or None.
        rules: The update checks by row name; rows with one are left alone.
        now: The run's time.

    Returns:
        The names of the rows answered, for which the sync's own worked-out
        checks needn't run.
    """
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
