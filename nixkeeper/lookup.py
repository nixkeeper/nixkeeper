"""Look up the tracked packages on Repology.

When a lookup fails, the nixkeeper-versions digest's versions or the last
run's data are used instead.
"""

import urllib.error

from . import config, history, log, schedule
from .datastore import data_file
from .sources import about, repology, versions_digest


def due(pname, rows, nixpkgs, now):
    """Return whether pname should be looked up on Repology now.

    It should at once when it's new, never dated, its lookup failed, or
    nixpkgs' version in the channel isn't the one Repology had (it changed
    since, or Repology lags); daily (schedule.daily) while it's outdated or
    flagged vulnerable. Otherwise every QUIET_DAYS (schedule.due): new
    releases still show within a few days, and most packages are updated
    by nixpkgs-update, which comes round every ten days or so.

    Args:
        pname: The tracked name.
        rows: Its rows at the last sync.
        nixpkgs: The package index, by attribute.
        now: The run's time.
    """
    if not rows:
        return True
    for row in rows:
        versions = {
            nixpkgs[a].get("version") for a in row.get("attrs") or [] if a in nixpkgs
        }
        if (
            not row.get("repologyCheckedAt")
            or row.get("staleSince")
            or (versions and row.get("nixVersion") not in versions)
        ):
            return True
    checked = min(r["repologyCheckedAt"] for r in rows)
    if any(
        r.get("nixStatus") in ("outdated", "legacy") or r.get("nixVulnerable")
        for r in rows
    ):
        return schedule.daily(checked, now)
    return schedule.due(pname, checked, now)


def collect_projects(
    wanted,
    previous,
    resolve=repology.resolve,
    out_dir=None,
    nixpkgs=None,
    now=None,
    digest=None,
    bulk=frozenset(),
):
    """Look up every tracked package on Repology.

    Several attributes (wesnoth and wesnoth-devel, heroic and
    heroic-unwrapped) can map to one project; their lookups are merged
    here, and split into rows by rows.project_rows. Each package is
    answered by the first of these that can:

    1. The nixkeeper-versions digest (versions_digest.answer), with no
       lookup, given nixpkgs. A digest that isn't current (stale: Repology
       may be down) is skipped here, and only used when a lookup fails.
    2. For bulk's pnames, which are never looked up: the digest, as it has
       them (even when the channel has moved on: Repology itself would say
       the same), else the last run's data, else not on Repology
       ("unlisted").
    3. Given nixpkgs and now, the last run's data for a package not due
       (due).
    4. A lookup. When it fails: the digest's versions, even stale, else the
       last run's data, else none ("lookupFailed", shown as not on
       Repology). The sync goes on whatever Repology does, its other
       sources fresh.

    Args:
        wanted: {pname: (attrs, fallback)}, as tracking.tracked_packages
            returns them.
        previous: The last run's index.
        resolve: Looks a package up on Repology (repology.resolve).
        out_dir: The data folder the last run's data is read from.
        nixpkgs: The package index, by attribute, or None.
        now: The run's time, or None.
        digest: nixkeeper-versions' projects by attribute
            (versions_digest.load), or None.
        bulk: With every package tracked, the pnames not on the lists.

    Returns:
        {project: {"name", "project", "attrs", "entries", "dataFile",
        "checkedAt"?, "staleSince"?, "unlisted"?, "lookupFailed"?}}.
    """
    out_dir = config.data_dir(out_dir)
    # The project each attribute had last run: asked for directly, it saves
    # a request (repology.resolve).
    known = {
        attr: row["project"]
        for row in previous["packages"]
        if row.get("project")
        for attr in row.get("attrs") or []
    }
    projects = {}
    failed = []
    kept = from_digest = looked_up = 0
    # A digest that isn't current answers only what Repology can't.
    fresh = None if getattr(digest, "stale", False) else digest
    for pname, (attrs, fallback) in sorted(wanted.items()):
        stale_since = None
        checked_at = now
        if (
            fresh
            and nixpkgs is not None
            and (found := versions_digest.answer(fresh, attrs, nixpkgs))
        ):
            project, entries, day = found
            from_digest += 1
            add(
                projects,
                pname,
                project,
                repology.trimmed(entries),
                attrs,
                f"{day}T00:00:00+00:00",  # the day the digest read it
            )
            continue
        if pname in bulk:
            from_digest += add_bulk(projects, pname, attrs, digest, previous, out_dir)
            continue
        rows = history.previous_rows(previous, pname, attrs)
        reused = (
            nixpkgs is not None
            and now
            and not due(pname, rows, nixpkgs, now)
            and history.previous_project(previous, pname, attrs, out_dir)
        )
        if reused:
            project, entries, _ = reused
            checked_at = min(r["repologyCheckedAt"] for r in rows)
            kept += 1
            add(projects, pname, project, entries, attrs, checked_at)
            continue
        log.info(f"Resolving {pname}...")
        looked_up += 1
        try:
            project, entries = resolve(
                fallback, attrs, next((known[a] for a in attrs if a in known), None)
            )
        except (urllib.error.URLError, OSError, ValueError) as e:
            failed.append(pname)
            if found := digest and versions_digest.answer(digest, attrs, {}):
                # What the digest last read: as Repology had it then.
                project, entries, day = found
                stale_since = f"{day}T00:00:00+00:00"
                log.info(
                    f"  giving up on {pname} ({e}); the digest's versions from {day}"
                )
                add(
                    projects,
                    pname,
                    project,
                    repology.trimmed(entries),
                    attrs,
                    None,
                    stale_since,
                )
                continue
            reused = history.previous_project(previous, pname, attrs, out_dir)
            if not reused:
                log.info(
                    f"  giving up on {pname} ({e}); no earlier data: shown as not "
                    "on Repology this run"
                )
                unlisted(projects, pname, attrs, lookup_failed=True)
                continue
            project, entries, stale_since = reused
            checked_at = None  # not checked this run, as with any failed lookup
            log.info(f"  giving up on {pname} ({e}); reusing data from {stale_since}")
        add(projects, pname, project, entries, attrs, checked_at, stale_since)
    if from_digest:
        log.info(f"  {from_digest} packages from the versions digest, without a lookup")
    if kept:
        log.info(
            f"  {kept} packages not looked up again: nothing going on, looked up "
            f"in the last {config.QUIET_DAYS} days"
        )

    if failed:
        # Repology down, most likely: the rest of the sync goes on (Hydra,
        # nixpkgs-update, ...), these keep their last versions.
        about.note(
            "repology",
            False,
            f"{len(failed):,} of {looked_up:,} lookups failed: their last versions "
            "kept",
        )
        log.warn(
            f"Repology lookups failed for {len(failed):,} of "
            f"{looked_up:,} packages; their last versions kept: "
            f"{', '.join(failed[:20])}" + (" ..." if len(failed) > 20 else "")
        )
    return projects


def add_bulk(projects, pname, attrs, digest, previous, out_dir):
    """Add a pname read in bulk (collect_projects' bulk), with no lookup.

    Returns:
        1 when the digest had it, else 0, for the count of packages taken
        from the digest.
    """
    found = digest and versions_digest.answer(digest, attrs, {})
    if found:
        project, entries, day = found
        add(
            projects,
            pname,
            project,
            repology.trimmed(entries),
            attrs,
            f"{day}T00:00:00+00:00",
        )
        return 1
    reused = previous["packages"] and history.previous_project(
        previous, pname, attrs, out_dir
    )
    if reused and reused[0]:
        project, entries, stale_since = reused
        add(projects, pname, project, entries, attrs, None, stale_since)
        return 0
    unlisted(projects, pname, attrs)
    return 0


def unlisted(projects, pname, attrs, lookup_failed=False):
    """Add pname as not on Repology.

    It gets an entry of its own, never joined to a Repology project of the
    same name, as add() would join it: that's how one project's attributes
    come together.

    Args:
        projects: The projects so far, by key, changed in place.
        pname: The package's pname.
        attrs: Its attributes.
        lookup_failed: Whether that's because Repology couldn't be asked,
            rather than because it doesn't list the package.
    """
    key = f"unlisted:{pname}"
    projects[key] = {
        "name": pname,
        "project": None,
        "attrs": attrs,
        "entries": [],
        "dataFile": data_file(key),
        "unlisted": True,
        **({"lookupFailed": True} if lookup_failed else {}),
    }


def add(projects, pname, project, entries, attrs, checked_at=None, stale_since=None):
    """Add pname's lookup to projects, merged with any for the same project.

    When two pnames found the same project, their attributes are merged,
    and the freshest lookup's entries hold for every row of it.

    Args:
        projects: The projects so far, by key, changed in place.
        pname: The package's pname.
        project: The Repology project it was found in, or None.
        entries: The project's Repology entries.
        attrs: The package's attributes.
        checked_at: When Repology was asked; None when it wasn't (the
            lookup failed).
        stale_since: Since when the data is stale, for reused data.
    """
    key = project or pname
    if key in projects:
        merged = projects[key]
        merged["attrs"] += [a for a in attrs if a not in merged["attrs"]]
        # The same project: its freshest data holds for every row of it.
        if (checked_at or "") > (merged.get("checkedAt") or ""):
            merged.update(entries=entries or [], checkedAt=checked_at)
            merged.pop("staleSince", None)
        return
    projects[key] = {
        "name": pname,
        "project": project,
        "attrs": attrs,
        "entries": entries or [],
        "dataFile": data_file(key),
    }
    if checked_at:
        projects[key]["checkedAt"] = checked_at
    if stale_since:
        projects[key]["staleSince"] = stale_since
