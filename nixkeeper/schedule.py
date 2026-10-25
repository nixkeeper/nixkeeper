"""Ask less often about what's quiet.

Something with nothing going on (a Hydra build that went fine, a package
with no open PRs or issues) is asked about every QUIET_DAYS instead of
daily: once on its own slot day, chosen by a hash of its name so every day
has about the same share (as nixpkgs-update spreads its queue), or once
that long has passed, in case a sync was missed. Whatever has something
going on is asked daily (daily); each source decides what that is
(hydra.due, github.add_counts). Both count time, not syncs: a sync run
every few hours asks no more often than a daily one, and what changed (a
new package, a version moved, an edited rule) is asked at once.
"""

import zlib
from datetime import UTC, datetime, timedelta

from . import config

# The time of day a sync runs varies a little: what was checked a bit less
# than QUIET_DAYS ago counts as due.
SLACK = timedelta(hours=6)
# Daily: asked again once this long has passed. A little under a day, so a
# daily sync up to 2 hours earlier than yesterday's still asks; and over 21
# hours, so syncs every 3 hours ask once a day (at the 24th hour), not at
# the 21st (about 8 times a week).
DAILY = timedelta(hours=22)


def slot(name, when):
    """Return whether when (a datetime) is name's day to be asked, while quiet.

    That's one day in QUIET_DAYS.
    """
    days = config.QUIET_DAYS
    return zlib.crc32(name.encode()) % days == when.date().toordinal() % days


def due(name, checked_at, now):
    """Return whether something quiet is due now.

    It is on its slot day, unless it was checked that day already, or once
    QUIET_DAYS have passed (less SLACK).

    Args:
        name: What it is, for its slot day.
        checked_at: When it was last checked (ISO), or None if never.
        now: The time now (ISO).
    """
    if not checked_at:
        return True
    when, checked = datetime.fromisoformat(now), datetime.fromisoformat(checked_at)
    if when - checked >= timedelta(days=config.QUIET_DAYS) - SLACK:
        return True
    return slot(name, when) and _day(checked) < _day(when)


def daily(checked_at, now):
    """Return whether something with something going on is due now.

    It is once DAILY has passed since checked_at (ISO, or None if never).
    """
    if not checked_at:
        return True
    return datetime.fromisoformat(now) - datetime.fromisoformat(checked_at) >= DAILY


def _day(when):
    """Return the UTC day of a time; one without a zone is taken as UTC."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).date()
