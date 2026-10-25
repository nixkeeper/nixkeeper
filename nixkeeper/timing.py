"""Time each phase of a run, and report the times in its log.

The report shows where a sync's minutes go, so they're seen rather than
guessed, and it's the evidence to start from before making a phase faster.
"""

import sys
import time


class Phases:
    """A run's phases, timed one after the other.

    Call lap(name) at the end of each phase: the phase began at the previous
    lap, or when Phases was made. Call report() at the end of the run.

    Args:
        clock: The clock to read, in seconds (time.monotonic; tests pass
            their own).
    """

    def __init__(self, clock=time.monotonic):
        """Start timing: the first phase begins now."""
        self._clock = clock
        self._last = self._start = clock()
        self.laps = []  # [(name, seconds)], in the order they ran

    def lap(self, name):
        """End the phase called name, which began at the previous lap."""
        now = self._clock()
        self.laps.append((name, now - self._last))
        self._last = now

    def report(self, out=sys.stderr):
        """Write every phase's time to the log, the longest first, with its share.

        Args:
            out: Where to write (standard error, the log, by default).
        """
        total = self._clock() - self._start
        print(f"Phases: {_took(total)} in all", file=out)
        for name, seconds in sorted(self.laps, key=lambda lap: -lap[1]):
            share = 100 * seconds / total if total else 0
            print(f"  {_took(seconds):>8} {share:3.0f}%  {name}", file=out)


def _took(seconds):
    """Format a duration in seconds briefly: "1.2 s", "47 s", "3 min 05 s"."""
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"
