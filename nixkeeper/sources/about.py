"""Record what the daily sync's sources were, for the manifest's "sources".

The manifest's "sources" is the page's "checked" panel: when each
digest's data is from, and whether the sync used it or, not trusting it,
asked per package instead (and why). Each source notes itself as it's
loaded, Hydra's from the background thread, and the sync takes them all
once it's done.
"""

import threading

_noted: dict[str, dict] = {}
_lock = threading.Lock()
# A reason longer than this is cut: an error's text can be long.
WHY_LENGTH = 200


def note(source, used, why=None, **about):
    """Note what a source was this run.

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
        _noted[source] = found


def taken():
    """Return every source noted since the last call, and start over.

    Starting over keeps a run's notes its own.

    Returns:
        {source: what was noted}, sorted by source.
    """
    with _lock:
        found = dict(sorted(_noted.items()))
        _noted.clear()
    return found
