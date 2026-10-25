"""Looking up tracked packages on Repology, with fallback to the last run."""

import sys
import urllib.error

from . import config, history, schedule
from .datastore import data_file
from .sources import about, repology, versions_digest


def due(pname, rows, nixpkgs, now):
    """Whether pname should be looked up on Repology now. At once when it's
    new, never dated, its lookup failed, or nixpkgs' version in the channel
    isn't the one Repology had (it changed since, or Repology lags); daily
    (schedule.daily) while it's outdated or flagged vulnerable (at the last
    sync, rows: its rows then). Otherwise every QUIET_DAYS (schedule.due): new releases
    still show within a few days, and most packages are updated by
    nixpkgs-update, which comes round every ten days or so."""
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
    """Look up every tracked package on Repology, falling back to the previous
    run's data (in out_dir) when a lookup fails. digest: nixkeeper-versions'
    projects by attribute (versions_digest.load), for the packages it can
    answer (versions_digest.answer), with no lookup; when it isn't current
    (stale: Repology may be down), only for those Repology can't answer.
    With nixpkgs and now, only the rest that are due (due) are looked up;
    the others keep the last run's data. Several attrs
    (wesnoth / wesnoth-devel, heroic / heroic-unwrapped) can map to one
    project; those are merged here and split into rows by rows.project_rows.
    bulk: the pnames (with every package tracked: those not on the lists)
    read from the digest only, never looked up: as the digest has them (even
    when the channel has moved on: Repology itself would say the same), else
    as the last run had them, else not on Repology ("unlisted": true).
    Returns project -> {"name", "project", "attrs", "entries", "dataFile"[,
    "checkedAt"][, "staleSince"][, "unlisted"][, "lookupFailed"]}. A lookup
    that fails keeps the stale digest's versions, else the last run's, else
    none ("lookupFailed": shown as not on Repology); the sync goes on
    whatever Repology does, its other sources fresh."""
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
        print(f"Resolving {pname}...", file=sys.stderr)
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
                print(
                    f"  giving up on {pname} ({e}); the digest's versions from {day}",
                    file=sys.stderr,
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
                print(
                    f"  giving up on {pname} ({e}); no earlier data: shown as not "
                    "on Repology this run",
                    file=sys.stderr,
                )
                unlisted(projects, pname, attrs, lookup_failed=True)
                continue
            project, entries, stale_since = reused
            checked_at = None  # not checked now: as failed lookups go
            print(
                f"  giving up on {pname} ({e}); reusing data from {stale_since}",
                file=sys.stderr,
            )
        add(projects, pname, project, entries, attrs, checked_at, stale_since)
    if from_digest:
        print(
            f"  {from_digest} packages from the versions digest, without a lookup",
            file=sys.stderr,
        )
    if kept:
        print(
            f"  {kept} packages not looked up again: nothing going on, looked up "
            f"in the last {config.QUIET_DAYS} days",
            file=sys.stderr,
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
        print(
            f"::warning::Repology lookups failed for {len(failed):,} of "
            f"{looked_up:,} packages; their last versions kept: "
            f"{', '.join(failed[:20])}" + (" ..." if len(failed) > 20 else ""),
            file=sys.stderr,
        )
    return projects


def add_bulk(projects, pname, attrs, digest, previous, out_dir):
    """Add a pname read in bulk (collect_projects' bulk), with no lookup.
    Returns 1 if the digest had it, else 0."""
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
    """Add pname as not on Repology: its own entry, never joined to a
    Repology project of the same name (add would: that's how one project's
    attributes come together). lookup_failed: because Repology couldn't be
    asked, not because it doesn't list it."""
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
    """Add pname's lookup to projects, merged with another pname's that found
    the same project. checked_at: when Repology was asked (None: it wasn't,
    the lookup failed); merged, the freshest lookup's data counts."""
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
