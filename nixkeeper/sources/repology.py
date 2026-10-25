"""Look projects up on Repology's API.

Lookups are retried, and fall back between domains when there are several
(config.REPOLOGY_URLS).
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config
from . import http

# What nixkeeper reads of a Repology entry (rows.py, and the page's details):
# the rest (summaries, licenses, maintainers, ...) only made data/ bigger.
FIELDS = ("repo", "srcname", "version", "status", "vulnerable")

# The domain that last answered: tried first for the rest of the run, so an
# unreachable first domain costs one failed connection, not one per lookup.
_working = None


def _domains():
    """Return Repology's domains, the one that last answered first."""
    domains = list(config.REPOLOGY_URLS)
    if _working in domains:
        domains.remove(_working)
        domains.insert(0, _working)
    return domains


def _answered(base):
    """Remember base as the domain that answered, for the rest of the run."""
    global _working
    if base != _working and base != config.REPOLOGY_URLS[0]:
        print(f"  using {base} for the rest of the run", file=sys.stderr)
    _working = base


def get(path):
    """GET a Repology path, as JSON.

    Each domain is tried, the last one that answered first, and the lot is
    retried after RETRY_DELAYS seconds.

    Returns:
        (json, the final URL), or (None, None) on a 404.

    Raises:
        urllib.error.URLError, OSError, ValueError: Every attempt failed;
            the last one's error.
    """
    last_err = None
    for attempt, delay in enumerate([0, *config.RETRY_DELAYS]):
        if attempt:
            # As long as Repology asked, if it did (http.retry_wait).
            delay = http.retry_wait(delay, last_err, "Repology")
            print(f"  retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)
        for base in _domains():
            req = urllib.request.Request(
                base + path, headers={"User-Agent": config.user_agent()}
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    result = json.loads(resp.read().decode()), resp.geturl()
                _answered(base)
                return result
            except urllib.error.HTTPError as e:
                e.close()  # an HTTP error is also an open response
                if e.code == 404:
                    _answered(base)
                    return None, None
                print(f"  {base} answered {e.code}", file=sys.stderr)
                last_err = e
            except (urllib.error.URLError, OSError, ValueError) as e:
                print(f"  {base} failed ({e}), trying next domain...", file=sys.stderr)
                last_err = e
    raise last_err


def trimmed(entries):
    """Return entries with only FIELDS, each once, in Repology's order.

    Repology lists a package once per binary package (xournalpp,
    xournalpp-doc, ...), and those read the same once trimmed.
    """
    seen, kept = set(), []
    for entry in entries or []:
        entry = {k: entry[k] for k in FIELDS if k in entry}
        key = json.dumps(entry, sort_keys=True)
        if key not in seen:
            seen.add(key)
            kept.append(entry)
    return kept


def project_for_attr(attr):
    """Find the Repology project of a nixpkgs attribute.

    Returns:
        (project, entries), or (None, None) when Repology doesn't know it.
    """
    query = urllib.parse.urlencode(
        {
            "repo": config.NIX_REPO,
            "name_type": "srcname",
            "target_page": "api_v1_project",
            "name": attr,
        }
    )
    entries, url = get(f"/tools/project-by?{query}")
    if entries is None:
        return None, None
    return urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1]), trimmed(entries)


def project_by_name(name):
    """Read a Repology project by name.

    Returns:
        (name, entries), or (None, None) when Repology has no such project.
    """
    entries, _ = get(f"/api/v1/project/{urllib.parse.quote(name)}")
    # Repology answers an unknown project with an empty list, not a 404.
    return (name, trimmed(entries)) if entries else (None, None)


def has_attrs(entries, attrs):
    """Return whether Repology's entries include nixpkgs packaging one of attrs."""
    return any(
        e.get("repo") == config.NIX_REPO and e.get("srcname") in attrs for e in entries
    )


def resolve(fallback, attrs, known=None):
    """Find the Repology project for tracked nixpkgs attributes.

    The attributes are looked up first, then fallback as a project name.

    Args:
        fallback: A project name to try when no attribute resolves (not in
            nixpkgs, or Repology hasn't caught up yet).
        attrs: The attributes.
        known: The project the last run found for them. Asked for directly,
            it takes one request, where asking by attribute takes two
            (Repology answers with a redirect to the project). It's used
            while it still has one of attrs in nixpkgs; otherwise (Repology
            renamed or split the project) they're looked up by attribute as
            before.

    Returns:
        (project, entries), or (None, None) when Repology doesn't know it.

    Raises:
        urllib.error.URLError, OSError, ValueError: A lookup failed.
    """
    if known and attrs:
        project, entries = project_by_name(known)
        time.sleep(1)
        if project and has_attrs(entries, attrs):
            return project, entries
    for attr in attrs:
        project, entries = project_for_attr(attr)
        time.sleep(1)  # be polite to Repology's API
        if project:
            return project, entries
    # Not in nixpkgs, or Repology hasn't caught up yet: try the fallback as a
    # Repology project name directly.
    project, entries = project_by_name(fallback)
    time.sleep(1)
    return project, entries
