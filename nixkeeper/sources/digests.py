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
import urllib.error
from datetime import datetime, timedelta

from .. import log
from . import about, http

# What reading a digest can fail with: the network, the file, its JSON, or a
# field it should have. A reader catches these, and gives up (give_up).
FAILURES = (urllib.error.URLError, OSError, ValueError, KeyError)


def read_meta(base, expected_format):
    """Read a digest's meta.json, checking its format.

    Args:
        base: The digest's URL, ending in "/".
        expected_format: The format this nixkeeper reads.

    Raises:
        ValueError: There's no meta.json, or it's in another format.
    """
    meta = json.loads(http.get(base + "meta.json") or "null")
    if not meta or meta.get("format") != expected_format:
        raise ValueError(f"no digest in a format this nixkeeper reads ({base})")
    return meta


def read_json(base, name, expected_format):
    """Read one of a digest's JSON files (sent compressed), checking its format.

    Args:
        base: The digest's URL, ending in "/".
        name: The file's name.
        expected_format: The format this nixkeeper reads.

    Raises:
        ValueError: The file is empty or in another format.
    """
    data = json.loads(http.get(base + name, compressed=True) or "null")
    if not data or data.get("format") != expected_format:
        raise ValueError(f"no {name} in a format this nixkeeper reads")
    return data


def download(base, name, missing_ok=False):
    """Download one of a digest's data files, as it is (compressed).

    Args:
        base: The digest's URL, ending in "/".
        name: The file's name.
        missing_ok: Return None when there's no such file, rather than raise.

    Raises:
        ValueError: The digest has no such file (unless missing_ok).
    """
    body = http.get_bytes(base + name)
    if body is None and not missing_ok:
        raise ValueError(f"its {name} is missing")
    return body


def read_json_gz(base, name, expected_format):
    """Read a .json.gz file beside a digest that describes itself.

    Args:
        base: The digest's URL, ending in "/".
        name: The file's name.
        expected_format: The format this nixkeeper reads.

    Returns:
        The file's JSON.

    Raises:
        ValueError: There's no such file yet, or it's in another format.
    """
    body = download(base, name, missing_ok=True)
    # "Yet", not download's "missing": these files appear once their digest
    # first writes them, so one not there may just be new.
    if body is None:
        raise ValueError(f"no {name} yet")
    found = json.loads(gzip.decompress(body))
    if found.get("format") != expected_format:
        raise ValueError(f"not in a format this nixkeeper reads ({base}{name})")
    return found


def hours_since(at, now):
    """Return how many hours have passed from at to now (ISO times)."""
    age = datetime.fromisoformat(now) - datetime.fromisoformat(at)
    return age / timedelta(hours=1)


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
    log.warn(f"{label}: couldn't use it ({error}){instead}")


def too_old(source, label, at, instead="", **more):
    """Note and log that a digest is too old to use.

    Args:
        source: Its name in the sources panel (about.note).
        label: Its name in the log.
        at: When it was read (ISO).
        instead: What the sync does instead, as the log says it.
        **more: What else the note says of it (its "eval", ...).
    """
    about.note(source, False, "too old", at=at, **more)
    log.warn(f"{label}: not used, read {at}{instead}")
