"""Keep the status issues up to date.

The status issues are GitHub issues in this repository showing what needs
attention, rewritten every sync, plus a comment (which is what notifies)
when something changed for the worse. There's the instance's own
("nixkeeper status", everything on its lists; off with `statusIssue =
false;` in the lists), and one for each maintainer or team in
notifications/ ("nixkeeper status: @iedame"), with only their packages.
Only runs that set --notify or NIXKEEPER_NOTIFY post (the workflows do);
see notify() for the methods.
"""

import os
import re
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime

from . import config
from .changes import (
    COUNTED_VULNERABILITIES,
    NOTIFY,
    STALE_LABELS,
    broken_builds,
    build_label,
    diff,
    failed_builds,
    failures,
    is_outdated,
    is_vulnerable,
    on_master,
    should_notify,
    stale_sources,
    waiting_for_channel,
)
from .errors import Problem
from .sources import github
from .sources import nixpkgs as nixpkgs_source

# The instance's own status issue's title, and the start of the others'.
TITLE = "nixkeeper status"
# Between one subscriber's issue and the next: GitHub limits how fast
# content is created.
SUBSCRIBER_PAUSE = 1.0


def days_text(since, now):
    """Say how long ago `since` was: "today", "1 day" or "N days"."""
    days = (datetime.fromisoformat(now) - datetime.fromisoformat(since)).days
    return "today" if days < 1 else "1 day" if days == 1 else f"{days} days"


def cves_url(project):
    """Return Repology's list of CVEs for a project, with the versions they affect.

    Its API only says whether a version is vulnerable, not to what.
    """
    return f"https://repology.org/project/{urllib.parse.quote(project)}/cves"


def pr_number(pr):
    """Write a nixpkgs PR's number in code, never as a link.

    A link to the PR (or its address) puts "mentioned this pull request" on
    the nixpkgs PR each time the issue is rewritten; a bare #number would
    link this repository's issue of that number instead.
    """
    return f"`#{pr['number']}`"


# The most CVEs a package's line names in a status issue; the rest are
# counted.
VULNERABILITIES_SHOWN = 3
# A NixOS security tracker issue's page.
TRACKER_ISSUE_URL = "https://tracker.security.nixos.org/issues/"


def vulnerability(v):
    """Write one counted CVE or advisory as a status issue names it.

    That's its id in code, its severity, and the security tracker's issue
    as a link: the tracker's page, never the nixpkgs issue, as that link
    would add a "mentioned" line to it each time the issue is rewritten.
    """
    said = [v["severity"]] if v.get("severity") else []
    if v.get("issue"):
        said.append(
            f"[{v['issue']}]({TRACKER_ISSUE_URL}{urllib.parse.quote(v['issue'])})"
        )
    elif v["source"] == "osv":
        said.append("OSV")
    return f"`{v['id']}`" + (f" ({', '.join(said)})" if said else "")


def describe(row, now):
    """Describe one package, as a bullet's text.

    The line has its versions and how long it has been outdated, its update
    PRs, why it fails, its counted vulnerabilities, links to the logs of its
    failed builds and update attempt, where nixpkgs marks it broken, and
    which of its sources couldn't be refreshed.
    """
    text = f"`{row['name']}`"
    if is_outdated(row):
        text += f" {row['nixVersion']} → {row.get('refVersion') or '?'}"
        upstream = row.get("upstream") or {}
        if upstream.get("newer") and upstream["version"] == row.get("refVersion"):
            text += " (found by nixkeeper's update check)"
        if row.get("outdatedSince"):
            text += f" · outdated {days_text(row['outdatedSince'], now)}"
        if waiting_for_channel(row):
            text += f" · on master ({on_master(row)}), waiting for nixos-unstable"
            if pr := row.get("masterPR"):
                text += f" ({pr_number(pr)})"
        elif pr := row.get("openPR"):
            state = "draft PR" if pr["draft"] else "PR"
            text += f" · {state} {pr_number(pr)} open"
    if failures(row):
        text += " — " + ", ".join(failures(row))
    if counted := [
        v
        for v in row.get("vulnerabilities") or []
        if v["verdict"] in COUNTED_VULNERABILITIES
    ]:
        shown = ", ".join(vulnerability(v) for v in counted[:VULNERABILITIES_SHOWN])
        more = len(counted) - VULNERABILITIES_SHOWN
        text += f" — vulnerable: {shown}" + (f", and {more} more" if more > 0 else "")
    if row.get("markedInsecure"):
        text += " — marked insecure in nixpkgs"
    if row.get("nixVulnerable"):
        text += " — flagged vulnerable by Repology"
        if row.get("project"):
            text += f" ([known CVEs]({cves_url(row['project'])}))"
    logs = [
        f"[{build_label(row, b)} log]({config.HYDRA_URL}/build/{b['build']}/log)"
        for b in failed_builds(row)
    ]
    update = row.get("update")
    if row.get("updateFailure") and update:
        logs.append(f"[update log]({update['log']})")
    if logs:
        text += " · " + " · ".join(logs)
    broken = [build_label(row, b) for b in broken_builds(row)]
    if broken:
        text += " — marked broken in nixpkgs on " + ", ".join(broken)
    if row.get("staleSince"):
        text += (
            f" — {STALE_LABELS['repology']}, showing data from {row['staleSince'][:10]}"
        )
    for source, info in (row.get("notRefreshed") or {}).items():
        text += (
            f" — {STALE_LABELS[source]} since {info['since'][:10]}: {info['reason']}"
        )
    return text


def bullets(rows, now):
    """Write rows as a bulleted list, one describe() line each."""
    return "\n".join(f"- {describe(row, now)}" for row in rows)


# Each kind of change (changes.diff), as the issues name it.
CHANGE_LABELS = {
    "outdated": "Newly outdated",
    "failed": "Newly failed",
    "vulnerable": "Newly vulnerable",
    "notRefreshed": "Not refreshed",
    "refreshed": "Refreshed again",
    "caughtUp": "Caught up",
    "fixed": "No longer failing",
    "broken": "Marked broken in nixpkgs",
    "added": "Now tracked",
    "removed": "No longer tracked",
}


def change_lines(changes, kinds, now):
    """Write the changes of kinds as bullets, one per kind that has any.

    Removed packages are named; the others are described (describe).
    """
    lines = []
    for kind in kinds:
        items = changes[kind]
        if not items:
            continue
        names = ", ".join(
            f"`{i}`" if isinstance(i, str) else describe(i, now) for i in items
        )
        lines.append(f"- **{CHANGE_LABELS[kind]}:** {names}")
    return lines


def status_body(rows, changes, now, page_url=None):
    """Write a status issue's body.

    It has the current state (failed, outdated, vulnerable, broken, not
    refreshed), then everything that changed since the previous sync.

    Args:
        rows: The packages it covers.
        changes: changes.diff's result for them.
        now: The run's time.
        page_url: The page to link to, or None.
    """
    sections = [
        ("Failed", [r for r in rows if failures(r)]),
        (
            "Outdated",
            sorted(
                (r for r in rows if is_outdated(r)),
                key=lambda r: r.get("outdatedSince") or "~",
            ),
        ),
        ("Vulnerable", [r for r in rows if is_vulnerable(r)]),
        ("Marked broken in nixpkgs", [r for r in rows if broken_builds(r)]),
        ("Not refreshed", [r for r in rows if stale_sources(r)]),
    ]
    parts = [
        f"Checked {now[:16].replace('T', ' ')} UTC · {len(rows)} packages tracked"
        + (f" · [open the page]({page_url})" if page_url else "")
    ]
    if not any(items for _, items in sections):
        parts.append("Nothing needs attention.")
    for title, items in sections:
        if items:
            parts.append(f"### {title} ({len(items)})\n{bullets(items, now)}")
    changed = change_lines(changes, CHANGE_LABELS, now)
    parts.append(
        "### Since the previous sync\n"
        + ("\n".join(changed) if changed else "No changes.")
    )
    parts.append(
        "<sub>Updated by the daily sync. A comment is posted when something newly "
        "needs attention; close this issue to reset it (the next sync opens a new "
        "one).</sub>"
    )
    return "\n\n".join(parts)


def change_comment(changes, now):
    """Write the comment that notifies: the changes that need attention."""
    return "\n".join(
        [f"**Changes in the {now[:10]} sync**", "", *change_lines(changes, NOTIFY, now)]
    )


def page_url(repo=None):
    """Return where the page lives, for links, or None.

    That's NIXKEEPER_PAGE_URL (set by the workflows: the instance's own
    site, when it has one), else the GitHub Pages project site of
    owner/repo.
    """
    if os.environ.get("NIXKEEPER_PAGE_URL"):
        return os.environ["NIXKEEPER_PAGE_URL"]
    if not repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner}.github.io/{name}/"


# notifications/'s folders, and the field each file in them has.
FOLDERS = {"maintainers": "maintainer", "teams": "team"}


def read_subscribers(path=None):
    """Read who gets a status issue of their own, from notifications/.

    The folder is config.notifications_path() unless path is given;
    nix/notifications.nix checks its format. A file that doesn't make sense
    (or isn't in its kind's folder) is left out, and the log says so.

    Returns:
        {"maintainers/iedame": {"maintainer": handle}, "teams/gaming":
        {"team": name, "mention": [handles]}, ...}, or {} without the
        folder, or when it doesn't evaluate.
    """
    path = path or config.notifications_path()
    if not os.path.exists(path):
        print(
            f"No notifications/ at {path}: no status issues of their own.",
            file=sys.stderr,
        )
        return {}
    try:
        read = nixpkgs_source.read_lists(path)
    except Problem as e:  # didn't evaluate: the sync goes on without them
        print(f"::warning::notifications/ not read: {e}", file=sys.stderr)
        return {}
    found = {}
    for folder, kind in FOLDERS.items():
        for name, sub in sorted((read.get(folder) or {}).items()):
            mention = sub.get("mention", []) if isinstance(sub, dict) else None
            if (
                not isinstance(sub, dict)
                or not isinstance(sub.get(kind), str)
                or not sub[kind]
                or set(FOLDERS.values()) - {kind} & set(sub)
                or not isinstance(mention, list)
                or not all(isinstance(m, str) and m for m in mention)
            ):
                print(
                    f"::warning::notifications/{folder}/{name}.nix: needs {kind} "
                    "(and mention, a list of handles, if any): left out",
                    file=sys.stderr,
                )
                continue
            found[f"{folder}/{name}"] = sub
    return found


def read_lists():
    """Read the package lists, for their settings (statusIssue).

    Returns:
        The lists, or {} when they can't be read: that never stops a run.
    """
    try:
        return nixpkgs_source.read_lists()
    except Problem as e:
        print(f"::warning::package lists not read for notifying: {e}", file=sys.stderr)
        return {}


def subscriber_title(sub):
    """Return a subscriber's issue title.

    That's "nixkeeper status: @iedame" or "nixkeeper status: Gaming team": a
    handle and a team of the same name never share an issue.
    """
    if "maintainer" in sub:
        return f"{TITLE}: @{sub['maintainer']}"
    return f"{TITLE}: {sub['team']} team"


def mentions(sub):
    """Return the handles a subscriber's issue mentions, which subscribes them."""
    handles = [sub["maintainer"]] if "maintainer" in sub else []
    return [*handles, *sub.get("mention", [])]


def is_subscribed(sub, row):
    """Return whether row is one of sub's packages.

    It is when it lists the maintainer, or is under the team (meta.teams,
    or a list named after it). Packages in a set updated in bulk aren't, as
    in the page's counts.
    """
    if row.get("set"):
        return False
    if "maintainer" in sub:
        handle = sub["maintainer"].lower()
        return any(m.lower() == handle for m in row.get("maintainers") or [])
    team = sub["team"].lower()
    return any(t.lower() == team for t in row.get("teams") or [])


def subscriber_page(base, sub):
    """Return the page showing sub's packages (?maintainer= or ?team=), or None."""
    if not base:
        return None
    query = (
        {"maintainer": sub["maintainer"]}
        if "maintainer" in sub
        else {"team": sub["team"]}
    )
    return f"{base.rstrip('/')}/?{urllib.parse.urlencode(query)}"


def subscriber_body(sub, rows, changes, now, base):
    """Write a subscriber's issue body: whose packages, then their status."""
    who = (
        f"@{sub['maintainer']}'s packages"
        if "maintainer" in sub
        else f"The {sub['team']} team's packages"
        + (
            f" · for {' '.join(f'@{m}' for m in sub.get('mention', []))}"
            if sub.get("mention")
            else ""
        )
    )
    return (
        f"{who}, as [nixkeeper]({base or 'https://github.com/nixkeeper/nixkeeper'}) "
        "sees them.\n\n"
        + status_body(rows, changes, now, subscriber_page(base, sub))
        + "\n\n<sub>From notifications/ in this repository: removing the file "
        "closes this issue.</sub>"
    )


def subscriber_issues(
    repo, token, subscribers, previous, everyone, now, news_only=False
):
    """Write each subscriber's issue, with only their packages.

    The issues whose file in notifications/ is gone are closed.

    Args:
        repo: The repository, owner/name.
        token: The GitHub token.
        subscribers: read_subscribers' result.
        previous: The last run's data, for the changes.
        everyone: Every row, among which each subscriber's packages are.
        now: The run's time.
        news_only: For the hourly checks: only the issues of those whose
            packages newly need attention are written, and none is closed,
            as the daily sync rewrites them all.
    """
    github.ensure_label(
        repo,
        token,
        github.SUBSCRIBER_LABEL,
        "A maintainer's or team's status issue (notifications/)",
    )
    issues = github.open_issues(repo, token, github.SUBSCRIBER_LABEL)
    base = page_url(repo)
    wanted = set()
    for sub in subscribers.values():
        title = subscriber_title(sub)
        wanted.add(title)
        rows = [r for r in everyone if is_subscribed(sub, r)]
        before = {
            **previous,
            "packages": [r for r in previous["packages"] if is_subscribed(sub, r)],
        }
        changes = diff(before, rows)
        news = should_notify(changes)
        if news_only and not news:
            continue
        comment = change_comment(changes, now) if news else None
        number = github.write_issue(
            repo,
            token,
            issues.get(title),
            title,
            subscriber_body(sub, rows, changes, now, base),
            github.SUBSCRIBER_LABEL,
            comment,
        )
        print(
            f"Updated {title!r} (#{number}, {len(rows)} packages)"
            + (" and commented" if comment else ""),
            file=sys.stderr,
        )
        time.sleep(SUBSCRIBER_PAUSE)
    for title, number in sorted(issues.items()):
        if news_only:
            break
        if re.match(re.escape(TITLE) + ": ", title) and title not in wanted:
            github.close_issue(
                repo,
                token,
                number,
                "Its file in notifications/ is gone: no longer updated.",
            )
            print(f"Closed {title!r} (#{number}): no file for it", file=sys.stderr)


def github_issue(
    rows,
    changes,
    now,
    previous=None,
    everyone=None,
    lists=None,
    subscribers=None,
    news_only=False,
):
    """Write the status issues in NIXKEEPER_GITHUB_REPO.

    In a workflow, that's the workflow's own repository. The instance's own
    issue is for rows, unless the lists turn it off (it's closed then); the
    subscribers' (notifications/) each have their packages among everyone.
    It needs a token given explicitly: the local gh login is never used to
    post.

    Args:
        rows: The instance's own rows.
        changes: changes.diff's result for them.
        now: The run's time.
        previous: The last run's data, for the subscribers' changes.
        everyone: Every row, for the subscribers' issues (rows by default).
        lists: The package lists, for statusIssue.
        subscribers: read_subscribers' result.
        news_only: As subscriber_issues takes it.
    """
    repo = os.environ.get("NIXKEEPER_GITHUB_REPO") or os.environ.get(
        "GITHUB_REPOSITORY"
    )
    token = github.token(use_gh=False)
    if not repo or not token:
        print(
            "::warning::github-issue notifications need a repository "
            "(NIXKEEPER_GITHUB_REPO) and a token (NIXKEEPER_GITHUB_TOKEN_FILE or "
            "GITHUB_TOKEN)",
            file=sys.stderr,
        )
        return
    if (lists or {}).get("statusIssue", True) is False:
        for number in github.open_issues(repo, token, github.STATUS_LABEL).values():
            github.close_issue(
                repo,
                token,
                number,
                "Turned off (`statusIssue = false;` in the package lists): no "
                "longer updated. Status issues of their own are in "
                "notifications/.",
            )
            print(f"Closed the status issue #{number}: turned off", file=sys.stderr)
    else:
        comment = change_comment(changes, now) if should_notify(changes) else None
        number = github.update_status_issue(
            repo, token, TITLE, status_body(rows, changes, now, page_url(repo)), comment
        )
        print(
            f"Updated status issue #{number}" + (" and commented" if comment else ""),
            file=sys.stderr,
        )
    if subscribers:
        subscriber_issues(
            repo, token, subscribers, previous, everyone or rows, now, news_only
        )


# How to notify, by NIXKEEPER_NOTIFY. Another way (ntfy, email, ...) is a
# function taking (rows, changes, now, **context), added here.
SENDERS = {"github-issue": github_issue}
# Earlier name for github-issue, still accepted.
ALIASES = {"1": "github-issue"}


def notify(
    previous,
    rows,
    now,
    everyone=None,
    everyone_before=None,
    lists=None,
    news_only=False,
):
    """Send what changed the way NIXKEEPER_NOTIFY says.

    Unset or "none" means not at all, as in local runs. It never fails the
    sync: a problem here is reported as a workflow warning.

    Args:
        previous: The last run's data.
        rows: The instance's own rows (its lists').
        now: The run's time.
        everyone: Every row, for the subscribers' issues (with every
            package: all of nixpkgs).
        everyone_before: The last run's data with every row, for the
            subscribers' changes.
        lists: The package lists, for statusIssue. They're read here when
            not given, as by the hourly checks: without them, a turned-off
            status issue came back.
        news_only: For the hourly checks: subscribers' issues only where
            their packages newly need attention.
    """
    method = config.NOTIFY or os.environ.get("NIXKEEPER_NOTIFY") or "none"
    method = ALIASES.get(method, method)
    if method == "none":
        print(
            "Not notifying (notify: none; the GitHub workflows use github-issue).",
            file=sys.stderr,
        )
        return
    if method not in SENDERS:
        print(
            f"::warning::{method} isn't a notification method "
            f"({', '.join(['none', *SENDERS])})",
            file=sys.stderr,
        )
        return
    try:
        if lists is None:
            lists = read_lists()
        subscribers = read_subscribers() if config.subscribers() else {}
        SENDERS[method](
            rows,
            diff(previous, rows),
            now,
            previous=everyone_before or previous,
            everyone=everyone or rows,
            lists=lists,
            subscribers=subscribers,
            news_only=news_only,
        )
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"::warning::Couldn't notify ({method}): {e}", file=sys.stderr)
