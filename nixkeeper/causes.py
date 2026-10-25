"""Group failed builds by their error, and the update bot's failures by cause.

Failed builds are grouped by the same error: the line of their log that
says it (nixkeeper-hydra's excerpt), with what differs from one package to
the next taken out (store paths, file paths and line numbers, numbers,
quoted names). A group is one cause with one fix pattern ("the abseil-cpp
update broke 7 packages"), which neither the blockers (those are failing,
not blocked) nor the reason filters (330 "compile") show. It's automatic: a
new compiler or library breaking many packages the same way is a new group
on the next sync, under any reason, "other" included; a big one there is
the next reason for nixkeeper-hydra's classifier to learn.

Groups get a friendly title where a pattern is known (TITLES), else the
error line itself, as read.
"""

import hashlib
import re
from collections import Counter

# Groups of fewer packages than this aren't shown: one-offs.
MIN_PACKAGES = 3
# How many groups the overview's card shows; the rest are a click away.
SHOWN = 8
# How many groups are kept, each a view of its packages.
KEPT = 40
# A line that says what failed, before others.
ERROR = re.compile(
    r"\berror\b|\bError\b|ERROR|\bfailed\b|FAILED|ModuleNotFoundError|"
    r"\bundefined reference\b|\bnot found\b",
)
# Lines that are the build's chatter, not its failure.
CHATTER = re.compile(r"^(Running phase|.*completed in \d|\s*$|\s*\d+ \|)")
# Lines that say that it failed, not why: a specific line wins over them,
# and a build with only these isn't grouped (its cause isn't in the excerpt).
GENERIC = re.compile(
    r"ld returned \d+ exit status|linker command failed|"
    r"could not compile .* due to \d+ previous error|test failed, to rerun|"
    r"^\s*FAIL\s*$|builder for .* failed|make(\[\d+\])?: \*\*\*|"
    r"ninja: build stopped|^error: \d+ errors? generated|"
    r"Command .* returned non-zero exit status|exited with code \d+$|"
    r"build failed, waiting for other jobs|for all supported options|"
    r"^error: aborting due to|Configuring incomplete, errors occurred|"
    r"^=+ .*\b\d+ (failed|errors?)\b.* in [\d.]+s =+$|"
    r"^TIP pass --env-dir|the following build command failed|^# ERROR: \d+$",
    re.IGNORECASE,
)
# What signature takes out of an error line, in order, and what it puts
# instead.
NORMALIZE = (
    (re.compile(r"/nix/store/[a-z0-9]{32}-[^/\s:'\"]*"), "<store>"),
    # A source file and line, wherever it is ("foo.c:12:3" and
    # "/build/source/src/foo.c:12:3" are the same error): before paths.
    (
        re.compile(
            r"(?<![\w<>])/?[\w./+-]*\.(?:c|cc|cpp|cxx|h|hh|hpp|rs|go|py|java|ts|js|nix)"
            r":\d+(?::\d+)?"
        ),
        "<file>",
    ),
    (re.compile(r"(?:/build|/tmp|/private/tmp)/[^\s:'\"]*"), "<path>"),
    (re.compile(r"'[^']{0,80}'|‘[^’]{0,80}’|\"[^\"]{0,80}\"|`[^`]{0,80}`"), "'…'"),
    (re.compile(r"\d+"), "N"),
    (re.compile(r"\s+"), " "),
)
# Friendly titles for patterns we know: (pattern on the line, title, what it
# concerns), the first that matches; "{}" in a title is the pattern's first
# group (the header, the module), so each is a group of its own.
TITLE_PATTERNS = (
    (
        r"METADATA specifies version|pyprojectVersionPatchHook",
        "Version doesn't match the package's metadata",
        "python",
    ),
    (r"No module named '([\w.]+)'", "Python module missing: {}", "python"),
    (r"ModuleNotFoundError|No module named", "A Python module is missing", "python"),
    (
        r"incompatible pointer type.*(cfg\d*|wiphy|net_device|ieee\d*)"
        r"|(cfg80211|wiphy).*incompatible",
        "Kernel driver vs. a newer kernel's API",
        "kernel drivers",
    ),
    (
        r"implicit declaration of function|call to undeclared function"
        r"|implicit function declaration",
        "Implicit function declarations (C23 by default)",
        "compiler",
    ),
    (r"absl::", "Broken by the abseil-cpp update", "abseil-cpp"),
    (r"boost::", "Broken by a Boost update", "boost"),
    (
        r"set but not used \[-Werror",
        "Unused variable is an error (newer compiler)",
        "compiler",
    ),
    (
        r"incompatible pointer type",
        "Incompatible pointer types (newer compiler)",
        "compiler",
    ),
    (
        r"discards \S+ qualifier|discarded-qualifiers",
        "Discards a const qualifier (newer compiler)",
        "compiler",
    ),
    (
        r"Compatibility with CMake < ?\d|cmake_minimum_required",
        "Too old for CMake 4",
        "cmake",
    ),
    (r"hash mismatch|got: *sha", "Source hash mismatch", "fetch"),
    (r"undefined reference to", "Link: undefined reference", "link"),
    (
        r"fatal error: '?([\w./+-]+\.h\w*)'?:? (?:file not found|No such file)",
        "Missing header: {}",
        "headers",
    ),
    (
        r"fatal error: .+ file not found|fatal error: .+: No such file or directory",
        "A header is missing",
        "headers",
    ),
    (r"is deprecated \[-Werror", "Deprecated declaration is an error", "compiler"),
)
TITLES = tuple((re.compile(p), title, about) for p, title, about in TITLE_PATTERNS)
# In a kernel module, these errors mean the kernel changed (a function it
# dropped, a callback's new signature), not the compiler: the kernel's title.
KERNEL_API = next(t[1:] for t in TITLES if t[2] == "kernel drivers")
KERNEL_MEANS_API = {
    "Implicit function declarations (C23 by default)",
    "Incompatible pointer types (newer compiler)",
}
# A kernel module's attribute: one per kernel.
KERNEL_MODULE = re.compile(r"^(?:linuxKernel\.packages\.[\w]+|linuxPackages\w*)\.")


def error_line(excerpt):
    """Return the line of a failed build's excerpt that says why it failed.

    That's the first line that looks like an error and isn't a generic one
    (GENERIC), else the first specific line naming a known cause (TITLES).

    Args:
        excerpt: The excerpt, as a list of lines or one string.

    Returns:
        The line, or "" when only generic lines say it.
    """
    lines = excerpt if isinstance(excerpt, list) else str(excerpt or "").splitlines()
    lines = [
        line for line in lines if not CHATTER.match(line) and not GENERIC.search(line)
    ]
    return next(
        (line for line in lines if ERROR.search(line)),
        next((line for line in lines if title_of(line)[0]), ""),
    )


def signature(line):
    """Return line with what differs between packages taken out.

    The same error in two packages then gives the same signature.
    """
    for pattern, said in NORMALIZE:
        line = pattern.sub(said, line)
    return line.strip()[:160]


def title_of(line):
    """Return the friendly title for an error line, and what it concerns.

    Returns:
        (title, what it concerns) for a line we know, raw or normalized;
        else (None, None).
    """
    for pattern, title, about in TITLES:
        if m := pattern.search(line):
            return (title.format(m.group(1)) if "{}" in title else title), about
    return None, None


def is_kernel_module(row):
    """Return whether a package is built against a kernel.

    That's linuxPackages.foo and the like, one per kernel.
    """
    return any(KERNEL_MODULE.match(a) for a in [row["name"], *(row.get("attrs") or [])])


def key_of(sig):
    """Return a group's key, for its view and the page's address (?cause=)."""
    return hashlib.sha256(sig.encode()).hexdigest()[:10]


def build_groups(rows):
    """Group the failed builds that share an error.

    Only rows not in a set updated in bulk count (those count on their
    set's line), each package once however many of its builds fail the
    same way. Groups of fewer than MIN_PACKAGES packages are left out, and
    the biggest KEPT are kept.

    Returns:
        [{"key", "signature", "line", "reason", "count", "title"?,
        "about"?, "rows"}], the biggest first. line is one package's own
        line, as an example; reason is the commonest of the group's
        (nixkeeper-hydra's failedBecause).
    """
    groups = {}
    for row in rows:
        if row.get("set"):
            continue
        seen = set()
        for build in row.get("builds") or []:
            if build["status"] != "failed" or not build.get("failedExcerpt"):
                continue
            line = error_line(build["failedExcerpt"])
            sig = signature(line)
            if not sig:
                continue
            # A known cause is one group whatever the line's wording; else
            # the line itself.
            title, about = title_of(line)
            if title in KERNEL_MEANS_API and is_kernel_module(row):
                title, about = KERNEL_API
            key = f"title:{title}" if title else sig
            if key in seen:
                continue
            seen.add(key)
            group = groups.setdefault(
                key,
                {
                    "line": line.strip()[:200],
                    "signature": sig,
                    "title": title,
                    "about": about,
                    "reasons": Counter(),
                    "rows": [],
                },
            )
            group["reasons"][build.get("failedBecause") or "other"] += 1
            group["rows"].append(row)
    found = []
    for key, group in groups.items():
        if len(group["rows"]) < MIN_PACKAGES:
            continue
        entry = {
            "key": key_of(key),
            "signature": group["signature"],
            "line": group["line"],
            "reason": group["reasons"].most_common(1)[0][0],
            "count": len(group["rows"]),
            "rows": group["rows"],
        }
        if group["title"]:
            entry["title"], entry["about"] = group["title"], group["about"]
        found.append(entry)
    found.sort(key=lambda g: (-g["count"], g["signature"]))
    return found[:KEPT]


def bot_causes(rows):
    """Count the update bot's failures by cause.

    The cause is nixkeeper's reading of the bot's logs (failedBecause),
    "other" without one. Rows in a set updated in bulk are left out.

    Returns:
        {cause: packages}, the commonest first.
    """
    found = Counter(
        (row.get("update") or {}).get("failedBecause") or "other"
        for row in rows
        if row.get("updateFailure") and not row.get("set")
    )
    return dict(found.most_common())
