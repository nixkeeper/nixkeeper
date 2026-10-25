"""Ask Hydra about the tracked packages' builds.

Hydra builds nixpkgs master. This finds the latest build of each tracked
package on each platform it claims and, when that build didn't succeed,
the last one that did. The daily sync answers most jobs from
nixkeeper-hydra's digest (hydra_digest), and asks Hydra here about the
rest.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
from datetime import UTC, datetime

from .. import config, history, schedule
from ..changes import is_outdated
from ..shape import Row
from ..versions import is_newer, version_key
from . import http

# Hydra's buildstatus codes. 1 and 6 ("failed with output") are the package's
# own failure; 2 is a dependency's. Anything else (aborted, cancelled, timed
# out, log or output limit exceeded, ...) means the build didn't finish.
FAILED = {1, 6}
DEPENDENCY_FAILED = 2


def get(path):
    """Return a Hydra path's JSON, or None when Hydra answers 404."""
    body = http.get(config.HYDRA_URL + path, accept="application/json")
    return None if body is None else json.loads(body)


def status(buildstatus):
    """Name a Hydra buildstatus code: "ok", "failed", "dependency" or "unfinished"."""
    if buildstatus == 0:
        return "ok"
    if buildstatus in FAILED:
        return "failed"
    if buildstatus == DEPENDENCY_FAILED:
        return "dependency"
    return "unfinished"


def job_url(job):
    """Return the URL of a Hydra job's page."""
    return f"{config.HYDRA_URL}/job/{config.HYDRA_PROJECT}/{config.HYDRA_JOBSET}/{job}"


def latest_build(job):
    """Return the job's most recent finished build, or None if Hydra has none."""
    query = urllib.parse.urlencode(
        {
            "nr": 1,
            "project": config.HYDRA_PROJECT,
            "jobset": config.HYDRA_JOBSET,
            "job": job,
        }
    )
    builds = get(f"/api/latestbuilds?{query}")
    return builds[0] if builds else None


def last_success(job):
    """Return the job's last successful build.

    Returns:
        {"lastSuccess": its ISO time, or None when the job never succeeded,
        "lastSuccessBuild"?: its id, "lastSuccessName"?: what it built,
        such as "libfoo-1.2.3"}.
    """
    build = get(f"/job/{config.HYDRA_PROJECT}/{config.HYDRA_JOBSET}/{job}/latest")
    build = build or {}
    stoptime = build.get("stoptime")
    result = {
        "lastSuccess": (
            datetime.fromtimestamp(stoptime, UTC).isoformat() if stoptime else None
        )
    }
    if stoptime and build.get("id"):
        result["lastSuccessBuild"] = build["id"]
    if stoptime and build.get("nixname"):
        result["lastSuccessName"] = build["nixname"]
    return result


def check(attr, system, broken=False):
    """Ask Hydra about one job.

    Whenever the latest build didn't succeed, the last one that did is
    asked about too (last_success).

    Args:
        attr: The job's attribute.
        system: The job's platform.
        broken: Whether nixpkgs marks it broken there.

    Returns:
        {"attr", "system", "status", "build"?, "name"?, "lastSuccess"?,
        "lastSuccessBuild"?, "lastSuccessName"?}. status is "ok", "failed",
        "dependency" or "unfinished"; "notBuilt" when Hydra has no build of
        it; or "broken" when nixpkgs marks it broken there, whatever Hydra's
        last build did (the failure is known). name is what master built,
        such as "wesnoth-devel-1.19.28": master can be ahead of the channel.
    """
    job = f"{attr}.{system}"
    result = {"attr": attr, "system": system}
    build = latest_build(job)
    time.sleep(1)  # be polite to Hydra
    if build is None:
        return {**result, "status": "broken" if broken else "notBuilt"}
    result.update(status=status(build.get("buildstatus")), build=build["id"])
    if build.get("nixname"):
        result["name"] = build["nixname"]
    if broken or result["status"] != "ok":
        result.update(last_success(job))
        time.sleep(1)
    if broken:
        result["status"] = "broken"
    return result


def is_unfree(pkg):
    """Return whether a package is unfree.

    Hydra doesn't build unfree packages, so there's nothing to ask about
    them.
    """
    meta = pkg["meta"]
    if meta.get("unfree"):
        return True
    licenses = meta.get("license") or []
    if not isinstance(licenses, list):
        licenses = [licenses]
    return any(isinstance(lic, dict) and lic.get("free") is False for lic in licenses)


def systems(pkg):
    """Return the Hydra platforms a package claims to build on.

    All of them when it doesn't declare meta.platforms; none when
    meta.hydraPlatforms is empty.
    """
    meta = pkg["meta"]
    wanted = config.HYDRA_SYSTEMS
    if meta.get("platforms"):
        wanted = [s for s in wanted if s in meta["platforms"]]
    if meta.get("hydraPlatforms") is not None:
        wanted = [s for s in wanted if s in meta["hydraPlatforms"]]
    return wanted


def version_of(name, pkg):
    """Return the version in a Hydra build's name, or None.

    Given the package's pname, "wesnoth-devel-1.19.28" has the version
    1.19.28. None when the name doesn't start with the pname.
    """
    prefix = f"{pkg.get('pname')}-"
    if name and name.startswith(prefix) and len(name) > len(prefix):
        return name[len(prefix) :]
    return None


def add_versions(build, pkg):
    """Add the versions of build's latest and last successful builds.

    They go in "version" and "lastSuccessVersion", for the page, which
    doesn't have the pnames to work them out.

    Returns:
        build, changed in place.
    """
    for name, field in (("name", "version"), ("lastSuccessName", "lastSuccessVersion")):
        if version := version_of(build.get(name), pkg):
            build[field] = version
    return build


def master_version(row, pkgs):
    """Return master's version of row, when it's newer than the channel's.

    Hydra builds master, and the channel lags it by a few days, so a merged
    update shows here first. The version comes from the builds' names
    ("wesnoth-devel-1.19.28") and the channel index's pname, which are in
    the same format; the row's own attribute is tried first, when it has
    several.

    Returns:
        The version, or None when master isn't ahead, or Hydra has no build
        to tell (unfree packages).
    """
    for attr in sorted(pkgs, key=lambda a: a != row["name"]):
        pkg = pkgs[attr]
        versions = [
            v
            for b in row["builds"]
            if b["attr"] == attr and (v := version_of(b.get("name"), pkg))
        ]
        if versions:
            newest = max(versions, key=version_key)
            return newest if is_newer(newest, pkg.get("version")) else None
    return None


def jobs(attrs, nixpkgs):
    """Return the Hydra jobs of attrs, as [(attr, system)].

    Those are the attributes in nixpkgs that aren't unfree, on the
    platforms each claims (systems).
    """
    return [
        (attr, system)
        for attr in attrs
        if attr in nixpkgs and not is_unfree(nixpkgs[attr])
        for system in systems(nixpkgs[attr])
    ]


# A job in one of these states has nothing going on (Hydra built it, or has
# never built it on that platform): asked every QUIET_DAYS (due).
QUIET = {"ok", "notBuilt"}


def due(job, nixpkgs, before, now, broken=None):
    """Return whether Hydra should be asked about a job now.

    It should at once when the job is new, the package's version in the
    channel isn't the one Hydra built, or it wasn't read fine last time.
    Daily (schedule.daily) while something's going on: a status other than
    QUIET's, marked broken, or at the last sync outdated, ahead on master,
    or with an update PR. Otherwise every QUIET_DAYS (schedule.due).

    Args:
        job: (attr, system).
        nixpkgs: The package index, by attribute.
        before: The last run's builds by job and rows by attribute
            (last_run).
        now: The run's time.
        broken: {attr: [the systems nixpkgs marks it broken on]}.
    """
    attr, system = job
    builds, rows = before
    old, row = builds.get(job), rows.get(attr)
    if old is None or row is None:
        return True  # new
    version = old.get("version")
    if (version and version != nixpkgs[attr].get("version")) or "builds" in (
        row.get("notRefreshed") or {}
    ):
        return True
    if (
        old.get("status") not in QUIET
        or system in (broken or {}).get(attr, [])
        or is_outdated(row)
        or any(row.get(k) for k in ("master", "openPR", "masterPR"))
    ):
        return schedule.daily(old.get("checkedAt"), now)
    return schedule.due(attr, old.get("checkedAt"), now)


def last_run(previous):
    """Index the last run's data, for due.

    Returns:
        ({(attr, system): build}, {attr: its row}).
    """
    packages = previous["packages"]
    return (
        {
            (b["attr"], b["system"]): b
            for row in packages
            for b in row.get("builds") or []
        },
        {a: row for row in packages for a in row.get("attrs") or []},
    )


def due_jobs(attrs, nixpkgs, previous, now, broken=None):
    """Return the jobs of attrs (jobs) that are due now (due)."""
    before = last_run(previous)
    return [j for j in jobs(attrs, nixpkgs) if due(j, nixpkgs, before, now, broken)]


def fetch(wanted, broken=None):
    """Ask Hydra about each job in wanted, one at a time (check).

    After HYDRA_MAX_CONSECUTIVE_FAILURES lookups in a row fail, Hydra is
    likely down, so the rest aren't asked: each gets an OSError saying so.
    This is the network half of add_builds, which the daily sync runs in
    the background (sync.py).

    Args:
        wanted: The jobs, as [(attr, system)].
        broken: {attr: [the systems nixpkgs marks it broken on]}.

    Returns:
        {(attr, system): its result, or the error asking failed with}.
    """
    broken = broken or {}
    results = {}
    consecutive = 0
    for attr, system in wanted:
        if (attr, system) in results:
            continue
        if consecutive >= config.HYDRA_MAX_CONSECUTIVE_FAILURES:
            results[attr, system] = OSError(
                "not asked: it didn't answer earlier lookups"
            )
            continue
        try:
            results[attr, system] = check(attr, system, system in broken.get(attr, []))
            consecutive = 0
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"  {attr}.{system}: {e}", file=sys.stderr)
            results[attr, system] = e
            consecutive += 1
    return results


def add_builds(rows: list[Row], nixpkgs, previous, now, broken=None, fetched=None):
    """Give every row in nixpkgs its Hydra builds.

    Each row gets "builds", each with when Hydra was asked ("checkedAt"),
    or "unfree": True and no builds. Only jobs that are due (due) are
    asked; the rest keep the last run's result. A job whose lookup failed
    keeps the previous run's result, if there is one, and the row is
    marked as not refreshed. The version master has, when it's ahead of
    the channel, goes in "master".

    Args:
        rows: The rows, changed in place.
        nixpkgs: The package index, by attribute.
        previous: The last run's data.
        now: The run's time.
        broken: {attr: [the systems nixpkgs marks it broken on]}.
        fetched: fetch()'s answers, if Hydra was asked already; a due job
            missing from them is asked now.
    """
    broken = broken or {}
    print("Checking Hydra builds...", file=sys.stderr)
    attrs = [a for row in rows for a in row["attrs"]]
    wanted = jobs(attrs, nixpkgs)
    asking = due_jobs(attrs, nixpkgs, previous, now, broken)
    fetched = dict(fetched or {})
    fresh = {j for j in wanted if j in fetched} | set(asking)
    print(
        f"  {len(fresh)} of {len(wanted)} jobs read fresh; the rest were checked "
        f"in the last {config.QUIET_DAYS} days, with nothing going on",
        file=sys.stderr,
    )
    fetched.update(fetch([j for j in asking if j not in fetched], broken))
    before = last_run(previous)[0]
    before_rows = {row["name"]: row for row in previous["packages"]}
    failed = 0
    for row in rows:
        error = None
        pkgs = {a: nixpkgs[a] for a in row["attrs"] if a in nixpkgs}
        if not pkgs:
            continue  # not in nixpkgs: nothing Hydra could build
        free = {a: p for a, p in pkgs.items() if not is_unfree(p)}
        if not free:
            row["unfree"] = True
            row["builds"] = []
            continue
        builds = []
        for attr, pkg in free.items():
            for system in systems(pkg):
                if (attr, system) not in fetched:  # not due: as last checked
                    builds.append(dict(before[attr, system]))
                    continue
                result = fetched[attr, system]
                if not isinstance(result, Exception):
                    builds.append({**add_versions(dict(result), pkg), "checkedAt": now})
                    continue
                failed += 1
                error = error or str(result)
                build = dict(
                    before.get((attr, system))
                    or {"attr": attr, "system": system, "status": "unknown"}
                )
                if system in broken.get(attr, []):
                    build["status"] = "broken"
                builds.append(build)
        row["builds"] = builds
        if master := master_version(row, free):
            row["master"] = master
        if error:
            history.not_refreshed(
                row,
                "builds",
                f"couldn't reach Hydra ({error})",
                before_rows.get(row["name"]),
                now,
            )
    if failed:
        print(
            f"::warning::{failed} Hydra lookups failed; those show the previous "
            "run's result (or unknown)",
            file=sys.stderr,
        )
