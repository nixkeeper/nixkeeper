"""The PR check: for every outdated package, the update PR that's open (to
review) and the one merged into master (waiting for the channel), hourly, so
those badges don't wait for the sync. A merged PR shows "on master" as soon
as it's found, before Hydra has built it. Changes rarely: only when an update
PR opens, becomes ready or is merged. `nixkeeper pr-check`; from a checkout,
`nix run .#pr-check`.

From nixkeeper-prs' digest (prs_digest), made hourly: every outdated
package's update PRs in one download, no token, no search. Its lists are up
to an hour old, so the packages of the lists' maintainers (the "maintained"
list) are still searched for directly, for the freshest "on master"; the
other lists' and teams' (and, with every package, the rest of nixpkgs) only
through the digest, so those lists can grow without the searches growing.
Without a usable digest, as before: searched per package (with every
package, the lists' own only)."""

import sys
from datetime import UTC, datetime

from . import follows, partial
from .changes import count_prs, is_outdated
from .sources import github, github_bulk, nixpkgs, nixpkgs_update, prs_digest
from .tracking import MAINTAINED


def searched_directly(row):
    """Whether row's update PRs are searched for directly, beside the digest:
    a package of the lists' maintainers."""
    return MAINTAINED in (row.get("lists") or [])


def from_digest(rows, digest, revision, now):
    """Give rows their open update PR ("openPR") from the digest's open PRs,
    and their update PR merged into master ("masterPR") from its merged ones
    when it has them (else they keep theirs). Returns whether it did."""
    if not digest or not digest.get("open"):
        return False
    listing = github_bulk.Listing(*digest["open"])
    for row in rows:
        row.pop("openPR", None)
        if pr := listing.open_update_pr(row):
            row["openPR"] = pr
    if digest.get("merged") is not None:
        github_bulk.add_master_prs(rows, revision, now, digest["merged"])
    return True


def main():
    now = datetime.now(UTC).isoformat()
    previous, packages = partial.load()
    outdated = [row for row in packages if is_outdated(row)]
    if not outdated:
        print("Nothing outdated: no update PRs to look for.", file=sys.stderr)
        return
    revision = nixpkgs.channel_revision()
    digest = prs_digest.load(now, revision) or {}
    # What the last sync took from the digest about each update PR: kept
    # while the same PR is found (the digest's own replace them below).
    facts = {
        row["name"]: row["openPR"]
        for row in outdated
        if (row.get("openPR") or {}).get("facts")
    }
    if from_digest(outdated, digest, revision, now):
        direct = [row for row in outdated if searched_directly(row)]
        print(
            f"PR check: {len(outdated):,} outdated packages from the PRs digest, "
            f"{len(direct)} searched directly too",
            file=sys.stderr,
        )
    else:
        # With every package, the lists' own: searched per package, the rest
        # of nixpkgs' update PRs wait for the sync.
        direct = [
            row
            for row in outdated
            if row.get("lists") or not previous.get("allPackages")
        ]
        print(f"PR check: {', '.join(row['name'] for row in direct)}", file=sys.stderr)
    if direct:
        # Who opened and merged each update PR, from the digest: the search
        # doesn't say (a fix's credit, history.fixes).
        who = {
            row["name"]: row["masterPR"]
            for row in direct
            if (row.get("masterPR") or {}).get("mergedBy")
        }
        # Merged PRs since the channel's commit only: those it doesn't have yet.
        since = github_bulk.merged_since(revision)
        github.add_update_prs(direct, merged_since=since)
        for row in direct:
            pr, theirs = row.get("masterPR"), who.get(row["name"])
            if pr and theirs and pr["number"] == theirs["number"]:
                pr.update(
                    {k: theirs[k] for k in ("author", "mergedBy") if theirs.get(k)}
                )
    # On staging or staging-next: when the digest's list is current (else the
    # sync's are kept).
    if digest.get("staging") is not None:
        prs_digest.add_staging_prs(outdated, digest["staging"])
    if digest.get("facts"):
        prs_digest.add_facts(outdated, digest)
        # add_facts replaces the PR facts and issue checks: behind,
        # vulnerable and the CVE issues again.
        prs_digest.cross_check(outdated)
        if digest.get("open"):
            prs_digest.add_cve_issues(outdated, digest["open"][1])
    else:
        for row in outdated:
            pr, before = row.get("openPR"), facts.get(row["name"])
            if pr and before and pr["number"] == before["number"]:
                pr["facts"] = before["facts"]
    # Packages that follow another (follows.py): the same PRs, as its own.
    follows.apply_prs(packages, follows.recorded(packages))
    # Outdated with no newer version named: the newest its update PRs bring.
    for row in outdated:
        count_prs(row)
    # A merged PR can supersede a failed bot attempt before Hydra builds it.
    nixpkgs_update.recheck_superseded(outdated)
    partial.publish(previous, packages, now)


if __name__ == "__main__":
    main()
