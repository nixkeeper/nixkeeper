"""Load the sets' own sources of versions, and compare rows with them.

For the sets Repology mostly can't compare, nixkeeper-versions reads their
own sources daily, beside its Repology digest
(https://github.com/nixkeeper/digest-versions): Typst Universe
(typst_digest.py), the Emacs package archives (emacs_digest.py), Stackage
LTS (stackage_digest.py), CRAN and Bioconductor (cran_digest.py), and
the indexes of five more generated sets (sets_digest.py). Each
is one file next to the digest, loaded the same way (load), and compared
with its set's rows by its own rules. Each such row then says what it was
compared with ("feed", set by compare).
"""

from .. import config, verdict
from ..shape import Row
from . import digests

# The files' format this nixkeeper reads.
FORMAT = 1


def load(file, source, label, now):
    """Read one of the sets' sources, beside the versions digest.

    Args:
        file: The file's name (typst.json.gz, emacs.json.gz, ...).
        source: Its name in the sources panel (about.note).
        label: Its name in the log.
        now: The run's time.

    Returns:
        The file's body, or None when the digest is turned off, or (noted
        for the sources panel) the file isn't there, isn't current or can't
        be read; Repology's verdicts then stay for its set.
    """
    base = config.VERSIONS_DIGEST_URL
    if not base:
        return None
    try:
        found = digests.read_json_gz(base, file, FORMAT)
        at = found["fetchedAt"]
        if digests.hours_since(at, now) > config.VERSIONS_DIGEST_MAX_AGE_HOURS:
            digests.too_old(source, label, at, "; Repology's stay")
            return None
    except digests.FAILURES as e:
        digests.give_up(source, label, e, "; Repology's stay")
        return None
    return found


def compare(row: Row, name, newest, url, released=None, dated=False, **more):
    """Compare row with a version from its set's source.

    The row says what it was compared with ("feed"), and is no longer kept
    beside a newer version (keptBeside). It's outdated or newest against
    that version (verdict._feed).

    Args:
        row: The row, changed in place.
        name: The source's name, as the page shows it.
        newest: The source's newest version.
        url: The package's page on the source.
        released: The day that version was published, when known.
        dated: Whether the source's versions are a build's date and time,
            as MELPA's are.
        **more: What else the source says, kept in "feed".
    """
    row["feed"] = {
        "name": name,
        "version": newest,
        "url": url,
        **({"released": released} if released else {}),
        **({"dated": True} if dated else {}),
        **more,
    }
    row.pop("keptBeside", None)
    verdict.decide(row)
