"""Read the update bot's attempts from its public logs.

nixpkgs-update (the r-ryantm bot) tries to update packages and logs each
attempt. This module finds the outcome of its latest attempt at each
tracked package. The logs carry no exit code, so the outcome is recognised
from how the log reads, as github.com/asymmetric/nixpkgs-update-notifier
does. Where the nixkeeper-updates digest has already read an attempt
(updates_digest), it's taken from there instead.
"""

import copy
import re
import sys
import time
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta

from .. import config, history
from ..changes import is_outdated, on_master
from ..rows import search_term
from ..shape import Row
from . import http, updates_digest

# A log's file name in a package's directory listing: the attempt's date.
LOG_NAME = re.compile(r'href="(\d{4}-\d{2}-\d{2})\.log"')
# The version of parse()'s rules, stored with each attempt ("parser"). A sync
# reuses the previous run's reading of a log it has already read (the same
# attribute and date) instead of downloading it again, but only a reading
# made with these same rules. Bump this whenever parse() changes how it
# reads a log, so the next sync reads every log again and the change
# applies at once.
PARSER = 5
# What add_attempts adds to an attempt after reading its log, from the
# state of nixpkgs and the rules at the time. as_read() takes them off, so
# they're judged again.
JUDGED = ("supersededOutcome", "supersededOn", "reason", "community")
# The update a log is for: "UPDATE_INFO: egoboo 2.7.3 -> 2.8.1 https://...",
# or "0 -> 1" when the package's own updateScript decides the version.
UPDATE_INFO = re.compile(r"UPDATE_INFO: \S+ (\S+) -> (\S+)")
UPDATE_SCRIPT = "0"  # the "from" of an updateScript attempt
UPDATE_SCRIPT_TO = "1"  # and its "to", before the script runs
# With an updateScript, what nixpkgs had shows as a name-version instead:
# "Going to be running update for following packages:\n - wesnoth-devel-1.19.24".
UPDATE_SCRIPT_PACKAGE = re.compile(
    r"Going to be running update for following packages:\s*\n\s*- (\S+)"
)
# Where the update's diff starts in a log.
DIFF_HEAD = "Diff after rewrites:\n"
# The PR the bot opened, or found open, as its API URL names it.
PR = re.compile(r"api\.github\.com/repos/NixOS/nixpkgs/(?:pulls|issues)/(\d+)")
PR_EXISTS = "There might already be an open PR"
# Several PRs are already open for this update's branch (nixpkgs-update's
# GH.hs).
TOO_MANY_PRS = "Too many open PRs from "
# Every rewriter left the package as it was. After an updateScript attempt
# ("0 -> 1") that means there was nothing to update; after a real version
# ("1.37 -> 1.38"), that the bot has no way to update this package.
EMPTY_DIFF = "The diff was empty after rewrites"
# The same, said when the derivation's file came out unchanged (Update.hs).
NO_REWRITES = "No rewrites performed on derivation."
# Why the rewriters that could have applied didn't: "[version] generic
# version rewriter does not support multiple hashes".
REWRITER = re.compile(r"^\[(?:version|updateScript)\] (\S.*)$", re.MULTILINE)
# Logs saying the update changed nothing.
NO_CHANGE = (
    EMPTY_DIFF,
    NO_REWRITES,
    "Package version did not change",
    # Someone updated it before the bot got to it.
    "not present in master derivation file",
)
# The bot already pushed this update to its branch (its PR open, or on its
# way): "An auto update branch exists with message `karakeep: 0.33.1 ->
# 0.33.2`. New version is 0.33.2." then this.
BRANCH_EXISTS = "An auto update branch exists with an equal or greater version"
BRANCH_MESSAGE = re.compile(
    r"An auto update branch exists with message `\S+ (\S+) -> (\S+)`"
)
# Nothing to update, and why: the candidate isn't newer by Nix's order ("0.1.0
# is not newer than 0.1.0-unstable-2024-06-14 according to Nix"), the
# rewriters found the same source, revision or dependencies' hash
# (Rewrite.hs, Update.hs), or the edit changes nothing nixpkgs builds.
NOTHING_NEWER = re.compile(
    r"^(?:\S+ is not newer than \S+ according to Nix.*"
    r"|(?:Hashes|cargo hashes|deps hashes|rev) equal; no update necessary.*"
    r"|Update edits cause no rebuilds\.)\s*$",
    re.MULTILINE,
)
# An updateScript package without a version: the bot can't tell what it
# updated to (Update.hs), so it can't update it.
NO_VERSION = re.compile(r"^The derivation has no 'version' attribute.*$", re.MULTILINE)
# The version rewriter changed the version but not where the source comes
# from: the bot can't update this package.
SOURCE_UNCHANGED = re.compile(r"^Source url did not change\.", re.MULTILINE)
# A request that failed, most often to GitHub's API (opening the PR). The
# dump of the request is no use as an excerpt; its host and the answer are.
HTTP_ERROR = re.compile(r"^HTTPError \(HttpExceptionRequest", re.MULTILINE)
HTTP_HOST = re.compile(r'host\s*=\s*"([^"]+)"')
HTTP_STATUS = re.compile(r'statusCode = (\d+), statusMessage = "([^"]*)"')
HTTP_EXCEPTION = re.compile(
    r"\b(ConnectionTimeout|ResponseTimeout|ConnectionFailure|TooManyRedirects|"
    r"InternalException|ConnectionClosed)\b"
)
# The bot's own checks before it tries anything. A line right after one of
# these that no other rule reads is why it stopped there on purpose (its
# skiplist: "Derivation file opts-out of auto-updates", "Do not update GNOME
# during a release cycle", "Python package with too many package rebuilds
# 3150 > 100", "rocm packages are upgraded in lockstep ...", "same as
# dune_3").
CHECKS = re.compile(
    r"^(?:attrpath: \S+|Checking auto update branch\.\.\."
    r"|No auto update branch exists)$"
)
# What makes an attempt failed: nix's build errors, nixpkgs-update's own
# and update scripts' errors, and the bot's checks of a build that went
# wrong (Nix.hs, Check.hs), which can end a log with no error line of nix's.
FAILED = re.compile(
    r"^error:|ExitFailure|failed with|^nix build failed\.|"
    r"nix log failed trying to get build logs|Could not find result link|"
    r"build succeeded unexpectedly|grep did not find version in file names|"
    r"Failed to read expected nix boolean",
    re.MULTILINE,
)
# Why a failed attempt failed ("failedBecause"): the first rule in
# FAILED_BECAUSE, in order, that one of the log's lines meets; that line and
# the next ones are its excerpt. The rules come from ~200 failed attempts'
# logs (2026-10-07). A reason earlier in the list causes those later (a
# missing dependency makes the build fail, a source gone makes nix-update
# fail).
#
# BOT_FAILURE is the bot's own machine failing, not the package
# (2026-10-08: 1,306 failed attempts said "the build users group 'nixbld'
# has no members"). It comes first, as it explains whatever follows it. It
# still counts as an update failure (someone should tell nixpkgs-update's
# maintainers), told apart by its reason.
BOT_FAILURE = (
    r"build users group '\S+' has no members"
    r"|cannot connect to socket at '\S*daemon-socket\S*'"
)
FAILED_BECAUSE = tuple(
    (because, re.compile(rule))
    for because, rule in (
        ("bot", BOT_FAILURE),
        # Not built where the bot builds: broken, insecure, not on x86_64-linux
        # (the package or a dependency).
        (
            "unavailable",
            r"Refusing to evaluate|is not available on the requested hostPlatform"
            r"|is marked as broken|not supported for interpreter",
        ),
        # nixpkgs' own changes to the source no longer apply: patches,
        # substituteInPlace.
        (
            "patch",
            r"Hunk #\d+ FAILED|patch does not apply|can't find file to patch"
            r"|Reversed \(or previously applied\) patch"
            r"|doesn't match anything in file"
            r"|substitute\(\): ERROR: file .* does not exist",
        ),
        # A dependency too old, missing, or new (a build backend, a module).
        (
            "dependency",
            r"not satisfied by version|^\s*- \S+ not installed$|Unmet dependencies"
            r"|Backend '\S+' is not available|Could NOT find"
            r"|required packages were not found|pkg-config tool not found"
            r"|Package '\S+'.* not found|Dependency \S+ found: NO|No module named"
            r"|no required module provides package|required \S+ module not found"
            r"|fatal error: \S+\.h: No such file",
        ),
        # A fixed-output hash (vendored dependencies, mostly) not updated, or
        # one the bot couldn't work out: it builds them with a wrong hash to
        # be told the right one, and they failed to build instead.
        (
            "hash",
            r"hash mismatch in fixed-output|ERROR: npmDepsHash|is out of date"
            r"|build succeeded unexpectedly",
        ),
        # The new version's source can't be fetched.
        (
            "source",
            r"curl: \(22\)|HTTP error 404|couldn't find remote ref|invalid refspec"
            r"|Unable to checkout|unable to download",
        ),
        # The package's updateScript (nix-update, mostly) failed on its own.
        (
            "updateScript",
            r"nix_update\.errors\.\w+:|update\.sh: line \d+:"
            r"|grep did not find version|does not provide attribute .*\.src'"
            r"|does not have a `passthru\.updateScript`|urllib\.error\.HTTPError:",
        ),
        (
            "tests",
            r"test result: FAILED|^Fail: +[1-9]|^=+ .*\d+ failed|^FAILED \S+::"
            r"|tests? failed out of|^--- FAIL:|^FAIL\s",
        ),
        # The build failed, and nix kept no log of it to tell why.
        ("noLog", r"build log of .* is not available"),
        # Any other error building it.
        (
            "build",
            r"error\[E\d+\]|fatal error:|: error:|error TS\d+|cannot find symbol"
            r"|[Cc]ompilation failed|undefined reference to|^CMake Error|^panic: "
            r"|^\S+: error: |^error: |\berror [A-Z]+\d+:|^ERROR[: ]|make: \*\*\*"
            r"|^\S+(?:Error|Exception|Invalid\w*): |cannot stat"
            r"|No such file or directory$"
            r"|but \.dist-info/METADATA specifies version",
        ),
    )
)
# nix's wrapping of a failed build: the reason comes before it.
WRAPPING = re.compile(
    r"^error: (?:Cannot build|builder for|\d+ dependencies of derivation|build of)"
    r"|^\s*For full logs, run:"
)
# Lines no rule reads as a reason: nix's wrapping, and a lookup the bot
# makes of every Go package's source that fails harmlessly.
NOT_A_REASON = re.compile(
    rf"{WRAPPING.pattern}|in selection path '\S+\.originalSrc' not found"
)
# What the bot runs, not what it printed.
NOT_OUTPUT = ("Raw command:", "Standard output:")
# An update script failing, in the bot's words.
UPDATE_SCRIPT_FAILED = "The update script for"
# Terminal colour codes.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# How many lines an excerpt keeps.
EXCERPT_LINES = 3


def attempts_url(attr):
    """Return the URL of the directory holding the bot's logs for attr."""
    return f"{config.NIXPKGS_UPDATE_LOGS_URL}/{search_term(attr)}/"


# The log site's front page lists every package's directory with when it
# last changed (nginx, in UTC): "<a href="unciv/">unciv/</a>   03-Oct-2026 00:00".
DIRECTORY = re.compile(
    r'<a href="([^"/]+)/">[^<]*</a>\s+(\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2})'
)
# Fewer directories than this means the page isn't the index it should be.
MIN_DIRECTORIES = 1000


def directory_dates():
    """Read when each package's log directory last changed, from the index.

    The log site's front page lists them all: one request instead of one
    listing per package (see unchanged). A directory also changes when old
    logs are cleaned up, so a change doesn't mean a new attempt; but no
    change means none.

    Returns:
        {directory: when it last changed}, or None when the index can't be
        read, so every package is listed as before.
    """
    try:
        page = http.get(f"{config.NIXPKGS_UPDATE_LOGS_URL}/", compressed=True)
    except (urllib.error.URLError, OSError) as e:
        print(f"  the log site's index: {e}; listing every package", file=sys.stderr)
        return None
    time.sleep(1)  # be polite
    found = {
        urllib.parse.unquote(name): datetime.strptime(when, "%d-%b-%Y %H:%M").replace(
            tzinfo=UTC
        )
        for name, when in DIRECTORY.findall(page or "")
    }
    if len(found) < MIN_DIRECTORIES:
        print(
            f"  the log site's index lists {len(found)} packages: not used",
            file=sys.stderr,
        )
        return None
    return found


def unchanged(attr, dates, since):
    """Return whether the bot's logs for attr can't have changed since `since`.

    They can't have when the package's directory last changed before since
    (with a minute's margin, as the index only shows minutes), or when it
    has no directory (the bot has never tried it).

    Args:
        attr: The attribute.
        dates: directory_dates' result, or None.
        since: When the logs were last listed (ISO), or None.
    """
    if dates is None or not since:
        return False
    changed = dates.get(search_term(attr))
    return changed is None or changed < datetime.fromisoformat(since) - timedelta(
        minutes=1
    )


def latest_date(attr):
    """Return the date of the bot's latest attempt at attr, or None."""
    listing = http.get(attempts_url(attr))
    time.sleep(1)  # be polite
    dates = LOG_NAME.findall(listing or "")
    return max(dates) if dates else None


def excerpt(log):
    """Return the last few meaningful lines of a log.

    Where a failed build stops is usually the reason; the ExitFailure line
    itself only says "Received ExitFailure".
    """
    lines = [
        ANSI.sub("", line).rstrip()[:200]
        for line in log.splitlines()
        if line.strip() and not line.startswith("@nix")
    ]
    return lines[-EXCERPT_LINES:]


def meaningful_lines(log):
    """Return log's lines without colours, trailing spaces or blank lines."""
    return [
        line
        for line in (ANSI.sub("", raw).rstrip() for raw in log.splitlines())
        if line
    ]


def http_excerpt(log):
    """Describe a failed request, as an excerpt.

    Returns:
        One line, such as "HTTPError from api.github.com: 500 Internal
        Server Error", with the exception's name instead of the status when
        there was no answer (a timeout).
    """
    host = HTTP_HOST.search(log)
    status = HTTP_STATUS.search(log)
    exception = HTTP_EXCEPTION.search(log)
    what = (
        f"{status.group(1)} {status.group(2)}".strip()
        if status
        else exception.group(1)
        if exception
        else "no answer"
    )
    return [f"HTTPError from {host.group(1)}: {what}" if host else f"HTTPError: {what}"]


def output_lines(log):
    """Return what the builds and scripts printed in log.

    That's its meaningful lines without the update's diff, the rewriters'
    notes ("[version] ...") and the commands the bot ran, and without the
    "> " nix puts before a build's lines.
    """
    lines, in_diff = [], False
    for raw in log.splitlines():
        line = ANSI.sub("", raw).rstrip()
        if line == DIFF_HEAD.strip():
            in_diff = True
            continue
        if in_diff:
            if not line or re.match(r"[ +\-@\\]|diff |index ", line):
                continue
            in_diff = False
        if not line.strip() or raw.startswith("@nix") or re.match(r"\[\w+\]", line):
            continue
        line = re.sub(r"^\s*> ?", "", line)
        if not line.startswith(NOT_OUTPUT):
            lines.append(line)
    return lines


def failed_because(log):
    """Work out why a failed attempt failed.

    Returns:
        (reason, excerpt). The reason is the first of FAILED_BECAUSE's rules
        that a line of log meets, and the excerpt is that line and the ones
        after it. When none does, the reason is "updateScript" if an update
        script failed, else "other", and the excerpt is the last lines
        before nix's wrapping of the failure, or the log's last lines.
    """
    lines = output_lines(log)
    for because, rule in FAILED_BECAUSE:
        for i, line in enumerate(lines):
            if not NOT_A_REASON.search(line) and rule.search(line):
                return because, [
                    shown.strip()[:200] for shown in lines[i : i + EXCERPT_LINES]
                ]
    because = "updateScript" if UPDATE_SCRIPT_FAILED in log else "other"
    wrapped = next((i for i, line in enumerate(lines) if WRAPPING.search(line)), None)
    if wrapped:
        return because, [
            shown.strip()[:200]
            for shown in lines[max(0, wrapped - EXCERPT_LINES) : wrapped]
        ]
    return because, excerpt(log)


def skip_reason(log):
    """Return why the bot stopped right after its own checks, or None.

    That's the line after the checks (CHECKS), when it's the log's last.
    """
    lines = meaningful_lines(log)
    if len(lines) >= 2 and CHECKS.match(lines[-2]) and not CHECKS.match(lines[-1]):
        return lines[-1][:200]
    return None


def diff_versions(log, was):
    """Read an updateScript attempt's versions from its diff.

    An updateScript log says "0 -> 1", so the versions come from the diff:
    every version change in it must update the version in was to the same
    new version.

    Args:
        log: The log.
        was: What nixpkgs had, as a name-version (wesnoth-devel-1.19.24).

    Returns:
        (from, to), or None when there's no diff (the script failed before
        writing one) or its changes don't agree.
    """
    if not was or DIFF_HEAD not in log:
        return None
    diff = log.split(DIFF_HEAD, 1)[1].splitlines()
    removed = [
        line[1:] for line in diff if line.startswith("-") and not line.startswith("---")
    ]
    added = [
        line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")
    ]
    parts = was.split("-")
    candidates = ["-".join(parts[i:]) for i in range(1, len(parts))]
    found = set()
    for old in candidates:
        quoted = f'"{old}"'
        for minus in removed:
            if quoted not in minus:
                continue
            pattern = re.escape(minus).replace(re.escape(quoted), r'"([^"\n]+)"', 1)
            pattern = pattern.replace(re.escape(quoted), r'"\1"')
            for plus in added:
                if (match := re.fullmatch(pattern, plus)) and match.group(1) != old:
                    found.add((old, match.group(1)))
    return next(iter(found)) if len(found) == 1 else None


def parse(log):
    """Read the attempt one log tells of.

    Returns:
        {"outcome", "from"?, "to"?, "was"?, "pr"?, "excerpt"?,
        "failedBecause"?}. outcome is one of:

        - prOpened or prExists;
        - branchExists: the bot already pushed this update to its branch;
        - cantUpdate: there's a newer version, but no way for the bot to
          update the package (excerpt says why);
        - noChange: excerpt says why, when the log does;
        - skipped: the bot passed it over on purpose (excerpt says why);
        - failed: failedBecause says why (see FAILED_BECAUSE), "request"
          when the bot's own request failed;
        - other.

        was is what nixpkgs had when the bot tried: a version (2.7.3) or,
        with an updateScript, a name-version (wesnoth-devel-1.19.24).
    """
    result = {}
    if info := UPDATE_INFO.search(log):
        result["from"], result["to"] = info.groups()
        if result["from"] != UPDATE_SCRIPT:
            result["was"] = result["from"]
        if "://" in result["to"]:
            # No new version, only where it would come from
            # (ocamlPackages.labltk's "8.06.16 -> https://github.com/...",
            # 2026-10-03).
            del result["to"]
    if "was" not in result and (package := UPDATE_SCRIPT_PACKAGE.search(log)):
        result["was"] = package.group(1)
    if result.get("from") == UPDATE_SCRIPT and (
        versions := diff_versions(log, result.get("was"))
    ):
        result["from"], result["to"] = versions
    prs = PR.findall(log)
    # A version the bot tried, not an updateScript's run (0 -> 1).
    real_version = result.get("from") not in (None, UPDATE_SCRIPT)
    if PR_EXISTS in log or TOO_MANY_PRS in log:
        result["outcome"] = "prExists"
    elif prs:
        result["outcome"] = "prOpened"
    elif BRANCH_EXISTS in log:
        result["outcome"] = "branchExists"
        branch = BRANCH_MESSAGE.search(log)
        if branch and result.get("from") in (None, UPDATE_SCRIPT):
            result["from"], result["to"] = branch.groups()  # the script's versions
    elif HTTP_ERROR.search(log):
        # The bot's own request (to GitHub's API, mostly), not the package.
        result.update(
            outcome="failed", failedBecause="request", excerpt=http_excerpt(log)
        )
    elif (EMPTY_DIFF in log or NO_REWRITES in log) and real_version:
        result.update(outcome="cantUpdate", excerpt=REWRITER.findall(log))
    elif no_version := NO_VERSION.search(log):
        result.update(outcome="cantUpdate", excerpt=[no_version.group(0).strip()])
    elif unchanged := SOURCE_UNCHANGED.search(log):
        result.update(outcome="cantUpdate", excerpt=[unchanged.group(0)])
    elif any(text in log for text in NO_CHANGE):
        result["outcome"] = "noChange"
    elif nothing := NOTHING_NEWER.search(log):
        result.update(outcome="noChange", excerpt=[nothing.group(0).strip()])
    elif FAILED.search(log):
        because, lines = failed_because(log)
        result.update(outcome="failed", failedBecause=because, excerpt=lines)
    elif reason := skip_reason(log):
        result.update(outcome="skipped", excerpt=[reason])
    else:
        result["outcome"] = "other"
    if prs and result["outcome"] in ("prExists", "prOpened"):
        result["pr"] = int(prs[-1])
    return result


def latest_attempt(attr, known=None, same=False):
    """Return the bot's latest attempt at attr, or None if it never tried.

    Args:
        attr: The attribute.
        known: An attempt read before (the previous run's). If it's this
            same attempt, read with the same rules, its reading is reused
            (as_read) instead of downloading the log again.
        same: Whether known is still the latest, as the logs haven't
            changed since it was read (unchanged). Then nothing is
            requested at all.

    Returns:
        {"attr", "date", "log", "parser", and parse's fields}, or None.
    """
    if same:
        if known is None:
            return None  # it hadn't tried, and still hasn't
        if reused := as_read(known, attr, known.get("date")):
            return reused
    date = latest_date(attr)
    if date is None:
        return None
    reused = as_read(known, attr, date)
    if reused:
        return reused
    url = f"{attempts_url(attr)}{date}.log"
    log = http.get(url) or ""
    time.sleep(1)
    return {"attr": attr, "date": date, "log": url, "parser": PARSER, **parse(log)}


def as_read(known, attr, date):
    """Return known as its log was read, if that reading can be reused.

    It can be when it's the attempt at attr on date, read by these rules
    (PARSER). What add_attempts judged afterwards (JUDGED: superseded,
    ignored) is left out, as it depends on the state of nixpkgs and the
    rules now, and is judged again.

    Returns:
        A copy, or None when it can't be reused.
    """
    if not known or known.get("parser") != PARSER:
        return None
    if known.get("attr") != attr or known.get("date") != date:
        return None
    if known.get("outcome") == "superseded" and not known.get("supersededOutcome"):
        return None  # can't tell what it was: read the log again
    attempt = {k: copy.deepcopy(v) for k, v in known.items() if k not in JUDGED}
    if known.get("outcome") == "superseded":
        attempt["outcome"] = known["supersededOutcome"]
    return attempt


def moved_on(attempt, version):
    """Return whether version differs from what nixpkgs had when the bot tried.

    False when the log doesn't say what that was.
    """
    was = attempt.get("was")
    if not was or not version or was == UPDATE_SCRIPT:
        return False
    # A name-version ends in the version: wesnoth-devel-1.19.24.
    return was != version and not was.endswith(f"-{version}")


def superseded(attempt, nix_version, master=None):
    """Return where nixpkgs has moved on since the attempt, or None.

    Someone updated the package another way, so the attempt's failure no
    longer matters. "nixos-unstable" is the channel; "master" means merged,
    but not in the channel yet.
    """
    if moved_on(attempt, nix_version):
        return "nixos-unstable"
    if moved_on(attempt, master):
        return "master"
    return None


# Outcomes that stop mattering once nixpkgs has moved past the version the
# bot tried.
SUPERSEDABLE = ("failed", "cantUpdate")


# BOT_FAILURE, to search an attempt's excerpt with.
BOT_FAILED = re.compile(BOT_FAILURE)


def with_bot_reason(attempt):
    """Set attempt's reason to "bot" when its excerpt shows the bot's machine failed.

    That's for attempts read before that reason existed (2026-10-08), by
    nixkeeper-updates or by an earlier sync, without reading their logs
    again: the excerpt holds the error.

    Returns:
        attempt, changed in place.
    """
    if (
        attempt
        and attempt.get("outcome") == "failed"
        and attempt.get("failedBecause") != "bot"
        and BOT_FAILED.search("\n".join(attempt.get("excerpt") or []))
    ):
        attempt["failedBecause"] = "bot"
    return attempt


def supersede(attempt, where):
    """Mark attempt superseded, keeping its outcome in supersededOutcome.

    The page then says what it was: "failed" or "couldn't update".

    Args:
        attempt: The attempt, changed in place.
        where: "nixos-unstable" or "master" (where nixpkgs moved past it),
            or "ignored" (a rule ignores it).
    """
    attempt.update(
        supersededOutcome=attempt["outcome"], outcome="superseded", supersededOn=where
    )


def recheck_superseded(rows: list[Row]):
    """Mark failed attempts superseded by an update found on master since.

    An update PR merged into master can be found after the logs were read.
    Marking the attempt superseded keeps a row that's waiting for the
    channel from also showing as failed.
    """
    for row in rows:
        attempt = row.get("update")
        if not attempt or attempt.get("outcome") not in SUPERSEDABLE:
            continue
        where = superseded(attempt, row.get("nixVersion"), on_master(row))
        if where:
            supersede(attempt, where)
            row["updateFailure"] = False


def at_version(attempt, version):
    """Return whether attempt is for version.

    That's its target ("to"), or, when an updateScript failed before
    picking one ("0 -> 1"), the version nixpkgs had ("was").
    """
    if not attempt or not version or version == UPDATE_SCRIPT_TO:
        return False
    if attempt.get("to") != UPDATE_SCRIPT_TO:
        return attempt.get("to") == version
    return bool(attempt.get("was")) and not moved_on(attempt, version)


def ignored(attempt, rules, outdated=False):
    """Return the reason a manual rule gives for ignoring a failed attempt.

    Args:
        attempt: The attempt.
        rules: {version: reason}, the row's entry in
            package-lists/ignored-updates.nix. A rule matches the version
            the bot tried to update to ("to"), or, when an updateScript
            failed before picking one ("0 -> 1") and the package isn't
            outdated, the version nixpkgs had ("was").
        outdated: Whether the package is outdated.

    Returns:
        The reason, or None when no rule matches.
    """
    if attempt.get("outcome") != "failed" or not rules:
        return None
    if attempt.get("to") == UPDATE_SCRIPT_TO and outdated:
        return None
    for version, reason in rules.items():
        if at_version(attempt, version):
            return reason
    return None


def read_attempts(attrs, old, dates, since, digest=None):
    """Read the bot's latest attempt at each of attrs it has tried.

    Each comes from the nixkeeper-updates digest where it can say
    (updates_digest.attempt), else from the logs, reusing the last sync's
    reading of a log that hasn't changed since.

    Args:
        attrs: The row's attributes in nixpkgs.
        old: The row in the last sync's data, or None.
        dates: directory_dates' result, or None.
        since: When the last sync listed the logs (ISO).
        digest: The updates digest (updates_digest.load), or None.

    Returns:
        (the attempts, how many of them came from the digest).

    Raises:
        urllib.error.URLError, OSError: The logs can't be read.
    """
    known = (old or {}).get("update")
    # Read fine last time: what it found still holds while the logs haven't
    # changed.
    refreshed = read_last_time(old)
    attempts, taken = [], 0
    for attr in attrs:
        if digest is not None:
            entry = digest.get(search_term(attr))
            if entry is None:
                continue  # the bot has never tried it
            if found := updates_digest.attempt(entry, attr, PARSER):
                attempts.append(found)
                taken += 1
                continue  # else read the log: the digest hasn't read it
        if dates is not None and search_term(attr) not in dates:
            continue  # no logs at all: the bot has never tried it
        mine = known if (known or {}).get("attr") == attr else None
        same = (
            refreshed
            and unchanged(attr, dates, since)
            and (mine is not None or known is None)
        )
        if attempt := latest_attempt(attr, mine if same else known, same):
            attempts.append(attempt)
    return attempts, taken


def read_last_time(old):
    """Return whether the last sync read the row's attempts.

    Not when it couldn't (notRefreshed), nor when the row's turn hadn't
    come (unread, with every package).

    Args:
        old: The row in the last sync's data, or None.
    """
    return (
        old is not None
        and "update" not in (old.get("notRefreshed") or {})
        and "update" not in (old.get("unread") or [])
    )


def to_read(row, attrs, old, dates, since):
    """Return whether reading row's attempts takes a request.

    It does when one of attrs has logs whose directory changed since the
    last sync read them, or when that sync couldn't read them.
    """
    known = (old or {}).get("update")
    refreshed = read_last_time(old)
    for attr in attrs:
        if dates is not None and search_term(attr) not in dates:
            continue  # no logs: nothing to read
        mine = known if (known or {}).get("attr") == attr else None
        if not (
            refreshed
            and unchanged(attr, dates, since)
            and (mine is not None or known is None)
        ):
            return True
    return False


def bulk_turns(rows, nixpkgs, before, dates, since, bulk):
    """Choose the rows in bulk whose attempts are read this sync.

    With every package, the rows in bulk (not on the lists, and not in a
    set updated in bulk) can't all be read each sync. Of those that take a
    request (to_read), at most UPDATE_LOGS_BUDGET are read: outdated or
    failing ones first, then those waiting longest. The rest keep their
    last attempt until a later sync.

    Returns:
        The rows' names; none when the log site's index can't be read, as
        each row would then take a request.
    """
    if dates is None:
        return set()
    waiting = []
    for row in rows:
        if row["name"] not in bulk or row.get("set"):
            continue
        attrs = [a for a in row["attrs"] if a in nixpkgs]
        old = before.get(row["name"])
        if attrs and to_read(row, attrs, old, dates, since):
            urgent = is_outdated(row) or bool((old or {}).get("updateFailure"))
            read = ((old or {}).get("update") or {}).get("date") or ""
            waiting.append((not urgent, read, row["name"]))
    waiting.sort()
    return {name for _, _, name in waiting[: config.UPDATE_LOGS_BUDGET]}


def add_queue(rows, nixpkgs, queue):
    """Mark the rows the update bot will try again, from its queue.

    Each such row gets "queued": {"by": the day it's expected, "candidates":
    [[version, source URL], ...], "script"?}, from its soonest attribute's
    entry in the queue (updates_digest.load_queue). The candidates are the
    versions the bot would update it to that nixpkgs doesn't have yet;
    "script" says it also runs the package's updateScript. Rows not in
    nixpkgs or not in the queue get none.

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        queue: The queue, or None (then nothing changes).
    """
    if not queue:
        return
    for row in rows:
        found = [
            queue[search_term(a)]
            for a in row.get("attrs") or []
            if a in nixpkgs and search_term(a) in queue
        ]
        if not found:
            continue
        soonest = min(found, key=lambda e: e["by"])
        candidates = []
        for candidate in soonest["candidates"]:
            # Each is [from, to, source URL], without a URL when the queue
            # had none.
            to, source = candidate[1], (candidate[2:] or [""])[0]
            if to != row.get("nixVersion") and [to, source] not in candidates:
                candidates.append([to, source])
        row["queued"] = {"by": soonest["by"]}
        if candidates:
            row["queued"]["candidates"] = candidates
        if soonest.get("script"):
            # It also runs the package's updateScript, which decides the version.
            row["queued"]["script"] = True


def add_attempts(
    rows: list[Row],
    nixpkgs,
    previous,
    now,
    ignored_updates=None,
    community=(),
    bulk=frozenset(),
    digest=None,
):
    """Give every row in nixpkgs the update bot's latest attempt.

    Each row gets "update" (None when the bot never tried) and
    "updateFailure" (whether that attempt failed). With several attributes,
    the most recently attempted one counts. A row whose logs can't be read
    keeps the previous run's result and is marked as not refreshed. A
    failed attempt is marked superseded when nixpkgs has moved past it, or
    when a manual rule ignores it.

    Each row's attempts are found first (_Finder.find), then the latest is
    judged (judge).

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        previous: The last run's data.
        now: The run's time.
        ignored_updates: {row name: {version: reason}}: versions whose
            failed attempts count as superseded (a version that was never
            really released, say).
        community: The (row name, version) pairs of ignored_updates that
            are community rules (community.py); their attempts are marked
            so.
        bulk: With every package, the names of the rows not on the lists.
            They get the digest's last read attempt, and one with none gets
            "unread": ["update"]. Without the digest, they're read within a
            budget (bulk_turns), except those in sets updated in bulk, which
            the bot rarely tries.
        digest: The nixkeeper-updates digest (updates_digest.load): the
            attempts it can answer are taken from it instead of the logs.
    """
    ignored_updates = ignored_updates or {}
    print("Checking nixpkgs-update logs...", file=sys.stderr)
    finder = _Finder(rows, nixpkgs, previous, now, bulk, digest)
    for row in rows:
        attrs = [a for a in row["attrs"] if a in nixpkgs]
        if not attrs:
            continue  # not in nixpkgs: nothing for the bot to update
        attempts = finder.find(row, attrs)
        # None: the row is done with (kept or unread). An empty list still
        # goes to judge: the bot never tried, so "update" is None.
        if attempts is not None:
            judge(row, attempts, ignored_updates.get(row["name"]), community)
    finder.report()


class _Finder:
    """Finds each row's attempts, from the digest, the logs or the last sync.

    It holds what's read once for every row (the logs' dates, the bulk
    rows' turns), and counts what it found, for report().
    """

    def __init__(self, rows, nixpkgs, previous, now, bulk, digest):
        """Read what every row's search shares.

        Args:
            rows: The rows.
            nixpkgs: The package index, by attribute.
            previous: The last run's data.
            now: The run's time.
            bulk: The names of the rows not on the lists (add_attempts).
            digest: The updates digest, or None.
        """
        self.now, self.bulk, self.digest = now, bulk, digest
        self.before = {row["name"]: row for row in previous["packages"]}
        # When each package's logs last changed, in one request: those that
        # haven't since the last sync listed them aren't listed again.
        self.dates = directory_dates()
        self.since = previous.get("checkedAt")
        self.turns = (
            bulk_turns(rows, nixpkgs, self.before, self.dates, self.since, bulk)
            if bulk and digest is None
            else set()
        )
        self.failed = self.consecutive = self.waited = self.from_digest = 0

    def find(self, row, attrs):
        """Return the row's attempts, or None when the row is done with.

        None when the row keeps the last sync's attempt (its turn hasn't
        come, or its logs can't be read), or, in a set updated in bulk
        without the digest, gets none.

        Args:
            row: The row; marked "unread" or not refreshed here when its
                attempts aren't read.
            attrs: The row's attributes in nixpkgs.
        """
        old = self.before.get(row["name"])
        if row["name"] in self.bulk:
            if self.digest is not None:
                return self._known(row, attrs)
            if row.get("set"):
                return None  # sets updated in bulk: the digest's attempts only
            if row["name"] not in self.turns and (
                self.dates is None or to_read(row, attrs, old, self.dates, self.since)
            ):
                self.waited += 1
                _keep(row, old)
                row["unread"] = ["update"]
                return None
        return self._read(row, attrs, old)

    def _known(self, row, attrs):
        """Return the digest's last read attempts at attrs.

        Those are taken even where it hasn't read the newest yet; a row
        with none read there is marked "unread".
        """
        entries = [(a, self.digest.get(search_term(a))) for a in attrs]
        attempts = [
            found
            for a, entry in entries
            if entry and (found := updates_digest.known(entry, a))
        ]
        self.from_digest += bool(attempts)
        if not attempts and any(entry for _, entry in entries):
            self.waited += 1
            row["unread"] = ["update"]
        return attempts

    def _read(self, row, attrs, old):
        """Return the attempts from the digest or the logs (read_attempts).

        After UPDATE_LOGS_MAX_CONSECUTIVE_FAILURES failed lookups in a row,
        the logs aren't asked again this sync. A row whose attempts can't
        be read keeps the last sync's, marked not refreshed, and gets None.
        """
        down = self.consecutive >= config.UPDATE_LOGS_MAX_CONSECUTIVE_FAILURES
        try:
            if down:
                raise OSError("not asked: it didn't answer earlier lookups")
            attempts, taken = read_attempts(
                attrs, old, self.dates, self.since, self.digest
            )
        except (urllib.error.URLError, OSError) as e:
            self.failed += 1
            self.consecutive += not down
            if not down:
                print(f"  {row['name']}: {e}", file=sys.stderr)
            _keep(row, old or {})
            history.not_refreshed(
                row,
                "update",
                f"couldn't read the nixpkgs-update logs ({e})",
                old or {},
                self.now,
            )
            return None
        self.from_digest += taken
        self.consecutive = 0
        return attempts

    def report(self):
        """Say in the log what couldn't be read, and where attempts came from."""
        if self.failed:
            print(
                f"::warning::{self.failed} nixpkgs-update log lookups failed; "
                "those show the previous run's result",
                file=sys.stderr,
            )
        if self.digest is not None:
            print(
                f"  {self.from_digest:,} attempts from the updates digest"
                + (
                    f"; {self.waited:,} packages not read yet there"
                    if self.waited
                    else ""
                ),
                file=sys.stderr,
            )
        elif self.bulk:
            print(
                f"  {len(self.turns):,} packages not on the lists read (at most "
                f"{config.UPDATE_LOGS_BUDGET:,} a sync); {self.waited:,} not read",
                file=sys.stderr,
            )


def _keep(row: Row, old):
    """Give row the last sync's attempt, as it isn't read this time.

    Args:
        row: The row, changed in place.
        old: The row in the last sync's data, or None.
    """
    row["update"] = with_bot_reason((old or {}).get("update"))
    row["updateFailure"] = bool((old or {}).get("updateFailure"))


def judge(row: Row, attempts, rules=None, community=()):
    """Give row the latest of attempts, judged by nixpkgs' state and the rules.

    A failed attempt is superseded where nixpkgs has moved past it
    (superseded: "master" comes from Hydra, read before this), or else when
    one of rules ignores it (ignored). A rule that no longer matches the
    latest attempt is said in the log, as it can go, unless it's a
    community rule (community-check lists those).

    Args:
        row: The row, changed in place: "update" and "updateFailure".
        attempts: The row's attempts, one per attribute the bot tried.
        rules: {version: reason}, the row's ignored updates, or None.
        community: The (row name, version) pairs of rules that are
            community rules.
    """
    rules = rules or {}
    attempt = with_bot_reason(max(attempts, key=lambda a: a["date"], default=None))
    if (
        attempt
        and attempt.get("from") == UPDATE_SCRIPT
        and "was" not in attempt
        and row.get("nixVersion")
    ):
        attempt["was"] = row["nixVersion"]
    where = (
        attempt
        and attempt["outcome"] in SUPERSEDABLE
        and superseded(attempt, row.get("nixVersion"), row.get("master"))
    )
    if where:
        supersede(attempt, where)
    elif attempt and (reason := ignored(attempt, rules, is_outdated(row))):
        supersede(attempt, "ignored")
        attempt["reason"] = reason
        if any((row["name"], v) in community and at_version(attempt, v) for v in rules):
            attempt["community"] = True
    for version in rules:
        # Community rules are listed by the community's own tidy-up
        # (community-check), not here.
        if (row["name"], version) in community:
            continue
        if not at_version(attempt, version):
            print(
                f"::notice::ignoredUpdates.{row['name']}: the bot's latest "
                f"attempt isn't at {version} anymore; the rule can go",
                file=sys.stderr,
            )
    row["update"] = attempt
    row["updateFailure"] = bool(attempt and attempt["outcome"] == "failed")
