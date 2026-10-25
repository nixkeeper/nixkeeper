"""Fetch and check the digests' files: the part every digest reader shares.

Each digest repository (nixkeeper-hydra, -versions, -updates,
-vulnerabilities, -prs) publishes a meta.json and data files on its data
branch, or files that describe themselves (the version feeds, the
branches, the bot's queue). The readers (hydra_digest.py, updates_digest.py,
...) fetch and check them with these, so a change to how a digest's file is
fetched, checked or given up on is made here once. What makes a digest
current, and how its data is parsed, stay each reader's own.
"""

import gzip
import json
import sys
import urllib.error
from datetime import datetime, timedelta

from . import about, http

# What reading a digest can fail with: the network, the file, its JSON, or a
# field it should have. A reader catches these, and gives up (give_up).
FAILURES = (urllib.error.URLError, OSError, ValueError, KeyError)


def read_meta(base, format):
    """Read a digest's meta.json, checking its format.

    Args:
        base: The digest's URL, ending in "/".
        format: The format this nixkeeper reads.

    Raises:
        ValueError: There's no meta.json, or it's in another format.
    """
    meta = json.loads(http.get(base + "meta.json") or "null")
    if not meta or meta.get("format") != format:
        raise ValueError(f"no digest in a format this nixkeeper reads ({base})")
    return meta


def download(base, name):
    """Download one of a digest's data files, as it is (compressed).

    Raises:
        ValueError: The digest has no such file.
    """
    body = http.get_bytes(base + name)
    if body is None:
        raise ValueError(f"its {name} is missing")
    return body


def read_json_gz(base, name, format):
    """Read a .json.gz file beside a digest that describes itself.

    Args:
        base: The digest's URL, ending in "/".
        name: The file's name.
        format: The format this nixkeeper reads.

    Returns:
        The file's JSON.

    Raises:
        ValueError: There's no such file yet, or it's in another format.
    """
    body = http.get_bytes(base + name)
    if body is None:
        raise ValueError(f"no {name} yet")
    found = json.loads(gzip.decompress(body))
    if found.get("format") != format:
        raise ValueError(f"not in a format this nixkeeper reads ({base}{name})")
    return found


def hours_since(at, now):
    """Return how many hours have passed from at to now (ISO times)."""
    return (datetime.fromisoformat(now) - datetime.fromisoformat(at)) / timedelta(
        hours=1
    )


def give_up(source, label, error, instead=""):
    """Note and log that a digest couldn't be read.

    Args:
        source: Its name in the sources panel (about.note).
        label: Its name in the log.
        error: What went wrong.
        instead: What the sync does instead, as the log says it ("; asking
            Hydra about each job").
    """
    about.note(source, False, f"couldn't be read ({error})")
    print(f"::warning::{label}: couldn't use it ({error}){instead}", file=sys.stderr)
