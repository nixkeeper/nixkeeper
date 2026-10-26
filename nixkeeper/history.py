"""Carry what a run needs over from the previous one.

That's the previous run's data, for lookups that fail; when each package
became outdated or began failing; since when a source couldn't be
refreshed; and what was fixed since.
"""

import functools
from datetime import datetime, timedelta

from . import config, datastore
from .changes import is_outdated
from .shape import Row
from .sources import repology


class PreviousRun(dict):
    """The last run's index, as load_previous_run reads it.

    A dict, so its fields read as before (previous["packages"]), with its
    rows indexed once, on first use (by_key): with every package there are
    over 100,000 to look through. The index goes with the run's data.
    """

    @functools.cached_property
    def by_key(self):
        """The rows' indexes by name, searchTerm and attribute (built on first use)."""
        return _by_key(self["packages"])


def load_previous_run(out_dir=None):
    """Return the last successful run's index, or an empty one, as a PreviousRun."""
    return PreviousRun(datastore.load(out_dir))


def previous_rows(previous, pname, attrs):
    """Return the last run's rows for a tracked pname, in their order there.

    A row matches by its name, or by any of attrs.

    Args:
        previous: The last run's index, as a PreviousRun.
        pname: The tracked pname.
        attrs: Its attributes.
    """
    found = {i for key in (pname, *attrs) for i in previous.by_key.get(key, ())}
    return [previous["packages"][i] for i in sorted(found)]


def _by_key(packages):
    """Index the last run's rows by name, searchTerm and attribute.

    Returns:
        {key: the indexes of the rows with it}.
    """
    index = {}
    for i, row in enumerate(packages):
        keys = {row["name"], row.get("searchTerm"), *(row.get("attrs") or [])}
        for key in keys - {None}:
            index.setdefault(key, []).append(i)
    return index


def new_packages(previous, wanted):
    """Return how many of wanted the last run didn't have.

    Args:
        previous: The last run's index.
        wanted: {pname: (attrs, fallback)}, as tracking.tracked_packages
            returns them.
    """
    names = {
        n for row in previous["packages"] for n in (row["name"], row.get("searchTerm"))
    }
    attrs = {a for row in previous["packages"] for a in row.get("attrs") or []}
    return sum(
        1 for p, (a, _) in wanted.items() if p not in names and not set(a) & attrs
    )


def previous_project(previous, pname, attrs, out_dir=None):
    """Reuse the last run's data for a pname whose lookup failed or isn't due.

    Returns:
        (project, entries, stale_since), or None when there's nothing to
        reuse.
    """
    out_dir = config.data_dir(out_dir)
    for row in previous_rows(previous, pname, attrs):
        entries = []
        if row.get("project"):
            try:
                # A file from before trimming has all of Repology's.
                entries = repology.trimmed(datastore.entries(row, out_dir))
            except (OSError, ValueError):
                return None
        return (
            row.get("project"),
            entries,
            row.get("staleSince") or previous.get("checkedAt"),
        )
    return None


def not_refreshed(row, source, reason, before, now):
    """Record that a source couldn't be refreshed for row this run.

    What the row shows from that source is then the previous run's, or
    nothing.

    Args:
        row: The row, changed in place.
        source: "builds", "update" or "upstream".
        reason: Why, as the status issue says it.
        before: The row in the previous run, if any. The time the source
            started failing carries over, so "since" stays the first
            failing run's.
        now: The run's time.
    """
    since = ((before or {}).get("notRefreshed") or {}).get(source, {}).get("since")
    row.setdefault("notRefreshed", {})[source] = {
        "since": since or now,
        "reason": reason,
    }


def add_outdated_since(rows: list[Row], previous, now):
    """Mark when each outdated row first became outdated ("outdatedSince").

    Neither Repology nor nixpkgs has that date, so it's carried from run to
    run: kept while the row stays outdated (even when nixpkgs updates but
    is still behind), set to now when it newly falls behind, and gone once
    it has caught up.
    """
    before = {row["name"]: row for row in previous["packages"]}
    for row in rows:
        if is_outdated(row):
            row["outdatedSince"] = (
                before.get(row["name"], {}).get("outdatedSince") or now
            )


def add_failing_since(rows, previous, now):
    """Mark since when each row's builds and update attempts have been failing.

    - "failingSince", for the builds: their last success, as Hydra says it
      each run (the failing began after it), the earliest of the failed
      builds' that have one. None when Hydra says none of them ever
      succeeded. While it isn't known yet, it's carried from run to run as
      outdatedSince is, else now.
    - "neverBuiltOn": the systems whose failed build never succeeded.
    - "updateFailingSince", for the update attempts: carried the same way,
      first set to the failed attempt's day, else now.

    Each is dropped once fixed.
    """
    before = {row["name"]: row for row in previous["packages"]}
    for row in rows:
        old = before.get(row["name"], {})
        failed = [b for b in row.get("builds") or [] if b["status"] == "failed"]
        row.pop("failingSince", None)
        row.pop("neverBuiltOn", None)
        if failed:
            last = [b["lastSuccess"] for b in failed if b.get("lastSuccess")]
            never = [b for b in failed if "lastSuccess" in b and not b["lastSuccess"]]
            if never:
                row["neverBuiltOn"] = sorted({b["system"] for b in never})
            if last:
                row["failingSince"] = min(last)
            elif len(never) < len(failed):  # not known yet
                row["failingSince"] = old.get("failingSince") or now
        row.pop("updateFailingSince", None)
        if row.get("updateFailure"):
            day = (row.get("update") or {}).get("date")
            row["updateFailingSince"] = old.get("updateFailingSince") or (
                f"{day}T00:00:00+00:00" if day else now
            )


# What a sync counts as fixed since the last one (fixes). Each kind needs
# something that shows it, so a source that's down or late, or a change in
# how nixkeeper counts, never looks like a wave of fixes:
#   build: was failing; now no build fails, and Hydra has a success
#   update: was outdated; now it isn't, and nixpkgs' version changed
#   bot: nixpkgs-update was failing; now it isn't, and its attempt changed
#     (a newer one, or superseded: nixpkgs moved on)
FIXES = ("build", "update", "bot")


def credit(pr, likely=False):
    """Return what a fix is credited to: its PR, and who opened and merged it.

    Returns:
        {"pr", "author"?, "mergedBy"?, "likely"?}, or {} without a PR.
    """
    if not pr or not pr.get("number"):
        return {}
    found = {"pr": pr["number"]}
    found.update({k: pr[k] for k in ("author", "mergedBy") if pr.get(k)})
    if likely:
        found["likely"] = True
    return found


def family(old):
    """Return {"family": ...} when old moves with others, else {}.

    Families come from rows.add_families; the overview lists their fixes as
    one.
    """
    return {"family": old["family"]} if old.get("family") else {}


def lasted(old, field):
    """Return {"since": ...} when old says since when it had the problem, else {}.

    Args:
        old: The row at the last sync.
        field: failingSince, outdatedSince or updateFailingSince.
    """
    return {"since": old[field]} if old.get(field) else {}


def fixes(rows, previous, now):
    """List the fixes since the previous run.

    Only fully checked rows count: not new or removed packages, those of
    sets updated in bulk, or ones whose data wasn't refreshed. Each fix is
    one of FIXES. Its "since" is since when the row had been failing or
    outdated, as the last sync had it: for a build, from Hydra's last
    success; for an update, from when nixkeeper first saw it outdated.

    An update, or the end of the bot's failure, is credited to the update
    PR merged into master that the last sync saw ("masterPR"). A build fix
    is credited, as likely, to the PR merged since it began failing that
    touched it ("buildFixPR").

    Returns:
        [{"at", "name", "kind", "since"?, "from"?, "to"?, "pr"?,
        "author"?, "mergedBy"?, "likely"?, "family"?}].
    """
    before = {row["name"]: row for row in previous["packages"]}
    found = []
    for row in rows:
        old = before.get(row["name"])
        if not old or row.get("set") or old.get("set"):
            continue
        builds = row.get("builds") or []
        if (
            (old.get("failingSince") or old.get("neverBuiltOn"))
            and not (row.get("failingSince") or row.get("neverBuiltOn"))
            and not any(b["status"] == "failed" for b in builds)
            and any(b["status"] == "ok" for b in builds)
        ):
            found.append(
                {
                    "at": now,
                    "name": row["name"],
                    "kind": "build",
                    **family(old),
                    **lasted(old, "failingSince"),
                    **credit(old.get("buildFixPR"), likely=True),
                }
            )
        if (
            is_outdated(old)
            and not is_outdated(row)
            and not row.get("staleSince")
            and row.get("nixVersion")
            and row.get("nixVersion") != old.get("nixVersion")
        ):
            found.append(
                {
                    "at": now,
                    "name": row["name"],
                    "kind": "update",
                    "from": old.get("nixVersion"),
                    "to": row["nixVersion"],
                    **family(old),
                    **lasted(old, "outdatedSince"),
                    **credit(old.get("masterPR")),
                }
            )
        update, was = row.get("update") or {}, old.get("update") or {}
        if (
            old.get("updateFailure")
            and not row.get("updateFailure")
            and "update" not in (row.get("unread") or [])
            and update
            and (update.get("date") != was.get("date") or update.get("supersededOn"))
        ):
            found.append(
                {
                    "at": now,
                    "name": row["name"],
                    "kind": "bot",
                    **family(old),
                    **lasted(old, "updateFailingSince"),
                    **credit(old.get("masterPR")),
                }
            )
    return found


# A package's own fixes, for its panel: those of the last RECENT_FIXES_DAYS
# days, at most RECENT_FIXES_KEPT of them.
RECENT_FIXES_DAYS = 30
RECENT_FIXES_KEPT = 3


def add_recent_fixes(rows, previous, found, now):
    """Give each row its own recent fixes, for its panel ("recentFixes").

    Those are this sync's (found, from fixes()) and those its row had at
    the last sync, within RECENT_FIXES_DAYS days: at most
    RECENT_FIXES_KEPT, newest first, each as fixes() makes it but without
    the name.
    """
    before = {row["name"]: row for row in previous.get("packages") or []}
    new = {}
    for fix in found:
        new.setdefault(fix["name"], []).append(
            {k: v for k, v in fix.items() if k != "name"}
        )
    cutoff = (
        datetime.fromisoformat(now) - timedelta(days=RECENT_FIXES_DAYS)
    ).isoformat()
    for row in rows:
        row.pop("recentFixes", None)
        kept = [
            f
            for f in [
                *new.get(row["name"], []),
                *((before.get(row["name"]) or {}).get("recentFixes") or []),
            ]
            if f.get("at", "") > cutoff
        ]
        if kept:
            row["recentFixes"] = sorted(kept, key=lambda f: f["at"], reverse=True)[
                :RECENT_FIXES_KEPT
            ]
