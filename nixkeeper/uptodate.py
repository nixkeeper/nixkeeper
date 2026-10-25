"""Apply the up-to-date rules: versions Repology gets wrong.

The rules (package-lists/up-to-date.nix, and the community's
community/up-to-date.nix) each name a version nixpkgs has that Repology
gets wrong (calls it untrusted, incorrect or ignored, or compares it with a
version that isn't really newer), so the row should count as up to date:

    pacvim = {
      version = "2018-05-16";  # nixpkgs' version the rule is about
      newest = "1.1.1";        # what Repology shows as newest elsewhere
      reason = "A snapshot from after the 1.1.1 release.";
    };

A rule applies while nixpkgs has that version and Repology knows of
nothing newer than `newest` elsewhere (leave `newest` out when it shows
none). A real new release, or nixpkgs moving on, ends it, and the sync (or,
for the community's, community-check) says it can go. While it applies, the
row has nixStatus "newest", no refVersion, and `upToDate` with what
Repology said.

Only Repology's verdict is overridden: nixkeeper's update checks and master
still count, as they come after. The exception is a worked-out check (one
nobody wrote) that finds the very version `newest` names: it isn't a real
release there either. So a wrong worked-out result is silenced with a rule
naming it, as a wrong Repology verdict is.
"""

import sys

from . import verdict
from .shape import Row
from .versions import is_newer

# The fields an up-to-date rule can have.
FIELDS = {"version", "newest", "reason"}


def why_not(row: Row, rule):
    """Return why rule no longer applies to row, or None if it still does.

    The row is taken as Repology has it, before any rule.
    """
    version = row.get("nixVersion")
    if version != rule.get("version"):
        return f"nixpkgs is now at {version or '?'}"
    ref, newest = row.get("refVersion"), rule.get("newest")
    if ref and (not newest or is_newer(ref, newest)):
        return f"Repology now shows {ref} as newest elsewhere"
    return None


def apply(rows: list[Row], rules, community=frozenset()):
    """Mark the rows the rules apply to as up to date.

    A rule of your own that no longer applies gets a notice saying it can
    go; the community's are community-check's to report.

    Args:
        rows: The rows, changed in place.
        rules: {name: rule}, your own and the community's.
        community: The names of the community's rules.

    Returns:
        The names of the rows it marked.
    """
    by_name = {row["name"]: row for row in rows}
    marked = []
    for name, rule in sorted(rules.items()):
        row = by_name.get(name)
        if row is None:  # not tracked: listcheck reports your own
            continue
        if why := why_not(row, rule):
            if name not in community:
                print(
                    f"::notice::upToDate.{name}: {why}; the rule can go",
                    file=sys.stderr,
                )
            continue
        found = {"status": row.get("nixStatus"), "reason": rule.get("reason")}
        if row.get("refVersion"):
            found["newest"] = row["refVersion"]
        if rule.get("newest"):
            # The version the rule says isn't a real release: a worked-out
            # update check finding it is silenced too (upstream.apply).
            found["ruleNewest"] = rule["newest"]
        if name in community:
            found["community"] = True
        row["upToDate"] = found
        verdict.decide(row)  # newest (verdict._up_to_date)
        marked.append(name)
    return marked
