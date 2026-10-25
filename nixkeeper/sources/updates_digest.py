"""Read nixkeeper-updates' digest of the update bot's attempts.

The digest (https://github.com/nixkeeper/digest-update-bot) has
nixpkgs-update's latest attempt at every package, its log read with these
same rules (nixpkgs_update.parse), refreshed every 3 hours. The daily sync
takes attempts from it instead of reading each package's logs
(nixpkgs_update.add_attempts). It still reads the logs of the lists'
packages the digest can't answer: an attempt it hasn't read yet
("pending"), or one read with other rules (another PARSER); and all of
them when the digest isn't current or can't be read.
"""

import gzip
import io
import json
import sys
from datetime import datetime, timedelta

from .. import config
from . import about, digests, http

# The digest's format this nixkeeper reads.
FORMAT = 1


def current(meta, now):
    """Return whether the digest is recent enough.

    It is when it was made within UPDATES_DIGEST_MAX_AGE_HOURS; its
    workflow runs every 3 hours.
    """
    hours = digests.hours_since(meta["fetchedAt"], now)
    return hours <= config.UPDATES_DIGEST_MAX_AGE_HOURS


def load(now):
    """Read the digest's entries.

    Returns:
        {the bot's attribute: entry}, with the attribute as the logs name
        it (python3Packages.requests: rows.search_term). None when the
        digest is turned off, or (with the reason in the log) not current
        or unreadable.
    """
    base = config.UPDATES_DIGEST_URL
    if not base:
        return None
    try:
        meta = digests.read_meta(base, FORMAT)
        if not current(meta, now):
            about.note("updates", False, "too old", at=meta["fetchedAt"])
            print(
                f"::warning::Updates digest: not used, it's from {meta['fetchedAt']}; "
                "reading the logs per package",
                file=sys.stderr,
            )
            return None
        body = digests.download(base, "attempts.jsonl.gz")
        found = {}
        with gzip.open(io.BytesIO(body), "rt") as lines:
            for line in lines:
                entry = json.loads(line)
                found[entry.pop("attr")] = entry
    except digests.FAILURES as e:
        digests.give_up(
            "updates", "Updates digest", e, "; reading the logs per package"
        )
        return None
    print(
        f"Updates digest: {len(found):,} packages, made {meta['fetchedAt']} "
        f"({meta.get('pending', 0):,} attempts not read yet)",
        file=sys.stderr,
    )
    about.note("updates", True, at=meta["fetchedAt"], pending=meta.get("pending", 0))
    return found


def load_queue(now):
    """Read when the bot will next try each package, from its queue.

    The digest keeps a copy of the bot's queue (queue.json.gz, made from
    ~supervisor/queue.html). The queue goes round in "cycleDays": a package
    at position p of n is reached about p / n of a cycle after the page was
    made.

    Returns:
        {the bot's attribute: {"by": the day it's expected, "candidates":
        [[from, to, source URL], ...], "script": whether it runs the
        package's updateScript}}. None when the digest is turned off, or
        (with the reason noted) has no queue, an old one, or an unreadable
        one.
    """
    base = config.UPDATES_DIGEST_URL
    if not base:
        return None
    try:
        body = http.get_bytes(base + "queue.json.gz")
        if body is None:
            about.note("queue", False, "the digest has no queue yet")
            return None
        queue = json.loads(gzip.decompress(body))
        made = datetime.fromisoformat(queue["updatedAt"])
        if digests.hours_since(queue["updatedAt"], now) > (
            config.UPDATES_QUEUE_MAX_AGE_HOURS
        ):
            about.note("queue", False, "too old", at=queue["updatedAt"])
            return None
        cycle, positions = queue["cycleDays"], queue["positions"]
        found = {
            attr: {
                "by": (made + timedelta(days=cycle * entry["position"] / positions))
                .date()
                .isoformat(),
                "candidates": entry.get("candidates", []),
                "script": bool(entry.get("script")),
            }
            for attr, entry in queue["queue"].items()
        }
    except (*digests.FAILURES, TypeError) as e:
        digests.give_up("queue", "The bot's queue", e)
        return None
    about.note("queue", True, at=queue["updatedAt"], cycleDays=cycle)
    print(
        f"The bot's queue: {len(found):,} packages, a {cycle:g}-day cycle, "
        f"from {queue['updatedAt']}",
        file=sys.stderr,
    )
    return found


def attempt(entry, attr, parser):
    """Return the latest attempt at attr from its digest entry, or None.

    The attempt is as nixpkgs_update.latest_attempt would read it. None
    means the digest can't say: there's a newer attempt it hasn't read
    ("pending"), or it read this one with other rules than parser.

    Args:
        entry: The digest's entry for the package.
        attr: nixkeeper's attribute.
        parser: The rules' version (nixpkgs_update.PARSER).
    """
    found = entry.get("attempt")
    if not found or "pending" in entry or found.get("parser") != parser:
        return None
    return {**{k: v for k, v in found.items() if k != "started"}, "attr": attr}


def known(entry, attr):
    """Return the attempt the digest last read for attr, or None.

    Unlike attempt(), this ignores a newer attempt the digest hasn't read
    yet ("pending"): it's only for packages read in bulk, which keep the
    last attempt read.
    """
    found = entry.get("attempt")
    if not found:
        return None
    return {**{k: v for k, v in found.items() if k != "started"}, "attr": attr}
