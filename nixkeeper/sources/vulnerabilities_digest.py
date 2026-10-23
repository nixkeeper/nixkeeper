"""nixkeeper-vulnerabilities' digest (https://github.com/nixkeeper/
digest-vulnerabilities): what the NixOS security tracker and OSV say about nixpkgs
packages, in one download, read by the daily sync.

Each row gets "vulnerabilities": its CVEs (the tracker's) and advisories
(OSV's), each with a verdict:

- the tracker's issue says "not affected" or "not for us": "dismissed";
  "won't fix": "wontFix" (counted);
- else nixVersion against the CVE record's affected ranges, as nixkeeper
  orders versions: "affected" (counted) in one, "fixed" outside them all.
  The tracker's own status is that same check, but on the version a
  branch had when it last evaluated it, often long ago (2026-10-08: 487
  of its 873 "affected on master" already fixed in nixpkgs): it's used
  only when a range can't be read, "tracker" (counted) when it said
  affected, "fixed" unaffected, "unconfirmed" otherwise;
- OSV's advisories, "osv" (counted), but not for a CVE the tracker has;
- and a counted one nixpkgs patches (a patch named after the CVE, on the
  channel's commit): "patched", not counted (2026-10-08: 28 packages).

A row is vulnerable (changes.is_vulnerable) when one is counted, nixpkgs
marks it insecure, or Repology flags it: the tracker's entries cover some
of a package's CVEs, not necessarily those Repology flags it for, so its
flag stays a source of its own. Without a usable digest, Repology's flag
and nixpkgs' mark decide, as before."""

import gzip
import json
import re
import sys
import urllib.error
from datetime import datetime, timedelta

from .. import config
from ..changes import COUNTED_VULNERABILITIES
from ..versions import version_key
from . import about, http, nixpkgs

FORMAT = 1
# Verdicts that make a row vulnerable: changes.COUNTED_VULNERABILITIES.
COUNTED = COUNTED_VULNERABILITIES
# Worst first: the order a row's list is in, and its worst severity.
SEVERITIES = ("critical", "high", "medium", "moderate", "low")
# The tracker's status of a package, worst first, over a row's attributes.
STATUS_ORDER = ("affected", "unknown", "unaffected", None)
CLAUSE = re.compile(r"(<=|>=|<|>|==|=)\s*v?(\d[\w.+~-]*?)(?:\.\*)?")


def current(meta, now):
    """Why the digest can be used, or None: the tracker read through once
    (complete), and recently (within VULNERABILITIES_DIGEST_MAX_AGE_HOURS)."""
    tracker = meta.get("tracker") or {}
    if not tracker.get("complete") or not tracker.get("readAt"):
        return None
    read = datetime.fromisoformat(tracker["readAt"])
    hours = (datetime.fromisoformat(now) - read) / timedelta(hours=1)
    if hours > config.VULNERABILITIES_DIGEST_MAX_AGE_HOURS:
        return None
    return f"read {hours:.0f} h ago"


def load(now):
    """The digest ({"tracker", "osv"}), or None (saying why) when it's turned
    off, not current or can't be read."""
    base = config.VULNERABILITIES_DIGEST_URL
    if not base:
        return None
    try:
        meta = json.loads(http.get(base + "meta.json") or "null")
        if not meta or meta.get("format") != FORMAT:
            raise ValueError(f"no digest in a format this nixkeeper reads ({base})")
        why = current(meta, now)
        if not why:
            about.note("tracker", False, "not read through yet, or too old")
            print(
                "::warning::Vulnerabilities digest: not used (the tracker not read "
                "through yet, or too old); Repology's flag decides",
                file=sys.stderr,
            )
            return None
        body = http.get_bytes(base + "vulnerabilities.json.gz")
        if body is None:
            raise ValueError("its vulnerabilities.json.gz is missing")
        found = json.loads(gzip.decompress(body))
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        about.note("tracker", False, f"couldn't be read ({e})")
        print(
            f"::warning::Vulnerabilities digest: couldn't use it ({e})", file=sys.stderr
        )
        return None
    tracker, osv = meta.get("tracker") or {}, meta.get("osv") or {}
    digest = {"tracker": found.get("tracker") or {}, "osv": found.get("osv") or {}}
    digest["newestRelease"] = newest_release(digest)
    # The release fixes are to be backported to ("26.05"), for the page.
    release = (digest["newestRelease"] or "").removeprefix("release-") or None
    about.note(
        "tracker",
        True,
        at=tracker.get("readAt"),
        suggestions=tracker.get("suggestions"),
        packages=tracker.get("packages"),
        release=release,
    )
    if osv:
        about.note(
            "osv",
            True,
            at=osv.get("readAt"),
            advisories=osv.get("advisories"),
            packages=osv.get("packages"),
        )
    print(
        f"Vulnerabilities digest: {tracker.get('suggestions'):,} tracker "
        f"suggestions, {osv.get('advisories', 0):,} OSV advisories, {why}",
        file=sys.stderr,
    )
    digest["stable"] = stable_versions(digest["newestRelease"])
    digest["stableRevision"] = stable_revision(digest["newestRelease"])
    return digest


def stable_revision(newest):
    """The newest release's channel commit, or None when it can't be read."""
    if not newest or not config.STABLE_INDEX_URL:
        return None
    url = config.STABLE_REVISION_URL.format(release=newest.removeprefix("release-"))
    try:
        return (http.get(url) or "").strip() or None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def stable_versions(newest):
    """{attribute: version} of the newest release's channel (its package
    index), or {} when it can't be read (the tracker's status for it is used
    then)."""
    if not newest or not config.STABLE_INDEX_URL:
        return {}
    release = newest.removeprefix("release-")
    url = config.STABLE_INDEX_URL.format(release=release)
    try:
        index = nixpkgs.load_index(url)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(
            f"::warning::nixos-{release}'s package index couldn't be read ({e}): "
            "the tracker's status says what's to backport",
            file=sys.stderr,
        )
        return {}
    versions = {a: p["version"] for a, p in index.items() if p.get("version")}
    print(f"  nixos-{release}: {len(versions):,} versions", file=sys.stderr)
    return versions


def newest_release(digest):
    """The newest release branch the tracker evaluates ("release-26.05"),
    by its version, or None: where a fix on master still needs backporting."""
    names = {
        branch
        for s in (digest["tracker"].get("suggestions") or {}).values()
        for p in (s.get("packages") or {}).values()
        for branch in (p.get("branches") or {})
        if branch.startswith("release-")
    }
    return max(
        names, key=lambda b: version_key(b.removeprefix("release-")), default=None
    )


def matches(version, expression):
    """Whether version is in a range as the tracker gives it (from the CVE
    record: "<1.2", "==>= 1.0, < 1.2", "=<1.1", "==1.0", "*"): True, False,
    or None when it can't be read (a list of versions, "x.59.21")."""
    e = (expression or "").strip()
    if e == "*":
        return True
    e = re.sub(r"^===\s*", "==", e)
    if e.startswith("==") and e[2:3] in ("<", ">", "="):
        e = e[2:].strip()  # "==< 1.0": the operator after it
    e = e.replace("=<", "<=").replace("=>", ">=")
    clauses = [c.strip() for c in e.split(",")]
    if not clauses or not all(clauses):
        return None
    key = version_key(version)
    for clause in clauses:
        m = CLAUSE.fullmatch(clause)
        if not m:
            return None
        op, bound = m.group(1), version_key(m.group(2))
        held = {
            "<": key < bound,
            "<=": key <= bound,
            ">": key > bound,
            ">=": key >= bound,
            "==": key == bound,
            "=": key == bound,
        }[op]
        if not held:
            return False
    return True


def by_version(version, affected):
    """ "affected", "fixed" or None (can't tell) for version against a
    suggestion's affected products' ranges ([["affected", "<1.2"],
    ["unaffected", ">=1.2"], ...])."""
    if not version or not affected:
        return None
    hit, cleared, unreadable, any_range = False, False, False, False
    for product in affected:
        for constraint in product.get("versions") or []:
            if not isinstance(constraint, list) or len(constraint) != 2:
                unreadable = True
                continue
            status, expression = constraint
            any_range = True
            found = matches(version, expression)
            if found is None:
                unreadable = True
            elif found and status == "affected":
                hit = True
            elif found and status == "unaffected":
                cleared = True
    if hit and not cleared:
        return "affected"
    if hit or unreadable or not any_range:
        return None  # contradictory, or not all read
    return "fixed"


COMMIT = re.compile(r"(?=[0-9]*[a-f])[0-9a-f]{7,40}")


def fixed_in(version, affected):
    """The first version past version that none of a suggestion's affected
    ranges takes in ("affected <2026.2.16593": 2026.2.16593), or None: the
    bounds the ranges name ("<X", an "unaffected" ">=X"), the lowest newer
    than version that by_version calls fixed. What an update needs to reach,
    for the page to say whether the newest release or an update PR does.
    Only for a version the ranges call affected; and versions only, not a
    commit ("<44b2f096...", for a package without releases)."""
    if by_version(version, affected) != "affected":
        return None
    bounds = set()
    for product in affected:
        for constraint in product.get("versions") or []:
            if not isinstance(constraint, list) or len(constraint) != 2:
                continue
            status, expression = constraint
            for m in re.finditer(r"(?<![=<>])(<|>=)\s*([^\s,<>=]+)", expression or ""):
                op, bound = m.groups()
                bound = re.sub(r"^v(?=\d)", "", bound)
                fixes = op == "<" or status == "unaffected"
                if fixes and not COMMIT.fullmatch(bound):
                    bounds.add(bound)
    newer = [
        b
        for b in bounds
        if version_key(b) > version_key(version) and by_version(b, affected) == "fixed"
    ]
    return min(newer, key=version_key, default=None)


def tracker_status(row, packages):
    """The tracker's entries for a row's attributes, by suggestion: {id:
    (worst status, its branches)}."""
    found = {}
    for attr in row.get("attrs") or [row["name"]]:
        for entry in packages.get(attr) or []:
            key = entry["suggestion"]
            status = entry.get("status")
            known = found.get(key)
            if known is None or STATUS_ORDER.index(status) < STATUS_ORDER.index(
                known[0]
            ):
                found[key] = (status, attr)
    return found


def releases(suggestion, attr, newest=None, version=None):
    """{release branch: status} of a suggestion's package, master left out
    (what the verdict's from): where a fix may still need backporting. The
    tracker's status for each, but the newest release's by its current
    version against the CVE's ranges, when known and they can be read."""
    branches = (suggestion.get("packages", {}).get(attr) or {}).get("branches") or {}
    found = {b: v.get("status") for b, v in sorted(branches.items()) if b != "master"}
    if newest and version:
        own = by_version(version, suggestion.get("affected"))
        if own:
            found[newest] = "affected" if own == "affected" else "unaffected"
    return found


def verdict(row, suggestion, status, issue):
    """The verdict on one of the tracker's CVEs for a row: its issue's
    verdict when people gave one, else nixVersion against the CVE's ranges,
    else (ranges it can't read) the tracker's last status."""
    issue_status = (issue or {}).get("status")
    if issue_status in ("notAffected", "notForUs"):
        return "dismissed"
    if issue_status == "wontFix":
        return "wontFix"
    found = by_version(row.get("nixVersion"), suggestion.get("affected"))
    if found:
        return found  # "affected" or "fixed"
    return {"affected": "tracker", "unaffected": "fixed"}.get(status, "unconfirmed")


def stable_version(attr, attrs, stable):
    """The newest release's version of a row's package: attr's, else any of
    its attributes'; None when not known."""
    return stable.get(attr) or next((stable[a] for a in attrs if a in stable), None)


def counted_first(entry):
    """Sort key: counted verdicts before the others."""
    return 0 if entry["verdict"] in COUNTED else 1


def severity_rank(entry):
    severity = entry.get("severity")
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def for_row(row, digest):
    """A row's CVEs and advisories with their verdicts ("vulnerabilities"),
    counted ones first, worst severity first; [] when the digest has none."""
    tracker, osv = digest["tracker"], digest["osv"]
    suggestions, issues = tracker.get("suggestions") or {}, tracker.get("issues") or {}
    newest, stable = digest.get("newestRelease"), digest.get("stable") or {}
    attrs = row.get("attrs") or [row["name"]]
    found, cves = {}, set()
    for key, (status, attr) in tracker_status(
        row, tracker.get("packages") or {}
    ).items():
        s = suggestions.get(key)
        if not s:
            continue
        issue = issues.get(s.get("issue")) if s.get("issue") else None
        cve = s.get("cve") or f"suggestion {key}"
        cves.add(cve)
        entry = {
            "id": cve,
            "source": "tracker",
            "verdict": verdict(row, s, status, issue),
            **({"issue": s["issue"]} if s.get("issue") else {}),
            **({"github": issue["github"]} if (issue or {}).get("github") else {}),
            **{k: s[k] for k in ("severity", "score") if s.get(k) is not None},
            **({"summary": s["title"]} if s.get("title") else {}),
            # The version that fixes it, for an affected one: not for an
            # older series kept beside a newer one, whose CVEs' ranges are
            # written for the newer (firefox-esr: "fixed in 158").
            **(
                {"fixedIn": f}
                if not row.get("keptBeside")
                and (f := fixed_in(row.get("nixVersion"), s.get("affected")))
                else {}
            ),
            **(
                {"releases": r}
                if (r := releases(s, attr, newest, stable_version(attr, attrs, stable)))
                else {}
            ),
        }
        # Several suggestions for one CVE (several packages): the worst.
        known = found.get(cve)
        if known is None or counted_first(entry) < counted_first(known):
            found[cve] = entry
    advisories = osv.get("advisories") or {}
    for attr in row.get("attrs") or [row["name"]]:
        for advisory in (osv.get("packages") or {}).get(attr) or []:
            a = advisories.get(advisory) or {}
            if advisory in found or cves & set(a.get("cves") or []):
                continue  # the tracker's verdict on that CVE stands
            found[advisory] = {
                "id": advisory,
                "source": "osv",
                "verdict": "osv",
                **({"cves": a["cves"]} if a.get("cves") else {}),
                **({"severity": a["severity"]} if a.get("severity") else {}),
                **({"summary": a["summary"]} if a.get("summary") else {}),
                "ecosystem": a.get("ecosystem"),
            }
    return sorted(
        found.values(), key=lambda e: (counted_first(e), severity_rank(e), e["id"])
    )


def to_backport(found, newest):
    """The CVEs of found (a row's "vulnerabilities") fixed on master (by
    version, or by a patch) but still affected on newest, the newest
    release branch."""
    return [
        v["id"]
        for v in found
        if newest
        and v["verdict"] in ("fixed", "patched")
        and (v.get("releases") or {}).get(newest) == "affected"
    ]


CVE_ID = re.compile(r"CVE-\d{4}-\d+", re.IGNORECASE)


def cve_ids(entry):
    """The CVE ids a patch fixing entry would be named after: its own (a
    tracker entry's), or its aliases (an OSV advisory's)."""
    return [
        i.upper()
        for i in [entry["id"], *(entry.get("cves") or [])]
        if CVE_ID.fullmatch(i)
    ]


def patched(rows, revision, wanted):
    """{row name: {CVE ids in its patches}} at revision, for the rows
    wanted(row) picks: nixpkgs' patches named after a CVE (a file
    CVE-2026-1234.patch, a fetchpatch's name or URL). {} when nixpkgs can't
    be evaluated there (each CVE then stands as it is)."""
    picked = [row for row in rows if wanted(row)]
    if not picked or not revision or revision == config.NIXPKGS_BRANCH:
        return {}
    attrs = {a for row in picked for a in row.get("attrs") or [row["name"]]}
    try:
        found = nixpkgs.patches(attrs, revision)
    except nixpkgs.EvalError as e:
        print(f"::warning::Patches at {revision[:12]}: not read ({e})", file=sys.stderr)
        return {}
    out = {}
    for row in picked:
        text = " ".join(
            t for a in row.get("attrs") or [row["name"]] for t in found.get(a) or []
        )
        if ids := {i.upper() for i in CVE_ID.findall(text)}:
            out[row["name"]] = ids
    return out


def add(rows, digest, revision=None):
    """Give each row its "vulnerabilities" (only when the digest has any for
    it), and "backport": those fixed on master, still affected on the
    newest release branch, when there's a digest. A counted CVE nixpkgs
    patches at revision (the channel's commit) is "patched", not counted;
    one to backport that the newest release's channel patches isn't one.
    Returns how many rows got some."""
    if digest is None:
        return 0
    newest = digest.get("newestRelease") or newest_release(digest)
    n = 0
    for row in rows:
        row.pop("vulnerabilities", None)
        row.pop("backport", None)
        if found := for_row(row, digest):
            row["vulnerabilities"] = found
            n += 1

    def counted(row):
        return any(v["verdict"] in COUNTED for v in row.get("vulnerabilities") or [])

    on_unstable = patched(rows, revision, counted)
    for row in rows:
        for v in row.get("vulnerabilities") or []:
            if v["verdict"] in COUNTED and set(cve_ids(v)) & on_unstable.get(
                row["name"], set()
            ):
                v["verdict"] = "patched"
        if "vulnerabilities" in row:
            row["vulnerabilities"].sort(
                key=lambda e: (counted_first(e), severity_rank(e), e["id"])
            )
            if ids := to_backport(row["vulnerabilities"], newest):
                row["backport"] = ids
    on_stable = patched(
        rows, digest.get("stableRevision"), lambda row: row.get("backport")
    )
    for row in rows:
        if not row.get("backport"):
            continue
        done = on_stable.get(row["name"], set())
        for v in row["vulnerabilities"]:
            if v["id"] in row["backport"] and set(cve_ids(v)) & done:
                v.setdefault("releases", {})[newest] = "patched"
        if not (still := [i for i in row["backport"] if i.upper() not in done]):
            del row["backport"]
        else:
            row["backport"] = still
    return n


def summary(row):
    """The list's view of a row with "vulnerabilities" ("vuln" in its
    summary entry): {"n", "severity"?, "by"} of what's counted, its sources
    with nixpkgs' insecure mark and Repology's flag; None when none says
    so. A row without "vulnerabilities" has no "vuln": Repology's flag and
    nixpkgs' mark decide, as before."""
    counted = [v for v in row["vulnerabilities"] if v["verdict"] in COUNTED]
    by = (
        sorted({v["source"] for v in counted})
        + (["nixpkgs"] if row.get("markedInsecure") else [])
        + (["repology"] if row.get("nixVulnerable") else [])
    )
    if not by:
        return None
    worst = min(counted, key=severity_rank, default={})
    return {
        "n": len(counted),
        **({"severity": worst["severity"]} if worst.get("severity") else {}),
        "by": by,
    }
