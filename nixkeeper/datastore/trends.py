"""The records kept from run to run: the history, what was fixed, the events.

history.json holds each day's counts (with_point, with_split), the fixes of
the last days (with_fixed, fixed_summary) and the events marked on the
trends (with_events); each part is read back by its read_ function.
"""

import os
from datetime import UTC, datetime, timedelta

from .. import config
from . import facts, shards

# How many days of counts history.json keeps (with every package).
HISTORY_DAYS = 365


def with_split(history, previous):
    """Add the previous run's split failure counts to its day's point.

    The failures were recorded as one count before 0.13.0, and as two
    after (SPLIT_COUNTS). The previous manifest has them apart, so its
    day's point gets them where it doesn't have them yet. Older manifests
    have no buildFailures count; the count of the overview's failing
    highlights stands for it.

    Args:
        history: The history points, oldest first.
        previous: The previous run's manifest.

    Returns:
        history, with that day's point completed, or as it was when the
        manifest lacks either count.
    """
    run = previous.get("checkedAt") or ""
    counts = previous.get("counts") or {}
    found = {
        "buildFailures": counts.get("buildFailures")
        if "buildFailures" in counts
        else ((previous.get("highlights") or {}).get("failing") or {}).get("count"),
        "updateFailures": counts.get("updateFailures"),
    }
    if not run or any(v is None for v in found.values()):
        return history
    return [{**found, **p} if p.get("day") == run[:10] else p for p in history]


def with_point(history, run, counts):
    """Record this run's counts as its day's point in the history.

    A second sync on the same day replaces the first one's point. Only the
    last HISTORY_DAYS days are kept.

    Args:
        history: The points, each {"day", counts...}, oldest first.
        run: The run's time.
        counts: The manifest's counts, of the fully checked rows. The ones
            in HISTORY_COUNTS are recorded.

    Returns:
        The points, oldest first.
    """
    day = (run or "")[:10]
    point = {"day": day, **{k: counts[k] for k in HISTORY_COUNTS}}
    kept = [p for p in history if p.get("day") != day]
    return sorted([*kept, point], key=lambda p: p["day"])[-HISTORY_DAYS:]


# The counts history.json records each day, of the fully checked rows.
HISTORY_COUNTS = (
    "tracked",
    "outdated",
    "failed",
    "buildFailures",
    "updateFailures",
    "vulnerable",
    "broken",
)
# The counts a history point didn't have before 0.13.0, when the failures
# were split in two. with_split takes them from the previous manifest for
# its own day's point.
SPLIT_COUNTS = ("buildFailures", "updateFailures")


# How many days of fixes history.json keeps, and how many days the
# overview counts them over.
FIXED_DAYS = 30
FIXED_RECENT_DAYS = 7


def read_fixed(out_dir=None):
    """Return the fixes kept in the last run's history.json, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return (
            shards.read_json(os.path.join(out_dir, "history.json")).get("fixed") or []
        )
    except (OSError, ValueError, AttributeError):
        return []


def with_fixed(fixed, new, run):
    """Add this run's fixes to the kept ones.

    A package's fix of one kind is kept once a day, as a second sync on the
    same day finds it again. Only the last FIXED_DAYS days are kept.

    Args:
        fixed: The kept fixes, oldest first.
        new: This run's fixes.
        run: The run's time.

    Returns:
        The fixes, oldest first.
    """
    cutoff = _day_before(run, FIXED_DAYS)
    seen, kept = set(), []
    for fix in [*fixed, *new]:
        key = (fix["at"][:10], fix["name"], fix["kind"])
        if fix["at"][:10] > cutoff and key not in seen:
            seen.add(key)
            kept.append(fix)
    return sorted(kept, key=lambda f: (f["at"], f["name"], f["kind"]))


def fixed_summary(fixed, run):
    """Summarize the recent fixes, for the manifest's "fixed".

    For each kind of fix (build, update, bot), count the fixes of the last
    FIXED_RECENT_DAYS days and pick HIGHLIGHTS of them to show. The list is
    called "newest" from when it held the newest ones; it now holds the
    fixes whose problem had lasted longest first (with about a hundred
    fixes a day, the newest are all the last sync's), then those that don't
    say since when, newest first. A family is listed once, as its first
    member.

    Args:
        fixed: The kept fixes.
        run: The run's time.

    Returns:
        {"days": FIXED_RECENT_DAYS, and for each kind: {"count", "newest"}},
        each fix in "newest" as _fixed_entry formats it.
    """
    cutoff = _day_before(run, FIXED_RECENT_DAYS)
    out = {}
    for kind in ("build", "update", "bot"):
        mine = [f for f in fixed if f["kind"] == kind and f["at"][:10] > cutoff]
        # Newest first, ties by name. The sort by how long the problem
        # lasted, below, keeps this order among equals.
        newest = sorted(
            sorted(mine, key=lambda f: f["name"]), key=lambda f: f["at"], reverse=True
        )
        shown = facts.grouped(
            sorted(newest, key=_lasted, reverse=True),
            lambda f: f.get("family"),
            lambda f: f["name"],
        )[: facts.HIGHLIGHTS]
        out[kind] = {
            "count": len(mine),
            "newest": [_fixed_entry(f, members) for f, members in shown],
        }
    return {"days": FIXED_RECENT_DAYS, **out}


def _lasted(fix):
    """Return how long fix's problem had lasted, in seconds.

    Returns:
        The seconds from when the problem began to when it was fixed, or -1
        when the fix doesn't say when it began.
    """
    try:
        since = datetime.fromisoformat(fix["since"])
        if since.tzinfo is None:  # a day without a time: midnight UTC
            since = since.replace(tzinfo=UTC)
        return max(0, (datetime.fromisoformat(fix["at"]) - since).total_seconds())
    except (KeyError, TypeError, ValueError):
        return -1


def _fixed_entry(fix, members=None):
    """Format a fix as the manifest lists it (see fixed_summary).

    Args:
        fix: The fix.
        members: For a family's first fix, the names of the family's
            members fixed with it; None otherwise.

    Returns:
        [name, at, from, to, credit, since, family], without trailing nulls
        (but always the first four). from and to are an update's versions,
        else null; credit is {"pr", "author"?, "mergedBy"?, "likely"?}
        (history.credit) or null; since is when the problem began; family
        is family_entry's, when other members of its family were fixed
        with it.
    """
    credit = {k: fix[k] for k in ("pr", "author", "mergedBy", "likely") if k in fix}
    entry = [
        fix["name"],
        fix["at"],
        fix.get("from"),
        fix.get("to"),
        credit if fix.get("pr") else None,
        fix.get("since"),
        facts.family_entry(members) if members else None,
    ]
    while len(entry) > 4 and entry[-1] is None:
        entry.pop()
    return entry


def _day_before(run, days):
    """Return the day (YYYY-MM-DD) that is days before run's day."""
    day = datetime.fromisoformat((run or "1970-01-01")[:10])
    return (day - timedelta(days=days)).date().isoformat()


def read_events(out_dir=None):
    """Return the trend markers kept in the last run's history.json, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return (
            shards.read_json(os.path.join(out_dir, "history.json")).get("events") or []
        )
    except (OSError, ValueError, AttributeError):
        return []


def with_events(events, new, run):
    """Add this run's trend markers to the kept ones.

    The markers are what the trend charts mark: staging-next merges (mass
    rebuilds, after which failing builds jump for days), nixkeeper's own
    updates, and changes in how it counts (config.COUNTING_CHANGES). Each
    is kept once: a merge by its PR, an update by its version, a counting
    change by its text. Only the last HISTORY_DAYS days are kept.

    Args:
        events: The kept markers.
        new: This run's markers.
        run: The run's time.

    Returns:
        The markers, oldest first.
    """
    cutoff = _day_before(run, HISTORY_DAYS)
    kept = {}
    for event in [*events, *new]:
        key = (
            event["kind"],
            event.get("pr") or event.get("version") or event.get("text"),
        )
        if event["day"] > cutoff:
            kept[key] = event  # a later copy replaces an earlier one
    return sorted(kept.values(), key=lambda e: (e["day"], e["kind"]))


def read_history(out_dir=None):
    """Return the last run's history.json points, or []."""
    out_dir = config.data_dir(out_dir)
    try:
        return (
            shards.read_json(os.path.join(out_dir, "history.json")).get("points") or []
        )
    except (OSError, ValueError, AttributeError):
        return []
