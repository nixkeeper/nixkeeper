"""What data/ must look like (docs/data.md), checked before it's written
(datastore.write, datastore.update): a row's fields and their types, and
the manifest's counts against the files they count. Three readers trust
the data as it is (the page, nixkeeper-mcp, the notifications): what
breaks it should stop here, said, rather than be published.

For now the problems are only reported (the sync's log); once syncs have
reported none, they're to stop the sync instead."""

import sys
import zlib

# A row's fields: the types each may have (None: it may be null), and
# whether every row has it. A field not here is a problem: a misspelt or
# new one, to add here and to docs/data.md.
ALWAYS, SOMETIMES = True, False
ROW = {
    # What it is
    "name": ((str,), ALWAYS),
    "attrs": ((list,), ALWAYS),
    "searchTerm": ((str,), ALWAYS),
    "lists": ((list,), ALWAYS),
    "project": ((str, None), SOMETIMES),
    "dataFile": ((str,), SOMETIMES),
    "platforms": ((dict, None), SOMETIMES),
    "homepage": ((str, None), SOMETIMES),
    "maintainers": ((list,), SOMETIMES),
    "nonTeamMaintainers": ((list,), SOMETIMES),
    "markedBroken": ((bool,), SOMETIMES),
    "markedInsecure": ((list,), SOMETIMES),
    "teams": ((list,), SOMETIMES),
    "teamsByList": ((list,), SOMETIMES),
    "set": ((str,), SOMETIMES),
    "branch": ((dict,), SOMETIMES),
    "lookupFailed": ((bool,), SOMETIMES),
    "unversioned": ((bool,), SOMETIMES),
    "unread": ((list,), SOMETIMES),
    "source": ((str,), SOMETIMES),
    "family": ((str,), SOMETIMES),
    "unfree": ((bool,), SOMETIMES),
    "devel": ((bool,), SOMETIMES),
    # Versions
    "nixStatus": ((str,), ALWAYS),
    # null for a list entry nixpkgs doesn't have (nixStatus "missing").
    "nixVersion": ((str, None), SOMETIMES),
    "refVersion": ((str, None), SOMETIMES),
    "refFromMaster": ((bool,), SOMETIMES),
    "refFromPR": ((bool,), SOMETIMES),
    "repoCount": ((int,), SOMETIMES),
    "repology": ((list,), SOMETIMES),
    "repologyCheckedAt": ((str,), SOMETIMES),
    "repologyVersion": ((str,), SOMETIMES),
    "repologySaid": ((dict,), SOMETIMES),
    "onlyNixpkgs": ((bool,), SOMETIMES),
    "staleSince": ((str,), SOMETIMES),
    "upstream": ((dict,), SOMETIMES),
    "feed": ((dict,), SOMETIMES),
    "upToDate": ((dict,), SOMETIMES),
    "keptBeside": ((dict,), SOMETIMES),
    "archived": ((bool,), SOMETIMES),
    "searchShowsMore": ((list,), SOMETIMES),
    "outdatedSince": ((str,), SOMETIMES),
    "nixVulnerable": ((bool,), SOMETIMES),
    "vulnerabilities": ((list,), SOMETIMES),
    "backport": ((list,), SOMETIMES),
    # Master, update PRs, GitHub
    "master": ((str,), SOMETIMES),
    "masterPR": ((dict,), SOMETIMES),
    "openPR": ((dict,), SOMETIMES),
    "otherPRs": ((list,), SOMETIMES),
    "dropPR": ((dict,), SOMETIMES),
    "stagingPR": ((dict,), SOMETIMES),
    "supersededPRs": ((list,), SOMETIMES),
    "fixPRs": ((list,), SOMETIMES),
    "openPRs": ((int,), SOMETIMES),
    "openIssues": ((int,), SOMETIMES),
    "countedAt": ((str,), SOMETIMES),
    "issueChecks": ((list,), SOMETIMES),
    # Builds
    "builds": ((list,), SOMETIMES),
    "neverBuiltOn": ((list,), SOMETIMES),
    "failingSince": ((str,), SOMETIMES),
    "buildFixPR": ((dict,), SOMETIMES),
    "buildCausePR": ((dict,), SOMETIMES),
    "stagingNextBreaks": ((dict,), SOMETIMES),
    "stagingNextBlockedBy": ((dict,), SOMETIMES),
    "stagingNextBlocks": ((dict,), SOMETIMES),
    # Updates (nixpkgs-update)
    "update": ((dict, None), SOMETIMES),
    "updateFailure": ((bool,), SOMETIMES),
    "updateFailingSince": ((str,), SOMETIMES),
    "queued": ((dict,), SOMETIMES),
    # Fixes, and sources not refreshed
    "recentFixes": ((list,), SOMETIMES),
    "notRefreshed": ((dict, list), SOMETIMES),
}

# Views whose length index.json's "views" says.
COUNTED_VIEWS = ("attention", "broken", "backport", "blocked", "unbuilt", "superseded")
# The rest of the manifest's counts that a view says too.
SAME_AS_VIEW = {"broken": "broken", "backport": "backport"}
# How many problems the log shows of each kind (the count is all of them).
SHOWN = 5


def _type_name(kinds):
    return " or ".join("null" if k is None else k.__name__ for k in kinds)


def row_problems(row):
    """What's wrong with one row's fields, as sentences."""
    found = []
    for field, (kinds, always) in ROW.items():
        if field not in row:
            if always:
                found.append(f"missing {field}")
            continue
        value = row[field]
        # bool is an int to isinstance: an int field holding true is wrong.
        if not any(value is None if k is None else type(value) is k for k in kinds):
            found.append(f"{field} is {type(value).__name__}, not {_type_name(kinds)}")
    found.extend(f"unknown field {field}" for field in row.keys() - ROW.keys())
    return found


def _listed_on(entry, system):
    """Whether nixpkgs lists entry for system (x86_64-linux), as docs/data.md
    has `platforms`: null for no restriction; its family's flag; and
    `systems`, when there, the family's systems it's on."""
    platforms = entry.get("platforms")
    if platforms is None:
        return True
    systems = platforms.get("systems")
    return bool(platforms.get(system.rsplit("-", 1)[-1])) and (
        systems is None or system in systems
    )


def _failing_on(entry, platform):
    """Whether entry's own build fails on platform (a system, or a family:
    on one of its systems), where nixpkgs lists it."""
    return any(
        b["status"] == "failed"
        and b["system"].endswith(platform)
        and _listed_on(entry, b["system"])
        for b in entry.get("builds") or []
    )


def problems(files, slug):
    """What's wrong with files ({path in data/: data}, datastore.files),
    by kind: {kind: [sentence]}. slug: a team's or list's name as its view's
    file name (datastore.slug)."""
    found = {}

    def say(kind, text):
        found.setdefault(kind, []).append(text)

    manifest = files["index.json"]
    count = manifest["shardCount"]
    names = set()
    for path, data in files.items():
        if not path.startswith("rows/"):
            continue
        shard = int(path[len("rows/") : -len(".json")])
        for row in data["packages"]:
            name = row.get("name")
            for text in row_problems(row):
                say("row fields", f"{name}: {text}")
            if name in names:
                say("rows", f"{name}: twice")
            names.add(name)
            if zlib.crc32(name.encode()) % count != shard:
                say("rows", f"{name}: in shard {shard}, not its own")
    shards = sum(path.startswith("rows/") for path in files)
    if shards != count:
        say("manifest", f"shardCount {count}, but {shards} shards")
    if manifest["packageCount"] != len(names):
        say("manifest", f"packageCount {manifest['packageCount']}, rows {len(names)}")
    if "views" in manifest:
        _views_problems(files, manifest, names, slug, say)
    return found


def _views_problems(files, manifest, names, slug, say):
    """With every package: the views' rows are rows, and the manifest says
    their lengths and what they count."""
    views = manifest["views"]

    def entries(path):
        # A view with no rows isn't written (views): its count then says 0.
        return files[path]["packages"] if path in files else []

    for path, data in files.items():
        if path.startswith("views/") and "packages" in data:
            for entry in data["packages"]:
                if entry["name"] not in names:
                    say("views", f"{path}: {entry['name']} isn't a row")
    for view in COUNTED_VIEWS:
        if view in views:
            n = len(entries(f"views/{view}.json"))
            if views[view] != n:
                say("manifest", f"views.{view} {views[view]}, its view {n}")
    for kind, key in (("team", "teams"), ("list", "lists"), ("set", "sets")):
        for name, said in (views.get(key) or {}).items():
            file = slug(name) if kind != "set" else name
            n = len(entries(f"views/{kind}/{file}.json"))
            said = said if isinstance(said, int) else said["packages"]
            if said != n:
                say("manifest", f"views.{key}.{name} {said}, its view {n}")
    counts = manifest["counts"]
    for count, view in SAME_AS_VIEW.items():
        if count in counts and view in views and counts[count] != views[view]:
            say(
                "manifest",
                f"counts.{count} {counts[count]}, views.{view} {views[view]}",
            )
    # The build failures, as the page counts them from the attention view:
    # an own build failed (on a platform: there, and listed for it).
    attention = entries("views/attention.json")
    failed = [
        e
        for e in attention
        if any(b["status"] == "failed" for b in e.get("builds") or [])
    ]
    if counts.get("buildFailures") not in (None, len(failed)):
        say(
            "manifest",
            f"counts.buildFailures {counts['buildFailures']}, the view's {len(failed)}",
        )
    for platform, said in (counts.get("buildFailuresOn") or {}).items():
        n = sum(_failing_on(e, platform) for e in failed)
        if said != n:
            say("manifest", f"counts.buildFailuresOn.{platform} {said}, the view's {n}")


def report(found, out=sys.stderr):
    """found (problems) in the log: how many of each kind, the first few.
    Nothing when there are none."""
    for kind, texts in found.items():
        print(f"Data shape: {len(texts):,} {kind} problems", file=out)
        for text in texts[:SHOWN]:
            print(f"  {text}", file=out)
        if len(texts) > SHOWN:
            print(f"  ... and {len(texts) - SHOWN:,} more", file=out)
