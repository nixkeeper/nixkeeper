"""Compare the gems and crates nixpkgs fetches with their registries.

The versions come from the nixkeeper-versions digest's registries.json.gz
(feeds.py): each gem's newest release on RubyGems, each crate's on
crates.io, and which gem or crate each attribute is ("attrs", from its
source: a crate's name is often not the attribute's). Repology mostly sees
nixpkgs alone in rubyPackages' projects, so the daily sync compares the
rows of those attributes with their registry instead (apply), as it does
the generated sets':

- rubygems: the gem's newest release;
- crates.io: the crate's newest release, or its newest pre-release when
  nixpkgs' version is a pre-release too (pijul's 1.0.0 betas).

A registry the digest last read over config.VERSIONS_DIGEST_MAX_AGE_HOURS
ago keeps Repology's verdicts.
"""

from .. import config, log
from ..shape import Row
from ..versions import is_newer, is_pre_release
from . import about, digests, feeds

FILE = "registries.json.gz"
# Each registry: its name on the page, and a package's page on it.
REGISTRIES = {
    "rubygems": ("RubyGems", "https://rubygems.org/gems/{name}"),
    "crates.io": ("crates.io", "https://crates.io/crates/{name}"),
}
# Any attribute can be fetched from a registry (sync.FEEDS).
PREFIX = ("",)


def load(now):
    """Read the registries' newest versions.

    Returns:
        {registry: {"fetchedAt", "attrs", "packages"}} for the registries
        read recently enough, or None when the file can't be used
        (feeds.load says why); Repology's verdicts then stay.
    """
    found = feeds.load(FILE, "registries", "the registries' versions", now)
    if found is None:
        return None
    current = {}
    for name, part in (found.get("registries") or {}).items():
        if name not in REGISTRIES:
            continue
        if digests.hours_since(part["fetchedAt"], now) > (
            config.VERSIONS_DIGEST_MAX_AGE_HOURS
        ):
            log.info(f"{REGISTRIES[name][0]}: read {part['fetchedAt']}, too long ago")
            continue
        current[name] = part
    counts = {name: len(part.get("packages") or {}) for name, part in current.items()}
    log.info(
        "Registries: "
        + ", ".join(f"{REGISTRIES[n][0]} {c:,}" for n, c in counts.items())
    )
    about.note("registries", True, at=found["fetchedAt"], **counts)
    return current


def newest_for(entry, nix_version):
    """Return the version of a registry's entry to compare nixpkgs' with.

    Args:
        entry: The package's entry ({"version", "preRelease"?}).
        nix_version: nixpkgs' version.

    Returns:
        Its newest pre-release when nixpkgs' version is a pre-release and
        that's newer, else its newest release.
    """
    pre = entry.get("preRelease")
    if pre and is_pre_release(nix_version) and is_newer(pre, entry["version"]):
        return pre
    return entry["version"]


def apply(rows: list[Row], nixpkgs, found):
    """Compare the rows of the attributes fetched from a registry with it.

    Each row compared says so ("feed"), outdated or newest against the
    registry's version. A gem or crate the registry didn't answer for, and
    the registries not read recently, keep Repology's verdict.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute (unused: the digest says
            which attribute is which package).
        found: load's result, or None (then nothing changes).
    """
    if not found:
        return
    for row in rows:
        version = row.get("nixVersion")
        if not version:
            continue
        for registry, part in found.items():
            names = part.get("attrs") or {}
            name = next((names[a] for a in row.get("attrs") or [] if a in names), None)
            entry = name and (part.get("packages") or {}).get(name)
            if entry:
                label, url = REGISTRIES[registry]
                feeds.compare(
                    row, label, newest_for(entry, version), url.format(name=name)
                )
                break
