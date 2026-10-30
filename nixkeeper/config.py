"""Hold the settings shared across nixkeeper.

Modules read them as config.NAME when they're used, not at import, so the
command's flags and tests that patch them apply.
"""

import os
import re

# Where things live, and how to notify. The `nixkeeper` command (cli.py) sets
# these from its flags, which win over these environment variables, which win
# over the defaults: the user's own folders (XDG), so the installed command
# works from anywhere. From a checkout, the flake's apps (nix run .#sync)
# pass --lists package-lists --data-dir data instead.
#
# NIXKEEPER_DATA_DIR (--data-dir): the published data (the page's data/), also
#   where the next run finds the previous one. Default:
#   ~/.local/state/nixkeeper/data ($XDG_STATE_HOME).
# NIXKEEPER_LISTS (--lists): the package lists, as the Nix folder
#   (package-lists/, evaluated with nix) or as a JSON file of what it
#   evaluates to. Default: ~/.config/nixkeeper/package-lists, or lists.json
#   there if that's what exists ($XDG_CONFIG_HOME).
# NIXKEEPER_NOTIFY (--notify): how to report what changed (notify.py).
# NIXKEEPER_CONTACT: how the people who run this copy can be reached (an
#   email or a URL), added to the User-Agent; see user_agent().
# NIXKEEPER_ALL_PACKAGES (sync --all-packages): track every nixpkgs package,
#   not only the lists'; see all_packages().


def _xdg(variable, fallback):
    """Return an XDG base folder.

    That's the variable when it's an absolute path (the spec ignores
    relative ones), else ~/fallback.
    """
    value = os.environ.get(variable, "")
    return value if os.path.isabs(value) else os.path.expanduser(f"~/{fallback}")


CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "nixkeeper")
STATE_DIR = os.path.join(_xdg("XDG_STATE_HOME", ".local/state"), "nixkeeper")


def _default_lists():
    """Return the default package lists.

    That's the folder, or lists.json beside it when only that exists.
    """
    folder = os.path.join(CONFIG_DIR, "package-lists")
    json_file = os.path.join(CONFIG_DIR, "lists.json")
    return (
        json_file
        if not os.path.exists(folder) and os.path.exists(json_file)
        else folder
    )


# The settings' defaults (`nixkeeper paths` says which is in use).
DEFAULTS = {
    "OUT_DIR": os.path.join(STATE_DIR, "data"),
    "LISTS": _default_lists(),
    "NOTIFY": "none",
}
OUT_DIR = os.environ.get("NIXKEEPER_DATA_DIR") or DEFAULTS["OUT_DIR"]
LISTS = os.environ.get("NIXKEEPER_LISTS") or DEFAULTS["LISTS"]
# NIXKEEPER_NOTIFICATIONS: who gets a status issue of their own
# (notifications/, notify.py); unset, beside the package lists in use
# (notifications_path).
NOTIFICATIONS = os.environ.get("NIXKEEPER_NOTIFICATIONS")


def data_dir(out_dir=None):
    """Return the data folder: out_dir, or the configured one by default.

    The configured one is OUT_DIR, set by --data-dir or NIXKEEPER_DATA_DIR.
    It's read when this is called, not when the caller's module was
    imported, so the command's --data-dir and tests that set it apply.

    Args:
        out_dir: A data folder the caller was given, or None.

    Returns:
        out_dir, or OUT_DIR when out_dir is None or empty.
    """
    return out_dir or OUT_DIR


def notifications_path():
    """Return where notifications/ is.

    That's NIXKEEPER_NOTIFICATIONS, else beside the package lists. It's
    worked out when asked, not at import: --lists sets LISTS after this
    module loads (the workflows' sync passes it), and a path fixed at
    import pointed at the default lists' folder instead.
    """
    return NOTIFICATIONS or os.path.join(
        os.path.dirname(os.path.abspath(LISTS)), "notifications"
    )


def subscribers():
    """Return whether the maintainers and teams in notifications/ get their own issues.

    NIXKEEPER_SUBSCRIBERS says so (1, true, yes; or 0, false, no). Without
    it, they do with every package (the community instance, whose folder
    they are) and don't elsewhere: a copy of this repository has the
    community's files, and would otherwise open their issues and mention
    them. The copy's own status issue (the lists' statusIssue) doesn't
    depend on this.
    """
    value = os.environ.get("NIXKEEPER_SUBSCRIBERS", "").strip().lower()
    if value:
        return value in ("1", "true", "yes")
    return all_packages()


NOTIFY = None  # set by the command; otherwise NIXKEEPER_NOTIFY, read when used
# Repology's repository for nixpkgs unstable.
NIX_REPO = "nix_unstable"
ALL_PACKAGES = None  # set by the command; otherwise NIXKEEPER_ALL_PACKAGES


def all_packages():
    """Return whether the sync tracks every nixpkgs package, not only the lists'.

    That's the community instance's mode (docs/all-packages.md): the lists'
    own packages are read as always, the rest only in bulk (the digests and
    listings), each source with no per-package lookups. It's off unless the
    command or NIXKEEPER_ALL_PACKAGES (1, true, yes) turns it on, and never
    from the lists, which forks copy.
    """
    if ALL_PACKAGES is not None:
        return ALL_PACKAGES
    value = os.environ.get("NIXKEEPER_ALL_PACKAGES", "")
    return value.strip().lower() in ("1", "true", "yes")


# Package sets generated from another ecosystem's index (CRAN, Hackage, ...)
# and kept current in bulk by their own tooling, not one PR per package:
# with every package, their rows (not on the lists) carry "set", are counted
# on their set's line on the overview instead of the cards, and say what
# updates them. Versions from Repology and builds from Hydra as any row;
# the bot's attempts where it has any (it tries some TeX Live and Emacs
# packages). For each: a name, what updates it and where that is in
# nixpkgs, and a short form for badges.
NIXPKGS_TREE = "https://github.com/NixOS/nixpkgs/tree/master/"
SET_PROFILES = {
    "akkuPackages": {
        "name": "Akku",
        "updatedBy": "the Akku index import (update.sh)",
        "short": "Akku import",
        "link": NIXPKGS_TREE + "pkgs/tools/package-management/akku",
    },
    "azure-cli-extensions": {
        "name": "Azure CLI extensions",
        "updatedBy": "the extension index import (extensions-tool.py)",
        "short": "extensions-tool",
        "link": NIXPKGS_TREE + "pkgs/by-name/az/azure-cli",
    },
    "chickenPackages_5": {
        "name": "CHICKEN 5",
        "updatedBy": "the egg import (update.sh 5)",
        "short": "egg import",
        "link": NIXPKGS_TREE + "pkgs/development/compilers/chicken/common/update.sh",
    },
    "chickenPackages_6": {
        "name": "CHICKEN 6",
        "updatedBy": "the egg import (update.sh 6)",
        "short": "egg import",
        "link": NIXPKGS_TREE + "pkgs/development/compilers/chicken/common/update.sh",
    },
    "emacsPackages": {
        "name": "Emacs",
        "updatedBy": "the ELPA, NonGNU ELPA and MELPA update scripts",
        "short": "ELPA/MELPA",
        "link": NIXPKGS_TREE + "pkgs/applications/editors/emacs/elisp-packages",
    },
    "gnomeExtensions": {
        "name": "GNOME Shell extensions",
        "updatedBy": "the extensions.gnome.org import (update-extensions.py)",
        "short": "extensions import",
        "link": NIXPKGS_TREE + "pkgs/desktops/gnome/extensions",
    },
    "haskellPackages": {
        "name": "Haskell",
        "updatedBy": "hackage2nix, on the haskell-updates branch",
        "short": "hackage2nix",
        # Where updates wait before master (sources/branches.py).
        "branch": "haskell-updates",
        "link": NIXPKGS_TREE
        + "maintainers/scripts/haskell/regenerate-hackage-packages.sh",
    },
    "rPackages": {
        "name": "R",
        "updatedBy": "the CRAN and Bioconductor import (generate-r-packages.R)",
        "short": "CRAN import",
        "link": NIXPKGS_TREE + "pkgs/development/r-modules",
    },
    "sbclPackages": {
        "name": "Common Lisp",
        "updatedBy": "the Quicklisp import (ql-import.lisp)",
        "short": "Quicklisp import",
        "link": NIXPKGS_TREE + "pkgs/development/lisp-modules",
    },
    "texlivePackages": {
        "name": "TeX Live",
        "updatedBy": "a snapshot of TeX Live's package database (tlpdb.nix)",
        "short": "TeX Live snapshot",
        "link": NIXPKGS_TREE + "pkgs/tools/typesetting/tex/texlive/UPGRADING.md",
    },
    "typstPackages": {
        "name": "Typst",
        "updatedBy": "the Typst Universe import (update-typst-packages.py)",
        "short": "Typst Universe import",
        "link": NIXPKGS_TREE + "maintainers/scripts/update-typst-packages.py",
    },
}
# Attribute sets that aren't software with releases to compare (system
# components: darwin's SDK pieces, FreeBSD's base): their rows say so
# ("unversioned") instead of a version status; their builds count as any.
UNVERSIONED_SETS = ("darwin", "freebsd")
# With every package and no updates digest (it isn't current): how many
# packages not on the lists a sync reads the nixpkgs-update logs of (those
# whose logs changed since the last sync; one or two requests each), the
# outdated and failing first. It's 0: about 4,000 log folders change a day,
# more than a sync can read politely, so they keep the attempt last read,
# marked unread, until the digest is back.
UPDATE_LOGS_BUDGET = 0
# With every package: the other repositories kept for a row not on the
# lists (the newest, one entry each): what its details show first. The rest
# are on Repology, linked from there.
REPOLOGY_ENTRIES_KEPT = 8
# Where nixkeeper lives, named in the User-Agent.
UPSTREAM_URL = "https://github.com/nixkeeper/nixkeeper"
CONTACT_MAX = 100  # characters of NIXKEEPER_CONTACT kept in the User-Agent


def on_github_actions():
    """Return whether this runs on GitHub Actions."""
    return os.environ.get("GITHUB_ACTIONS") == "true"


def user_agent():
    """Return the User-Agent header nixkeeper sends to every source.

    As API etiquette asks, it names the software, its version and where it
    lives (the same for every copy: a fix belongs there), then who runs
    this copy, where that's public or chosen: the repository running it on
    GitHub Actions (public anyway), and NIXKEEPER_CONTACT. A personal
    machine adds nothing unless asked:

      nixkeeper/0.9.0 (+https://github.com/nixkeeper/nixkeeper; someone/nixkeeper)
    """
    from . import version  # here: nixkeeper/__init__.py imports nothing back

    who = []
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if on_github_actions() and repo and not UPSTREAM_URL.endswith(f"/{repo}"):
        who.append(repo)
    contact = _comment_safe(os.environ.get("NIXKEEPER_CONTACT", ""))
    if contact:
        who.append(contact)
    return f"nixkeeper/{version()} ({'; '.join([f'+{UPSTREAM_URL}', *who])})"


def _comment_safe(text):
    """Make text fit for the User-Agent's comment.

    That's printable ASCII only (no line breaks: they'd start a new header),
    no parentheses or semicolons (they'd end the comment or a part of it),
    spaces collapsed, and at most CONTACT_MAX characters.
    """
    text = re.sub(r"[^\x20-\x7e]|[();]", " ", text)
    return " ".join(text.split())[:CONTACT_MAX].strip()


# Every package in nixos-unstable with its meta (maintainers, platforms, ...).
# Same channel Repology's nix_unstable tracks, and far cheaper than evaluating
# nixpkgs ourselves.
NIXPKGS_INDEX_URL = "https://channels.nixos.org/nixos-unstable/packages.json.br"
# The nixpkgs commit that channel was built from: source links point there, so
# their line numbers match the data even after the files change.
NIXPKGS_REVISION_URL = "https://channels.nixos.org/nixos-unstable/git-revision"
NIXPKGS_BRANCH = "nixos-unstable"  # link target if the revision can't be fetched
NIXPKGS_SOURCE_URL = "https://github.com/NixOS/nixpkgs/blob/{revision}/{path}"

# Repology's addresses, tried in order (repology.py). Only repology.org now:
# repology.amdmi3.ru, the fallback while repology.org was down, is
# discontinued on 2026-10-09. REPOLOGY_BASE_URL sets another one instead.
_override = os.environ.get("REPOLOGY_BASE_URL")
REPOLOGY_URLS = [_override] if _override else ["https://repology.org"]
# Seconds before each retry of a failed request (repology.py, http.py).
RETRY_DELAYS = [5, 15]
# The longest one answer may take to arrive in full, in seconds (http.py):
# a request's own timeout only bounds each wait for the next bytes, so a
# server sending a little at a time could otherwise hold a run for hours.
# Past it, the request has failed (and is retried). Downloads (a digest, up
# to about 12 MB) get longer: enough at 40 kB/s.
FETCH_DEADLINE_SECONDS = 60
DOWNLOAD_DEADLINE_SECONDS = 300
# A server that answers "too many requests" or "unavailable" may say how long
# to wait (Retry-After): nixkeeper waits that long, up to this many seconds.
# Asked to wait longer, it gives that request up instead of stalling the run
# (the package keeps its previous data, as with any failed lookup).
MAX_RETRY_AFTER = 300

# Repology statuses the page shows as outdated. Not "legacy" (KEPT): an
# older version nixpkgs keeps on purpose beside a newer one under another
# attribute (tracy_0_11 beside tracy, php82Extensions beside php84's). It's
# outdated only by a newer release in its own series (an update check), or,
# for a devel variant (a beta), a newer devel version elsewhere.
OUTDATED_STATUSES = {"outdated"}

# Changes in how nixkeeper counts that step a count overnight, for the
# overview's trends (marked, with every package): when each was merged, and
# what it changed. A sync marks one on the first day it ran with it. Add one
# with any rule change that moves the counts.
COUNTING_CHANGES = [
    {
        "merged": "2026-10-06T09:03:41+00:00",
        "text": "older versions kept beside a newer one aren't outdated",
    },
    {
        # Between the last daily sync before the merge and the first after.
        "merged": "2026-10-06T21:00:00+00:00",
        "text": "nixpkgs-update logs read anew: a failed request is an update failure",
    },
    {
        # Between today's syncs; set to the merge's time if later.
        "merged": "2026-10-07T13:00:00+00:00",
        "text": "versions ordered as Repology orders them: a pre-release before "
        "its release",
    },
    {
        # Set to the merge's time when it's merged.
        "merged": "2026-10-10T00:00:00+00:00",
        "text": "GitHub releases checked for every package fetched from GitHub: "
        "newer ones Repology hasn't seen count as outdated",
    },
    {
        # The first of the two merged (#242, coq); the second the same day.
        "merged": "2026-10-15T11:55:00+00:00",
        "text": "kept series: coq's aren't devel variants, and a release kept "
        "only beside its own beta (firefox) counts as the main line",
    },
    {
        # Set to the merge's time when it's merged.
        "merged": "2026-10-15T15:00:00+00:00",
        "text": "kept series behind in their own series count as outdated "
        "(glibmm_2_4 2.66.8, 2.66.10 out)",
    },
    {
        # Set to the merge's time when it's merged.
        "merged": "2026-10-15T17:00:00+00:00",
        "text": "one distribution's snapshot of a release isn't a newer version "
        "(mintotp 0.3.0, SlackBuilds' 0.3.0.20240120)",
    },
]
KEPT = "legacy"
# Repology's repositories that are a language's own package index, where a
# version is the upstream release itself, not a distribution's packaging
# (rows.snapshot_only: iso4217's 1.16.20260101 on PyPI is a release).
UPSTREAM_INDEXES = {
    "cpan",
    "cran",
    "crates_io",
    "gnu_elpa",
    "hackage",
    "luarocks",
    "melpa",
    "melpa_stable",
    "metacpan",
    "opam",
    "pypi",
    "rubygems",
    "stackage_lts",
}

# Hydra, nixpkgs' build farm. The nixpkgs/unstable jobset builds master (not the
# nixos-unstable channel, which only advances once enough of it has built).
HYDRA_URL = "https://hydra.nixos.org"
HYDRA_PROJECT = "nixpkgs"
HYDRA_JOBSET = "unstable"
# nixkeeper-hydra's digest of Hydra's builds (sources/hydra_digest.py): every
# job of the newest evaluation in one download, instead of a request or two
# per job. NIXKEEPER_HYDRA_DIGEST="" turns it off (Hydra is then asked about
# each job, as it is whenever the digest isn't current).
HYDRA_DIGEST_URL = os.environ.get(
    "NIXKEEPER_HYDRA_DIGEST",
    "https://raw.githubusercontent.com/nixkeeper/digest-builds/data/data/",
)
# A digest behind Hydra's newest evaluation is still used when it was read
# this recently (its workflow runs hourly); older, it isn't.
HYDRA_DIGEST_MAX_AGE_HOURS = 12
# nixkeeper-versions' digest of Repology (sources/versions_digest.py): every
# nixpkgs project, read in bulk daily, instead of a lookup per package.
# NIXKEEPER_VERSIONS_DIGEST="" turns it off (Repology is then asked about
# each package, as it is whenever the digest isn't current).
VERSIONS_DIGEST_URL = os.environ.get(
    "NIXKEEPER_VERSIONS_DIGEST",
    "https://raw.githubusercontent.com/nixkeeper/digest-versions/data/data/",
)
# The digest is used while its outdated projects were read this recently
# (its workflow runs daily, at 04:07 UTC).
VERSIONS_DIGEST_MAX_AGE_HOURS = 36
# nixkeeper-updates' digest of nixpkgs-update (sources/updates_digest.py):
# the bot's latest attempt at every package, read with nixkeeper's own rules,
# instead of reading each package's logs. NIXKEEPER_UPDATES_DIGEST="" turns
# it off (the logs are then read per package, as they are whenever the
# digest isn't current).
UPDATES_DIGEST_URL = os.environ.get(
    "NIXKEEPER_UPDATES_DIGEST",
    "https://raw.githubusercontent.com/nixkeeper/digest-update-bot/data/data/",
)
# The digest is used while it was made this recently (its workflow runs
# every 3 hours).
UPDATES_DIGEST_MAX_AGE_HOURS = 12
# The bot's queue (the digest's queue.json.gz) older than this isn't used:
# its days to come would be off.
UPDATES_QUEUE_MAX_AGE_HOURS = 24
# nixkeeper-vulnerabilities' digest (sources/vulnerabilities_digest.py):
# the NixOS security tracker's CVEs for nixpkgs packages and OSV's
# advisories, with which packages they concern. NIXKEEPER_VULNERABILITIES_
# DIGEST="" turns it off (Repology's flag and nixpkgs' insecure mark then
# decide alone, as they do whenever the digest isn't current).
VULNERABILITIES_DIGEST_URL = os.environ.get(
    "NIXKEEPER_VULNERABILITIES_DIGEST",
    "https://raw.githubusercontent.com/nixkeeper/digest-vulnerabilities/data/data/",
)
# Used while the tracker was read this recently (its workflow runs hourly).
VULNERABILITIES_DIGEST_MAX_AGE_HOURS = 72
# nixkeeper-prs' digest of nixpkgs' PRs and issues (sources/prs_digest.py):
# every open PR and issue, and the PRs merged into master since the
# channel's commit, listed hourly, instead of the sync listing them itself.
# NIXKEEPER_PRS_DIGEST="" turns it off (the sync then lists them, as it
# does whenever the digest isn't current).
PRS_DIGEST_URL = os.environ.get(
    "NIXKEEPER_PRS_DIGEST",
    "https://raw.githubusercontent.com/nixkeeper/digest-prs/data/data/",
)
# Used while each list was made this recently (its workflow runs hourly and
# takes about half an hour; the daily full sweep about an hour).
PRS_DIGEST_MAX_AGE_HOURS = 6
# The package index of the newest NixOS release's channel ({release}: 26.05,
# from the tracker's newest release branch): its versions say whether a CVE
# fixed on unstable is still to backport (sources/vulnerabilities_digest.py).
# NIXKEEPER_STABLE_INDEX="" goes by the tracker's status for releases instead.
STABLE_INDEX_URL = os.environ.get(
    "NIXKEEPER_STABLE_INDEX",
    "https://channels.nixos.org/nixos-{release}/packages.json.br",
)
# That channel's commit: its patches say whether a CVE is fixed there without
# a version bump.
STABLE_REVISION_URL = "https://channels.nixos.org/nixos-{release}/git-revision"
# Platforms nixpkgs builds; x86_64-darwin is no longer one of them.
HYDRA_SYSTEMS = ["x86_64-linux", "aarch64-linux", "aarch64-darwin"]
# After this many lookups in a row fail, Hydra is likely down: the rest of the
# run reuses the previous run's results instead of retrying each job.
HYDRA_MAX_CONSECUTIVE_FAILURES = 3
# What has nothing going on (a Hydra job that built fine for an unchanged,
# up-to-date package; a package with no open PRs or issues) is asked about
# every this many days, not daily: a third of them each day (schedule.py).
QUIET_DAYS = 3

# Logs of nixpkgs-update (the r-ryantm bot): one directory per attribute, one
# log per attempt (<attr>/<YYYY-MM-DD>.log). It tries each package every ten
# days or so. Moved from nixpkgs-update-logs.nix-community.org in 2026.
NIXPKGS_UPDATE_LOGS_URL = "https://nixpkgs-update-logs.nixos.org"
# After this many lookups in a row fail, the log site is likely down (as for
# Hydra).
UPDATE_LOGS_MAX_CONSECUTIVE_FAILURES = 3

GITHUB_REPO = "NixOS/nixpkgs"
GITHUB_SEARCH_BATCH = 20  # searches per GraphQL request
# Repositories per GraphQL request for the update checks' tags and branches:
# a request for all of them at once grows too big to answer with many rules.
GITHUB_REPOS_BATCH = 50
# Update checks' pages: at most one request this often to the same site
# (http.pace); different sites follow one another freely.
SITE_PAUSE_SECONDS = 1
# nixpkgs PR/issue titles name packages in versioned sets by their alias
# ("python3Packages.requests: 2.34 -> 2.35"), which the index doesn't carry.
SEARCH_ALIASES = [
    (re.compile(r"^python3\d+Packages\."), "python3Packages."),
]
