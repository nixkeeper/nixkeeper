"""Work out update checks from nixpkgs itself.

A package fetched from a GitHub tag (fetchFromGitHub, a release download)
is checked against that repository's tags, with the tag scheme its own tag
shows ("v" + version, ...). These checks run with the other update checks
(upstream.py), for packages without a rule of their own or the
community's (which win), unless the lists turn them off
(`workedOutChecks = false;`). Each daily sync also logs how they compare
with Repology, and with the packages' rules.
"""

import collections
import re

from . import config, log
from .sources import github, upstream
from .sources import nixpkgs as nixpkgs_source
from .versions import is_newer

# A GitHub repository's URL: its owner and name.
GITHUB = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)")
# A full commit hash.
COMMIT = re.compile(r"^[0-9a-f]{40}$")
# A release download's tag, in its URL.
RELEASE = re.compile(r"/releases/download/([^/]+)/")
# A source archive's tag, in its URL.
ARCHIVE = re.compile(r"/archive/(?:refs/tags/)?(.+?)\.(?:tar\.gz|zip)$")
# Versions made of numbers only (1.19.28, 2024.05, 7_2): the tags a check
# worked out this way looks for. Others (betas, unstable versions) are left
# to Repology for now.
PLAIN = re.compile(r"[0-9]+(?:[._-][0-9]+)*")
# A versioned attribute, kept for one series of its program: its name ends in
# that series' numbers (tracy_0_11, gcc13, python313).
SUFFIX = re.compile(r"(?<![0-9])([0-9]+(?:_[0-9]+)*)$")


def series(attr, version):
    """Return the series a versioned attribute keeps, or None.

    The series is the start of its version: the digits the attribute's
    name ends in are the version's first parts, with underscores between
    them or run together, short of the whole version. tracy_0_11 with
    0.11.1 keeps "0.11"; python313 with 3.13.7 keeps "3.13".
    """
    m = SUFFIX.search(attr or "")
    if not m:
        return None
    parts = re.split(r"[._-]", version)
    for k in range(1, len(parts)):
        if m.group(1) in ("_".join(parts[:k]), "".join(parts[:k])):
            # The version's text up to the end of its k-th part (separators
            # are one character each).
            return version[: sum(map(len, parts[:k])) + k - 1]
    return None


def tag_of(src):
    """Return the tag (or commit) src was fetched from, or None."""
    if src.get("tag"):
        return src["tag"]
    rev = src.get("rev") or ""
    if rev.startswith("refs/tags/"):
        return rev.removeprefix("refs/tags/")
    url = src.get("url") or ""
    if m := RELEASE.search(url) or ARCHIVE.search(url):
        return m.group(1)
    return rev or None


def github_check(src, attr=None):
    """Work out the GitHub tags check src's package would have.

    The tags it takes look like nixpkgs' version: the same prefix and
    separators, and, for a version with separators (1.2.3), at least one
    (not 20240214, a date). For a versioned attribute (series), only that
    series' tags count.

    Args:
        src: The package's source, as nixpkgs evaluates it.
        attr: The package's attribute.

    Returns:
        (check, None), the check as an update check ({"github", "tags"});
        or (None, why not).
    """
    m = GITHUB.match(src.get("gitRepoUrl") or "") or GITHUB.match(src.get("url") or "")
    if not m:
        return None, "not from GitHub"
    version, tag = src.get("version") or "", tag_of(src)
    if not tag:
        return None, "no tag"
    if COMMIT.match(tag):
        return None, "a commit (unstable version)"
    if not PLAIN.fullmatch(version):
        return None, "not a plain version"
    if not tag.endswith(version):
        return None, "tag doesn't end with the version"
    # The separators the version uses (dots, as a rule), so 1.2.3 doesn't
    # match 1_2_3-style tags of another scheme.
    seps = "".join(sorted(set(re.sub("[0-9]", "", version))))
    if not seps:  # a single number (4065): a single number, or more parts
        number = r"[0-9]+(?:[.][0-9]+)*"
    elif kept := series(attr, version):
        number = f"{re.escape(kept)}(?:[{re.escape(seps)}][0-9]+)+"
    else:
        number = f"[0-9]+(?:[{re.escape(seps)}][0-9]+)+"
    prefix = re.escape(tag.removesuffix(version))
    return {
        "github": f"{m.group(1)}/{m.group(2)}",
        "tags": f"^{prefix}({number})$",
    }, None


def for_row(row, sources):
    """Work out a row's check from the first of its attributes that gives one.

    Returns:
        (check, None), or (None, why not) from the first attribute that has
        a source.
    """
    why = "no source"
    for attr in row.get("attrs") or [row["name"]]:
        if attr not in sources:
            continue
        check, reason = github_check(sources[attr], attr)
        if check:
            return check, None
        if why == "no source":
            why = reason
    return None, why


def verdict(row, version, rule):
    """Compare a worked-out check's version with what the sync has.

    It's compared with Repology, or, when the row has an update check of
    its own (rule), with that rule's result. Where those differ, the rule
    is what the row uses (a series the worked-out check can't tell, for
    example), so that's no disagreement.

    Returns:
        ("agree", "disagree" or "rule differs", what to say).
    """
    nix = row.get("nixVersion")
    if rule:
        theirs = (row.get("upstream") or {}).get("version")
        if theirs is None or theirs == version:
            return "agree", f"{version}, as its rule"
        return "rule differs", f"{version}, its rule {theirs}"
    by_github = is_newer(version, nix)
    by_repology = row.get("nixStatus") in config.OUTDATED_STATUSES
    ref = row.get("refVersion")
    if not by_github and not by_repology:
        return "agree", "up to date"
    if by_github and by_repology:
        if ref == version:
            return "agree", f"outdated, {version}"
        return "disagree", f"both outdated: GitHub {version}, Repology {ref}"
    if by_github:
        return "disagree", f"GitHub {version}, Repology up to date"
    return "disagree", f"Repology {ref}, GitHub {version}"


def enabled(lists):
    """Return whether the lists use worked-out checks.

    They do unless they turn them off with `workedOutChecks = false;`.
    """
    return (lists or {}).get("workedOutChecks") is not False


class WorkedOut:
    """The checks worked out for a sync's rows.

    Attributes:
        checks: {name: check}.
        not_worked: Why the rest have none, as a Counter.
        repology: Each row's newest version by Repology before the update
            checks change it ({name: refVersion}), to compare with.
    """

    def __init__(self, checks, not_worked, repology):
        """Hold the checks, the reasons for the rest, and Repology's versions."""
        self.checks, self.not_worked, self.repology = checks, not_worked, repology

    def to_run(self, rules):
        """Return the worked-out checks of packages without a rule."""
        return {n: c for n, c in self.checks.items() if n not in rules}


def work_out(lists, rows, rules, revision):
    """Work out the update checks for rows.

    Args:
        lists: The package lists.
        rows: The rows.
        rules: The update checks the lists and the community give.
        revision: The nixpkgs revision to evaluate the sources at.

    Returns:
        A WorkedOut, or None when the checks are turned off, or (with the
        reason in the log) there's no GitHub token to run them with, or
        nixpkgs didn't evaluate.
    """
    if not enabled(lists):
        return None
    if not github.token():
        log.info("Worked-out update checks: skipped (no GITHUB_TOKEN)")
        return None
    rows = [row for row in rows if row.get("nixVersion")]
    try:
        attrs = {a for row in rows for a in row.get("attrs") or [row["name"]]}
        sources = nixpkgs_source.sources(attrs, revision)
    except nixpkgs_source.EvalError as e:
        log.info(f"Worked-out update checks: skipped ({e})")
        return None
    checks, not_worked = {}, collections.Counter()
    for row in rows:
        if "follows" in rules.get(row["name"], {}):
            continue
        check, why = for_row(row, sources)
        if check:
            checks[row["name"]] = check
        else:
            not_worked[why] += 1
    repology = {row["name"]: row.get("refVersion") for row in rows}
    return WorkedOut(checks, not_worked, repology)


def report(worked, rows, rules, failed):
    """Log how the worked-out checks compare, in a log group of the sync's output.

    The checks that ran are read from their rows (after
    upstream.add_checks) and compared with Repology. Those of packages with
    a rule are run here, only for this, and compared with the rule's
    result.

    Args:
        worked: work_out's result.
        rows: The rows.
        rules: The update checks the lists and the community give.
        failed: add_checks' {name: why} for the worked-out checks that
            couldn't run.
    """
    by_name = {row["name"]: row for row in rows}
    failed, found = dict(failed), {}
    for name in worked.to_run(rules):
        up = by_name[name].get("upstream") or {}
        if up.get("inferred"):
            found[name] = up["version"]

    def keep_previous(name, why):
        """Note that name's check couldn't run."""
        failed[name] = why

    def add(name, version, where, what, **_):
        """Note a check's version for name, or that nothing matched in where."""
        if version is None:
            failed[name] = f"nothing in {where} matches {what}"
        else:
            found[name] = version

    ruled = {n: c for n, c in worked.checks.items() if n in rules}
    if ruled:
        # The same requests as the tags checks: GITHUB_REPOS_BATCH
        # repositories each.
        upstream.check_tags(github.token(), ruled, keep_previous, add)
    lines = collections.defaultdict(list)
    for name in sorted(found):
        # Repology's view as it was before the update checks.
        row = {**by_name[name], "refVersion": worked.repology.get(name)}
        kind, what = verdict(row, found[name], name in rules)
        lines[kind].append(
            f"  {name} {row['nixVersion']}: {what}  ({worked.checks[name]['github']})"
        )
    agree, disagree = len(lines["agree"]), len(lines["disagree"])
    differ = len(lines["rule differs"])
    used = len(worked.to_run(rules))
    title = (
        f"Worked-out update checks: {len(worked.checks)} of "
        f"{len(worked.repology)} packages ({used} used, {len(ruled)} with a "
        f"rule), {agree} agree with Repology or their rule, {disagree} don't, "
        f"{differ} differ from their rule (the rule is used), {len(failed)} failed"
    )
    with log.group(title):
        log.info(
            "Not worked out: "
            + ", ".join(f"{n} {why}" for why, n in worked.not_worked.most_common())
        )
        for heading, kind in (
            ("Disagree", "disagree"),
            ("Rule differs (the rule is used)", "rule differs"),
            ("Agree", "agree"),
        ):
            log.info("\n".join([f"{heading}:", *lines[kind]]))
        log.info("Failed (left to Repology):")
        for name in sorted(failed):
            log.info(f"  {name}: {failed[name]}")
