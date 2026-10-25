"""Compare version strings the way Repology does.

This is Repology's algorithm (libversion, https://github.com/repology/
libversion, doc/ALGORITHM.md), used for the update checks and for what
master has, so nixkeeper orders versions as Repology does. The page has the
same in JavaScript (page/logic.js: compareVersions); both are tested
against Repology's test suite (tests/data/version-comparison-tests.txt).

A version is split into numeric and alphabetic components (anything else
separates them), each ranked: pre-release (alpha, beta, rc, pre..., and
any other word) < zero < post-release (post..., patch..., pl, errata) <
nonzero < a letter suffix (1.0a: a letter right after a number, not
followed by one). Versions compare component by component, rank first,
then words by their first letter (any case), numbers as numbers; the
shorter one is padded with zeros (1 == 1.0, 1.0alpha < 1.0 < 1.0patch1 <
1.0.1 < 1.0a).

One addition, for nixpkgs' versions: one with "unstable" in it is the
version before the word and a snapshot after it (the nixpkgs manual's
0-unstable-2022-07-13, 1.2-unstable-2025-05-01; the older
unstable-2015-10-15 has none before it, as 0). It's compared by that
version first, then a snapshot comes after the version itself, then by
what follows the word (its date): 1.2 < 1.2-unstable-2025-05-01 < 1.3,
0-unstable-2022-07-13 < 0.0.1. libversion, not knowing the word, would
take it for a pre-release, before the version it follows.
"""

import functools
import re

# A component's ranks, lowest first.
PRE_RELEASE, ZERO, POST_RELEASE, NONZERO, LETTER_SUFFIX = range(5)
# A component: a run of letters, or of digits.
TOKEN = re.compile(r"([A-Za-z]+)|([0-9]+)")


def keyword(word):
    """Return a word's rank as Repology classifies it, or None when it's no keyword.

    That's libversion's classify_keyword.
    """
    w = word.lower()
    if w in ("alpha", "beta", "rc") or w.startswith("pre"):
        return PRE_RELEASE
    if w.startswith(("post", "patch")) or w in ("pl", "errata"):
        return POST_RELEASE
    return None


def components(version):
    """Split version into its components, as (rank, kind, value) tuples.

    kind is 0 for an empty value (a zero), 1 for a word (value: its first
    letter, in lower case), and 2 for a number. Trailing zeros are left
    out: they're what padding adds.
    """
    found = []
    pos = 0
    for m in TOKEN.finditer(version):
        word, number = m.groups()
        if word:
            # Right after a number, and not followed by one: a letter
            # suffix (1.0a, 1.0a.1; not 1.0a1, nor 1.0.a).
            after_number = m.start() == pos and found and found[-1][1] != 1
            followed = version[m.end() : m.end() + 1].isdigit()
            rank = keyword(word)
            if rank is None:
                rank = LETTER_SUFFIX if after_number and not followed else PRE_RELEASE
            found.append((rank, 1, word[0].lower()))
        else:
            value = int(number)
            found.append((NONZERO, 2, value) if value else (ZERO, 0, 0))
        pos = m.end()
    while found and found[-1] == (ZERO, 0, 0):
        found.pop()
    return tuple(found)


# The word that marks a nixpkgs snapshot version.
UNSTABLE = re.compile(r"unstable", re.IGNORECASE)
# What a shorter version is padded with: a zero.
PAD = (ZERO, 0, 0)


def compare_components(a, b):
    """Compare a's components with b's, the shorter padded with zeros.

    Returns:
        -1, 0 or 1.
    """
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else PAD
        y = b[i] if i < len(b) else PAD
        if x != y:
            return -1 if x < y else 1
    return 0


# Words Repology ranks as pre-release, but that name a release
# (godot's 4.7.2-stable).
RELEASE_WORDS = re.compile(
    r"(?<![A-Za-z])(stable|release|final|ga|lts)(?![A-Za-z])", re.IGNORECASE
)


def is_pre_release(version):
    """Return whether version is a pre-release, as Repology orders it.

    That's a version with a component ranked before a release's (158.0b1,
    5.0.0-beta8, 1.7.0-rc0). Not a snapshot ("unstable"), which comes after
    its version, nor a release named so (4.7.2-stable).
    """
    if not version or UNSTABLE.search(version):
        return False
    return any(
        rank == PRE_RELEASE for rank, _, _ in components(without_release_words(version))
    )


def without_release_words(version):
    """Return version without the words naming it a release (4.7.2-stable: 4.7.2)."""
    return RELEASE_WORDS.sub(" ", version or "")


@functools.total_ordering
class Version:
    """A version, compared as Repology compares it, with nixpkgs' snapshots.

    It's held as (its components before "unstable", whether it's a
    snapshot, its components after), and compared by the version, then a
    snapshot after it, then the snapshot's date.
    """

    __slots__ = ("parts",)

    def __init__(self, version):
        """Split version into its parts."""
        version = version or ""
        if m := UNSTABLE.search(version):
            self.parts = (
                components(version[: m.start()]),
                1,
                components(version[m.end() :]),
            )
        else:
            self.parts = (components(version), 0, ())

    def _compare(self, other):
        """Compare with other: -1, 0 or 1."""
        (a, snap_a, after_a), (b, snap_b, after_b) = self.parts, other.parts
        found = compare_components(a, b)
        if found or snap_a != snap_b:
            return found or (-1 if snap_a < snap_b else 1)
        return compare_components(after_a, after_b)

    def __eq__(self, other):
        return isinstance(other, Version) and self.parts == other.parts

    def __lt__(self, other):
        return self._compare(other) < 0

    def __hash__(self):
        return hash(self.parts)

    def __repr__(self):
        return f"Version({self.parts!r})"


def version_key(version):
    """Return a sort key for version strings, ordering them as Repology does.

    1.19.28 > 1.19.9, and 1.0rc1 < 1.0 == 1 < 1.0.1.
    """
    return Version(version)


def is_newer(version, than):
    """Return whether version is newer than than.

    False when either is missing: an empty version counts as 0 in
    Repology's order, which is above an unstable one
    (0-unstable-2022-07-13), and no version isn't a newer one.
    """
    return bool(version) and bool(than) and version_key(version) > version_key(than)
