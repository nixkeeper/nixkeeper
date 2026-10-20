"""Turning Repology projects into the page's rows."""

import hashlib
import os
import re

from . import config
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
    """What the GitHub PR/issue searches look for: the attribute name, with
    versioned sets under the alias nixpkgs titles use."""
    for pattern, alias in config.SEARCH_ALIASES:
        attr = pattern.sub(alias, attr)
    return attr


# An attribute named for a development channel (wesnoth-devel, foo-beta,
# bar_unstable, baz-nightly, code-insiders).
DEVEL_NAME = re.compile(
    r"[-_.](devel|dev|beta|alpha|unstable|nightly|rc|preview|insiders|canary|git)$"
)


def name_blockers(rows):
    """Each dependency-failed build's blockedBy (the digest's: attributes,
    or store names no job builds) as the page links them: [{"name": the
    row named by that attribute, or the attribute or name as it is,
    "row": true when it's a row}]."""
    by_attr = {a: row["name"] for row in rows for a in row.get("attrs") or []}
    for row in rows:
        for build in row.get("builds") or []:
            if build.get("blockedBy") and isinstance(build["blockedBy"][0], str):
                build["blockedBy"] = [
                    {"name": by_attr[a], "row": True} if a in by_attr else {"name": a}
                    for a in build["blockedBy"]
                ]


def row_name(attrs):
    """The attribute a row is named after: the first top-level one, else the
    first (cmake, not azure-sdk-for-cpp.cmake, a set passing it on)."""
    return min(attrs, key=lambda a: ("." in a, a))


def project_rows(proj, nixpkgs):
    """Rows for one Repology project: normally one, but one per version when
    the tracked nixpkgs variants differ (wesnoth / wesnoth-devel). Variants
    sharing a version (heroic / heroic-unwrapped) stay one row."""
    entries = proj["entries"]
    nix_all = [e for e in entries if e.get("repo") == config.NIX_REPO]
    others = [e for e in entries if e.get("repo") != config.NIX_REPO]

    groups = {}  # version -> nix entries of tracked attrs
    for e in nix_all:
        if e.get("srcname") in proj["attrs"]:
            groups.setdefault(e.get("version"), []).append(e)
    if len(groups) < 2:
        nix = next(iter(groups.values()), nix_all)[:1]
        attrs = sorted(proj["attrs"])
        # Named after its nixpkgs attribute, like the lists and GitHub searches;
        # the list entry itself when nixpkgs doesn't have it.
        name = row_name(attrs) if attrs else proj["name"]
        return [
            make_row(
                proj, name, attrs, nix[0] if nix else None, others, nixpkgs, devel=False
            )
        ]

    # Stable first: the variant Repology calls newest, else the shortest
    # attr (wesnoth before wesnoth-devel); in a project of kept series only
    # (coq's, once its current one moved to rocq), the newest version
    # (coq_8_20, not coq_8_7: else every newer series was a devel variant,
    # behind). The rest are devel variants, compared
    # against devel versions, when they're newer than it or named so
    # (wesnoth-devel, _1password-gui-beta); otherwise older versions kept
    # beside it (gnumake42, php82Extensions.zip).
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


VERSION_PART = re.compile(r"[A-Za-z]+|[0-9]+")
WORD = re.compile(r"[A-Za-z]+")
# Build metadata, not a newer release (jdk 21.0.12+8.2 beside 21.0.12.1+1).
BUILD = re.compile(r"\+.*")
# Statuses a version counts by in its series: not one Repology distrusts,
# can't order, or a rolling one (3.13.9999).
SERIES_STATUSES = {"newest", "outdated", "legacy", "unique"}
# Distributions that must have a version in a kept series for it to count,
# as it makes the package outdated (repositories named alike are one:
# debian_13 and debian_unstable): one alone is often its own packaging (eigen2 2.0.55,
# firebird 4.0.7.3271 in EPEL).
SERIES_REPOS = 2
# In a series named by its first part alone, the next part more than doubled
# and this: another numbering (zulu17 17.68.203 for 17.0.19) or the next
# major's previews (gimp2 2.99.10 for 2.10.38), not 535.309 for 535.288.
SERIES_JUMP = 5


def named_parts(name, parts):
    """How many of a version's numeric parts the attribute's trailing digits
    spell (python313: 2, glew_1_10: 2, icu60: 1, sbcl_2_4_6: 3), else 0."""
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
    """version without release words or build metadata (4.5.1-stable: 4.5.1,
    21.0.12.1+1: 21.0.12.1), as parts."""
    return VERSION_PART.findall(BUILD.sub("", without_release_words(version)))


# What a distribution's snapshot adds to the release it follows: a date,
# maybe with a word and a commit (0.3.0.20240120, 1.2.0+20251126,
# 1.04-20190106, 2.1-git20240301.abc1234).
SNAPSHOT_ADDED = re.compile(
    r"[-_.+~]?(?:git|svn|hg|snapshot|p|r)?[-_.+~]?"
    r"20[0-9]{2}(?:0[1-9]|1[0-2])(?:[0-2][0-9]|3[01])(?:[-_.+]?[0-9a-f]{4,12})?",
    re.IGNORECASE,
)


def snapshot_only(version, newest, others):
    """Whether newest is only a distribution's snapshot of version: version
    with a date added, in one distribution and no upstream index (mintotp's
    0.3.0.20240120, SlackBuilds' only). Not when PyPI or the like has it
    (iso4217's 1.16.20260101 is a release), nor when several distributions
    do (fcitx5-pinyin-zhwiki's 0.3.0.20260416: the dictionary's date)."""
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


# nixpkgs' spelling of a snapshot of a date, with nothing (or 0) before it:
# unstable-2022-10-20, 0-unstable-2012-12-08.
NIX_SNAPSHOT = re.compile(r"(?:0-)?unstable-([0-9]{4}-[0-9]{2}-[0-9]{2})")


def same_snapshot(version, newest):
    """Whether newest is only another spelling of nixpkgs' snapshot version:
    the date alone (gawkextlib.csv's unstable-2022-10-20, which nixpkgs'
    older channels spelled 2022-10-20, and Repology ranks above it)."""
    match = NIX_SNAPSHOT.fullmatch(version or "")
    return bool(match) and match[1] == newest


def not_packaging(families):
    """The versions of families ({version: the distributions that have
    it}) that aren't only a packaging of another: one adding a part to
    another in as many distributions or more (Chocolatey's ruby 3.4.11.1
    beside 3.4.11, Baulk's curl 8.23.0.1 beside 8.23.0, AUR's rakudo
    2026.09_01 beside 2026.09)."""
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
    """The newest release in version's own series, when nixpkgs has a newer
    series of the same project (another attribute: python315 beside
    python313) and it's newer than version; else None. The series: the
    versions sharing version's parts up to the first where it differs from
    the next newer series in nixpkgs (3.13 for 3.13.15 beside 3.15.0), or as
    many as the attribute names (electron_40: 40); for a kept one (kept),
    of three parts or more and not named, at least two (tcl 8.6.16 beside
    9.0: 8.6, not 8.7). Not for a snapshot, nor an attribute naming the
    whole version (sbcl_2_4_6). Counted: releases besides nixpkgs' (for a
    kept one, in two distributions or more), in version's shape, not
    pre-releases, nor ones adding words, a part (14.24.4 for 14.24, but
    26.08.1 for 26.08) or a revision (1.91.0-1)."""
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
    sibling = VERSION_PART.findall(min(newer, key=version_key))
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
        # A distribution: debian_13 and debian_unstable, manjaro_stable and
        # manjaro_testing are one.
        families.setdefault(v, set()).add(e.get("repo", "").split("_")[0])
    found = {
        v: f for v, f in families.items() if len(f) >= (SERIES_REPOS if kept else 1)
    }
    best = max(not_packaging(found), key=version_key, default=None)
    plain = BUILD.sub("", without_release_words(version))
    return best if best and is_newer(BUILD.sub("", best), plain) else None


def make_row(proj, name, attrs, nix, others, nixpkgs, devel):
    def newest(status):
        """The highest version among the other repositories with status;
        for an outdated package, the one to update to: not a packaging of
        another (not_packaging: curl 8.23.0, not Baulk's 8.23.0.1)."""
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

    row = {
        "name": name,
        # The attribute name, which unlike the pname tells variants apart
        # (_1password-gui and _1password-gui-beta are both pname "1password").
        "searchTerm": search_term(name) if attrs else name,
        "project": proj["project"],
        "dataFile": proj["dataFile"],
        "attrs": attrs,
        "nixVersion": nix.get("version") if nix else None,
        "nixStatus": nix.get("status") if nix else "missing",
        "nixVulnerable": bool(nix.get("vulnerable")) if nix else False,
        # When only Nix packages it (msedgedriver), Repology marks no
        # repository newest, but the one ahead (a stable branch with a
        # backport, say) unique: compared within the family, nixpkgs
        # unstable can still be outdated against it.
        "refVersion": (devel and newest("devel"))
        or newest("newest")
        or newest("unique"),
        # Repositories, not entries: one can list a package several times.
        "repoCount": len({e.get("repo") for e in others}),
        # A devel variant of a split project, or a version Repology itself
        # classifies as devel (lincity).
        "devel": devel or (nix or {}).get("status") == "devel",
    }
    # An older series nixpkgs keeps beside a newer one, behind in its own
    # series: compared within it (python313 3.13.15 → 3.13.16, not Python's
    # newest, 3.15.0, which python315 has).
    if (
        nix
        and not row["devel"]
        and nix.get("status") == "outdated"
        and (ref := series_ref(name, nix.get("version"), proj["entries"], others))
    ):
        row["refVersion"] = ref
    if (
        nix
        and nix.get("status") == "outdated"
        and row["refVersion"]
        and RELEASE_WORDS.search(nix.get("version") or "")
        and version_key(without_release_words(nix.get("version")))
        == version_key(row["refVersion"])
    ):
        # Outdated only by a word naming the release, which Repology ranks
        # lower (godot 4.7.2-stable against 4.7.2): the newest. Not when
        # ahead of it, which Repology's rules have reasons for (xcircuit
        # 3.10.42 against 3.9.73).
        row["nixStatus"] = "newest"
    if (
        nix
        and nix.get("status") == "outdated"
        and row["refVersion"]
        and snapshot_only(nix.get("version"), row["refVersion"], others)
    ):
        # Outdated only by one distribution's snapshot of this very release
        # (python3Packages.mintotp 0.3.0, SlackBuilds' 0.3.0.20240120): the
        # newest.
        row["nixStatus"] = "newest"
    if (
        nix
        and nix.get("status") == "outdated"
        and same_snapshot(nix.get("version"), row["refVersion"])
    ):
        # Outdated only by another spelling of the same snapshot, mostly
        # nixpkgs' own older channels' (104 rows on 2026-10-20): the newest.
        row["nixStatus"] = "newest"
    if nix and nix.get("status") == config.KEPT:
        # An older version kept beside a newer one: which, for the page.
        newer = [
            e
            for e in proj["entries"]
            if e.get("repo") == config.NIX_REPO
            and e.get("version")
            and version_key(e["version"]) > version_key(nix.get("version") or "")
        ]
        if newer and not devel and all(is_pre_release(e["version"]) for e in newer):
            # Newer only as a beta nixpkgs also has (firefox beside
            # firefox-devedition 158.0b1): Repology calls it legacy, but it's
            # the main line, compared with the newest release like any.
            ref = row["refVersion"]
            behind = ref and is_newer(ref, nix.get("version") or "")
            row["nixStatus"] = "outdated" if behind else "newest"
            newer = []
        if newer:
            # Beside its newer release rather than a beta, when nixpkgs has
            # both (firefox-esr beside firefox 158.0, not firefox-devedition).
            newer = [e for e in newer if not is_pre_release(e["version"])] or newer
            best = max(version_key(e["version"]) for e in newer)
            # Of those with that version, the plainest name (tracy, not tracy_0_14).
            top = min(
                (e for e in newer if version_key(e["version"]) == best),
                key=lambda e: (len(e.get("srcname") or ""), e.get("srcname") or ""),
            )
            row["keptBeside"] = {"attr": top.get("srcname"), "version": top["version"]}
            # Kept, but behind in its own series (glibmm_2_4 2.66.8, 2.66.10
            # out): outdated against that, still kept beside the newer one.
            if not devel and (
                ref := series_ref(
                    name, nix.get("version"), proj["entries"], others, kept=True
                )
            ):
                row["nixStatus"] = "outdated"
                row["refVersion"] = ref
    pkgs = [nixpkgs[a] for a in attrs if a in nixpkgs]
    if pkgs and not nix:
        # In nixpkgs, but Repology doesn't list nixpkgs' package: not on
        # Repology at all (read in bulk, with every package), or found by
        # its name in a project of other repositories only (Repology leaves
        # out nixpkgs packages whose version it can't read: keeperrl's
        # "alpha34", airstrike's "pre6a"). nixpkgs' version, and nothing
        # to compare it with; not "missing", which says nixpkgs hasn't it.
        row["nixVersion"] = pkgs[0].get("version")
        row["nixStatus"] = "unlisted"
    if pkgs:  # not in nixpkgs: nothing to say about platforms or homepage
        row["platforms"] = platforms(pkgs)
        homepage = next(
            (p["meta"].get("homepage") for p in pkgs if p["meta"].get("homepage")), None
        )
        row["homepage"] = homepage[0] if isinstance(homepage, list) else homepage
        row["maintainers"] = maintainers(pkgs)
        if found := teams(pkgs):
            row["teams"] = found
            # nixpkgs adds its teams' members to meta.maintainers; those it
            # lists directly (meta.nonTeamMaintainers), when that's fewer: a
            # maintainer's page can leave out what they have only via a team.
            direct = non_team_maintainers(pkgs)
            if direct is not None and direct != row["maintainers"]:
                row["nonTeamMaintainers"] = direct
        # meta.broken, as the package index has it (x86_64-linux): Hydra's
        # builds say where it's broken, but a broken package often has no
        # Hydra job at all (hydraPlatforms = [], as hackage2nix sets it).
        if any(p["meta"].get("broken") for p in pkgs):
            row["markedBroken"] = True
        # meta.knownVulnerabilities: nixpkgs itself marks it insecure (it
        # won't build without permittedInsecurePackages), with its reasons.
        if found := insecure(pkgs):
            row["markedInsecure"] = found
    return row


def insecure(pkgs):
    """The reasons in pkgs' meta.knownVulnerabilities, each once, in order;
    [] when nixpkgs doesn't mark any of them insecure."""
    found = []
    for p in pkgs:
        for reason in p["meta"].get("knownVulnerabilities") or []:
            if isinstance(reason, str) and reason and reason not in found:
                found.append(reason)
    return found


def maintainers(pkgs, field="maintainers"):
    """The GitHub handles in pkgs' meta.maintainers (or another such field),
    each once (whatever its case), in order; [] when none has any (a
    maintainer without a GitHub handle can't be searched for)."""
    found = {}
    for p in pkgs:
        for m in p["meta"].get(field) or []:
            handle = m.get("github") if isinstance(m, dict) else None
            if isinstance(handle, str) and handle:
                found.setdefault(handle.lower(), handle)
    return list(found.values())


def non_team_maintainers(pkgs):
    """The handles pkgs list directly (meta.nonTeamMaintainers: not added as
    their teams' members), or None when an index entry doesn't say (older
    nixpkgs)."""
    if any("nonTeamMaintainers" not in p["meta"] for p in pkgs):
        return None
    return maintainers(pkgs, "nonTeamMaintainers")


def teams(pkgs):
    """The nixpkgs teams in pkgs' meta.teams (maintainers/team-list.nix), by
    their shortName ("Gaming", "Qt-KDE"), each once, in order."""
    found = []
    for p in pkgs:
        for team in p["meta"].get("teams") or []:
            name = team.get("shortName") if isinstance(team, dict) else None
            if isinstance(name, str) and name and name not in found:
                found.append(name)
    return found


# Repology's statuses a version from the channel can replace: the ones
# comparing it with the newest elsewhere, and a kept older series (its
# status stays: firefox-esr 153.5.0esr in the channel, Repology's 153.4.0 a
# day behind); not one Repology distrusts or can't order.
CHANNEL_STATUSES = {"newest", "outdated", "unique", "devel", config.KEPT}
LETTERS_ONLY = re.compile(r"[-_.+~]?[A-Za-z]+")


def channel_versions(rows, nixpkgs):
    """Make nixVersion the channel's, from the package index the sync reads,
    when that's newer than Repology's: Repology reads nixos-unstable some
    hours after it moves, and nixkeeper-versions' digest some hours after
    that (microsoft-edge 154.0.4258.62, 2026-10-08). nixStatus is then
    worked out again against refVersion, and repologyVersion keeps what
    Repology had. Only when the row's attributes agree on one version, and
    not when the channel's only adds letters to Repology's: Repology's rules
    drop those (thunderbird-esr-bin 153.3.1esr, which it has as 153.3.1).
    Repology's vulnerable flag, for its version, goes with it. A kept
    series' keptBeside takes the channel's version too. Returns the names of
    the rows changed."""
    changed = []
    for row in rows:
        # The release a kept series is named beside, at the channel's version
        # too (firefox-esr beside firefox 158.0, Repology still at 157.0.1).
        beside = row.get("keptBeside") or {}
        channel = (nixpkgs.get(beside.get("attr")) or {}).get("version")
        if channel and is_newer(channel, beside.get("version")):
            beside["version"] = channel
        if row.get("nixStatus") not in CHANNEL_STATUSES or not row.get("nixVersion"):
            continue
        versions = {nixpkgs[a].get("version") for a in row["attrs"] if a in nixpkgs}
        if len(versions) != 1:
            continue
        ours = versions.pop()
        theirs = row["nixVersion"]
        if not is_newer(ours, theirs) or LETTERS_ONLY.fullmatch(
            ours.removeprefix(theirs)
        ):
            continue
        row["repologyVersion"] = theirs
        row["nixVersion"] = ours
        # Repology's flag is for its version, not the channel's newer one
        # (firefox-esr 153.4.0's, shown as 153.5.0esr's); the security
        # tracker's and OSV's verdicts, checked against ours, stay.
        row.pop("nixVulnerable", None)
        # Outdated against nothing Repology names (beads): left as it says.
        ref = row.get("refVersion")
        if row["nixStatus"] == "outdated" and ref and not is_newer(ref, ours):
            # A kept series caught up in its own series: kept again.
            row["nixStatus"] = config.KEPT if row.get("keptBeside") else "newest"
        changed.append(row["name"])
    return changed


def build_rows(projects, nixpkgs):
    """All rows, sorted by name."""
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
    """Mark rows one update moves together ("family": a short key shared by
    two or more): the same package file in nixpkgs, the same version and the
    same homepage, so one PR updates them all (the 187 huaweicloudsdk*
    Python packages, indi-3rdparty's drivers, a kernel module once per
    kernel). Not rows of a set updated in bulk, nor ones without a source.
    The overview's lists show a family as one entry (datastore.highlights,
    fixed_summary)."""
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
    """What a family's members are called together: the one name they all
    end in, for one package in several sets (a kernel module once per
    kernel: "mbp2018-bridge-drv"); else their names' common start and a "*"
    ("python313Packages.huaweicloudsdk*", "indi-3rdparty.indi-*",
    "freebsd.*"); None when they share fewer than 4 characters."""
    ends = {name.rsplit(".", 1)[-1] for name in names}
    if len(ends) == 1:
        return ends.pop()
    start = os.path.commonprefix(list(names))
    return start + "*" if len(start) >= 4 else None


def source_url(position, revision):
    """GitHub link for a meta.position, e.g.
    "pkgs/by-name/we/wesnoth/package.nix:147"."""
    path, _, line = position.rpartition(":")
    if not line.isdigit():
        path, line = position, ""
    url = config.NIXPKGS_SOURCE_URL.format(revision=revision, path=path)
    return f"{url}#L{line}" if line else url


def add_source_links(rows, nixpkgs, revision):
    """Link each row to where nixpkgs defines it: the first of its attrs that
    has a position (packages not in nixpkgs get none)."""
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
