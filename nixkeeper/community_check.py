"""Check the community's rules for real: `nixkeeper community-check`.

The sync only reads and merges the community's rules (community.py). This
is the command that checks them: it runs the update checks against
nixpkgs' current versions (run), finds the ignore and up-to-date rules
that no longer do anything (stale_ignores, stale_up_to_date), reports
them (report), and keeps the community rules' status issue up to date
(publish).
"""

import json
import os
import re
import sys
from datetime import UTC, datetime

from . import community, rows, uptodate
from .datastore import data_file
from .errors import Problem
from .sources import github, nixpkgs_update, repology, upstream
from .sources import nixpkgs as nixpkgs_source


def run(names=None, file=None):
    """Run community update checks for real, as a sync would.

    That's `nixkeeper community-check`, against nixpkgs' current versions.

    Args:
        names: The rules to run; None for every one.
        file: Another update checks file.

    Returns:
        {name: (the version found or None, why not)}.
    """

    if names is not None and not names:
        return {}
    all_rules = community.rules(file)
    unknown = sorted(set(names or ()) - set(all_rules))
    chosen = {n: r for n, r in all_rules.items() if names is None or n in names}
    index = nixpkgs_source.load_index()
    results = {n: (None, "no community rule of that name") for n in unknown}
    rows = []
    for name in chosen:
        if name not in index:
            results[name] = (None, "not in nixpkgs' channel index")
            continue
        target = chosen[name].get("follows")
        if target is not None:
            # Nothing of its own to try: the package it follows has to exist.
            results[name] = (
                (index[target].get("version"), None)
                if target in index
                else (None, f"follows {target}, which isn't in nixpkgs' channel index")
            )
            continue
        version = index[name].get("version")
        rows.append({"name": name, "nixVersion": version, "refVersion": version})
    now = datetime.now(UTC).isoformat()
    upstream.add_checks(rows, chosen, {"packages": []}, now, set(chosen))
    for row in rows:
        failing = (row.get("notRefreshed") or {}).get("upstream")
        if failing:
            results[row["name"]] = (None, failing["reason"])
        else:
            results[row["name"]] = (row["upstream"]["version"], None)
    return results


def sort_names(names, file=None):
    """Sort package names given by hand by the community rules they have.

    A name can have both kinds.

    Args:
        names: The names.
        file: Another update checks file, as for run().

    Returns:
        (those with an update check, those with ignore or up-to-date rules,
        those with neither).
    """
    with_checks = set(community.rules(file))
    with_ignores = set(community.ignores()) | set(community.up_to_date())
    return (
        [n for n in names if n in with_checks],
        [n for n in names if n in with_ignores],
        [n for n in names if n not in with_checks and n not in with_ignores],
    )


def stale_up_to_date(names=None, file=None):
    """Find the community up-to-date rules that no longer do anything.

    That's when nixpkgs has moved on, or Repology now shows a newer version
    elsewhere (uptodate.why_not). A package Repology can't be reached for
    is left out, not called stale.

    Args:
        names: The rules to check; None for every one.
        file: Another up-to-date rules file.

    Returns:
        {name: (version, why)}.
    """

    chosen = {
        name: rule
        for name, rule in sorted(community.up_to_date(file).items())
        if names is None or name in names
    }
    if not chosen:
        return {}
    index = nixpkgs_source.load_index()
    found = {}
    for name, rule in chosen.items():
        version = rule.get("version")
        if name not in index:
            found[name] = (version, "not in nixpkgs' channel index")
            continue
        # As a sync that tracks it would see it.
        try:
            project, entries = repology.resolve(
                index[name].get("pname") or name, [name]
            )
        except (OSError, ValueError) as e:  # urllib's errors are OSErrors
            print(f"  {name}: couldn't reach Repology ({e})", file=sys.stderr)
            continue
        if not project:
            found[name] = (version, "Repology doesn't know this package")
            continue
        proj = {
            "name": name,
            "project": project,
            "attrs": [name],
            "entries": entries,
            "dataFile": data_file(project),
        }
        (row,) = rows.project_rows(proj, index)  # one attribute: one row
        if why := uptodate.why_not(row, rule):
            found[name] = (version, why)
    return found


def stale_ignores(names=None, file=None):
    """Find the community ignore rules that no longer do anything.

    That's when the bot's latest attempt isn't a failure at that version
    anymore (it moved on, or never tried), so the rule can go. A package
    whose log can't be read is left out, not called stale.

    Args:
        names: The rules to check; None for every one.
        file: Another ignore rules file.

    Returns:
        {name: [(version, why)]}.
    """

    found = {}
    for name, versions in sorted(community.ignores(file).items()):
        if names is not None and name not in names:
            continue
        try:
            attempt = nixpkgs_update.latest_attempt(name)
            if (
                attempt
                and attempt.get("from") == nixpkgs_update.UPDATE_SCRIPT
                and "was" not in attempt
                and (v := (nixpkgs_source.load_index().get(name) or {}).get("version"))
            ):
                attempt["was"] = v
        except OSError as e:  # urllib's errors are OSErrors
            print(
                f"  {name}: couldn't read the nixpkgs-update logs ({e})",
                file=sys.stderr,
            )
            continue
        for version in sorted(versions):
            if attempt is None:
                why = "the bot has never tried this package"
            elif not nixpkgs_update.at_version(attempt, version):
                at = attempt.get("to")
                if at == nixpkgs_update.UPDATE_SCRIPT_TO:
                    at = attempt.get("was")
                why = f"the bot's latest attempt is at {at or '?'}"
            elif attempt.get("outcome") != "failed":
                why = f"the bot's attempt at {version} didn't fail"
            else:
                continue
            found.setdefault(name, []).append((version, why))
    return found


def report(results, stale=None, stale_up_to_date=None):
    """Print the community checks' results, and add them to the job summary.

    That's run()'s, stale_ignores()' and stale_up_to_date()'s results, also
    written as a GitHub Actions job summary when there is one.

    Returns:
        How many update checks failed.
    """
    lines = ["| Package | Found | Problem |", "|---|---|---|"]
    failed = 0
    for name, (version, why) in sorted(results.items()):
        print(f"  {name}: {version or 'FAILED'}{f' ({why})' if why else ''}")
        lines.append(f"| {name} | {version or '–'} | {why or ''} |")
        failed += why is not None
    stale_lines = []
    for name, versions in sorted((stale or {}).items()):
        for version, why in versions:
            print(f"  ignore rule {name} {version}: can go ({why})")
            stale_lines.append(f"| {name} | {version} | {why} |")
    stale_up_lines = []
    for name, (version, why) in sorted((stale_up_to_date or {}).items()):
        print(f"  up-to-date rule {name} {version}: can go ({why})")
        stale_up_lines.append(f"| {name} | {version} | {why} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            if results:
                f.write("## Community update checks\n\n" + "\n".join(lines) + "\n\n")
            if stale_lines:
                f.write(
                    "## Community ignore rules that can go\n\n"
                    "| Package | Version | Why |\n|---|---|---|\n"
                    + "\n".join(stale_lines)
                    + "\n"
                )
            if stale_up_lines:
                f.write(
                    "## Community up-to-date rules that can go\n\n"
                    "| Package | Version | Why |\n|---|---|---|\n"
                    + "\n".join(stale_up_lines)
                    + "\n"
                )
    return failed


def changed(base_dir):
    """Return the rules added or changed since base_dir.

    base_dir is main's community/, for a pull request: only those rules are
    tried there, so a PR isn't failed by a rule it didn't touch.

    Returns:
        (update check names, ignore and up-to-date rule names).
    """

    def differ(name, current):
        """Return the names in current whose rule differs from base_dir's."""
        base_file = os.path.join(base_dir, name)
        base = community.rules(base_file) if os.path.exists(base_file) else {}
        return [n for n, rule in current.items() if base.get(n) != rule]

    ignored = differ(community.IGNORES, community.ignores()) + differ(
        community.UP_TO_DATE, community.up_to_date()
    )
    checks = differ(community.CHECKS, community.rules())
    return sorted(set(checks)), sorted(set(ignored))


# The community rules' own status issue: which update checks are broken, since
# when, and which ignore and up-to-date rules can go. Found by its label (the
# title is only used when it's opened).
ISSUE_LABEL = "nixkeeper-community-status"
ISSUE_TITLE = "Community rules status"
# The record of broken rules, kept in the issue's body between runs.
STATE = re.compile(r"<!-- nixkeeper-community-state (\{.*?\}) -->", re.S)


def track(results, previous, now):
    """Update the record of broken rules with a run's results.

    Returns:
        (the record, {name: {"since", "reason"}}; the names newly broken;
        the names that work again).
    """
    broken = {}
    for name, (_, why) in results.items():
        if why is not None:
            since = (previous.get(name) or {}).get("since") or now
            broken[name] = {"since": since, "reason": why}
    newly = sorted(set(broken) - set(previous))
    recovered = sorted(n for n in set(previous) - set(broken) if n in results)
    return broken, newly, recovered


def issue_body(results, broken, now, stale=None, stale_up_to_date=None):
    """Write the community rules' status issue's body.

    It lists the broken update checks and the ignore and up-to-date rules
    that can go, and ends with the record of broken rules, kept there for
    the next run.
    """
    total = len(results)
    lines = [
        "The community rules (`community/`), checked weekly by the "
        '"Community: update checks still work" workflow. Rewritten by each run.',
        "",
        "### Update checks",
        "",
    ]
    if broken:
        lines += [
            f"**{len(broken)} of {total} broken:**",
            "",
            "| Rule | Broken since | Why |",
            "|---|---|---|",
        ]
        lines += [
            f"| `{name}` | {info['since'][:10]} | {info['reason'].replace('|', '/')} |"
            for name, info in sorted(broken.items())
        ]
        lines += [
            "",
            "Fix or remove them in `community/update-checks.nix`; until then, each "
            'shows as "check failing" on that package\'s row for subscribers.',
        ]
    else:
        lines.append(f"**All {total} work.**")
    lines += ["", "### Ignore rules", ""]
    if stale:
        lines += [
            "**These no longer do anything** (the bot's latest attempt isn't a "
            "failure at that version anymore), so they can go from "
            "`community/ignored-updates.nix`:",
            "",
            "| Package | Version | Why |",
            "|---|---|---|",
        ]
        lines += [
            f"| `{name}` | {version} | {why} |"
            for name, versions in sorted(stale.items())
            for version, why in versions
        ]
    else:
        lines.append("**All still apply.**")

    lines += ["", "### Up-to-date rules", ""]
    if stale_up_to_date:
        lines += [
            "**These no longer do anything** (nixpkgs has moved on, or Repology "
            "now shows a newer version elsewhere), so they can go from "
            "`community/up-to-date.nix`:",
            "",
            "| Package | Version | Why |",
            "|---|---|---|",
        ]
        lines += [
            f"| `{name}` | {version} | {why} |"
            for name, (version, why) in sorted(stale_up_to_date.items())
        ]
    else:
        lines.append("**All still apply.**")

    record = json.dumps(broken, sort_keys=True)
    lines += ["", f"_Last run: {now[:16].replace('T', ' ')} UTC._", ""]
    lines.append(f"<!-- nixkeeper-community-state {record} -->")
    return "\n".join(lines)


def publish(results, stale=None, stale_up_to_date=None, now=None):
    """Update the community rules' status issue with a run's results.

    The issue is in NIXKEEPER_GITHUB_REPO, or the workflow's own
    repository; a comment is posted when a rule newly breaks or works
    again. It needs a token given explicitly, never the local gh login.

    Raises:
        Problem: There's no repository or no token.
    """

    now = now or datetime.now(UTC).isoformat()
    repo = os.environ.get("NIXKEEPER_GITHUB_REPO") or os.environ.get(
        "GITHUB_REPOSITORY"
    )
    token = github.token(use_gh=False)
    if not repo or not token:
        raise Problem(
            "--report-issue needs a repository (NIXKEEPER_GITHUB_REPO) and a token "
            "(NIXKEEPER_GITHUB_TOKEN_FILE or GITHUB_TOKEN)"
        )
    body = github.status_issue_body(repo, token, ISSUE_LABEL) or ""
    match = STATE.search(body)
    previous = json.loads(match.group(1)) if match else {}
    broken, newly, recovered = track(results, previous, now)
    comment = None
    if newly or recovered:
        comment = "\n".join(
            [f"**Broke:** `{n}`: {broken[n]['reason']}" for n in newly]
            + [f"**Works again:** `{n}`" for n in recovered]
        )
    number = github.update_status_issue(
        repo,
        token,
        ISSUE_TITLE,
        issue_body(results, broken, now, stale, stale_up_to_date),
        comment,
        label=ISSUE_LABEL,
        about="The community rules' status, kept up to date by nixkeeper",
    )
    print(f"Updated issue #{number}", file=sys.stderr)
