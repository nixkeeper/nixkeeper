"""Compare five generated sets with the indexes they're made from.

The versions come from the nixkeeper-versions digest's sets.json.gz
(feeds.py), each set's index read as nixpkgs' own update script reads it.
Repology mostly sees nixpkgs alone in these sets ("unique"), so the daily
sync compares their rows with the index instead (apply), as it does Typst
Universe's:

- chickenPackages_5 and _6: CHICKEN's egg index for that major version,
  by egg (a row's pname without "chicken-");
- akkuPackages: Akku's index, by name (pname without "akku-");
- gnomeExtensions: extensions.gnome.org, by the extension the digest
  found in each attribute's source ("attrs": slugs aren't unique). The
  version is the newest for the GNOME Shells nixpkgs merges into
  gnomeExtensions: its own major and the two before, and any newer (an
  extension's version numbers only grow);
- azure-cli-extensions: the Azure CLI's extension index, by name: the
  newest version nixpkgs' azure-cli runs (azext.minCliCoreVersion), as
  nixpkgs' extensions-tool.py picks it.

A set whose index the digest last read over
config.VERSIONS_DIGEST_MAX_AGE_HOURS ago keeps Repology's verdicts.
"""

from .. import config, log
from ..shape import Row
from ..versions import is_newer, version_key
from . import about, digests, feeds

FILE = "sets.json.gz"
# Each set: its name on the page, and how a row's package is found in it.
SETS = {
    "chickenPackages_5": "CHICKEN 5 eggs",
    "chickenPackages_6": "CHICKEN 6 eggs",
    "akkuPackages": "Akku",
    "gnomeExtensions": "GNOME Extensions",
    "azure-cli-extensions": "Azure CLI extensions",
}
PREFIX = tuple(f"{name}." for name in SETS)
# How many GNOME Shell majors before nixpkgs' own it merges into
# gnomeExtensions (pkgs/desktops/gnome/extensions/default.nix: 48, 49, 50
# with GNOME 50).
GNOME_MERGED_BEFORE = 2
EGG_URL = "https://wiki.call-cc.org/eggref/{major}/{name}"
AKKU_URL = "https://akkuscm.org/packages/{name}/"
GNOME_URL = "https://extensions.gnome.org/extension/{pk}/{slug}/"
GNOME_SEARCH_URL = "https://extensions.gnome.org/?search={slug}"
# Most extensions' source is in Azure/azure-cli-extensions, under src/.
AZURE_URL = "https://github.com/Azure/azure-cli-extensions/tree/main/src/{name}"


def load(now):
    """Read the generated sets' indexes.

    Returns:
        {set: {"fetchedAt", "packages", "attrs"?}} for the sets read recently
        enough, or None when the file can't be used (feeds.load says why);
        Repology's verdicts then stay.
    """
    found = feeds.load(FILE, "sets", "the generated sets' indexes", now)
    if found is None:
        return None
    current = {}
    for name, part in (found.get("sets") or {}).items():
        if name not in SETS:
            continue
        if digests.hours_since(part["fetchedAt"], now) > (
            config.VERSIONS_DIGEST_MAX_AGE_HOURS
        ):
            log.info(f"{SETS[name]}: read {part['fetchedAt']}, too long ago")
            continue
        current[name] = part
    counts = {name: len(part.get("packages") or {}) for name, part in current.items()}
    log.info(
        "Generated sets' indexes: "
        + ", ".join(f"{SETS[n]} {c:,}" for n, c in counts.items())
    )
    about.note("sets", True, at=found["fetchedAt"], **counts)
    return current


def gnome_newest(extension, shell_version):
    """Return a GNOME extension's newest version for the shells nixpkgs merges.

    Args:
        extension: Its entry in the digest ({"slug", "shells"}).
        shell_version: nixpkgs' gnome-shell version (50.4).

    Returns:
        The version, or None when it has none for those shells.
    """
    try:
        oldest = int(shell_version.split(".")[0]) - GNOME_MERGED_BEFORE
    except (AttributeError, ValueError):
        return None
    versions = [
        v
        for shell, v in (extension.get("shells") or {}).items()
        if shell.isdigit() and int(shell) >= oldest
    ]
    return max(versions, key=int) if versions else None


def azure_newest(extension, cli_version):
    """Return an Azure CLI extension's newest version nixpkgs' azure-cli runs.

    Args:
        extension: Its entry in the digest ({"versions": [[version, minCli]]}).
        cli_version: nixpkgs' azure-cli version.

    Returns:
        The version, or None when none runs on it.
    """
    runs = [
        version
        for version, oldest in extension.get("versions") or []
        if cli_version and not is_newer(oldest, cli_version)
    ]
    return max(runs, key=version_key) if runs else None


def newest_of(name, attr, part, nixpkgs):
    """Return the version an attribute's index has for it, and its page.

    Args:
        name: The attribute's set.
        attr: The attribute.
        part: The set's part of the digest.
        nixpkgs: The package index, by attribute.

    Returns:
        (version, url), or None when the index doesn't have it.
    """
    packages = part.get("packages") or {}
    pname = (nixpkgs.get(attr) or {}).get("pname") or ""
    if name.startswith("chickenPackages_"):
        egg = pname.removeprefix("chicken-")
        found = packages.get(egg)
        major = name.rsplit("_", 1)[1]
        return found and (found["version"], EGG_URL.format(major=major, name=egg))
    if name == "akkuPackages":
        package = pname.removeprefix("akku-")
        found = packages.get(package)
        return found and (found["version"], AKKU_URL.format(name=package))
    if name == "gnomeExtensions":
        extension = packages.get((part.get("attrs") or {}).get(attr))
        shell = (nixpkgs.get("gnome-shell") or {}).get("version")
        version = extension and gnome_newest(extension, shell)
        if not version:
            return None
        slug = extension.get("slug") or ""
        url = (
            GNOME_URL.format(pk=extension["pk"], slug=slug)
            if extension.get("pk")
            else GNOME_SEARCH_URL.format(slug=slug)
        )
        return version, url
    extension = packages.get(attr.split(".", 1)[1])
    cli = (nixpkgs.get("azure-cli") or {}).get("version")
    version = extension and azure_newest(extension, cli)
    return version and (version, AZURE_URL.format(name=attr.split(".", 1)[1]))


def apply(rows: list[Row], nixpkgs, found):
    """Compare the generated sets' rows with their indexes.

    Each row compared says so ("feed"), outdated or newest against its
    index's version. Packages an index doesn't have, and the sets not read
    recently, keep Repology's verdict.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        found: load's result, or None (then nothing changes).
    """
    if not found:
        return
    for row in rows:
        version = row.get("nixVersion")
        attr = next((a for a in row.get("attrs") or [] if a.startswith(PREFIX)), None)
        if not version or not attr:
            continue
        name = attr.split(".", 1)[0]
        if name not in found:
            continue
        if newest := newest_of(name, attr, found[name], nixpkgs):
            feeds.compare(row, SETS[name], newest[0], newest[1])
