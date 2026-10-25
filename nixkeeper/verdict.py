"""Decide a row's verdict, nixStatus and refVersion, from what each source found.

Repology's verdict on the row comes first (rows.make_row, with its
corrections). The other sources each record what they found on the row
(the channel's version, a version feed, an up-to-date rule, an update
check, master's version, the update PRs), and then call decide, which works
the verdict out again from Repology's, through RULES in their order. So it
doesn't matter in which order the sources record, nor how often decide
runs: the sync and the hourly checks, which record only some of them,
reach the same verdict from the same findings.

Repology's own verdict is kept on the row as "repologyVerdict" while the
verdict differs from it; when they're the same, the verdict is Repology's.
Anything that writes nixStatus or refVersion other than through decide
must set Repology's verdict itself, as rows.make_row does, and as the
frequent check does after a fresh lookup (it removes "repologyVerdict").
"""

import dataclasses

from . import config
from .changes import ahead_on_master
from .shape import Row
from .versions import is_newer, version_key


@dataclasses.dataclass
class _Verdict:
    """The verdict as the rules work it out, and where its parts came from.

    Attributes:
        status: nixStatus.
        ref: refVersion: the version nixpkgs is compared with, or None.
        said: What Repology said, when an update check overruled it
            ("repologySaid"), else None.
        from_master: Whether ref is master's version ("refFromMaster").
        from_pr: Whether ref is an update PR's ("refFromPR").
    """

    status: str
    ref: str | None
    said: dict | None = None
    from_master: bool = False
    from_pr: bool = False


def decide(row: Row):
    """Work the row's verdict out again from Repology's, through RULES.

    Args:
        row: The row, changed in place: nixStatus, refVersion, and
            repologySaid, refFromMaster and refFromPR where they apply.
    """
    base = row.get("repologyVerdict") or _said(row["nixStatus"], row.get("refVersion"))
    verdict = _Verdict(base["status"], base.get("newest"))
    for rule in RULES:
        rule(row, verdict)
    row["nixStatus"] = verdict.status
    row["refVersion"] = verdict.ref
    _set(row, "repologySaid", verdict.said)
    _set(row, "refFromMaster", verdict.from_master or None)
    _set(row, "refFromPR", verdict.from_pr or None)
    differs = (verdict.status, verdict.ref) != (base["status"], base.get("newest"))
    _set(row, "repologyVerdict", base if differs else None)


def _said(status, ref):
    """Return a verdict as the row keeps it: {"status", "newest"?}."""
    return {"status": status, **({"newest": ref} if ref else {})}


def _set(row, field, value):
    """Set the row's field to value, or remove it when value is None."""
    if value is None:
        row.pop(field, None)
    else:
        row[field] = value


# The rules below each take the row (what the sources found) and the verdict
# so far, which they change. decide applies them in RULES' order, which
# matters: each reads the verdict the ones before it left.


def _channel(row, verdict):
    """Call it caught up when the channel has the version Repology is behind on.

    Repology reads nixos-unstable some hours after it moves, so the channel's
    version can be newer than Repology's (rows.channel_versions records it
    as nixVersion, keeping Repology's as repologyVersion). Outdated against
    a version the channel has reached: newest, or kept again for a kept
    series that caught up within its own series. Outdated without a
    refVersion (beads) is left as Repology says.
    """
    if (
        row.get("repologyVersion")
        and verdict.status == "outdated"
        and verdict.ref
        and not is_newer(verdict.ref, row.get("nixVersion") or "")
    ):
        verdict.status = config.KEPT if row.get("keptBeside") else "newest"


def _feed(row, verdict):
    """Compare with the set's own source, where it has one (sources/feeds.py).

    The feed's version is the one to compare with, instead of Repology's.
    A Typst package kept beside a newer one (typst_digest) is kept.
    """
    feed = row.get("feed")
    if not feed:
        return
    verdict.ref = feed["version"]
    if row.get("keptBeside"):
        verdict.status = config.KEPT
    elif version_key(feed["version"]) > version_key(row.get("nixVersion") or ""):
        verdict.status = "outdated"
    else:
        verdict.status = "newest"


def _up_to_date(row, verdict):
    """Call it newest when an up-to-date rule says so (uptodate.py)."""
    if row.get("upToDate"):
        verdict.status, verdict.ref = "newest", None


def _update_check(row, verdict):
    """Take an update check's result into account (upstream.apply records it).

    A newer version upstream is the one to compare with, unless the verdict
    already has an even newer one. A rule's check decides where it and the
    verdict disagree on whether nixpkgs is outdated, and what Repology said
    is kept beside it, for the page; a worked-out check, a result kept
    because the check failed this time, and a kept version don't decide.
    """
    found = row.get("upstream")
    if not found:
        return
    kept = verdict.status == config.KEPT or bool(row.get("keptBeside"))
    said = _said(verdict.status, verdict.ref)
    newer = found["newer"]
    if newer and not is_newer(verdict.ref or "", found["version"]):
        verdict.ref = found["version"]
    decides = "upstream" not in (row.get("notRefreshed") or {})
    if (
        decides
        and not found.get("inferred")
        and row.get("nixVersion")
        and not kept
        and newer != (verdict.status in config.OUTDATED_STATUSES)
    ):
        verdict.said = said
        verdict.status = "outdated" if newer else "newest"
        if not newer:
            # Nothing newer to update to (Repology's "newest elsewhere" was
            # older, or not newer by the check), as with an up-to-date rule.
            verdict.ref = None


def _master(row, verdict):
    """Take master's version when it's ahead of everything else known.

    Master can have a newer version than the channel (Hydra's builds say
    so: "master"). When it's newer than the version the verdict has, it's
    the one to update to; the row then reads as waiting for the channel.
    """
    if ahead_on_master(row) and (
        not verdict.ref or is_newer(row["master"], verdict.ref)
    ):
        verdict.ref = row["master"]
        verdict.from_master = True


def _update_prs(row, verdict):
    """Take the newest version the update PRs bring, when nothing names one.

    That's for a row Repology calls outdated without naming a newer version
    (its "-unclassified" projects: chatgpt 26.1007.21434, with every
    repository "outdated" too). The newest version an update PR of it
    brings, merged or open, is a release someone has packaged.
    """
    if verdict.status != "outdated" or verdict.ref:
        return
    mine = row.get("nixVersion") or ""
    versions = [
        pr["to"]
        for pr in (row.get("masterPR"), row.get("stagingPR"), row.get("openPR"))
        if pr and pr.get("to") and is_newer(pr["to"], mine)
    ]
    if versions:
        verdict.ref = max(versions, key=version_key)
        verdict.from_pr = True


# The rules decide applies, in this order.
RULES = (_channel, _feed, _up_to_date, _update_check, _master, _update_prs)
