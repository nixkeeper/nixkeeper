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

from . import config

# How deep in groups the lines being said are, for their indent off GitHub.
_depth = 0


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
    try:
        device, inode = (int(n) for n in os.environ["JOURNAL_STREAM"].split(":"))
        found = os.fstat(sys.stderr.fileno())
    except (KeyError, ValueError, OSError, AttributeError):
        return False  # not a journal, or not a file at all (tests' StringIO)
    return (found.st_dev, found.st_ino) == (device, inode)


def _say(text, priority=""):
    """Write a message, which may be several lines, to standard error.

    Args:
        text: The message.
        priority: The journal's priority for it ("<4>"), when it's one.
    """
    if _depth and not config.on_github_actions():
        text = "\n".join("  " * _depth + line for line in text.split("\n"))
    # sys.stderr is looked up each time, so tests can replace it.
    print((priority if _to_journal() else "") + text, file=sys.stderr)


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
    global _depth
    if not config.on_github_actions():
        _say(title)
        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
        return
    _say(f"::group::{_escaped(title)}")
    try:
        yield
    finally:
        _say("::endgroup::")
