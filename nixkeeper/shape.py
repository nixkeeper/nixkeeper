"""Check that the data matches what docs/data.md describes, before it's written.

The page, nixkeeper-mcp and the notifications all read the data as it is,
so a mistake in it (a misspelt field, a count that disagrees with the list
it counts) reaches every reader. `problems` finds such mistakes and
`report` writes them to the log. `datastore.write` and `datastore.update`
run both before writing anything.

For now the problems are only reported. Once several syncs have reported
none, they are meant to stop the sync instead, so that the last good data
stays published.

The check never raises on bad data: finding bad data is its job, so every
lookup expects the data to be malformed and reports what it finds instead.
"""

import re
import sys
import zlib
from typing import NamedTuple

NULL = type(None)


class Field(NamedTuple):
    """What a row's field may hold.

    Attributes:
        types: The types its value may have. NULL means it may be null.
        required: Whether every row has the field.
    """

    types: tuple
    required: bool = False


# Every field a row may have. A field not listed here is reported as
# unknown: either a typo, or a new field to add here and to docs/data.md
# (a test checks that every field here is named in docs/data.md).
ROW = {
    # What the package is.
    "name": Field((str,), required=True),
    "attrs": Field((list,), required=True),
    "searchTerm": Field((str,), required=True),
    "lists": Field((list,), required=True),
    "project": Field((str, NULL)),
    "dataFile": Field((str,)),
    "platforms": Field((dict, NULL)),
    "homepage": Field((str, NULL)),
    "maintainers": Field((list,)),
    "nonTeamMaintainers": Field((list,)),
    "markedBroken": Field((bool,)),
    "markedInsecure": Field((list,)),
    "teams": Field((list,)),
    "teamsByList": Field((list,)),
    "set": Field((str,)),
    "branch": Field((dict,)),
    "lookupFailed": Field((bool,)),
    "unversioned": Field((bool,)),
    "unread": Field((list,)),
    "source": Field((str,)),
    "family": Field((str,)),
    "unfree": Field((bool,)),
    "devel": Field((bool,)),
    # Its versions.
    "nixStatus": Field((str,), required=True),
    # Null for a list entry that nixpkgs doesn't have (nixStatus "missing").
    "nixVersion": Field((str, NULL)),
    "refVersion": Field((str, NULL)),
    "refFromMaster": Field((bool,)),
    "refFromPR": Field((bool,)),
    "repoCount": Field((int,)),
    "repology": Field((list,)),
    "repologyCheckedAt": Field((str,)),
    "repologyVersion": Field((str,)),
    "repologySaid": Field((dict,)),
    "onlyNixpkgs": Field((bool,)),
    "staleSince": Field((str,)),
    "upstream": Field((dict,)),
    "feed": Field((dict,)),
    "upToDate": Field((dict,)),
    "keptBeside": Field((dict,)),
    "archived": Field((bool,)),
    "searchShowsMore": Field((list,)),
    "outdatedSince": Field((str,)),
    "nixVulnerable": Field((bool,)),
    "vulnerabilities": Field((list,)),
    "backport": Field((list,)),
    # Master, its update PRs, and its other PRs and issues on GitHub.
    "master": Field((str,)),
    "masterPR": Field((dict,)),
    "openPR": Field((dict,)),
    "otherPRs": Field((list,)),
    "dropPR": Field((dict,)),
    "stagingPR": Field((dict,)),
    "supersededPRs": Field((list,)),
    "fixPRs": Field((list,)),
    "openPRs": Field((int,)),
    "openIssues": Field((int,)),
    "countedAt": Field((str,)),
    "issueChecks": Field((list,)),
    # Its builds on Hydra.
    "builds": Field((list,)),
    "neverBuiltOn": Field((list,)),
    "failingSince": Field((str,)),
    "buildFixPR": Field((dict,)),
    "buildCausePR": Field((dict,)),
    "stagingNextBreaks": Field((dict,)),
    "stagingNextBlockedBy": Field((dict,)),
    "stagingNextBlocks": Field((dict,)),
    # The update bot's attempts (nixpkgs-update).
    "update": Field((dict, NULL)),
    "updateFailure": Field((bool,)),
    "updateFailingSince": Field((str,)),
    "queued": Field((dict,)),
    # Recent fixes, and the sources that couldn't be refreshed.
    "recentFixes": Field((list,)),
    "notRefreshed": Field((dict, list)),
}

# The views whose length index.json's "views" states.
COUNTED_VIEWS = ("attention", "broken", "backport", "blocked", "unbuilt", "superseded")
# The counts in index.json's "counts" that must equal the view of the
# same name in "views".
COUNTS_OF_VIEWS = ("broken", "backport")
# How many problems of each kind the log shows. The count covers them all.
SHOWN = 5
SHARD = re.compile(r"rows/(\d+)\.json")


def row_problems(row):
    """Check one row's fields against ROW.

    Args:
        row: The row, as a dict.

    Returns:
        A list of sentences, one per problem, empty when there are none.
    """
    found = []
    for name, field in ROW.items():
        if name not in row:
            if field.required:
                found.append(f"missing {name}")
            continue
        value = row[name]
        # An exact type check: isinstance would accept True as an int.
        if type(value) not in field.types:
            expected = " or ".join(
                "null" if t is NULL else t.__name__ for t in field.types
            )
            found.append(f"{name} is {type(value).__name__}, not {expected}")
    found.extend(f"unknown field {name}" for name in row.keys() - ROW.keys())
    return found


def problems(files, slug):
    """Check the data before it's written.

    Args:
        files: The data, as datastore.files builds it: {path in data/: data}.
        slug: A function that turns a team's or list's name into its view's
            file name (datastore.slug).

    Returns:
        The problems found, by kind: {kind: [sentence, ...]}. Empty when the
        data has none.
    """
    found = {}

    def say(kind, text):
        found.setdefault(kind, []).append(text)

    manifest = files.get("index.json")
    if not isinstance(manifest, dict):
        say("manifest", "index.json is missing or isn't an object")
        return found
    count = manifest.get("shardCount")
    if not isinstance(count, int) or count < 1:
        say("manifest", f"shardCount is {count!r}, not a number of shards")
        count = None
    names = _check_rows(files, count, say)
    shards = sum(path.startswith("rows/") for path in files)
    if count is not None and shards != count:
        say("manifest", f"shardCount {count}, but {shards} shards")
    package_count = manifest.get("packageCount")
    if package_count != len(names):
        say("manifest", f"packageCount {package_count!r}, rows {len(names)}")
    if "views" in manifest:
        _check_views(files, manifest, names, slug, say)
    return found


def _check_rows(files, count, say):
    """Check every row in every shard, reporting through say.

    Args:
        files: The data, as given to problems.
        count: The number of shards the manifest states, or None when it
            doesn't state a usable one (shards then aren't checked).
        say: A function taking a problem's kind and its sentence.

    Returns:
        The set of the rows' names.
    """
    names = set()
    for path, data in files.items():
        if not path.startswith("rows/"):
            continue
        shard = SHARD.fullmatch(path)
        packages = data.get("packages") if isinstance(data, dict) else None
        if not shard or not isinstance(packages, list):
            say("rows", f"{path} isn't a shard of rows")
            continue
        for position, row in enumerate(packages):
            name = row.get("name") if isinstance(row, dict) else None
            if not isinstance(name, str):
                say("rows", f"{path}, row {position}: no name")
                continue
            for text in row_problems(row):
                say("row fields", f"{name}: {text}")
            if name in names:
                say("rows", f"{name}: appears twice")
            names.add(name)
            if count is not None and zlib.crc32(name.encode()) % count != int(
                shard.group(1)
            ):
                say("rows", f"{name}: in {path}, not in its own shard")
    return names


def _check_views(files, manifest, names, slug, say):
    """Check the views of an instance tracking every package.

    Every view's rows must be rows of the data, and the manifest's counts
    must equal the views they count. Problems are reported through say.
    """
    views = manifest.get("views")
    counts = manifest.get("counts")
    if not isinstance(views, dict) or not isinstance(counts, dict):
        say("manifest", "views or counts is missing or isn't an object")
        return
    for path, data in files.items():
        if path.startswith("views/"):
            for entry in _entries(data):
                if entry.get("name") not in names:
                    say("views", f"{path}: {entry.get('name')!r} isn't a row")
    for view in COUNTED_VIEWS:
        if view in views:
            _compare(say, f"views.{view}", views[view], _length(files, view))
    for kind, key in (("team", "teams"), ("list", "lists"), ("set", "sets")):
        for name, stated in (views.get(key) or {}).items():
            file = name if kind == "set" else slug(name)
            if isinstance(stated, dict):
                stated = stated.get("packages")
            _compare(
                say, f"views.{key}.{name}", stated, _length(files, f"{kind}/{file}")
            )
    for name in COUNTS_OF_VIEWS:
        if name in counts and name in views:
            _compare(
                say, f"counts.{name}", counts[name], views[name], f"views.{name} is"
            )
    # The build failures, counted as the page counts them from the attention
    # view: packages whose own build failed (on a platform: failed there,
    # where nixpkgs lists the package).
    failed = [
        entry
        for entry in _entries(files.get("views/attention.json"))
        if any(build.get("status") == "failed" for build in _builds(entry))
    ]
    if "buildFailures" in counts:
        _compare(
            say,
            "counts.buildFailures",
            counts["buildFailures"],
            len(failed),
            "the attention view has",
        )
    for platform, stated in (counts.get("buildFailuresOn") or {}).items():
        actual = sum(_failing_on(entry, platform) for entry in failed)
        _compare(
            say,
            f"counts.buildFailuresOn.{platform}",
            stated,
            actual,
            "the attention view has",
        )


def _compare(say, what, stated, actual, source="its view has"):
    """Report a count the manifest states that differs from the actual one.

    Args:
        say: A function taking a problem's kind and its sentence.
        what: Where the manifest states the count ("views.attention").
        stated: The count the manifest states.
        actual: The count it should state.
        source: What the actual count comes from, ending the sentence
            "... but <source> <actual>".
    """
    if stated != actual:
        say("manifest", f"{what} is {stated!r}, but {source} {actual}")


def _entries(data):
    """The entries of a view's data, skipping any that aren't objects.

    A view with no entries isn't written, so data may be None.
    """
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, list):
        return []
    return [entry for entry in packages if isinstance(entry, dict)]


def _length(files, view):
    """How many entries views/<view>.json has (0 when it isn't written)."""
    return len(_entries(files.get(f"views/{view}.json")))


def _builds(entry):
    """The builds of a view's entry, skipping any that aren't objects."""
    builds = entry.get("builds")
    if not isinstance(builds, list):
        return []
    return [build for build in builds if isinstance(build, dict)]


def _listed_on(entry, system):
    """Whether nixpkgs lists the package for a system.

    As docs/data.md describes `platforms`: null means no restriction;
    otherwise the family's flag (linux, darwin) must be true, and when
    `systems` is there, the system must be among them.

    Args:
        entry: A view's entry.
        system: A Hydra system, such as "x86_64-linux".
    """
    platforms = entry.get("platforms")
    if platforms is None:
        return True
    if not isinstance(platforms, dict):
        return False
    systems = platforms.get("systems")
    family = system.rsplit("-", 1)[-1]
    return bool(platforms.get(family)) and (systems is None or system in systems)


def _failing_on(entry, platform):
    """Whether the package's own build fails on a platform where it's listed.

    Args:
        entry: A view's entry.
        platform: A system ("aarch64-darwin") or a family ("darwin"). For a
            family, a failure on any of its systems counts.
    """
    return any(
        build.get("status") == "failed"
        and isinstance(build.get("system"), str)
        and build["system"].endswith(platform)
        and _listed_on(entry, build["system"])
        for build in _builds(entry)
    )


def report(found, out=sys.stderr):
    """Write the problems to the log: how many of each kind, and the first few.

    Args:
        found: The problems, as problems returns them. Nothing is written
            when there are none.
        out: Where to write them (standard error, the log, by default).
    """
    for kind, texts in found.items():
        print(f"Data shape: {len(texts):,} {kind} problems", file=out)
        for text in texts[:SHOWN]:
            print(f"  {text}", file=out)
        if len(texts) > SHOWN:
            print(f"  ... and {len(texts) - SHOWN:,} more", file=out)
