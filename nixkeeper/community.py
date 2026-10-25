"""Read the community's rules, and check that they still work.

The community lists (community/) hold rules anyone can contribute by PR,
for any nixpkgs package, in the format of your own lists:

- update checks (update-checks.nix), where to look for new releases;
- ignored updates (ignored-updates.nix), failed nixpkgs-update attempts that
  don't count (a version that was never really released);
- up-to-date rules (up-to-date.nix), versions Repology gets wrong
  (nixkeeper/uptodate.py).

Each kind is opt-in in the package lists:

    community = { updateChecks = true; ignoredUpdates = true; upToDate = true; };

Then each sync uses the community's rules for the packages it tracks, your
own winning over the community's (for an update check or an up-to-date rule,
per package; for an ignore rule, per version). The rules come with nixkeeper
(the version you have pinned): new ones arrive when you update it, never in
between.

Community update checks run on every subscriber's machine, so they're held
to limits your own aren't (safety(), and http.get's safe mode): an unsafe one
is refused and reported, never fetched. Ignore and up-to-date rules fetch
nothing.

`nixkeeper community-check`, which runs the rules for real and keeps the
community rules' status issue up to date, is community_check.py.
"""

import ipaddress
import json
import os
import re
import subprocess
from importlib import resources
from urllib.parse import urlsplit

from . import log

# Where the package carries the files (copied in from community/ when it's
# built), and where a checkout has them.
_PACKAGED = resources.files("nixkeeper") / "community"
_CHECKOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "community")
# The community files, in community/.
CHECKS = "update-checks.nix"
IGNORES = "ignored-updates.nix"
UP_TO_DATE = "up-to-date.nix"

# The fields a community rule may have (as your own rules: github + tags,
# github + branch (+ outdatedAfter), or url + pattern, and frequent).
FIELDS = {
    "github",
    "tags",
    "branch",
    "outdatedAfter",
    "url",
    "pattern",
    "frequent",
    "follows",
}
# A nixpkgs attribute, for follows: letters, digits, _ - + ' and dots between.
ATTRIBUTE = re.compile(r"^[A-Za-z_][A-Za-z0-9_'+-]*(?:\.[A-Za-z_][A-Za-z0-9_'+-]*)*$")
# A GitHub owner (letters, digits, hyphens) and repository (not "." or "..").
GITHUB_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/(?!\.\.?$)[A-Za-z0-9_.-]+$")
# Hostnames that only mean something on a local network.
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
# The longest a community rule's pattern may be.
MAX_PATTERN = 200
# A group with a repeat inside that is repeated itself, like (a+)+ or (\w*)*:
# the shape that can take a very long time on a page that almost matches.
NESTED_REPEAT = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)[+*{]")


def path(name=CHECKS):
    """Return a community file's path: the package's copy, or a checkout's."""
    if (_PACKAGED / name).is_file():
        return str(_PACKAGED / name)
    return os.path.normpath(os.path.join(_CHECKOUT, name))


def opted(lists, kind):
    """Return whether the lists opt in to the community's kind of rules.

    kind is "updateChecks", "ignoredUpdates" or "upToDate"; the lists opt
    in with `community.<kind> = true;`.
    """
    return (lists.get("community") or {}).get(kind) is True


def rules(file=None):
    """Read a community file, evaluated with Nix.

    Args:
        file: The file; the update checks by default.

    Returns:
        {package name: rule}, or {} with a warning when it can't be read.
    """
    file = file or path()
    try:
        result = subprocess.run(
            [
                "nix",
                "eval",
                "--extra-experimental-features",
                "nix-command flakes",
                "--json",
                "-f",
                file,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        detail = getattr(e, "stderr", None) or e
        log.warn(f"community update checks: couldn't read {file} ({detail})")
        return {}


def ignores(file=None):
    """Return the community's ignore rules: {package name: {version: reason}}."""
    return rules(file or path(IGNORES))


def up_to_date(file=None):
    """Return the community's up-to-date rules.

    Returns:
        {package name: {"version", "newest"?, "reason"}}.
    """
    return rules(file or path(UP_TO_DATE))


def merge_up_to_date(lists, tracked):
    """Return the up-to-date rules to apply.

    They're your own, plus the community's for packages you track and have
    no rule of your own for (only with `community.upToDate = true;`).

    Returns:
        (rules, the names of the community's).
    """
    own = lists.get("upToDate") or {}
    if not opted(lists, "upToDate"):
        return own, set()
    merged = dict(own)
    from_community = set()
    for name, version in up_to_date().items():
        if name not in set(tracked):
            continue
        if name not in merged:
            merged[name] = version
            from_community.add(name)
    return merged, from_community


def merge_ignores(lists, tracked):
    """Return the ignore rules to apply.

    They're your own, plus the community's for packages you track (only
    with `community.ignoredUpdates = true;`); your reason wins for the same
    version.

    Returns:
        (rules, {(name, version)} of the community's).
    """
    own = lists.get("ignoredUpdates") or {}
    if not opted(lists, "ignoredUpdates"):
        return own, set()
    merged = {name: dict(versions) for name, versions in own.items()}
    from_community = set()
    for name, versions in ignores().items():
        if name not in set(tracked):
            continue
        for version, reason in versions.items():
            if version not in merged.setdefault(name, {}):
                merged[name][version] = reason
                from_community.add((name, version))
    return merged, from_community


def merge(lists, tracked):
    """Return the update checks to run.

    They're your own, plus the community's for packages you track and have
    no rule of your own for (only with `community.updateChecks = true;`).

    Returns:
        (checks, the names of the community's).
    """
    own = lists.get("updateChecks") or {}
    if not opted(lists, "updateChecks"):
        return own, set()
    community = {
        name: rule
        for name, rule in rules().items()
        if name in set(tracked) and name not in own
    }
    if community:
        log.info(f"Community update checks for: {', '.join(sorted(community))}")
    return {**own, **community}, set(community)


def is_public_host(host):
    """Return whether host is a name on the public internet.

    Not when it's an IP address written out, localhost, or a local-network
    name (LOCAL_SUFFIXES).
    """
    host = (host or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False  # an address written out, not a name
    except ValueError:
        return "." in host


def safety(rule):
    """Return why a community rule can't run, or None if it can.

    It can't when it isn't a rule at all (not an attrset), or with an
    unknown field; a malformed github; a follows that's malformed or has
    other fields beside it; a url that isn't https to a public host, or
    that names a port or credentials; or a pattern that's too long or
    could take very long to match (a nested repeat, or a reference back to
    a group).
    """
    if not isinstance(rule, dict):
        return "not a rule"
    unknown = set(rule) - FIELDS
    if unknown:
        return f"unknown field {', '.join(sorted(unknown))}"
    if "follows" in rule:
        # Fetches nothing: only another package's results are used.
        if set(rule) != {"follows"}:
            return "follows takes no other fields"
        if not ATTRIBUTE.match(str(rule["follows"])):
            return "follows must be a nixpkgs attribute"
        return None
    if "github" in rule and not GITHUB_REPO.match(str(rule["github"])):
        return 'github must be "owner/repo"'
    if "url" in rule:
        parts = urlsplit(str(rule["url"]))
        if parts.scheme != "https":
            return "url must be https://"
        if parts.port not in (None, 443) or parts.username or parts.password:
            return "url can't name a port or credentials"
        if not is_public_host(parts.hostname):
            return "url must name a public host, not an address or local name"
    for field in ("tags", "pattern"):
        pattern = rule.get(field)
        if pattern is None:
            continue
        if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN:
            return f"{field} must be a pattern of at most {MAX_PATTERN} characters"
        if NESTED_REPEAT.search(pattern) or re.search(r"\\[1-9]", pattern):
            return f"{field} repeats a repeat or refers back to a group: too slow"
    return None


def problems(rules):
    """Return what's wrong with community rules beyond their format, for CI.

    The format is nix/package-lists.nix's to check. These are the limits
    (safety), the patterns as Python compiles them, and the follows
    (follows_problems).

    Returns:
        ["name: why", ...], sorted.
    """
    found = []
    for name, rule in sorted(rules.items()):
        if why := safety(rule):
            found.append(f"{name}: {why}")
            continue
        for field in ("tags", "pattern"):
            if field in rule:
                try:
                    if re.compile(rule[field]).groups > 1:
                        found.append(f"{name}: {field} has more than one capture group")
                except re.error as e:
                    found.append(f"{name}: {field} is not a valid regex ({e})")
    found += follows_problems(rules)
    return sorted(found)


def follows_problems(rules):
    """Return the rules that follow themselves, or a package that follows another.

    There are no chains: follows.py would skip them.
    """
    following = {
        name: rule["follows"]
        for name, rule in rules.items()
        if isinstance(rule, dict) and isinstance(rule.get("follows"), str)
    }
    found = []
    for name, target in sorted(following.items()):
        if target == name:
            found.append(f"{name}: follows itself")
        elif target in following:
            found.append(f"{name}: follows {target}, which follows another package")
    return found
