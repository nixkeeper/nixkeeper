"""What carries over from the previous run: its data, for lookups that fail,
when each package became outdated, and since when a source couldn't be
refreshed."""

from datetime import datetime, timedelta

from . import config, datastore
from .changes import is_outdated
from .sources import repology


def load_previous_run(out_dir=None):
    """The last successful run's index, or an empty one."""
    return datastore.load(out_dir)


def previous_rows(previous, pname, attrs):
    """The last run's rows for a tracked pname (by name, or any of attrs), in
    their order there."""
    index = _by_key(previous["packages"])
    found = {i for key in (pname, *attrs) for i in index.get(key, ())}
    return [previous["packages"][i] for i in sorted(found)]


_index = (None, None)


def _by_key(packages):
    """{name, searchTerm or attribute: the indexes of the rows with it} for
    the last run's rows, made once (with every package there are over
    100,000 to look through)."""
    global _index
    if _index[0] is not packages:
        index = {}
        for i, row in enumerate(packages):
            keys = {row["name"], row.get("searchTerm"), *(row.get("attrs") or [])}
            for key in keys - {None}:
                index.setdefault(key, []).append(i)
        _index = (packages, index)
    return _index[1]


def new_packages(previous, wanted):
    """How many of wanted ({pname: (attrs, fallback)}, tracking.py) the last
    run didn't have."""
    names = {
        n for row in previous["packages"] for n in (row["name"], row.get("searchTerm"))
    }
    attrs = {a for row in previous["packages"] for a in row.get("attrs") or []}
    return sum(
        1 for p, (a, _) in wanted.items() if p not in names and not set(a) & attrs
    )


def previous_project(previous, pname, attrs, out_dir=None):
    """Reuse the last run's data for a pname (its lookup failed, or isn't due).
    Returns (project, entries, stale_since), or None if there's nothing to
    reuse."""
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
    """Record that source ("builds", "update" or "upstream") couldn't be
    refreshed for row this run, so what it shows is the previous run's (or
    nothing). before is the row's previous-run version, if any: the date it
    started failing carries over, so "since" stays the first failing run."""
    since = ((before or {}).get("notRefreshed") or {}).get(source, {}).get("since")
    row.setdefault("notRefreshed", {})[source] = {
        "since": since or now,
        "reason": reason,
    }


def add_outdated_since(rows, previous, now):
    """Mark when each outdated row first became outdated. Neither Repology nor
    nixpkgs has that date, so it's carried from run to run: kept while the row
    stays outdated (even if nixpkgs updates but is still behind), set to now
    when it newly falls behind, dropped once it's caught up."""
    before = {row["name"]: row for row in previous["packages"]}
    for row in rows:
        if is_outdated(row):
            row["outdatedSince"] = (
                before.get(row["name"], {}).get("outdatedSince") or now
            )


def add_failing_since(rows, previous, now):
    """Mark since when each row's builds have been failing ("failingSince")
    and its update attempts ("updateFailingSince"); dropped once fixed.
    Builds: their last success, as Hydra says it each run (the failing
    began after it; the earliest of the failed builds' that have one);
    none when Hydra says none of them ever succeeded; while it isn't known
    yet, carried from run to run as outdatedSince is (else now). And
    "neverBuiltOn": the systems whose failed build never succeeded. Update
    attempts: carried the same way, first seen the failed attempt's day,
    else now."""
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


# What a sync counts as fixed since the last (fixes): only with something
# that shows it, so a source that's down or late, or a change in how
# nixkeeper counts, never looks like a wave of fixes.
#   build: was failing; now no failed build, and Hydra has a success
#   update: was outdated; now not, and nixpkgs' version changed
#   bot: nixpkgs-update was failing; now not, and its attempt changed (a
#     newer one, or superseded: nixpkgs moved on)
FIXES = ("build", "update", "bot")


def credit(pr, likely=False):
    """What a fix is credited to: its PR's number, who opened and merged it
    ({"pr", "author"?, "mergedBy"?, "likely"?}), or {} without one."""
    if not pr or not pr.get("number"):
        return {}
    found = {"pr": pr["number"]}
    found.update({k: pr[k] for k in ("author", "mergedBy") if pr.get(k)})
    if likely:
        found["likely"] = True
    return found


def family(old):
    """{"family": ...} when old moves with others (rows.add_families): the
    overview lists their fixes as one."""
    return {"family": old["family"]} if old.get("family") else {}


def lasted(old, field):
    """{"since": ...} when old says since when it had the problem (field:
    failingSince, outdatedSince, updateFailingSince), else {}."""
    return {"since": old[field]} if old.get(field) else {}


def fixes(rows, previous, now):
    """[{"at", "name", "kind", "since"?, "from"?, "to"?, "pr"?, "author"?,
    "mergedBy"?, "likely"?}] for each fully checked row fixed since
    previous (FIXES); not for new or removed packages, those of sets updated
    in bulk, or ones whose data wasn't refreshed. "since": since when it had
    been failing or outdated, as the last sync had it (a build's from
    Hydra's last success; outdated, from when nixkeeper first saw it so).
    An update (or the bot's
    failure it ended) is credited to the update PR merged into master the
    last sync saw ("masterPR"); a build fix, likely, to the PR merged since
    it began failing that touched it ("buildFixPR")."""
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


# A package's own fixes, for its panel: the last this many days, at most
# RECENT_FIXES_KEPT of them.
RECENT_FIXES_DAYS = 30
RECENT_FIXES_KEPT = 3


def add_recent_fixes(rows, previous, found, now):
    """Give each row its fixes of the last RECENT_FIXES_DAYS days
    ("recentFixes": fixes' entries without the name, newest first, at most
    RECENT_FIXES_KEPT): this sync's (found: fixes') and those its row had
    at the last."""
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
