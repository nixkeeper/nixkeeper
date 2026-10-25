"""Read nixkeeper-versions' digest of Repology.

The digest (https://github.com/nixkeeper/digest-versions) has every nixpkgs
project's packages in every repository, read in bulk the way nixpkgs-update
reads Repology, refreshed daily for outdated projects and weekly for the
rest. The daily sync takes the tracked packages' projects from it instead
of looking each up on Repology (lookup.py). It still asks Repology about
those the digest can't answer: missing from it (new in nixpkgs), or with
another version than the channel's (changed since); and about all of them
when the digest isn't current or can't be read.
"""

import gzip
import io
import json
import sys

from .. import config
from . import about, digests

# The digest's format this nixkeeper reads.
FORMAT = 1


def current(meta, now):
    """Return whether the digest is recent enough.

    It is when its outdated projects were read within
    VERSIONS_DIGEST_MAX_AGE_HOURS; its workflow runs daily.
    """
    hours = digests.hours_since(meta["outdatedAt"], now)
    return hours <= config.VERSIONS_DIGEST_MAX_AGE_HOURS


def projects_of(lines, attrs):
    """Pick the tracked attributes' projects from the digest's lines.

    Each line is one project. Only the projects of attrs are kept, so
    memory stays small: the whole digest is about 2 million entries.

    Returns:
        {attr: (project, entries, the day it was checked)}.
    """
    found = {}
    for line in lines:
        project = json.loads(line)
        for entry in project["entries"]:
            attr = entry.get("srcname")
            if entry["repo"] == config.NIX_REPO and attr in attrs:
                found[attr] = (
                    project["project"],
                    project["entries"],
                    project["checked"],
                )
    return found


class Stale(dict):
    """A digest that isn't current, as load returns it.

    What it has is only used where Repology can't be reached, or for
    packages read in bulk, which keep their last versions anyway
    (lookup.py).
    """

    stale = True


def load(attrs, now):
    """Read the digest's projects for the tracked attributes.

    Returns:
        {attr: (project, entries, the day it was checked)} for the attrs
        the digest has: a Stale one when it isn't current (Repology is then
        asked first, and the digest used only where Repology can't be
        reached). None when it's turned off, or can't be read (the log says
        why).
    """
    base = config.VERSIONS_DIGEST_URL
    if not base:
        return None
    try:
        meta = digests.read_meta(base, FORMAT)
        body = digests.download(base, "projects.jsonl.gz")
        with gzip.open(io.BytesIO(body), "rt") as lines:
            found = projects_of(lines, set(attrs))
        if not current(meta, now):
            # Repology may be down (the digest's run couldn't read it): its
            # last versions, where Repology can't be reached.
            about.note(
                "versions",
                False,
                "too old: used only where Repology can't be reached",
                at=meta["outdatedAt"],
            )
            print(
                f"::warning::Versions digest: its outdated projects are from "
                f"{meta['outdatedAt']}; looking packages up on Repology, the "
                "digest only where that fails",
                file=sys.stderr,
            )
            return Stale(found)
    except digests.FAILURES as e:
        digests.give_up(
            "versions", "Versions digest", e, "; looking packages up on Repology"
        )
        return None
    print(
        f"Versions digest: {meta['projects']:,} projects, outdated ones read "
        f"{meta['outdatedAt']}; {len(found):,} of {len(set(attrs)):,} tracked "
        "attributes in it",
        file=sys.stderr,
    )
    about.note("versions", True, at=meta["outdatedAt"], projects=meta.get("projects"))
    return found


def answer(digest, attrs, nixpkgs):
    """Return a tracked package's project from the digest, or None.

    None means Repology must be asked: none of the package's attributes is
    in the digest, or one is, with another version than the channel's
    (nixpkgs changed it since the digest was read, or Repology hasn't
    caught up).

    Args:
        digest: load's result.
        attrs: The package's attributes.
        nixpkgs: The package index, by attribute; {} takes the digest as it
            is.

    Returns:
        (project, entries, the day it was checked), or None.
    """
    found = None
    for attr in attrs:
        if attr not in digest:
            continue
        project, entries, checked = digest[attr]
        nix = [
            e
            for e in entries
            if e["repo"] == config.NIX_REPO and e.get("srcname") == attr
        ]
        channel = (nixpkgs.get(attr) or {}).get("version")
        if channel and all(e.get("version") != channel for e in nix):
            return None
        found = found or (project, entries, checked)
    return found
