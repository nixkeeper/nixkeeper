"""Turn Repology projects into the page's rows.

A row is one package as the page shows it: its version in nixpkgs, its
status, the version it's compared with ("refVersion"), and what nixpkgs'
package index says about it (platforms, maintainers, teams, ...). Most of
this module decides that comparison, correcting Repology's verdict where it
doesn't fit nixpkgs: older series kept beside newer ones, snapshots,
commits, and nixpkgs' own release channels.
"""

import dataclasses
import hashlib
import os
import re

from . import config
from .shape import Row
from .sources.nixpkgs import platforms
from .versions import (
    RELEASE_WORDS,
    UNSTABLE,
    is_newer,
    is_pre_release,
    version_key,
    without_release_words,
)


def search_term(attr):
    """Return what the GitHub PR and issue searches look for, for attr.

    That's the attribute name, except that versioned sets are written with
    the alias nixpkgs uses in PR titles (config.SEARCH_ALIASES).
    """
    for pattern, alias in config.SEARCH_ALIASES:
        attr = pattern.sub(alias, attr)
    return attr


# An attribute named for a development channel (wesnoth-devel, foo-beta,
# bar_unstable, baz-nightly, code-insiders).
DEVEL_NAME = re.compile(
    r"[-_.](devel|dev|beta|alpha|unstable|nightly|rc|preview|insiders|canary|git)$"
)


def name_blockers(rows):
    """Turn each dependency-failed build's blockedBy into the page's links.

    The Hydra digest names the blocking dependencies by attribute, or by
    store name when no job builds them. One that is a row's attribute
    becomes {"name": the row's name, "row": True}; any other, {"name": the
    attribute or store name as it is}. Builds already converted are left as
    they are.

    Args:
        rows: Every row. Their builds are changed in place.
    """
    by_attr = {a: row["name"] for row in rows for a in row.get("attrs") or []}
    for row in rows:
        for build in row.get("builds") or []:
            if build.get("blockedBy") and isinstance(build["blockedBy"][0], str):
                build["blockedBy"] = [
                    {"name": by_attr[a], "row": True} if a in by_attr else {"name": a}
                    for a in build["blockedBy"]
                ]


def row_name(attrs):
    """Return the attribute a row is named after.

    That's the first top-level attribute in sorted order, else the first
    one: cmake, not azure-sdk-for-cpp.cmake (a set passing cmake on).
    """
    return min(attrs, key=lambda a: ("." in a, a))


def project_rows(proj, nixpkgs):
    """Make the rows for one Repology project.

    Usually there's one row. When the nixpkgs attributes the lists track
    have different versions (wesnoth and wesnoth-devel), there's one row
    per version; attributes sharing a version (heroic and heroic-unwrapped)
    share a row.

    Args:
        proj: The project as looked up (by lookup), with "entries",
            "attrs" and "name".
        nixpkgs: The package index, by attribute.

    Returns:
        The rows.
    """
    entries = proj["entries"]
    nix_all = [e for e in entries if e.get("repo") == config.NIX_REPO]
    others = [e for e in entries if e.get("repo") != config.NIX_REPO]

    groups = {}  # {version: the nixpkgs entries of the tracked attributes}
    for e in nix_all:
        if e.get("srcname") in proj["attrs"]:
            groups.setdefault(e.get("version"), []).append(e)
    if len(groups) < 2:
        nix = next(iter(groups.values()), nix_all)[:1]
        attrs = sorted(proj["attrs"])
        # Named after its nixpkgs attribute, as the lists and the GitHub
        # searches name it, or after the list's entry when nixpkgs doesn't
        # have it.
        name = row_name(attrs) if attrs else proj["name"]
        return [
            make_row(
                proj, name, attrs, nix[0] if nix else None, others, nixpkgs, devel=False
            )
        ]

    # The stable variant comes first: the one Repology calls newest, else
    # the one with the shortest attribute (wesnoth before wesnoth-devel). In
    # a project whose versions are all kept series (coq's, once its current
    # series moved to rocq), the newest version comes first instead
    # (coq_8_20, not coq_8_7); otherwise every newer series would be a devel
    # variant, behind. The other groups are devel variants, compared with
    # devel versions, when they're newer than the stable one or named as one
    # (wesnoth-devel, _1password-gui-beta); otherwise they're older versions
    # kept beside it (gnumake42, php82Extensions.zip).
    ordered = sorted(
        groups.values(),
        key=lambda g: (
            not any(e.get("status") == "newest" for e in g),
            min(len(e["srcname"]) for e in g),
            min(e["srcname"] for e in g),
        ),
    )
    if all(e.get("status") == config.KEPT for g in ordered for e in g):
        top = max(ordered, key=lambda g: version_key(g[0].get("version") or ""))
        ordered = [top, *(g for g in ordered if g is not top)]
    stable = version_key(ordered[0][0].get("version") or "")
    rows = []
    for i, group in enumerate(ordered):
        attrs = sorted(e["srcname"] for e in group)
        devel = i > 0 and (
            version_key(group[0].get("version") or "") > stable
            or any(DEVEL_NAME.search(a) for a in attrs)
        )
        rows.append(
            make_row(
                proj, row_name(attrs), attrs, group[0], others, nixpkgs, devel=devel
            )
        )
    return rows


# A version's parts: runs of letters or of digits.
VERSION_PART = re.compile(r"[A-Za-z]+|[0-9]+")
# Build metadata, which doesn't make a release newer (jdk's 21.0.12+8.2
# beside 21.0.12.1+1).
BUILD = re.compile(r"\+.*")
# The Repology statuses a version needs to count in its series: not one
# Repology distrusts or can't order, nor a rolling one (3.13.9999).
SERIES_STATUSES = {"newest", "outdated", "legacy", "unique"}
# How many distributions must have a version for it to count in a kept
# series, as it would make the package outdated. Repositories named alike
# are one distribution (debian_13 and debian_unstable). A version in one
# alone is often its own packaging (eigen2 2.0.55, firebird 4.0.7.3271 in
# EPEL).
SERIES_REPOS = 2
# In a series named by its first part alone, a second part more than twice
# the version's plus this is another numbering (zulu17's 17.68.203 for
# 17.0.19) or the next major version's previews (gimp2's 2.99.10 for
# 2.10.38), not a release of the series. 535.309 for 535.288 still counts.
SERIES_JUMP = 5


def named_parts(name, parts):
    """Return how many of a version's numbers the attribute's name spells.

    The trailing digits of the attribute's last part are matched against
    the version's numbers: python313 spells 2 (3.13), glew_1_10 2, icu60 1,
    sbcl_2_4_6 3.

    Args:
        name: The attribute.
        parts: The version's parts (plain_version).

    Returns:
        How many numbers, or 0 when the digits don't spell the version's
        start.
    """
    m = re.search(r"[0-9][0-9_]*$", name.rsplit(".", 1)[-1])
    if not m:
        return 0
    digits = m.group().replace("_", "")
    spelled = ""
    for i, part in enumerate(p for p in parts if p.isdigit()):
        spelled += part
        if spelled == digits:
            return i + 1
        if not digits.startswith(spelled):
            return 0
    return 0


def plain_version(version):
    """Split version into parts, without release words or build metadata.

    4.5.1-stable gives ["4", "5", "1"], and 21.0.12.1+1 gives ["21", "0",
    "12", "1"].
    """
    return VERSION_PART.findall(BUILD.sub("", without_release_words(version)))


# What a distribution's snapshot adds to the release it follows: a date,
# maybe with a word before it and a commit after (0.3.0.20240120,
# 1.2.0+20251126, 1.04-20190106, 2.1-git20240301.abc1234).
SNAPSHOT_ADDED = re.compile(
    r"[-_.+~]?(?:git|svn|hg|snapshot|p|r)?[-_.+~]?"
    r"20[0-9]{2}(?:0[1-9]|1[0-2])(?:[0-2][0-9]|3[01])(?:[-_.+]?[0-9a-f]{4,12})?",
    re.IGNORECASE,
)


def snapshot_only(version, newest, others):
    """Return whether newest is only a distribution's snapshot of version.

    That's version with a date added, in one distribution only and in no
    upstream index (mintotp's 0.3.0.20240120, in SlackBuilds alone). Not
    when PyPI or another upstream index has it (iso4217's 1.16.20260101 is
    a release), nor when several distributions do (fcitx5-pinyin-zhwiki's
    0.3.0.20260416: the date is the dictionary's).
    """
    if not version or not newest.startswith(version):
        return False
    if not SNAPSHOT_ADDED.fullmatch(newest[len(version) :]):
        return False
    repos = {e.get("repo", "") for e in others if e.get("version") == newest}
    return (
        bool(repos)
        and not repos & config.UPSTREAM_INDEXES
        and len({r.split("_")[0] for r in repos}) == 1
    )


# nixpkgs' spelling of a snapshot version, with nothing (or 0) before the
# date: unstable-2022-10-20, 0-unstable-2012-12-08.
NIX_SNAPSHOT = re.compile(r"(?:0-)?unstable-([0-9]{4}-[0-9]{2}-[0-9]{2})")


def same_snapshot(version, newest):
    """Return whether newest is another spelling of nixpkgs' snapshot version.

    That's the date alone: gawkextlib.csv's unstable-2022-10-20, which
    nixpkgs' older channels spelled 2022-10-20, and which Repology ranks
    above it.
    """
    match = NIX_SNAPSHOT.fullmatch(version or "")
    return bool(match) and match[1] == newest


def old_channels(others):
    """Return the nixpkgs release channels in others older than the newest.

    The older channels (nix_stable_25_11 beside nix_stable_26_05) get no
    more updates, so a version only they have isn't a release nixpkgs is
    behind. The newest channel isn't among them: it can be ahead of
    unstable for real, when a backport lands there first (msedgedriver).

    Args:
        others: The project's entries from repositories other than nixpkgs
            unstable.

    Returns:
        The channels' repository names.
    """
    channels = {
        e.get("repo", "") for e in others if e.get("repo", "").startswith("nix_stable_")
    }
    newest = max(channels, default=None)
    return channels - {newest}


# A commit named in a version (tree-sitter grammars' 0.0.0+rev=e45dbac).
COMMIT = re.compile(r"rev=[0-9a-f]{7,40}")


def commit_only(version, newest):
    """Return whether version and newest differ only by the commit they name.

    Commit hashes have no order, so newest isn't newer. Repology compares
    them as letters: nvim-treesitter-parsers.liquid's rev=e45dbac ranks
    below 26.05's rev=9566ca7.
    """
    return (
        bool(version and newest)
        and version != newest
        and bool(COMMIT.search(version))
        and COMMIT.sub("", version) == COMMIT.sub("", newest)
    )


# The version nixpkgs gives a package it doesn't build in its default
# configuration (cudaPackages.cuda_compat, for the CUDA version it defaults
# to).
UNSUPPORTED = "0-unsupported"


def ignored_channels(nix_version, others):
    """Return the nixpkgs release channels whose versions don't count.

    Usually that's the old ones (old_channels). When an upstream index
    (PyPI, CRAN, ...) has nixpkgs' own version, it's all of them, as the
    index says what's released: python3Packages.azure-ai-vision-
    imageanalysis is 1.0.0 on PyPI and in nixpkgs unstable, while 25.11 and
    26.05 still have 39.0.0, a mistake unstable reverted.

    Args:
        nix_version: nixpkgs unstable's version.
        others: The project's entries from repositories other than nixpkgs
            unstable.

    Returns:
        The channels' repository names.
    """
    if any(
        e.get("repo") in config.UPSTREAM_INDEXES and e.get("version") == nix_version
        for e in others
    ):
        return {
            e.get("repo", "")
            for e in others
            if e.get("repo", "").startswith("nix_stable_")
        }
    return old_channels(others)


def own_version_only(version, nix_version, others):
    """Return whether only ignored nixpkgs channels have version.

    Such a version is nixpkgs' own earlier one, not a release: a numbering
    nixpkgs has changed since (yaziPlugins' 25.5.31-unstable-2025-06-18,
    before 0-unstable-2026-09-30), or a mistake since reverted (azure's
    39.0.0).

    Args:
        version: The version nixpkgs is compared with.
        nix_version: nixpkgs unstable's version.
        others: The project's entries from repositories other than nixpkgs
            unstable.
    """
    repos = {e.get("repo", "") for e in others if e.get("version") == version}
    return bool(repos) and repos <= ignored_channels(nix_version, others)


def not_packaging(families):
    """Return the versions that aren't only a packaging of another version.

    A version is a packaging when it adds a part (after ".", "_" or "-") to
    another version that as many distributions or more have: Chocolatey's
    ruby 3.4.11.1 beside 3.4.11, Baulk's curl 8.23.0.1 beside 8.23.0, AUR's
    rakudo 2026.09_01 beside 2026.09.

    Args:
        families: {version: the distributions that have it}.

    Returns:
        The other versions.
    """
    return [
        v
        for v, f in families.items()
        if not any(
            v.startswith(o)
            and v[len(o) : len(o) + 1] in (".", "_", "-")
            and len(g) >= len(f)
            for o, g in families.items()
            if o != v
        )
    ]


def series_ref(name, version, entries, others, kept=False):
    """Return the newest release in version's own series, or None.

    This is for an older series nixpkgs keeps beside a newer series of the
    same project, under another attribute (python313 beside python315). The
    older one is compared within its series: python313's 3.13.15 with
    3.13.16, not with Python's newest.

    The series is the versions sharing version's parts up to the first part
    where it differs from nixpkgs' next newer series (3.13 for 3.13.15
    beside 3.15.0), or as many parts as the attribute's name spells
    (electron_40: 40), whichever is more. For a kept series (kept) of three
    numbers or more whose name spells none, it's at least two parts (tcl
    8.6.16 beside 9.0: the series is 8.6, so 8.7 isn't in it). There's no
    series for a snapshot, nor when the name spells the whole version
    (sbcl_2_4_6).

    The releases counted are those of repositories outside nixpkgs (for a
    kept series, those two distributions or more have), in version's shape.
    Pre-releases don't count, nor versions that add words, a revision
    (1.91.0-1), or, to a version of three numbers or more, a further part
    (for 26.08, 26.08.1 still counts).

    Args:
        name: The row's attribute.
        version: nixpkgs' version.
        entries: The project's Repology entries, nixpkgs' included.
        others: The entries from repositories other than nixpkgs unstable.
        kept: Whether version is a kept series (config.KEPT).

    Returns:
        The newest release counted, when it's newer than version; else
        None.
    """
    if not version or UNSTABLE.search(version):
        return None
    newer = [
        e["version"]
        for e in entries
        if e.get("repo") == config.NIX_REPO
        and e.get("version")
        and not is_pre_release(e["version"])
        and is_newer(e["version"], version)
    ]
    if not newer:
        return None
    mine = plain_version(version)
    # The next series: of nixpkgs' newer versions, preferably one whose
    # first part differs, rather than a newer release of version's own
    # series packaged another way (thunderbird-esr-bin's 153.5.0 beside
    # thunderbird-153's 153.4.0 made the series 153.4, missing 153.5.1,
    # 2026-10-23). Otherwise the nearest (python314 beside python313).
    apart = [v for v in newer if VERSION_PART.findall(v)[:1] != mine[:1]]
    sibling = VERSION_PART.findall(min(apart or newer, key=version_key))
    at = next(
        (i for i, (a, b) in enumerate(zip(mine, sibling, strict=False)) if a != b), None
    )
    if at is None:
        return None
    numbers = sum(p.isdigit() for p in mine)
    named = named_parts(name, mine)
    if named and named >= numbers:
        return None
    width = max(at + 1, named)
    if kept and not named and numbers >= 3:
        width = max(width, 2)
    words = {p.lower() for p in mine if not p.isdigit()}
    families = {}
    for e in others:
        v = e.get("version")
        if (
            e.get("status") not in SERIES_STATUSES
            or not v
            or e.get("repo", "").startswith("nix_")
            or is_pre_release(v)
            or "~" in v  # Debian's pre-releases (21.0.13~8ea)
        ):
            continue
        theirs = plain_version(v)
        if (
            theirs[:width] != mine[:width]
            # The same shape: numbers where version has numbers.
            or any(
                a.isdigit() != b.isdigit() for a, b in zip(theirs, mine, strict=False)
            )
            or {p.lower() for p in theirs if not p.isdigit()} - words
            or (
                width == 1
                and numbers >= 3
                and len(theirs) > 1
                and theirs[1].isdigit()
                and int(theirs[1]) > 2 * int(mine[1]) + SERIES_JUMP
            )
        ):
            continue
        ours, release = BUILD.sub("", version), BUILD.sub("", v)
        added = release[len(ours) : len(ours) + 1]
        if release.startswith(ours) and added and added in "-_" + "." * (numbers >= 3):
            continue
        # Counted by distribution: debian_13 and debian_unstable are one, as
        # are manjaro_stable and manjaro_testing.
        families.setdefault(v, set()).add(e.get("repo", "").split("_")[0])
    found = {
        v: f for v, f in families.items() if len(f) >= (SERIES_REPOS if kept else 1)
    }
    best = max(not_packaging(found), key=version_key, default=None)
    plain = BUILD.sub("", without_release_words(version))
    return best if best and is_newer(BUILD.sub("", best), plain) else None


def make_row(proj, name, attrs, nix, others, nixpkgs, devel) -> Row:
    """Make one row from a project's entries.

    The row starts from Repology's verdict on nixpkgs' entry. Then, when
    nixpkgs has an entry, each of CORRECTIONS corrects it where it doesn't
    fit nixpkgs, in that order. Then it gets what nixpkgs' package index
    says (_add_from_index).

    Args:
        proj: The project (as looked up by lookup).
        name: The row's name.
        attrs: The row's attributes, sorted.
        nix: nixpkgs unstable's Repology entry for the row, or None when
            Repology doesn't list one.
        others: The project's entries from repositories other than nixpkgs
            unstable.
        nixpkgs: The package index, by attribute.
        devel: Whether the row is a devel variant (project_rows).

    Returns:
        The row.
    """
    row: Row = {
        "name": name,
        # The attribute name, which unlike the pname tells variants apart
        # (_1password-gui and _1password-gui-beta both have pname
        # "1password").
        "searchTerm": search_term(name) if attrs else name,
        "project": proj["project"],
        "dataFile": proj["dataFile"],
        "attrs": attrs,
        "nixVersion": nix.get("version") if nix else None,
        "nixStatus": nix.get("status") if nix else "missing",
        "nixVulnerable": bool(nix.get("vulnerable")) if nix else False,
        # When only nixpkgs packages it (msedgedriver), Repology marks no
        # repository newest, but marks the one ahead unique (a release
        # channel with a backport, say): compared with it, nixpkgs unstable
        # can still be outdated.
        "refVersion": (devel and _newest("devel", nix, others))
        or _newest("newest", nix, others)
        or _newest("unique", nix, others),
        # Repositories, not entries: one can list a package several times.
        "repoCount": len({e.get("repo") for e in others}),
        # No repository outside nixpkgs has it (nixpkgs' release channels
        # don't count as another). Repology's "unique" then compared it with
        # nothing (datastore.nothing_compared).
        **(
            {"onlyNixpkgs": True}
            if not any(not e.get("repo", "").startswith("nix_") for e in others)
            else {}
        ),
        # A devel variant of a split project, or a version Repology itself
        # classifies as devel (lincity).
        "devel": devel or (nix or {}).get("status") == "devel",
    }
    if nix:
        found = _Found(name, nix, proj["entries"], others, devel)
        for correct in CORRECTIONS:
            correct(row, found)
    _add_from_index(row, [nixpkgs[a] for a in attrs if a in nixpkgs], nix)
    return row


def _newest(status, nix, others):
    """Return the highest version with status among the other repositories.

    For an outdated package, that's the version to update to, so a
    packaging of another version doesn't count (not_packaging: curl 8.23.0,
    not Baulk's 8.23.0.1), unless that leaves nothing newer than nixpkgs'
    own.

    Args:
        status: The Repology status to look for ("newest", "devel", ...).
        nix: nixpkgs unstable's Repology entry, or None.
        others: The project's entries from repositories other than nixpkgs
            unstable.
    """
    families = {}
    for e in others:
        if e.get("status") == status and e.get("version"):
            families.setdefault(e["version"], set()).add(
                e.get("repo", "").split("_")[0]
            )
    highest = max(families, key=version_key, default=None)
    if (nix or {}).get("status") != "outdated":
        return highest
    best = max(not_packaging(families), key=version_key, default=None)
    # Unless that leaves nothing newer than nixpkgs' own: then the added
    # part may be a real release, seen first in one distribution.
    mine = nix.get("version") or ""
    return best if is_newer(best or "", mine) else highest


@dataclasses.dataclass(frozen=True)
class _Found:
    """What the corrections read: a row's name, and Repology's entries for it.

    Attributes:
        name: The row's name.
        nix: nixpkgs unstable's Repology entry for the row.
        entries: The project's Repology entries, nixpkgs' included.
        others: Those from repositories other than nixpkgs unstable.
        devel: Whether project_rows split the row off as a devel variant.
            row["devel"] also counts Repology's own devel status; the
            corrections read each where the old code did, so don't
            swap one for the other.
    """

    name: str
    nix: dict
    entries: list
    others: list
    devel: bool

    @property
    def outdated(self):
        """Whether Repology calls nixpkgs' version outdated."""
        return self.nix.get("status") == "outdated"

    @property
    def version(self):
        """nixpkgs unstable's version, as Repology has it."""
        return self.nix.get("version")


# The corrections below each correct a row in place, where Repology's verdict
# doesn't fit nixpkgs. make_row applies them in CORRECTIONS' order, which
# matters: each reads the row as the ones before it left it.


def _within_own_series(row: Row, found):
    """Compare an older series kept beside a newer one within its own series.

    python313's 3.13.15 is compared with 3.13.16, not with Python's newest,
    3.15.0, which python315 has.
    """
    if (
        not row["devel"]
        and found.outdated
        and (ref := series_ref(found.name, found.version, found.entries, found.others))
    ):
        row["refVersion"] = ref


def _release_word(row: Row, found):
    """Call nixpkgs' version newest when only a word naming the release differs.

    Repology ranks such a word lower: godot's 4.7.2-stable against 4.7.2.
    Not when nixpkgs is ahead, which Repology's rules have reasons for
    (xcircuit 3.10.42 against 3.9.73).
    """
    if (
        found.outdated
        and row["refVersion"]
        and RELEASE_WORDS.search(found.version or "")
        and version_key(without_release_words(found.version))
        == version_key(row["refVersion"])
    ):
        row["nixStatus"] = "newest"


def _distribution_snapshot(row: Row, found):
    """Call nixpkgs' version newest when only a distribution's snapshot is newer.

    That's one distribution's snapshot of this same release:
    python3Packages.mintotp's 0.3.0, against SlackBuilds' 0.3.0.20240120.
    """
    if (
        found.outdated
        and row["refVersion"]
        and snapshot_only(found.version, row["refVersion"], found.others)
    ):
        row["nixStatus"] = "newest"


def _same_snapshot(row: Row, found):
    """Call nixpkgs' version newest when the newer one is the same snapshot.

    That's another spelling of the same snapshot, mostly in nixpkgs' own
    older channels (104 rows on 2026-10-20).
    """
    if found.outdated and same_snapshot(found.version, row["refVersion"]):
        row["nixStatus"] = "newest"


def _own_earlier_version(row: Row, found):
    """Compare with the other repositories when only nixpkgs' own is newer.

    That's a row behind only nixpkgs' own earlier version (231 rows on
    2026-10-20). It's outdated against the other repositories' newest when
    that's newer; otherwise newest (or unique, when nobody else packages
    it).
    """
    if (
        row["devel"]
        or row["nixStatus"] != "outdated"
        or not row["refVersion"]
        or not own_version_only(row["refVersion"], found.version, found.others)
    ):
        return
    old = ignored_channels(found.version, found.others)
    rest = [
        e["version"]
        for e in found.others
        if e.get("repo") not in old
        and e.get("status") in SERIES_STATUSES
        and e.get("version")
    ]
    best = max(rest, key=version_key, default=None)
    row["refVersion"] = best
    if not (best and is_newer(best, found.version or "")):
        row["nixStatus"] = "newest" if rest else "unique"


def _other_commit(row: Row, found):
    """Call nixpkgs' version newest when it's behind only another commit.

    That's another commit on a nixpkgs channel (75 rows on 2026-10-20,
    tree-sitter grammars against 26.05's). Commits have no order to say
    which is newer, and unstable is the one that moves on.
    """
    others = found.others
    if (
        row["nixStatus"] == "outdated"
        and commit_only(found.version, row["refVersion"])
        and {e.get("repo", "") for e in others if e.get("version") == row["refVersion"]}
        <= {e.get("repo", "") for e in others if e.get("repo", "").startswith("nix_")}
    ):
        row["nixStatus"] = "newest"
        row["refVersion"] = found.version


def _unsupported(row: Row, found):
    """Leave a version nixpkgs doesn't build by default uncompared.

    UNSUPPORTED isn't a version, so there's nothing to compare (10 rows were
    outdated by it on 2026-10-20).
    """
    if found.version == UNSUPPORTED:
        row["nixStatus"] = "unsupported"
        row["refVersion"] = None


def _kept_series(row: Row, found):
    """Work out what an older version kept beside a newer one is kept beside.

    That's a version Repology calls legacy (config.KEPT). It gets
    "keptBeside", for the page, unless it's really the main line (newer
    only as a beta nixpkgs also has); and it's outdated when it's behind in
    its own series.
    """
    if found.nix.get("status") != config.KEPT:
        return
    newer = [
        e
        for e in found.entries
        if e.get("repo") == config.NIX_REPO
        and e.get("version")
        and version_key(e["version"]) > version_key(found.version or "")
    ]
    if newer and not found.devel and all(is_pre_release(e["version"]) for e in newer):
        # Newer only as a beta nixpkgs also has (firefox beside
        # firefox-devedition's 158.0b1): Repology calls it legacy, but it's
        # the main line, compared with the newest release like any other.
        ref = row["refVersion"]
        behind = ref and is_newer(ref, found.version or "")
        row["nixStatus"] = "outdated" if behind else "newest"
        return
    if not newer:
        return
    # Beside its newer release rather than a beta, when nixpkgs has both
    # (firefox-esr beside firefox 158.0, not firefox-devedition).
    newer = [e for e in newer if not is_pre_release(e["version"])] or newer
    best = max(version_key(e["version"]) for e in newer)
    # Of those with that version, the one with the plainest name (tracy, not
    # tracy_0_14).
    top = min(
        (e for e in newer if version_key(e["version"]) == best),
        key=lambda e: (len(e.get("srcname") or ""), e.get("srcname") or ""),
    )
    row["keptBeside"] = {"attr": top.get("srcname"), "version": top["version"]}
    # Repology's vulnerable flag judges it by the newer series' CVE ranges,
    # but an older series kept on purpose gets its fixes backported
    # (firefox-esr 153.5.1 was flagged with nothing open in the tracker,
    # 2026-10-23). The security tracker's and OSV's verdicts, checked
    # against its version, decide instead.
    row.pop("nixVulnerable", None)
    # Kept, but behind in its own series (glibmm_2_4 2.66.8, with 2.66.10
    # out): outdated against that, and still kept beside the newer one.
    if not found.devel and (
        ref := series_ref(
            found.name, found.version, found.entries, found.others, kept=True
        )
    ):
        row["nixStatus"] = "outdated"
        row["refVersion"] = ref


# The corrections make_row applies to a row nixpkgs has an entry for, in
# this order.
CORRECTIONS = (
    _within_own_series,
    _release_word,
    _distribution_snapshot,
    _same_snapshot,
    _own_earlier_version,
    _other_commit,
    _unsupported,
    _kept_series,
)


def _add_from_index(row: Row, pkgs, nix):
    """Add what nixpkgs' package index says of the row's packages.

    Args:
        row: The row, changed in place.
        pkgs: The package index's entries for the row's attributes; none
            for a package not in nixpkgs, which has no platforms, homepage
            or maintainers.
        nix: nixpkgs unstable's Repology entry for the row, or None.
    """
    if pkgs and not nix:
        # In nixpkgs, but Repology doesn't list nixpkgs' package: either it
        # isn't on Repology at all (read in bulk, with every package), or it
        # was found by name in a project of other repositories only
        # (Repology leaves out nixpkgs packages whose version it can't read:
        # keeperrl's "alpha34", airstrike's "pre6a"). The row gets nixpkgs'
        # version and nothing to compare it with: "unlisted", not "missing",
        # which says nixpkgs doesn't have it.
        row["nixVersion"] = pkgs[0].get("version")
        row["nixStatus"] = "unlisted"
    if not pkgs:
        return
    row["platforms"] = platforms(pkgs)
    homepage = next(
        (p["meta"].get("homepage") for p in pkgs if p["meta"].get("homepage")), None
    )
    row["homepage"] = homepage[0] if isinstance(homepage, list) else homepage
    row["maintainers"] = maintainers(pkgs)
    if found := teams(pkgs):
        row["teams"] = found
        # nixpkgs adds its teams' members to meta.maintainers. When the
        # maintainers it lists directly (meta.nonTeamMaintainers) differ,
        # they're kept too, so a maintainer's page can leave out what they
        # have only through a team.
        direct = non_team_maintainers(pkgs)
        if direct is not None and direct != row["maintainers"]:
            row["nonTeamMaintainers"] = direct
    # meta.broken, as the package index has it (for x86_64-linux). Hydra's
    # builds say where a package is broken, but a broken package often has
    # no Hydra job at all (hydraPlatforms = [], as hackage2nix sets it).
    if any(p["meta"].get("broken") for p in pkgs):
        row["markedBroken"] = True
    # meta.knownVulnerabilities: nixpkgs itself marks it insecure (it won't
    # build without permittedInsecurePackages), with its reasons.
    if found := insecure(pkgs):
        row["markedInsecure"] = found


def insecure(pkgs):
    """Return why nixpkgs marks pkgs insecure (meta.knownVulnerabilities).

    Returns:
        The reasons, each once, in order; [] when none of pkgs is marked
        insecure.
    """
    found = []
    for p in pkgs:
        for reason in p["meta"].get("knownVulnerabilities") or []:
            if isinstance(reason, str) and reason and reason not in found:
                found.append(reason)
    return found


def maintainers(pkgs, field="maintainers"):
    """Return the GitHub handles in a meta field of pkgs (maintainers by default).

    Args:
        pkgs: The package index's entries.
        field: The meta field to read, "maintainers" by default.

    Returns:
        The handles, each once whatever its case, in order. A maintainer
        without a GitHub handle is left out, as they can't be searched for.
    """
    found = {}
    for p in pkgs:
        for m in p["meta"].get(field) or []:
            handle = m.get("github") if isinstance(m, dict) else None
            if isinstance(handle, str) and handle:
                found.setdefault(handle.lower(), handle)
    return list(found.values())


def non_team_maintainers(pkgs):
    """Return the handles pkgs list directly, not as their teams' members.

    Returns:
        The handles in meta.nonTeamMaintainers, or None when an index entry
        doesn't have that field (older nixpkgs).
    """
    if any("nonTeamMaintainers" not in p["meta"] for p in pkgs):
        return None
    return maintainers(pkgs, "nonTeamMaintainers")


def teams(pkgs):
    """Return the nixpkgs teams in pkgs' meta.teams, by short name.

    Returns:
        The teams' shortNames ("Gaming", "Qt-KDE", as in
        maintainers/team-list.nix), each once, in order.
    """
    found = []
    for p in pkgs:
        for team in p["meta"].get("teams") or []:
            name = team.get("shortName") if isinstance(team, dict) else None
            if isinstance(name, str) and name and name not in found:
                found.append(name)
    return found


# The Repology statuses whose version the channel's can replace: those
# comparing it with the newest elsewhere, and a kept older series (whose
# status stays: firefox-esr 153.5.0esr in the channel, with Repology's
# 153.4.0 a day behind). Not one Repology distrusts or can't order.
CHANNEL_STATUSES = {"newest", "outdated", "unique", "devel", config.KEPT}
# A suffix of letters only (esr), which Repology's rules drop.
LETTERS_ONLY = re.compile(r"[-_.+~]?[A-Za-z]+")


def channel_versions(rows: list[Row], nixpkgs):
    """Use the channel's versions where they're newer than Repology's.

    Repology reads nixos-unstable some hours after it moves, and the
    nixkeeper-versions digest some hours after that (microsoft-edge
    154.0.4258.62, 2026-10-08). So nixVersion becomes the version in the
    package index the sync reads, when that's newer; repologyVersion keeps
    Repology's, and nixStatus is worked out again against refVersion.
    Repology's vulnerable flag, which is for its version, is dropped.

    This is only done when the row's attributes agree on one version, and
    not when the channel's version only adds letters to Repology's, which
    Repology's rules drop (thunderbird-esr-bin 153.3.1esr, which Repology
    has as 153.3.1). A kept series' keptBeside takes the channel's version
    too.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.

    Returns:
        The names of the rows whose nixVersion changed.
    """
    changed = []
    for row in rows:
        # The release a kept series is shown beside takes the channel's
        # version too (firefox-esr beside firefox 158.0, while Repology still
        # had 157.0.1).
        beside = row.get("keptBeside") or {}
        channel = (nixpkgs.get(beside.get("attr")) or {}).get("version")
        if channel and is_newer(channel, beside.get("version")):
            beside["version"] = channel
        theirs = row.get("nixVersion")
        if row.get("nixStatus") not in CHANNEL_STATUSES or not theirs:
            continue
        versions = {nixpkgs[a].get("version") for a in row["attrs"] if a in nixpkgs}
        if len(versions) != 1:
            continue
        ours = versions.pop()
        if not is_newer(ours, theirs) or LETTERS_ONLY.fullmatch(
            ours.removeprefix(theirs)
        ):
            continue
        row["repologyVersion"] = theirs
        row["nixVersion"] = ours
        # Repology's flag is for its version, not the channel's newer one
        # (it was firefox-esr 153.4.0's, shown as 153.5.0esr's). The security
        # tracker's and OSV's verdicts, checked against the channel's
        # version, stay.
        row.pop("nixVulnerable", None)
        # Outdated without a refVersion (beads): left as Repology says.
        ref = row.get("refVersion")
        if row["nixStatus"] == "outdated" and ref and not is_newer(ref, ours):
            # A kept series that caught up within its own series is kept
            # again.
            row["nixStatus"] = config.KEPT if row.get("keptBeside") else "newest"
        changed.append(row["name"])
    return changed


def build_rows(projects, nixpkgs):
    """Make every row from the looked-up projects.

    Args:
        projects: The projects (lookup's), by key.
        nixpkgs: The package index, by attribute.

    Returns:
        The rows, sorted by name, case aside.
    """
    rows = []
    for proj in projects.values():
        for row in project_rows(proj, nixpkgs):
            if proj.get("staleSince"):
                row["staleSince"] = proj["staleSince"]  # when its data was last fetched
            if proj.get("lookupFailed"):
                row["lookupFailed"] = True  # Repology couldn't be asked: no data
            if proj.get("checkedAt"):
                row["repologyCheckedAt"] = proj["checkedAt"]
            rows.append(row)
    return sorted(rows, key=lambda p: p["name"].lower())


def add_families(rows):
    """Mark the rows that one update moves together.

    Rows in the same package file in nixpkgs, with the same version and the
    same homepage, are updated by one PR: the 187 huaweicloudsdk* Python
    packages, indi-3rdparty's drivers, a kernel module once per kernel.
    Each such group of two or more gets a "family", a short key they share.
    Rows in a set updated in bulk, and rows without a source, are left out.
    The overview's lists show a family as one entry (datastore.highlights
    and datastore.fixed_summary).

    Args:
        rows: The rows, changed in place.
    """
    members = {}
    for row in rows:
        row.pop("family", None)
        if row.get("set") or not row.get("source"):
            continue
        path = row["source"].split("#", 1)[0].rsplit("/blob/", 1)[-1].split("/", 1)[-1]
        key = "|".join([path, row.get("nixVersion") or "", row.get("homepage") or ""])
        members.setdefault(key, []).append(row)
    for key, found in members.items():
        if len(found) > 1:
            short = hashlib.sha256(key.encode()).hexdigest()[:8]
            for row in found:
                row["family"] = short


def family_label(names):
    """Return what a family's members are called together.

    For one package in several sets (a kernel module once per kernel),
    that's the one name they all end in ("mbp2018-bridge-drv"). Otherwise
    it's their names' common start and a "*"
    ("python313Packages.huaweicloudsdk*", "indi-3rdparty.indi-*",
    "freebsd.*").

    Args:
        names: The members' names.

    Returns:
        The label, or None when the names share fewer than 4 characters at
        the start.
    """
    ends = {name.rsplit(".", 1)[-1] for name in names}
    if len(ends) == 1:
        return ends.pop()
    start = os.path.commonprefix(list(names))
    return start + "*" if len(start) >= 4 else None


def source_url(position, revision):
    """Return the GitHub link for a meta.position.

    Args:
        position: Such as "pkgs/by-name/we/wesnoth/package.nix:147".
        revision: The nixpkgs revision to link to.
    """
    path, _, line = position.rpartition(":")
    if not line.isdigit():
        path, line = position, ""
    url = config.NIXPKGS_SOURCE_URL.format(revision=revision, path=path)
    return f"{url}#L{line}" if line else url


def add_source_links(rows, nixpkgs, revision):
    """Link each row to where nixpkgs defines it.

    The link is to the position of the first of the row's attributes that
    has one; packages not in nixpkgs get none.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        revision: The nixpkgs revision to link to.
    """
    for row in rows:
        position = next(
            (
                nixpkgs[a]["meta"]["position"]
                for a in row["attrs"]
                if a in nixpkgs and nixpkgs[a]["meta"].get("position")
            ),
            None,
        )
        if position:
            row["source"] = source_url(position, revision)
