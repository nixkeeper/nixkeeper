"""Estimate how big a sync is, and keep it within reason.

Every tracked package costs time and requests to public services
(Repology, Hydra, the nixpkgs-update logs, GitHub). So the sync says up
front how long it should take, the list check warns from WARN_PACKAGES
packages, and above MAX_PACKAGES the sync refuses to start unless the
lists raise the limit (maxPackages). A big team or a typo then can't send
thousands of requests by accident.

The costs below were measured on a real sync (241 packages, 2026-10-05)
that took Hydra's and Repology's data from the digests (nixkeeper-hydra,
nixkeeper-versions) and GitHub's from bulk listings. Most of a sync's cost
is then fixed (the listings, the digests, the package index), whatever the
lists' size. What's left per package is the Hydra jobs the digest can't
answer, the nixpkgs-update log folders that changed, and the update
checks. A package new to the data costs more the first time, because its
whole update-log folder is read. Without the digests (turned off, or out
of date) and the listings (failing), the sync asks per package instead,
and takes much longer than these estimates say.
"""

import os
import sys

# What a package costs, as (seconds, requests): in the first sync it's in
# (its whole update-log folder, and the Hydra jobs the digest can't answer),
# and on a typical day after (those Hydra jobs, and log folders that changed).
FIRST = (2.5, 3)
TYPICAL = (0.4, 0.3)
# What every sync costs, whatever its size: the package index, the digests,
# starting the meta.broken evaluations, the listing of all open PRs and
# issues (about 120 requests and 80 s), and the merged PRs.
FIXED = (120, 150)
# From this many packages, the list check warns. It was 500 until quiet
# packages were asked only every few days: a typical day for 1,500 now
# costs less than 500 did.
WARN_PACKAGES = 1500
# Above this many, the sync refuses to start unless the lists say
# otherwise: a safety net against a typo or a huge team. It was 2,000
# before the same change.
MAX_PACKAGES = 5000
# GitHub Actions stops a job after 6 hours, and the job then publishes
# nothing, so check warns about a sync expected to take nearly that long.
GITHUB_ACTIONS_SECONDS = 6 * 3600


def estimate(count, new=0):
    """Estimate how long a sync takes and how many requests it makes.

    Args:
        count: How many packages it tracks.
        new: How many of them are new to the data (they cost more the first
            time).

    Returns:
        (seconds, requests), rough estimates.
    """
    new = min(new, count)
    known = count - new
    seconds = FIXED[0] + known * TYPICAL[0] + new * FIRST[0]
    return seconds, round(FIXED[1] + known * TYPICAL[1] + new * FIRST[1])


def duration(seconds):
    """Say a duration as an estimate: "about 7 min", "about 1 h 30 min".

    Long durations are rounded to 10 minutes, so they don't look precise.
    """
    minutes = max(1, round(seconds / 60))
    if minutes < 50:
        return f"about {minutes} min"
    hours, minutes = divmod(round(minutes / 10) * 10, 60)
    return f"about {hours} h" + (f" {minutes} min" if minutes else "")


def about(requests):
    """Say a number of requests as an estimate: 2,400, not 2,397."""
    return f"{round(requests, -2 if requests >= 1000 else -1):,}"


def describe(count):
    """Describe what syncing count packages costs, as a phrase for messages.

    It gives a typical day's cost, then the first sync's (with every
    package new to the data).
    """
    typical, first = estimate(count), estimate(count, count)
    return (
        f"{count:,} packages: a sync takes {duration(typical[0])} and makes about "
        f"{about(typical[1])} requests to public services on a typical day "
        f"({duration(first[0])} and {about(first[1])} the first time)"
    )


def limit(lists):
    """Find the most packages the lists may track.

    Returns:
        The lists' maxPackages if it's a positive whole number, otherwise
        MAX_PACKAGES.
    """
    value = (lists or {}).get("maxPackages")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return MAX_PACKAGES


def check(lists, count, new=0):
    """Stop a sync that's too big; otherwise say how long it should take.

    The estimate goes to the log, and on GitHub Actions to the run's summary
    too, with a warning when the sync may outlast the job's 6 hours.

    Args:
        lists: The package lists (their maxPackages raises the limit).
        count: How many packages the sync tracks.
        new: How many of them are new to the data.

    Raises:
        SystemExit: count is over the limit; the message says how to raise it.
    """
    most = limit(lists)
    if count > most:
        sys.exit(
            f"The package lists track {describe(count)}, more than nixkeeper "
            f"syncs without being asked ({most:,}). To sync them anyway, set "
            f"maxPackages = {count}; in the lists (lists.maxPackages in the "
            "NixOS or nix-darwin module); or track fewer (smaller teams, "
            "shorter lists)."
        )
    seconds, requests = estimate(count, new)
    message = (
        f"Tracking {count:,} packages"
        + (f" ({new:,} new: asked about whole, the first time)" if new else "")
        + f": this sync should take {duration(seconds)} and make about "
        f"{about(requests)} requests to public services."
    )
    print(message, file=sys.stderr)
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and seconds > GITHUB_ACTIONS_SECONDS * 0.9
    ):
        print(
            f"::warning::This sync may outlast GitHub Actions' 6-hour limit, and "
            f"publish nothing: {new:,} packages are new to the data. Add big "
            "lists in stages (only new packages cost this much), or run this "
            "first sync somewhere without the limit.",
            file=sys.stderr,
        )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"{message}\n\n")


def problem(count, lists):
    """Warn, for the list check, when the lists track a lot of packages.

    Returns:
        A sentence when count is from WARN_PACKAGES up to the limit, else
        None (over the limit, the sync refuses to start anyway).
    """
    if count < WARN_PACKAGES or count > limit(lists):
        return None
    return (
        f"the lists track {describe(count)}: consider fewer (smaller teams, "
        "shorter lists), to go easy on those services"
    )
