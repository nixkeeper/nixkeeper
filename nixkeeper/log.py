"""What the commands say as they run, on standard error.

info is for what a run does. notice and warn are for what someone should
look at: on GitHub Actions they're the workflow's annotations (::notice::,
::warning::), shown on the run's page; elsewhere they're lines starting
"notice: " and "warning: ", which a systemd journal files at those
priorities. group folds the lines said within it under a title on GitHub
Actions; elsewhere the title is a line of its own, and the lines within
are indented.

Standard output is left to what a command prints as its answer
(cli.py, community_check.py).
"""

import contextlib
import os
import sys
import threading

from . import config

# Each thread's own: how deep in groups its lines are, for their indent off
# GitHub (Hydra's background thread says its lines while the main thread is
# in a group: they aren't that group's).
_local = threading.local()
# Whether each standard error is the journal's stream, by its id and
# JOURNAL_STREAM (_to_journal).
_journal: dict[tuple[int, str], bool] = {}


def _depth():
    """Return how deep in groups this thread's lines are."""
    return getattr(_local, "depth", 0)


def _escaped(text):
    """Return text as a GitHub workflow command's message carries it.

    A newline would end the annotation, the rest showing as plain lines; a
    "%" would start an escape of its own.
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _to_journal():
    """Return whether standard error is a systemd journal stream.

    systemd then reads a "<4>" (warning) or "<5>" (notice) at the start of a
    line as its priority (journalctl -p warning). It says which stream is
    the journal's in JOURNAL_STREAM ("device:inode").
    """
    stream = os.environ.get("JOURNAL_STREAM")
    if not stream:
        return False
    key = (id(sys.stderr), stream)
    if key not in _journal:
        try:
            device, inode = (int(n) for n in stream.split(":"))
            found = os.fstat(sys.stderr.fileno())
            _journal[key] = (found.st_dev, found.st_ino) == (device, inode)
        except (AttributeError, ValueError, OSError):
            _journal[key] = False  # not a file at all (tests' StringIO)
    return _journal[key]


def _say(text, priority=""):
    """Write a message, which may be several lines, to standard error.

    Args:
        text: The message.
        priority: The journal's priority for it ("<4>"), when it's one.
    """
    indent = "" if config.on_github_actions() else "  " * _depth()
    # The journal files each line on its own: each gets the priority, which
    # it reads only at the very start of a line.
    start = (priority if _to_journal() else "") + indent
    # sys.stderr is looked up each time, so tests can replace it.
    print("\n".join(start + line for line in text.split("\n")), file=sys.stderr)


def info(message):
    """Say what the run is doing or found.

    Args:
        message: The message; it may be several lines.
    """
    _say(message)


def notice(message):
    """Say something worth knowing that isn't a problem.

    Args:
        message: The message; it may be several lines.
    """
    if config.on_github_actions():
        _say(f"::notice::{_escaped(message)}")
    else:
        _say(f"notice: {message}", "<5>")


def warn(message):
    """Say something that went wrong, or needs someone to fix it.

    Args:
        message: The message; it may be several lines.
    """
    if config.on_github_actions():
        _say(f"::warning::{_escaped(message)}")
    else:
        _say(f"warning: {message}", "<4>")


@contextlib.contextmanager
def group(title):
    """Fold the lines said within it under title (a with block).

    GitHub Actions doesn't fold a group within another: don't nest them.

    Args:
        title: The group's title.
    """
    if not config.on_github_actions():
        _say(title)
        _local.depth = _depth() + 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    _say(f"::group::{_escaped(title)}")
    try:
        yield
    finally:
        _say("::endgroup::")
