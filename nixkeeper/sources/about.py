"""Record what the daily sync's sources were, for the manifest's "sources".

The manifest's "sources" is the page's "checked" panel: when each
digest's data is from, and whether the sync used it or, not trusting it,
asked per package instead (and why). Each source notes itself as it's
loaded, Hydra's from the background thread, and the sync takes them all
once it's done.
"""

import contextlib
import threading

# The collection open now (collecting), which note adds to; None outside
# one. Module-level, not the sync's Run: notes come from many modules and
# from Hydra's thread, and only collecting opens or closes it.
_current: dict | None = None
_lock = threading.Lock()
# A reason longer than this is cut: an error's text can be long.
WHY_LENGTH = 200


def note(source, used, why=None, **about):
    """Note what a source was this run, in the collection open now.

    Outside collecting() it does nothing: only a sync reports its sources,
    and a command or test that doesn't collect them keeps nothing.

    Args:
        source: The source's name.
        used: True, or False when the sync asked per package instead.
        why: Why it wasn't used, cut to WHY_LENGTH.
        **about: What else to say of it (its "at" time, evaluation, ...);
            values that are None are left out.
    """
    found = {"used": used, **{k: v for k, v in about.items() if v is not None}}
    if why:
        found["why"] = why if len(why) <= WHY_LENGTH else why[: WHY_LENGTH - 1] + "…"
    with _lock:
        if _current is not None:
            _current[source] = found


@contextlib.contextmanager
def collecting():
    """Collect the sources noted inside the with block.

    Yields:
        {source: what was noted}, filled as each source notes itself, and
        sorted by source once the block ends.

    Raises:
        RuntimeError: A collection is already open.
    """
    global _current
    noted = {}
    with _lock:
        if _current is not None:
            raise RuntimeError("already collecting")
        _current = noted
    try:
        yield noted
    finally:
        with _lock:
            _current = None
            found = sorted(noted.items())
            noted.clear()
            noted.update(found)
