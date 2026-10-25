"""Find the outdated packages' update PRs, hourly.

For every outdated package, the PR check finds the update PR that's open
(to review) and the one merged into master (waiting for the channel), so
those badges don't wait for the sync. A merged PR shows "on master" as soon
as it's found, before Hydra has built it. It changes rarely: only when an
update PR opens, becomes ready or is merged. Run it with `nixkeeper
pr-check`, or `nix run .#pr-check` from a checkout.

It reads nixkeeper-prs' digest (prs_digest), made hourly: every outdated
package's update PRs in one download, with no token and no search. The
digest's lists are up to an hour old, so the packages of the lists'
maintainers (the "maintained" list) are still searched for directly, for
the freshest "on master". The other lists' and teams' packages (and, with
every package, the rest of nixpkgs) only go through the digest, so those
lists can grow without the searches growing. Without a usable digest,
they're searched per package, as before (with every package, the lists'
own only).
"""

from datetime import UTC, datetime

from . import follows, log, partial, verdict
from .changes import is_outdated
from .sources import github, github_bulk, nixpkgs, nixpkgs_update, prs_digest
from .tracking import MAINTAINED


def searched_directly(row):
    """Return whether row's update PRs are also searched for directly.

    That's for the packages of the lists' maintainers, beside the digest.
    """
    return MAINTAINED in (row.get("lists") or [])


def from_digest(rows, digest, revision, now):
    """Give rows their update PRs from the digest.

    Each row gets its open update PR ("openPR") from the digest's open PRs,
    and its update PR merged into master ("masterPR") from its merged ones
    when it has them; otherwise the rows keep theirs.

    Returns:
        Whether the digest had open PRs to use.
    """
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
    """Run the PR check, and publish what changed."""
    now = datetime.now(UTC).isoformat()
    loaded = partial.load()
    if loaded is None:
        return  # waiting for a full sync (partial.load says so)
    previous, packages = loaded
    outdated = [row for row in packages if is_outdated(row)]
    if not outdated:
        log.info("Nothing outdated: no update PRs to look for.")
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
        log.info(
            f"PR check: {len(outdated):,} outdated packages from the PRs digest, "
            f"{len(direct)} searched directly too"
        )
    else:
        # With every package, the lists' own: searched per package, the rest
        # of nixpkgs' update PRs wait for the sync.
        direct = [
            row
            for row in outdated
            if row.get("lists") or not previous.get("allPackages")
        ]
        log.info(f"PR check: {', '.join(row['name'] for row in direct)}")
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
    # Outdated with no newer version named: the newest its update PRs bring
    # (verdict._update_prs).
    for row in outdated:
        verdict.decide(row)
    # A merged PR can supersede a failed bot attempt before Hydra builds it.
    nixpkgs_update.recheck_superseded(outdated)
    partial.publish(previous, packages, now)


if __name__ == "__main__":
    main()
