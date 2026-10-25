"""Read nixkeeper-prs' digest of nixpkgs' PRs and issues.

The digest (https://github.com/nixkeeper/digest-prs) lists every open PR
and issue of nixpkgs, and the PRs merged into master since the
nixos-unstable channel's commit, refreshed by its hourly workflow. The
daily sync counts each package's open PRs and issues, and finds its open
and merged update PRs, in these lists (github_bulk) instead of listing
them itself.

The lists come with the digest's own findings (facts): for each PR,
whether the merge bot can merge it, its update's state, whether it blocks
the update bot, and which PRs duplicate it; the PRs touching a package
whose build fails on Hydra; and the issues it checked (a build failure
against Hydra now, an update request against nixpkgs' version). add_facts
gives each row the findings for its own package, for its panel.

Each list is used only while it's recent (PRS_DIGEST_MAX_AGE_HOURS). The
merged PRs are used only when they were listed since the same channel
commit the sync reads: with a newer channel, PRs it has would be counted
as not in it yet. Otherwise the sync lists them itself, as it did before
the digest.
"""

import json
import re
import sys
from datetime import datetime, timedelta

from .. import config
from ..changes import is_vulnerable
from ..versions import is_newer, version_key
from . import about, digests, github, http

FORMAT = 1
# The update bot (nixpkgs-update), as GitHub names it.
BOT = "r-ryantm"
PR_URL = "https://github.com/NixOS/nixpkgs/pull/"
ISSUE_URL = "https://github.com/NixOS/nixpkgs/issues/"
# The most PRs and issues of each kind a package's panel shows; the rest are
# a GitHub search away.
SHOWN = 5
# The issue checks' verdicts worth showing: those that ask for something
# (closing the issue, or a build still failing).
BUILD_SHOWN = {"builds", "failing"}
UPDATE_SHOWN = {"done", "partly"}
# The package a PR's title names, by nixpkgs' convention ("foo: drop").
TITLE_PACKAGE = re.compile(r"^([\w.+-]+):")
# A PR's kinds, as the digest reads them from its title (nixkeeper-prs'
# facts.py).
KINDS = ("drop", "init", "update")
# The digest calls any "foo: drop ..." or "foo: remove ..." PR a drop, but
# most remove something from the package ("drop unused libmatthew_java",
# "remove meta.changelog": 85 of 125 on 2026-10-09). A PR removing the
# package itself says nothing more, or says so: "foo: drop", "foo: remove
# package", "foo: drop in favor of bar", "foo: drop, bar: init at 1.0",
# "fmt_9: remove version".
REMOVAL = re.compile(
    r"^[\w.+-]+: (?:drop|remove)(?:\s*$|\s*[,;(:]|\s+(?:the\s+)?package\b"
    r"|\s+in\s+favou?r\b|\s+(?:as|since|because|due)\b|\s+version\b)",
    re.IGNORECASE,
)
# PR titles name Python packages by their alias (python3Packages), rows by
# the versioned set it points to.
PYTHON_ALIAS = ("python3packages.", "python313packages.")


def package_key(name):
    """Return the key the digest's findings are kept under for a package.

    That's the name in lower case, with Python's alias replaced by the
    versioned set it points to.
    """
    key = (name or "").lower()
    if key.startswith(PYTHON_ALIAS[0]):
        key = PYTHON_ALIAS[1] + key[len(PYTHON_ALIAS[0]) :]
    return key


def pr_facts(pr, duplicates):
    """Return what the digest found about a PR, as a row's update PR keeps it.

    Args:
        pr: The digest's PR.
        duplicates: {PR number: the numbers of the PRs it duplicates}.

    Returns:
        Any of: "mergeBot" ("ready" when CI is green and there's no
        conflict, else "eligible"); "state" (superseded, overtaken,
        downgrade...), with nixpkgs' version as "now"; "blocksBot" (the day
        the update bot is expected to try, or True); "duplicates" (at most
        SHOWN). {} when there's none.
    """
    found = {}
    if mb := pr.get("mergeBot"):
        ready = mb.get("ready") and pr.get("mergeable") != "CONFLICTING"
        found["mergeBot"] = "ready" if ready else "eligible"
    if state := pr.get("state"):
        found["state"] = state
        if now := (pr.get("update") or {}).get("now"):
            found["now"] = now
    if blocking := pr.get("blocksBot"):
        found["blocksBot"] = blocking.get("by") or True
    if others := duplicates.get(pr["n"]):
        found["duplicates"] = others[:SHOWN]
    return found


# A removal PR without activity for this many days is only proposed, not
# likely.
REMOVAL_STALE_DAYS = 90


def removal_proposed(pr, now):
    """Return why a PR removing a package is only proposed, or None.

    A removal is only proposed when a committer asked for changes, or when
    nothing has happened on it for REMOVAL_STALE_DAYS days (7 of 26 on
    2026-10-20: telepresence's, fmt_10's, ...). The panel then says so, and
    the list's "being removed" badge stays off. None means the removal
    looks likely.

    Args:
        pr: The digest's PR.
        now: The time to measure from (ISO), or None.
    """
    if pr.get("review") == "CHANGES_REQUESTED":
        return "changes requested"
    updated = pr.get("updated")
    if now and updated:
        then = datetime.fromisoformat(updated)
        if datetime.fromisoformat(now) - then > timedelta(days=REMOVAL_STALE_DAYS):
            return f"no activity since {then:%Y-%m-%d}"
    return None


def facts(prs, groups, issues, now=None):
    """Collect the digest's findings, by PR number and by package.

    Args:
        prs: The digest's open PRs.
        groups: Its groups of duplicate PRs, each {"prs": [numbers]}.
        issues: Its open issues.
        now: The time to measure from (ISO), for removal_proposed.

    Returns:
        {"prs": {number: pr_facts}, "fixes": {package: the PRs touching it
        while its build fails on Hydra}, "issues": {package: its checked
        issues}, "open": {package: its open PRs, drafts left out}}, with
        packages by package_key. An open PR is listed under the package its
        title names and under each pkgs/by-name package it touches; a
        removal's "kind" and "proposed" are only on the copy under the
        package its title names.
    """
    duplicates = {}
    for group in groups:
        for n in group.get("prs") or []:
            others = [m for m in group["prs"] if m != n]
            duplicates.setdefault(n, [])
            duplicates[n] += [m for m in others if m not in duplicates[n]]
    by_number, fixes, open_prs = {}, {}, {}
    for pr in prs:
        if found := pr_facts(pr, duplicates):
            by_number[pr["n"]] = found
        if pr.get("draft"):
            continue
        item = {"number": pr["n"], "title": pr["title"]}
        kind = next((k for k in KINDS if k in (pr.get("buckets") or [])), None)
        if kind == "drop" and not REMOVAL.match(pr["title"]):
            kind = None  # it removes something from the package, not the package
        if kind:
            item["kind"] = kind
        if kind == "drop" and (why := removal_proposed(pr, now)):
            item["proposed"] = why
        if mb := found.get("mergeBot"):
            item["mergeBot"] = mb
        named = TITLE_PACKAGE.match(pr["title"])
        title_key = package_key(named.group(1)) if named else None
        keys = {package_key(p) for p in pr.get("packages") or []} | {title_key}
        # Only the package its title names is removed; the others it touches
        # are moved off it ("fmt_11: remove version" moves imhex's
        # package.nix to fmt).
        touched = {k: v for k, v in item.items() if k not in ("kind", "proposed")}
        for key in keys - {None}:
            mine = item if key == title_key or kind != "drop" else touched
            open_prs.setdefault(key, []).append(mine)
        for package in pr.get("hydraFailing") or {}:
            fixes.setdefault(package_key(package), []).append(
                {"number": pr["n"], "title": pr["title"], "url": PR_URL + str(pr["n"])}
            )
    checked = {}
    for issue in issues:
        hydra, update = issue.get("hydra") or {}, issue.get("update") or {}
        if hydra.get("verdict") in BUILD_SHOWN:
            check = {"kind": "build", "verdict": hydra["verdict"]}
            if hydra.get("condition"):
                check["condition"] = True
            package = hydra["package"]
        elif update.get("verdict") in UPDATE_SHOWN:
            check = {"kind": "update", "verdict": update["verdict"]}
            if update.get("now"):
                check["now"] = update["now"]
            package = update["package"]
        else:
            continue
        checked.setdefault(package_key(package), []).append(
            {
                "number": issue["n"],
                "title": issue["title"],
                "url": ISSUE_URL + str(issue["n"]),
                **check,
            }
        )
    return {"prs": by_number, "fixes": fixes, "issues": checked, "open": open_prs}


def cross_check(rows):
    """Add what nixkeeper knows about a row to its update PR's facts.

    The digest doesn't know these, so they're added to "openPR"'s "facts":

    - "behind": upstream's newer version (refVersion), when it's newer than
      the PR's. Merged, the PR would still leave the package outdated (496
      open update PRs on 2026-10-18, 152 of them ready for the merge bot).
    - "vulnerable": the package counts as vulnerable
      (changes.is_vulnerable), so the PR is worth reviewing first (98 PRs).

    Both are worked out again each time (CROSS). Call it after the versions
    and vulnerabilities are in: the sync calls it last, and the hourly
    check after add_facts.

    Args:
        rows: The rows, changed in place.
    """
    for row in rows:
        pr = row.get("openPR")
        if not pr:
            continue
        facts = {k: v for k, v in (pr.get("facts") or {}).items() if k not in CROSS}
        ref, to = row.get("refVersion"), pr.get("to")
        if ref and to and is_newer(ref, to):
            facts["behind"] = ref
        if is_vulnerable(row):
            facts["vulnerable"] = True
        if facts:
            pr["facts"] = facts
        else:
            pr.pop("facts", None)


# The facts cross_check adds, worked out again each time.
CROSS = ("behind", "vulnerable")
# A CVE's id, as issue titles write it.
CVE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
# The verdicts on a CVE (vulnerabilities_digest) that say nixpkgs' version
# isn't affected: outside every affected range, or patched.
NOT_AFFECTED = ("fixed", "patched")


def add_cve_prs(rows, prs):
    """Add the open PRs patching a row's CVEs to its vulnerabilities.

    A PR patches a CVE when its diff adds the CVE's id, mostly in a patch
    named after it (the digest's diffFacts "cves", 17 PRs on 2026-10-23).
    The panel then answers "is someone fixing this?". Only vulnerabilities
    still affecting the package get them, as "prs": [{"number", "title",
    "base"? (when it isn't master), "draft"?}], at most SHOWN, by number. A
    PR that only touches other packages doesn't count; one the digest maps
    to no package does (a patch in a shared file: binutils, gimp).

    Call it after the vulnerabilities are in.

    Args:
        rows: The rows, changed in place.
        prs: The digest's open PRs, or None.
    """
    by_cve = {}
    for pr in prs or []:
        for cve in (pr.get("diffFacts") or {}).get("cves") or []:
            by_cve.setdefault(cve.upper(), []).append(pr)
    if not by_cve:
        return
    for row in rows:
        keys = {package_key(n) for n in [row["name"], *(row.get("attrs") or [])]}
        for v in row.get("vulnerabilities") or []:
            found = [
                pr
                for pr in by_cve.get(v["id"].upper(), [])
                if v["verdict"] not in NOT_AFFECTED
                and (
                    not pr.get("packages")
                    or keys & {package_key(n) for n in pr["packages"]}
                )
            ]
            if found:
                v["prs"] = [
                    {
                        "number": pr["n"],
                        "title": pr["title"],
                        **(
                            {"base": pr["base"]}
                            if pr.get("base") not in (None, "master")
                            else {}
                        ),
                        **({"draft": True} if pr.get("draft") else {}),
                    }
                    for pr in sorted(found, key=lambda pr: pr["n"])[:SHOWN]
                ]


def add_cve_issues(rows, issues):
    """Add CVE issues that could be closed to their packages' issue checks.

    An open issue whose title names CVEs could be closed for a package when
    nixkeeper finds that none of them affects the package's nixpkgs version
    (each of its vulnerabilities' verdicts is fixed or patched): 4 of the
    17 such issues on 2026-10-18. It's added after the digest's checks, as
    {"kind": "cve", "verdict": "cveFixed", "cves"}, while there are fewer
    than SHOWN.

    Call it after the vulnerabilities are in: in the sync, and in the
    hourly check after add_facts, which replaces the checks.

    Args:
        rows: The rows, changed in place.
        issues: The digest's open issues, each {"number", "title"}.
    """
    # Worked out again each time, so an earlier call's are dropped first.
    for row in rows:
        if checks := row.get("issueChecks"):
            if kept := [c for c in checks if c.get("kind") != "cve"]:
                row["issueChecks"] = kept
            else:
                del row["issueChecks"]
    named = []
    for issue in issues:
        if cves := sorted({c.upper() for c in CVE.findall(issue.get("title") or "")}):
            named.append((issue, cves))
    if not named:
        return
    by_cve = {}
    for row in rows:
        for v in row.get("vulnerabilities") or []:
            by_cve.setdefault(v["id"].upper(), []).append(row)
    for issue, cves in named:
        candidates = {id(r): r for c in cves for r in by_cve.get(c, [])}
        for row in candidates.values():
            verdicts = {v["id"].upper(): v["verdict"] for v in row["vulnerabilities"]}
            if not all(verdicts.get(c) in NOT_AFFECTED for c in cves):
                continue
            checks = row.setdefault("issueChecks", [])
            if len(checks) >= SHOWN or any(
                c["number"] == issue["number"] for c in checks
            ):
                continue
            checks.append(
                {
                    "number": issue["number"],
                    "title": issue["title"],
                    "url": ISSUE_URL + str(issue["number"]),
                    "kind": "cve",
                    "verdict": "cveFixed",
                    "cves": cves,
                }
            )


def mergeable(prs, rows):
    """List the PRs a maintainer can merge now with the merge bot.

    The merge bot is nixpkgs' @NixOS/nixpkgs-merge-bot. A PR is listed when
    it's eligible (as nixpkgs' CI labels it, or as the digest finds), CI is
    green, it has no conflict and no changes requested, it isn't a draft,
    and it touches packages that have rows. The list is for the maintainer
    and team views' "You can merge these" (views/merge.json).

    Args:
        prs: The digest's open PRs.
        rows: The rows.

    Returns:
        The PRs, oldest (longest waiting) first, each {"number", "title",
        "author", "created", "base", "packages": the rows' names, "who":
        the maintainers of every package it touches (the digest's
        merge_bot), "approvedBy"?}. An update also has "behind" (upstream's
        newer version) and "vulnerable", as cross_check works them out.
    """
    by_key = {package_key(r["name"]): r for r in rows}
    for row in rows:
        for attr in row.get("attrs") or []:
            by_key.setdefault(package_key(attr), row)
    known = {key: row["name"] for key, row in by_key.items()}
    found = []
    for pr in prs:
        mb = pr.get("mergeBot") or {}
        if not (mb.get("ready") and mb.get("maintainers")):
            continue
        if pr.get("draft") or pr.get("mergeable") == "CONFLICTING":
            continue
        if pr.get("review") == "CHANGES_REQUESTED":
            continue
        packages = sorted(
            {known[k] for k in map(package_key, pr.get("packages") or []) if k in known}
        )
        if not packages:
            continue
        item = {
            "number": pr["n"],
            "title": pr["title"],
            "author": pr.get("author") or "",
            "created": pr.get("created") or "",
            "base": pr.get("base") or "",
            "packages": packages,
            "who": mb["maintainers"],
        }
        if pr.get("approvedBy"):
            item["approvedBy"] = pr["approvedBy"]
        update = pr.get("update") or {}
        if row := by_key.get(package_key(update.get("attr") or "")):
            ref, to = row.get("refVersion"), update.get("to")
            if ref and to and is_newer(ref, to):
                item["behind"] = ref
            if is_vulnerable(row):
                item["vulnerable"] = True
        found.append(item)
    found.sort(key=lambda p: (p["created"], p["number"]))
    return found


def mark_superseded(prs, rows):
    """Mark each row's open PRs that nixpkgs is already past.

    Two kinds are marked:

    - update PRs the digest finds "superseded": nixpkgs has the PR's
      version, or a newer one (255 on 2026-10-23, most of them r-ryantm's);
    - init PRs for an attribute nixpkgs has now, added another way while
      they waited (the digest's "alreadyIn", 68 on 2026-10-23), with
      "init": True.

    They go in the row's "supersededPRs", [{"number", "title", "author",
    "created", "now": nixpkgs' version, "draft"?, "init"?}], oldest first,
    for a maintainer's and a team's "Can be closed" and the list's filter.
    An earlier call's are replaced.

    Args:
        prs: The digest's open PRs, or None without the digest's list.
        rows: The rows, changed in place.

    Returns:
        {"prs", "bot": how many of them are r-ryantm's, "init"}, for the
        overview, or None without the digest's list.
    """
    if prs is None:
        return None
    by_key = {package_key(r["name"]): r for r in rows}
    for row in rows:
        row.pop("supersededPRs", None)
        for attr in row.get("attrs") or []:
            by_key.setdefault(package_key(attr), row)
    found = {"prs": 0, "bot": 0, "init": 0}
    for pr in prs:
        update = pr.get("update") or {}
        added = pr.get("alreadyIn") or {}
        if pr.get("state") == "superseded":
            attr, now = update.get("attr"), update.get("now")
        elif added.get("attr"):
            attr, now = added["attr"], added.get("version")
        else:
            continue
        row = by_key.get(package_key(attr or ""))
        if row is None:
            continue
        item = {
            "number": pr["n"],
            "title": pr["title"],
            "author": pr.get("author") or "",
            "created": pr.get("created") or "",
            "now": now or row.get("nixVersion") or "",
        }
        if pr.get("draft"):
            item["draft"] = True
        row.setdefault("supersededPRs", []).append(item)
        if pr.get("state") == "superseded":
            found["prs"] += 1
            found["bot"] += item["author"] == BOT
        else:
            item["init"] = True
            found["init"] += 1
    for row in rows:
        if row.get("supersededPRs"):
            row["supersededPRs"].sort(key=lambda p: (p["created"], p["number"]))
    return found


# How many days of waiting the overview's merge line counts as long.
MERGE_LONG_DAYS = 90


def merge_summary(prs, now):
    """Summarize mergeable's PRs, for the overview's line.

    Returns:
        {"prs": how many, "maintainers": how many could merge at least one,
        "over90": how many have waited over MERGE_LONG_DAYS days}.
    """
    then = datetime.fromisoformat(now) - timedelta(days=MERGE_LONG_DAYS)
    return {
        "prs": len(prs),
        "maintainers": len({m.lower() for pr in prs for m in pr["who"]}),
        "over90": sum(
            1
            for pr in prs
            if pr["created"] and datetime.fromisoformat(pr["created"]) < then
        ),
    }


def add_facts(rows, digest):
    """Give each row the digest's findings for its own package.

    Each row gets, from facts, at most SHOWN of each:

    - its update PR's facts ("openPR"'s "facts"), with "fixesBuild" when
      the PR touches the package while its build fails on Hydra;
    - the other open PRs that do ("fixPRs");
    - its other open PRs ("otherPRs"), a removal first, then the newest;
    - its checked issues ("issueChecks");
    - "dropPR", when an open PR removes the package from nixpkgs (the
      list's "being removed" badge).

    The last sync's are replaced.

    Args:
        rows: The rows, changed in place.
        digest: load's result, or None.
    """
    found = (digest or {}).get("facts")
    for row in rows:
        for field in ("fixPRs", "issueChecks", "otherPRs", "dropPR"):
            row.pop(field, None)
        if not found:
            continue
        pr = row.get("openPR")
        if pr and (theirs := found["prs"].get(pr["number"])):
            pr["facts"] = dict(theirs)
        # Sorted, so every loop over them goes in the same order in every run.
        keys = sorted(
            {package_key(a) for a in [row["name"], *(row.get("attrs") or [])]}
        )
        # The update PR is shown once, as the update PR (marked as touching
        # the failing build too), not again among the fixes.
        if pr and any(
            fix["number"] == pr["number"]
            for key in keys
            for fix in found["fixes"].get(key, [])
        ):
            pr.setdefault("facts", {})["fixesBuild"] = True
        for field, source in (("fixPRs", "fixes"), ("issueChecks", "issues")):
            items, seen = [], {pr["number"]} if pr and field == "fixPRs" else set()
            for key in keys:
                for item in found[source].get(key, []):
                    if item["number"] not in seen:
                        seen.add(item["number"])
                        items.append(item)
            if items:
                row[field] = items[:SHOWN]
        # Its other open PRs: neither the update PR nor the fixes, shown
        # above.
        said = {pr["number"]} if pr else set()
        said |= {fix["number"] for fix in row.get("fixPRs") or []}
        others = _other_prs(found.get("open", {}), keys, said)
        ordered = sorted(
            others.values(), key=lambda p: (p.get("kind") != "drop", -p["number"])
        )
        if ordered:
            row["otherPRs"] = ordered[:SHOWN]
        # Being removed: only when the PR's title names the row's own
        # package, not one of its other attributes ("sqlite-interactive:
        # drop" leaves sqlite).
        mine = package_key(row["name"])
        if drop := next(
            (
                p
                for p in ordered
                if p.get("kind") == "drop"
                and (m := TITLE_PACKAGE.match(p["title"]))
                and package_key(m.group(1)) == mine
            ),
            None,
        ):
            row["dropPR"] = {"number": drop["number"], "title": drop["title"]}
            if drop.get("proposed"):
                # Only proposed (removal_proposed): the list shows no badge.
                row["dropPR"]["proposed"] = drop["proposed"]


def _other_prs(open_prs, keys, said):
    """Collect a row's other open PRs, once each, from its names' lists.

    A PR touching several of the row's names is listed under each, and the
    copies differ: facts gives "kind" and "proposed" only to the copy under
    the package the PR's title names, so a removal isn't shown as removing
    the other packages it touches. Every copy of a PR is merged, in the
    names' sorted order, so a fact one copy has is kept and the result
    doesn't depend on any order. The copies differ only by the facts one
    leaves out; were a field to differ, the last name's copy would win. It
    once kept the last copy met in a set, whose order changes from one run
    to the next, and segger-jlink (with segger-jlink-headless) lost and
    regained its "being removed" PR between syncs (2026-10-25).

    Args:
        open_prs: The digest's open PRs by package (facts' "open").
        keys: The row's names (package_key), in any order: sorted here.
        said: The numbers of the PRs already shown (the update PR, the fixes).

    Returns:
        {number: PR}, each PR's copies merged into one.
    """
    others = {}
    for key in sorted(keys):
        for item in open_prs.get(key, []):
            number = item["number"]
            if number not in said:
                others[number] = {**others.get(number, {}), **item}
    return others


def recent(at, now):
    """Return whether a list made at `at` (ISO) is recent enough to use."""
    if not at:
        return False
    age = datetime.fromisoformat(now) - datetime.fromisoformat(at)
    return age <= timedelta(hours=config.PRS_DIGEST_MAX_AGE_HOURS)


def node(pr):
    """Return a PR as github_bulk's listings have it (GraphQL's names)."""
    return {
        "number": pr["n"],
        "title": pr["title"],
        "url": PR_URL + str(pr["n"]),
        "isDraft": pr.get("draft", False),
        "baseRefName": pr.get("base"),
    }


def _read(base, name):
    """Read one of the digest's files, checking its format.

    Raises:
        ValueError: The file is empty or in a format this nixkeeper doesn't
            read.
    """
    data = json.loads(http.get(base + name, compressed=True) or "null")
    if not data or data.get("format") != FORMAT:
        raise ValueError(f"no {name} in a format this nixkeeper reads")
    return data


def _list(base, name, key):
    """Read the list under key in one of the digest's files (name)."""
    return _read(base, name).get(key) or []


def load(now, revision):
    """Read the digest, as github_bulk's listings would give it.

    Args:
        now: The run's time (ISO).
        revision: The channel commit the sync reads.

    Returns:
        {"open": (PRs, issues), "merged": PRs, "staging": {"prs",
        "stagingNext"}, "facts"?: the digest's findings (facts), "raw"?:
        the open PRs as the digest wrote them}. "open", "merged" and
        "staging" are each None when that list isn't recent, and "merged"
        also when it was listed since another channel commit than revision.
        None when the digest is turned off (no PRS_DIGEST_URL), or can't be
        read (the log says why).
    """
    base = config.PRS_DIGEST_URL
    if not base:
        return None
    try:
        meta = digests.read_meta(base, FORMAT)
        issues_meta = meta.get("issues") or {}
        merged_meta = meta.get("merged") or {}
        staging_meta = meta.get("staging") or {}
        found = {"open": None, "merged": None, "staging": None}
        why = []
        if recent(meta.get("generatedAt"), now) and recent(issues_meta.get("at"), now):
            data = _read(base, "prs.json")
            raw_issues = _list(base, "issues.json", "issues")
            prs = [node(p) for p in data.get("prs") or []]
            issues = [{"number": i["n"], "title": i["title"]} for i in raw_issues]
            found["open"] = (prs, issues)
            found["facts"] = facts(
                data.get("prs") or [], data.get("groups") or [], raw_issues, now
            )
            found["raw"] = data.get("prs") or []
        else:
            why.append("open PRs and issues too old")
        if merged_meta.get("revision") != revision:
            why.append("merged PRs since another channel commit")
        elif not recent(merged_meta.get("at"), now):
            why.append("merged PRs too old")
        else:
            found["merged"] = [
                {
                    **node(p),
                    # Who opened and merged it, and the pkgs/by-name
                    # packages it touched (listed since 2026-10-09): what a
                    # fix is credited to (history.fixes, build_fix_prs).
                    **{
                        k: p[k]
                        for k in ("author", "mergedBy", "packages", "merged")
                        if p.get(k)
                    },
                }
                for p in _list(base, "merged.json", "prs")
                if p.get("n")
            ]
        # PRs merged into staging or staging-next but not on master yet
        # (listed since 2026-10-16): where each is, and the staging-next
        # cycle.
        if recent(staging_meta.get("at"), now):
            data = _read(base, "staging.json")
            found["staging"] = {
                "prs": [
                    {**node(p), "on": p["on"], "merged": p.get("merged")}
                    for p in data.get("prs") or []
                    if p.get("n") and p.get("on")
                ],
                "stagingNext": data.get("stagingNext") or {},
            }
    except digests.FAILURES as e:
        digests.give_up("prs", "PRs digest", e, "; listing them here")
        return None
    used = found["open"] is not None or found["merged"] is not None
    about.note(
        "prs",
        used,
        "; ".join(why) if not used else None,
        at=meta.get("generatedAt"),
        prs=len(found["open"][0]) if found["open"] else None,
        issues=len(found["open"][1]) if found["open"] else None,
        merged=len(found["merged"]) if found["merged"] is not None else None,
        staging=len(found["staging"]["prs"]) if found["staging"] else None,
        partly="; ".join(why) if used and why else None,
    )
    print(
        f"PRs digest: made {meta.get('generatedAt')}"
        + (
            f", {len(found['open'][0]):,} open PRs, {len(found['open'][1]):,} issues"
            if found["open"]
            else ""
        )
        + (
            f", {len(found['merged']):,} merged since the channel"
            if found["merged"] is not None
            else ""
        )
        + (f" ({'; '.join(why)}: listed here)" if why else ""),
        file=sys.stderr,
    )
    return found


def add_staging_prs(rows, staging):
    """Give each row its update PR merged into staging or staging-next.

    That's an update PR master doesn't have yet ("stagingPR"): the one
    going to the highest version, newer than nixpkgs' and master's, with
    staging-next's before staging's on a tie. Its "on" says which branch
    it's on; on staging-next, "cycle" is the open staging-next PR it
    reaches master with ({"n", "cut"}).

    Args:
        rows: The rows, changed in place.
        staging: load's "staging", or None. With None, rows keep no
            stagingPR: there's no other way to know.
    """
    # What the sync found about each PR's builds on staging-next
    # (branches.apply_staging_next) is kept while it's the same PR, as the
    # hourly check doesn't read those builds.
    before = {row["name"]: row.pop("stagingPR") for row in rows if row.get("stagingPR")}
    if not staging:
        return
    by_package = {}
    for pr in staging["prs"]:
        for package in github.title_packages(pr.get("title")):
            by_package.setdefault(package, []).append(pr)
    cycle = (staging.get("stagingNext") or {}).get("open")
    for row in rows:
        titled = list(
            {
                pr["number"]: pr
                for n in github.pr_names(row)
                for pr in by_package.get(n, [])
            }.values()
        )
        if not titled:
            continue
        where = {pr["number"]: pr for pr in titled}
        found = [
            {
                **pr,
                "on": where[pr["number"]]["on"],
                "merged": where[pr["number"]]["merged"],
            }
            for pr in github.update_prs(
                [{**p, "isDraft": False} for p in titled], github.pr_names(row)
            )
            if is_newer(pr["to"], row.get("nixVersion") or "")
            and (not row.get("master") or is_newer(pr["to"], row["master"]))
        ]
        if not found:
            continue
        best = max(
            found, key=lambda p: (version_key(p["to"]), p["on"] == "staging-next")
        )
        if best["on"] == "staging-next" and cycle:
            best["cycle"] = {"n": cycle["n"], "cut": cycle["cut"]}
        old = before.get(row["name"]) or {}
        if old.get("number") == best["number"] and old.get("on") == best["on"]:
            best.update({k: old[k] for k in ("builds", "eval", "inEval") if k in old})
        row["stagingPR"] = best


# A merged PR touching more pkgs/by-name packages than this is treewide
# ("treewide: remove explicit strictDeps"): a build fix is credited to it
# only when its title names the package.
FIX_MAX_TOUCHED = 3
# Marking a package broken stops Hydra building it: that's not a fix to
# credit.
MARKS_BROKEN = re.compile(r"\bmark\w*\b.*\bbroken\b", re.IGNORECASE)
# An update's title ("tgrep: 1.1.0 -> 1.2.4"), and the version it goes to.
UPDATE_TO = re.compile(r"^[\w.+-]+:\s*\S+\s*(?:->|→)\s*(\S+)")


def in_failed(pr, versions):
    """Return whether pr updates the package to one of versions.

    Args:
        pr: A merged PR.
        versions: The versions the package's failed builds are at.
    """
    to = UPDATE_TO.match(pr.get("title") or "")
    return bool(to) and to.group(1).removeprefix("v") in versions


def build_fix_prs(rows, merged, previous):
    """Credit each failing row's build fix, and its cause, to merged PRs.

    A row whose build is failing gets "buildFixPR": the newest PR merged
    into master since it began failing (failingSince) that touched it, by
    the package its title names or a pkgs/by-name directory of it. Only a
    PR touching at most FIX_MAX_TOUCHED packages counts by directory, so a
    treewide change in passing isn't credited. It's likely the fix, once
    Hydra builds the package (history.fixes credits a build fix to it). A
    row still failing keeps the one the last sync found, which a channel
    move may have taken off the list.

    An update PR to the version a failed build is at is in that build: not
    its fix, but likely what broke it. It goes in "buildCausePR" instead
    (tgrep's #575734, 1.1.0 -> 1.2.4, failing at 1.2.4 since). Both are
    {"number", "title", "url", "author"?, "mergedBy"?, "merged"?}.

    Args:
        rows: The rows, changed in place.
        merged: The digest's merged PRs, those since the channel's commit.
        previous: The last run's data.
    """
    before = {row["name"]: row for row in previous.get("packages") or []}
    touching = {}
    for pr in merged or []:
        if MARKS_BROKEN.search(pr.get("title") or ""):
            continue
        touched = pr.get("packages") or []
        keys = (
            {package_key(p) for p in touched}
            if len(touched) <= FIX_MAX_TOUCHED
            else set()
        )
        if named := TITLE_PACKAGE.match(pr.get("title") or ""):
            keys.add(package_key(named.group(1)))
        for key in keys:
            touching.setdefault(key, []).append(pr)

    def entry(pr):
        """Return pr as a row's buildFixPR or buildCausePR keeps it."""
        return {
            "number": pr["number"],
            "title": pr["title"],
            "url": pr["url"],
            **{k: pr[k] for k in ("author", "mergedBy", "merged") if pr.get(k)},
        }

    for row in rows:
        old = row.pop("buildFixPR", None)  # worked out again below
        old_cause = row.pop("buildCausePR", None)
        failed = [b for b in row.get("builds") or [] if b["status"] == "failed"]
        if not failed:
            continue
        # The versions its failed builds are at, when they last built at
        # another version: they began failing with that update.
        broke_at = {
            b["version"]
            for b in failed
            if b.get("version")
            and b.get("lastSuccessVersion")
            and b["version"] != b["lastSuccessVersion"]
        }
        since = row.get("failingSince") or ""
        # Sorted, so every loop over them goes in the same order in every run.
        keys = sorted(
            {package_key(a) for a in [row["name"], *(row.get("attrs") or [])]}
        )
        found, causes = [], []
        for key in keys:
            for pr in touching.get(key, []):
                if in_failed(pr, broke_at):
                    causes.append(pr)
                elif (pr.get("merged") or "") >= since:
                    found.append(pr)
        if found:
            row["buildFixPR"] = entry(max(found, key=lambda p: p.get("merged") or ""))
        elif (
            kept := (before.get(row["name"]) or {}).get("buildFixPR") or old
        ) and not in_failed(kept, broke_at):
            row["buildFixPR"] = kept
        if causes:
            row["buildCausePR"] = entry(
                max(causes, key=lambda p: p.get("merged") or "")
            )
        elif broke_at and (
            kept := (before.get(row["name"]) or {}).get("buildCausePR") or old_cause
        ):
            row["buildCausePR"] = kept
