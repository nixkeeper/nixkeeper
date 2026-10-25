"""What the commands say as they run, on standard error.

info is for what a run does. notice and warn are for what someone should
look at: on GitHub Actions they're the workflow's annotations (::notice::,
::warning::), shown on the run's page; elsewhere (a terminal, a systemd
journal) they're lines starting "notice: " and "warning: ". group folds
the lines said within it under a title on GitHub Actions; elsewhere the
title is a line of its own.

Standard output is left to what a command prints as its answer
(cli.py, community_check.py).
"""

import contextlib
import os
import sys


def _on_github():
    """Return whether this runs on GitHub Actions, which reads annotations."""
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _say(text):
    """Write one message, which may be several lines, to standard error."""
    # sys.stderr is looked up each time, so tests can replace it.
    print(text, file=sys.stderr)


def info(message):
    """Say what the run is doing or found.

    Args:
        message: The message; it may be several lines.
    """
    _say(message)


def notice(message):
    """Say something worth knowing that isn't a problem.

    Args:
        message: The message, on one line.
    """
    _say(f"::notice::{message}" if _on_github() else f"notice: {message}")


def warn(message):
    """Say something that went wrong, or needs someone to fix it.

    Args:
        message: The message, on one line.
    """
    _say(f"::warning::{message}" if _on_github() else f"warning: {message}")


@contextlib.contextmanager
def group(title):
    """Fold the lines said within it under title (a with block).

    Args:
        title: The group's title, on one line.
    """
    if not _on_github():
        _say(title)
        yield
        return
    _say(f"::group::{title}")
    try:
        yield
    finally:
        _say("::endgroup::")
