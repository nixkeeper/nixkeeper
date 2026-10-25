"""Read Hydra's builds of the branches that come before master.

haskell-updates is where the Haskell team updates haskellPackages
(hackage2nix), merging into master about every two weeks. Its builds come
from nixkeeper-hydra's digest of it (https://github.com/nixkeeper/
digest-builds: data/haskell-updates.json.gz). A row with a job there gets
what the branch has ("branch": its version, its build and how it went), so
the page can say an update is waiting for the branch's merge, or a failure
is fixed there (or isn't). It changes no count: the branch is a preview of
master.

staging-next (staging-next.json.gz, its differences from master) is read
for the updates merged into it (stagingPR): how each builds there, on every
platform, as of Hydra's newest evaluation of it. It also gives a forecast of
what staging-next will break or block once it's merged.
"""

import re

from .. import config, log
from ..versions import is_newer, version_key
from . import about, digests

# The files' format this nixkeeper reads.
FORMAT = 1
# Each branch nixkeeper reads: its file in the hydra digest, and which
# attributes it builds.
BRANCHES = {"haskell-updates": "haskellPackages."}
SYSTEM = "x86_64-linux"  # the branches' jobsets build only it
# A branch's file is read at least daily, even when the branch hasn't
# changed: one older than this means nixkeeper-hydra has stopped reading it.
MAX_AGE_HOURS = 48


def wanted(attrs):
    """Return the branches some of attrs, the tracked ones, are built on."""
    return [
        b for b, prefix in BRANCHES.items() if any(a.startswith(prefix) for a in attrs)
    ]


def load(branch, now):
    """Read branch's jobs on SYSTEM.

    Returns:
        {attr: {"version", "status", "build"}}, or None when the hydra
        digest is turned off, or (with the reason in the log) the file isn't
        there, isn't current or can't be read.
    """
    base = config.HYDRA_DIGEST_URL
    if not base:
        return None
    source = f"branch:{branch}"
    try:
        found = digests.read_json_gz(base, f"{branch}.json.gz", FORMAT)
        at = found["fetchedAt"]
        if digests.hours_since(at, now) > MAX_AGE_HOURS:
            digests.too_old(source, branch, at)
            return None
        columns = found["columns"]
        jobs = {}
        for values in found["jobs"]:
            job = dict(zip(columns, values, strict=True))
            if job["system"] != SYSTEM:
                continue
            # What it builds: name-version (Agda-2.8.0.2).
            version = job["name"].rsplit("-", 1)[-1] if "-" in job["name"] else ""
            jobs[job["attr"]] = {
                "version": version,
                "status": job["status"],
                "build": job["build"],
            }
    except digests.FAILURES as e:
        digests.give_up(source, branch, e)
        return None
    log.info(f"{branch}: evaluation {found['eval']}, {len(jobs):,} jobs, read {at}")
    about.note(source, True, at=at, eval=found["eval"], jobs=len(jobs))
    return jobs


# staging-next, read since 2026-10-16: all of nixpkgs, but only its
# differences from master (digest-builds' branches.py), for the updates on
# their way there (prs_digest.add_staging_prs), on every platform Hydra
# builds.
STAGING_NEXT = "staging-next"
# The version at the end of what a job builds: from the first part starting
# with a digit (imagemagick-7.1.2-34, python3.13-uharfbuzz-0.56.2,
# getconf-glibc-2.44-57).
NAME_VERSION = re.compile(r"-(\d[^-]*(?:-[^-]*)*)$")


def load_staging_next(now):
    """Read staging-next's newest evaluation.

    Returns:
        ({(attr, system): {"name", "status", "build", "blockedBy"}},
        {"eval", "evaluatedAt"}), or None as load returns it.
    """
    base = config.HYDRA_DIGEST_URL
    if not base:
        return None
    source = f"branch:{STAGING_NEXT}"
    try:
        found = digests.read_json_gz(base, f"{STAGING_NEXT}.json.gz", FORMAT)
        at = found["fetchedAt"]
        if digests.hours_since(at, now) > MAX_AGE_HOURS:
            digests.too_old(source, STAGING_NEXT, at)
            return None
        columns = found["columns"]
        jobs = {}
        for values in found["jobs"]:
            job = dict(zip(columns, values, strict=True))
            jobs[job["attr"], job["system"]] = {
                "name": job["name"],
                "status": job["status"],
                "build": job["build"],
                # The dependencies stopping it there, by attribute (or a
                # store name no job builds), when the digest has read them.
                "blockedBy": (job.get("blockedBy") or "").split(),
            }
        info = {"eval": found["eval"], "evaluatedAt": found.get("evaluatedAt")}
    except digests.FAILURES as e:
        digests.give_up(source, STAGING_NEXT, e)
        return None
    log.info(
        f"{STAGING_NEXT}: evaluation {found['eval']} "
        f"({info['evaluatedAt'] or 'date unknown'}), {len(jobs):,} jobs differing "
        f"from master, read {at}"
    )
    about.note(source, True, at=at, jobs=len(jobs), **info)
    return jobs, info


def current_staging_next(found, last_merged):
    """Return found, unless it's of the staging-next cycle merged into master.

    An evaluation made before the last staging-next cycle was merged is of
    that cycle, which is master's now: what the evaluation said of it (what
    it breaks, what blocks it) has happened there or not. None then, until
    Hydra evaluates the next cycle (2026-10-16: evaluation 1830329 at
    17:14, #571813 merged at 19:04).

    Args:
        found: load_staging_next's result, or None.
        last_merged: The PR digest's last staging-next merge, {"merged",
            ...}, or None.
    """
    if not found or not (last_merged or {}).get("merged"):
        return found
    _, info = found
    made = info.get("evaluatedAt")
    if made and made < last_merged["merged"]:
        about.note(
            f"branch:{STAGING_NEXT}",
            False,
            f"evaluation {info.get('eval')} is of the cycle merged into master "
            f"on {last_merged['merged'][:10]}",
        )
        log.info(
            f"{STAGING_NEXT}: evaluation {info.get('eval')} ({made}) is before "
            f"the merge of #{last_merged.get('n')} ({last_merged['merged']}): "
            "not used"
        )
        return None
    return found


def apply_staging_next(rows, found):
    """Give each row's update on staging-next how it builds there.

    That's for a row whose stagingPR is "on" staging-next. The PR gets
    "builds", [{"system", "status", "build"}] of its attributes' jobs at its
    version, each platform once; or at a newer version when staging-next
    has moved past it ("evalVersion", such as harfbuzz 14.5.1 for a PR to
    14.5.0); or none when the evaluation has neither (merged since:
    "inEval" false). "eval" says which evaluation, and when.

    Args:
        rows: The rows, changed in place.
        found: load_staging_next's result, or None (then nothing changes).
    """
    if not found:
        return
    jobs, info = found
    by_attr = {}
    for (attr, system), job in jobs.items():
        by_attr.setdefault(attr, []).append({"system": system, **job})
    for row in rows:
        pr = row.get("stagingPR")
        if not pr or pr.get("on") != STAGING_NEXT:
            continue
        theirs = [j for a in row.get("attrs") or [] for j in by_attr.get(a, [])]
        # The jobs at the PR's version, by what they build, a name-version
        # (imagemagick-7.1.2-34, python3.13-hatchling-1.32.0).
        at = [j for j in theirs if j["name"].endswith(f"-{pr['to']}")]
        pr.pop("evalVersion", None)
        if not at:
            # Past it: the newest version staging-next builds, if newer.
            newer = {
                v: [j for j in theirs if version(j["name"]) == v]
                for j in theirs
                if (v := version(j["name"])) and is_newer(v, pr["to"])
            }
            if newer:
                best = max(newer, key=version_key)
                at, pr["evalVersion"] = newer[best], best
        pr["eval"] = info
        pr["inEval"] = bool(at)
        # Each platform once: its first attribute's job (heroic's, not
        # heroic-unwrapped's too).
        builds = {}
        for j in at:
            builds.setdefault(
                j["system"],
                {"system": j["system"], "status": j["status"], "build": j["build"]},
            )
        pr["builds"] = sorted(builds.values(), key=lambda b: b["system"])


def apply_staging_next_breaks(rows, found, cycle=None):
    """Mark the rows staging-next will break once it's merged.

    A row's job breaks when it fails its own build in staging-next's newest
    evaluation (not a dependency's failure), at the same version master
    builds fine (not an update of it in progress there). Unless that's
    fixed, master fails the same once staging-next is merged into it. It's
    a forecast: it changes no count.

    Each such row gets "stagingNextBreaks": {"eval", "evaluatedAt",
    "builds": [{"attr", "system", "build"}], "cycle"?: the open
    staging-next PR ({"n", "cut"}), when known}.

    Args:
        rows: The rows, changed in place.
        found: load_staging_next's result, or None (then rows keep none).
        cycle: The open staging-next PR, or None.
    """
    for row in rows:
        row.pop("stagingNextBreaks", None)
    if not found:
        return
    jobs, info = found
    for row in rows:
        broken = []
        for b in row.get("builds") or []:
            job = jobs.get((b.get("attr"), b.get("system")))
            if (
                job
                and job["status"] == "failed"
                and b.get("status") == "ok"
                and b.get("name") == job["name"]
            ):
                broken.append(
                    {"attr": b["attr"], "system": b["system"], "build": job["build"]}
                )
        if broken:
            row["stagingNextBreaks"] = {
                **info,
                "builds": sorted(broken, key=lambda b: (b["system"], b["attr"])),
                **({"cycle": {"n": cycle["n"], "cut": cycle["cut"]}} if cycle else {}),
            }


def apply_staging_next_blocked(rows, found):
    """Mark what staging-next's failing dependencies stop.

    - A row with a job that builds on master, but is stopped on
      staging-next by a dependency at the same version, gets
      "stagingNextBlockedBy": {"eval", "evaluatedAt", "builds": [{"system",
      "build", "by": [{"name", "row"?}]}]}. Each dependency is named after
      its row when there is one, as rows.name_blockers names master's.
    - A row that stops others there gets "stagingNextBlocks": {"eval",
      "evaluatedAt", "packages", "builds"}: fixed on staging-next, they
      build again.

    Every row counts, those in sets too, as master's blockers are counted.
    It's a forecast: it changes no count.

    Args:
        rows: The rows, changed in place.
        found: load_staging_next's result, or None (then rows keep none).
    """
    for row in rows:
        row.pop("stagingNextBlockedBy", None)
        row.pop("stagingNextBlocks", None)
    if not found:
        return
    jobs, info = found
    by_attr = {a: row for row in rows for a in row.get("attrs") or []}
    stops = {}  # {blocker's name: [its row or None, {rows stopped}, builds]}
    for row in rows:
        blocked = []
        for b in row.get("builds") or []:
            job = jobs.get((b.get("attr"), b.get("system")))
            if not (
                job
                and job["status"] == "dependency"
                and job["blockedBy"]
                and b.get("status") == "ok"
                and b.get("name") == job["name"]
            ):
                continue
            by = []
            for attr in job["blockedBy"]:
                blocker = by_attr.get(attr)
                name = blocker["name"] if blocker else attr
                by.append({"name": name, "row": True} if blocker else {"name": name})
                stop = stops.setdefault(name, [blocker, set(), 0])
                stop[1].add(row["name"])
                stop[2] += 1
            blocked.append({"system": b["system"], "build": job["build"], "by": by})
        if blocked:
            row["stagingNextBlockedBy"] = {**info, "builds": blocked}
    for blocker, names, builds in stops.values():
        if blocker is not None:
            blocker["stagingNextBlocks"] = {
                **info,
                "packages": len(names),
                "builds": builds,
            }


def version(name):
    """Return the version at the end of what a job builds (NAME_VERSION), or None."""
    m = NAME_VERSION.search(name or "")
    return m.group(1) if m else None


def apply(rows, branch, jobs):
    """Give each row with a job on branch what the branch has.

    That's "branch": {"name": branch, "version", "status", "build"}, of its
    first attribute with a job there.

    Args:
        rows: The rows, changed in place.
        branch: The branch's name.
        jobs: load's result, or None (then nothing changes).
    """
    if not jobs:
        return
    for row in rows:
        job = next((jobs[a] for a in row.get("attrs") or [] if a in jobs), None)
        if job:
            row["branch"] = {"name": branch, **job}
