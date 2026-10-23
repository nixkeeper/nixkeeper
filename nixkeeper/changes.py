"""What changed since the previous run, for notifications."""

import re

from . import config
from .versions import is_newer, version_key


def is_outdated(row):
    """Outdated per Repology, per nixkeeper's own update check (a release
    Repology hasn't seen yet), or because master already has a newer version."""
    return (
        row.get("nixStatus") in config.OUTDATED_STATUSES
        or bool((row.get("upstream") or {}).get("newer"))
        or ahead_on_master(row)
        or behind_as_devel(row)
    )


def behind_as_devel(row):
    """A devel variant (a beta) Repology calls legacy because the stable one
    is newer: behind if a newer devel version is out elsewhere. Unlike a
    kept older series, a beta that's fallen behind is still an update to
    make."""
    return (
        row.get("nixStatus") == config.KEPT
        and bool(row.get("devel"))
        and is_newer(row.get("refVersion") or "", row.get("nixVersion"))
    )


# A suffix Repology leaves out of nixpkgs' version (firefox-esr's
# 153.5.1esr is 153.5.1 there), unlike a pre-release's.
PRE_RELEASE = re.compile(r"(?i)(a|b|c|alpha|beta|rc|pre|preview|dev|snapshot)")
SUFFIX = re.compile(r"[A-Za-z]+")


def same_release(version, channel):
    """Whether version is channel's release with a suffix Repology drops
    (153.5.1esr, 153.5.1): not a newer one."""
    rest = (version or "").removeprefix(channel or "\0")
    return (
        bool(channel)
        and rest != version
        and bool(SUFFIX.fullmatch(rest))
        and not PRE_RELEASE.fullmatch(rest)
    )


def ahead_on_master(row):
    """Hydra's build of master is newer than the channel's version: someone
    has packaged a newer release, so there is one, whether or not Repology or
    an update check has seen it yet. Not the channel's release with a suffix
    Repology drops (firefox-esr's 153.5.1esr against its 153.5.1: it read as
    on master, and outdated against Firefox's 158.0.1, 2026-10-23)."""
    master = row.get("master") or ""
    return is_newer(master, row.get("nixVersion")) and not same_release(
        master, row.get("nixVersion")
    )


def count_master(row):
    """When master is ahead of what Repology and the update checks know
    (refVersion), make its version the one to update to. The row then reads
    as outdated and, master already having it, as waiting for the channel.
    refFromMaster says where the version came from, for the page."""
    row.pop("refFromMaster", None)
    if ahead_on_master(row) and (
        not row.get("refVersion") or is_newer(row["master"], row["refVersion"])
    ):
        row["refVersion"] = row["master"]
        row["refFromMaster"] = True


PR_FIELDS = ("masterPR", "stagingPR", "openPR")


def count_prs(row):
    """When Repology calls a row outdated but names no newer version (its
    "-unclassified" projects: chatgpt 26.1007.21434, every repository also
    "outdated"), the newest an update PR of it brings, merged or open: a
    release someone has packaged. refFromPR says so, for the page; a row
    given one before (the hourly check) starts again without it."""
    if row.pop("refFromPR", None):
        row["refVersion"] = None
    if row.get("nixStatus") != "outdated" or row.get("refVersion"):
        return
    versions = [
        pr["to"]
        for pr in (row.get(k) for k in PR_FIELDS)
        if pr and pr.get("to") and is_newer(pr["to"], row.get("nixVersion") or "")
    ]
    if versions:
        row["refVersion"] = max(versions, key=version_key)
        row["refFromPR"] = True


def on_master(row):
    """The version master has, when it's ahead of the channel: what Hydra
    built there ("master"), or what an update PR merged into master brings
    ("masterPR", known before Hydra has built it), whichever is higher."""
    versions = [row.get("master"), (row.get("masterPR") or {}).get("to")]
    versions = [v for v in versions if v and not same_release(v, row.get("nixVersion"))]
    return max(versions, key=version_key, default=None)


def waiting_for_channel(row):
    """Outdated, but master already has the version it's compared against (or
    newer): the update is merged and only waits for nixos-unstable to catch up,
    usually a few days. Nothing to do but wait."""
    master = on_master(row)
    return (
        is_outdated(row)
        and bool(master)
        and not is_newer(row.get("refVersion") or "", master)
    )


def on_branch(row):
    """Outdated, and the branch that updates its set before master
    (haskell-updates, row's "branch") already has the version it's compared
    against (or newer): waiting for the branch's merge into master."""
    version = (row.get("branch") or {}).get("version")
    return (
        is_outdated(row)
        and bool(version)
        and not is_newer(row.get("refVersion") or "", version)
    )


def failed_builds(row):
    return [b for b in row.get("builds") or [] if b["status"] == "failed"]


def broken_builds(row):
    """Jobs nixpkgs marks broken: known failures, so not counted as failed."""
    return [b for b in row.get("builds") or [] if b["status"] == "broken"]


def build_label(row, build):
    """Which job failed: the platform, plus the attribute when the row has more
    than one (heroic / heroic-unwrapped)."""
    if build["attr"] == row["name"]:
        return build["system"]
    return f"{build['attr']} on {build['system']}"


# The verdicts of a row's "vulnerabilities" that make it vulnerable
# (sources/vulnerabilities_digest.py's COUNTED).
# ("byVersion": what "affected" was called before nixkeeper checked every
# version itself, 2026-10-08.)
COUNTED_VULNERABILITIES = ("affected", "byVersion", "tracker", "wontFix", "osv")


def counted_vulnerabilities(row):
    """The ids of a row's CVEs and advisories that count."""
    return [
        v["id"]
        for v in row.get("vulnerabilities") or []
        if v["verdict"] in COUNTED_VULNERABILITIES
    ]


def is_vulnerable(row):
    """Whether a row counts as vulnerable, by any of its sources: nixpkgs
    itself marks it insecure (markedInsecure); one of its CVEs or advisories
    from nixkeeper-vulnerabilities is counted ("vulnerabilities"); Repology
    flags nixpkgs' version (nixVulnerable). Repology's flag counts even where
    the digest has entries: the tracker's cover some of a package's CVEs,
    not necessarily Repology's (firefox-esr, 2026-10-08: one old CVE)."""
    return bool(
        row.get("markedInsecure")
        or row.get("nixVulnerable")
        or any(
            v["verdict"] in COUNTED_VULNERABILITIES
            for v in row.get("vulnerabilities") or []
        )
    )


def failures(row):
    """Why a row counts as failed (the page's red "failed" filter), if it does."""
    reasons = []
    if row.get("nixStatus") == "missing":
        reasons.append("not in nixpkgs")
    for build in failed_builds(row):
        reasons.append(f"build failure on {build_label(row, build)}")
    if row.get("updateFailure"):
        reasons.append("update failure reported")
    return reasons


# Changes that notify (posted as a comment), then ones only listed in the
# status issue: good news and bookkeeping shouldn't ping anyone.
NOTIFY = ("outdated", "failed", "vulnerable", "notRefreshed")
QUIET = ("caughtUp", "fixed", "broken", "refreshed", "added", "removed")

# What a source that couldn't be refreshed means for the row, for the issue.
STALE_LABELS = {
    "repology": "Repology lookup failed",
    "upstream": "nixkeeper's update check failing (package-lists/update-checks.nix)",
    "builds": "Hydra builds not refreshed",
    "update": "nixpkgs-update logs not refreshed",
}


def stale_sources(row):
    """Which of the row's sources couldn't be refreshed on its run."""
    sources = set(row.get("notRefreshed") or {})
    if row.get("staleSince"):
        sources.add("repology")
    return sources


def diff(previous, rows):
    """Rows (or names, for removed) per kind of change. Packages new to
    tracking only count as added: the first run, or a newly listed package that
    is already outdated, isn't news."""
    before = {row["name"]: row for row in previous["packages"]}
    names = {row["name"] for row in rows}
    changes = {kind: [] for kind in NOTIFY + QUIET}
    for row in rows:
        old = before.get(row["name"])
        if old is None:
            changes["added"].append(row)
            continue
        # Already fixed on master (updated before this sync noticed): not news.
        if is_outdated(row) and not is_outdated(old) and not waiting_for_channel(row):
            changes["outdated"].append(row)
        if is_outdated(old) and not is_outdated(row):
            changes["caughtUp"].append(row)
        # Per reason, so a second platform starting to fail is news too.
        now_failing, was_failing = set(failures(row)), set(failures(old))
        if now_failing - was_failing:
            changes["failed"].append(row)
        newly_broken = {build_label(row, b) for b in broken_builds(row)} - {
            build_label(old, b) for b in broken_builds(old)
        }
        if newly_broken:
            changes["broken"].append(row)
        # A failure nixpkgs now marks broken isn't fixed, just acknowledged.
        elif was_failing and not now_failing:
            changes["fixed"].append(row)
        # Newly vulnerable, or vulnerable to a CVE it wasn't before.
        if is_vulnerable(row) and (
            not is_vulnerable(old)
            or set(counted_vulnerabilities(row)) - set(counted_vulnerabilities(old))
        ):
            changes["vulnerable"].append(row)
        # Per source: Hydra failing too, a day after an update check, is news.
        now_stale, was_stale = stale_sources(row), stale_sources(old)
        if now_stale - was_stale:
            changes["notRefreshed"].append(row)
        if was_stale - now_stale:
            changes["refreshed"].append(row)
    changes["removed"] = sorted(name for name in before if name not in names)
    return changes


def should_notify(changes):
    return any(changes[kind] for kind in NOTIFY)
