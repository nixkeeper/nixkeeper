"""Read nixkeeper-hydra's digest of Hydra's builds.

The digest (https://github.com/nixkeeper/digest-builds) has every job of
Hydra's newest evaluation of nixpkgs master, with its newest finished build
and, when that isn't a success, the last successful one, in one download.
The daily sync takes the jobs it can answer from it instead of asking Hydra
about each (hydra.py). Hydra is still asked about the rest, and about
everything when the digest isn't current or can't be read.
"""

import csv
import gzip
import io
import json
import re
import sys
import urllib.error
from datetime import datetime, timedelta

from .. import config
from . import about, http

# The digest's format this nixkeeper reads.
FORMAT = 1
# An evaluation's id, in a link to it.
EVAL = re.compile(r"/eval/([0-9]+)")
# The digest's statuses nixkeeper takes as they are; "queued" (a job new to
# the digest, not built yet) is asked of Hydra.
FINISHED = {"ok", "failed", "dependency", "unfinished"}
# A result's fields about the job's last success.
LAST_SUCCESS = ("lastSuccess", "lastSuccessBuild", "lastSuccessName")
# A row's lastSuccessAt when Hydra says the job never succeeded (from
# nixkeeper-hydra's lookups, 2026-10-08; its build and name are empty).
NEVER = "never"


def newest_eval():
    """Return the id of Hydra's newest evaluation of the jobset.

    It's read from the jobset's list of evaluations, one small page. Not
    from its latest-eval, which is the newest whose builds have all
    finished, often a day behind.

    Raises:
        ValueError: The list has no evaluations.
    """
    path = f"/jobset/{config.HYDRA_PROJECT}/{config.HYDRA_JOBSET}/evals"
    page = http.get(config.HYDRA_URL + path) or ""
    ids = [int(i) for i in EVAL.findall(page)]
    if not ids:
        raise ValueError("Hydra's list of evaluations has none")
    return max(ids)


def current(meta, now):
    """Return why the digest can be used, or None.

    It can when it's of Hydra's newest evaluation, or behind it but read
    within HYDRA_DIGEST_MAX_AGE_HOURS (its workflow catches up hourly).

    Args:
        meta: The digest's meta.json.
        now: The run's time.
    """
    read = datetime.fromisoformat(meta["fetchedAt"])
    hours = (datetime.fromisoformat(now) - read) / timedelta(hours=1)
    try:
        newest = newest_eval()
    except (urllib.error.URLError, OSError, ValueError) as e:
        newest, why_not = None, f"Hydra's newest evaluation unknown: {e}"
    else:
        if meta["eval"] == newest:
            return f"evaluation {newest}, Hydra's newest"
        why_not = f"evaluation {meta['eval']}; Hydra's newest is {newest}"
    if hours <= config.HYDRA_DIGEST_MAX_AGE_HOURS:
        return f"{why_not}, but read {hours:.0f} h ago"
    return None


def load(now):
    """Read the digest's jobs.

    Returns:
        The digest's rows by (attr, system). None when it's turned off, or
        (with the reason in the log) not current (current) or unreadable.
    """
    base = config.HYDRA_DIGEST_URL
    if not base:
        return None
    try:
        meta = json.loads(http.get(base + "meta.json") or "null")
        if not meta or meta.get("format") != FORMAT:
            raise ValueError(f"no digest in a format this nixkeeper reads ({base})")
        why = current(meta, now)
        if not why:
            about.note(
                "hydra", False, "too old", at=meta["fetchedAt"], eval=meta["eval"]
            )
            print(
                f"::warning::Hydra digest: not used, it's from {meta['fetchedAt']} "
                f"(evaluation {meta['eval']}); asking Hydra about each job",
                file=sys.stderr,
            )
            return None
        body = http.get_bytes(base + "builds.csv.gz")
        if body is None:
            raise ValueError("its builds.csv.gz is missing")
        text = gzip.decompress(body).decode()
        rows = {(r["attr"], r["system"]): r for r in csv.DictReader(io.StringIO(text))}
    except (urllib.error.URLError, OSError, ValueError, KeyError, csv.Error) as e:
        about.note("hydra", False, f"couldn't be read ({e})")
        print(
            f"::warning::Hydra digest: couldn't use it ({e}); asking Hydra about "
            "each job",
            file=sys.stderr,
        )
        return None
    print(f"Hydra digest: {len(rows):,} jobs, {why}", file=sys.stderr)
    about.note("hydra", True, at=meta["fetchedAt"], eval=meta["eval"])
    return rows


def blocked_by(row):
    """Return which dependency failed, for a dependency-failed digest row.

    That's only known when the digest has read the build's page.

    Returns:
        {"blockedBy": [nixpkgs attributes, or store names no job builds
        (rows.name_blockers names them)]}, or {}.
    """
    if row["status"] == "dependency" and row.get("blockedBy"):
        return {"blockedBy": row["blockedBy"].split()}
    return {}


def failed_because(row):
    """Return why a failed build failed, for a failed digest row.

    That's only known when the digest has read the build's log
    (nixkeeper-hydra's reasons, since 2026-10-08).

    Returns:
        {"failedBecause": the reason (such as "cmake4"), "failedExcerpt"?:
        the lines that say so}, or {}.
    """
    if row["status"] == "failed" and row.get("failedBecause"):
        found = {"failedBecause": row["failedBecause"]}
        if row.get("failedExcerpt"):
            found["failedExcerpt"] = row["failedExcerpt"]
        return found
    return {}


def with_blockers(results, digest):
    """Add what the digest knows about the same builds to Hydra's answers.

    That's which dependency failed (blocked_by) and why a failed build
    failed (failed_because), which Hydra's answer doesn't say. A job the
    digest can't answer whole (its last success unknown) is asked of Hydra,
    and gets them here, when the digest's build is the one Hydra answered
    about.

    Args:
        results: Hydra's answers by job, changed in place.
        digest: load's result, or None.

    Returns:
        results.
    """
    for job, result in results.items():
        row = (digest or {}).get(job)
        if not row or str(result.get("build")) != row["build"]:
            continue
        if result.get("status") == "dependency":
            result.update(blocked_by(row))
        elif result.get("status") == "failed":
            result.update(failed_because(row))
    return results


def answer(row, broken, before):
    """Return a job's result from its digest row, as hydra.check gives it, or None.

    None means the digest can't say: the job is queued there, or its build
    isn't a success and nothing says when it last was.

    Args:
        row: The job's digest row.
        broken: Whether nixpkgs marks it broken on that platform.
        before: The job's result at the last sync, whose last success still
            holds for the same build.
    """
    if row["status"] not in FINISHED:
        return None
    result = {
        "attr": row["attr"],
        "system": row["system"],
        "status": row["status"],
        "build": int(row["build"]),
    }
    if row["name"]:
        result["name"] = row["name"]
    result.update(blocked_by(row))
    result.update(failed_because(row))
    if broken or row["status"] != "ok":
        if row["status"] == "ok":  # broken, but built: that's its last success
            last = {
                "lastSuccess": row["finished"],
                "lastSuccessBuild": result["build"],
                "lastSuccessName": row["name"],
            }
        elif row["lastSuccessBuild"]:
            last = {
                "lastSuccess": row["lastSuccessAt"],
                "lastSuccessBuild": int(row["lastSuccessBuild"]),
                "lastSuccessName": row["lastSuccessName"],
            }
        elif row["lastSuccessAt"] == NEVER:
            # nixkeeper-hydra asked Hydra: the job never succeeded (what
            # asking again would say).
            last = {"lastSuccess": None}
        elif (
            before
            and before.get("build") == result["build"]
            and "lastSuccess" in before
        ):
            last = {k: before[k] for k in LAST_SUCCESS if k in before}
        else:
            return None
        result.update({k: v for k, v in last.items() if v not in ("", None)})
        result.setdefault("lastSuccess", None)  # never, as Hydra would say
    if broken:
        result["status"] = "broken"
    return result


def answers(digest, wanted, broken, before):
    """Answer the jobs the digest can.

    Jobs missing from the digest are in neither list: they're asked of
    Hydra as before (hydra.due).

    Args:
        digest: load's result.
        wanted: The jobs, as [(attr, system)].
        broken: {attr: [the systems nixpkgs marks it broken on]}.
        before: The last sync's results by job (hydra.last_run).

    Returns:
        ({job: result} for the jobs the digest answers, [the jobs it has
        that Hydra must still be asked about: queued, or a build that isn't
        a success without a known last success]).
    """
    found, ask = {}, []
    for attr, system in wanted:
        row = digest.get((attr, system))
        if row is None:
            continue
        result = answer(row, system in broken.get(attr, []), before.get((attr, system)))
        if result is None:
            ask.append((attr, system))
        else:
            found[attr, system] = result
    return found, ask


def bulk_answers(digest, wanted, broken, before):
    """Answer every job in wanted without asking Hydra.

    This is for the jobs of packages not on the lists, with every package
    tracked. A job gets:

    - the digest's answer (answer), when it has one;
    - for a finished build whose last success the digest can't say, the
      result without one;
    - for a job the digest doesn't have, "notBuilt" (the digest has every
      job of the evaluation: Hydra would say the same), or "broken";
    - for a queued job, its result at the last sync, or "unknown" without
      one.

    With digest None (not current), every job is as the last sync had it.

    Args:
        digest: load's result, or None.
        wanted: The jobs, as [(attr, system)].
        broken: {attr: [the systems nixpkgs marks it broken on]}.
        before: The last sync's results by job (hydra.last_run).

    Returns:
        {job: result}.
    """
    found = {}
    for attr, system in wanted:
        job = (attr, system)
        is_broken = system in broken.get(attr, [])
        old = before.get(job)
        row = digest.get(job) if digest is not None else None
        if digest is not None and row is None:
            found[job] = {
                "attr": attr,
                "system": system,
                "status": "broken" if is_broken else "notBuilt",
            }
            continue
        result = row and answer(row, is_broken, old)
        if result is None and row and row["status"] in FINISHED:
            result = {
                "attr": attr,
                "system": system,
                "status": "broken" if is_broken else row["status"],
                "build": int(row["build"]),
            }
            if row["name"]:
                result["name"] = row["name"]
            result.update(blocked_by(row))
            result.update(failed_because(row))
        if result is None:
            result = (
                {k: v for k, v in old.items() if k != "checkedAt"}
                if old
                else {"attr": attr, "system": system, "status": "unknown"}
            )
        found[job] = result
    return found
