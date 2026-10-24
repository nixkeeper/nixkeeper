"""How long each phase of a run took, in its log: where a sync's minutes go,
seen rather than guessed (and the evidence before making one faster)."""

import sys
import time


class Phases:
    """A run's phases, timed one after the other: lap(name) ends the phase
    called name (it began at the last lap, or at the start), report() puts
    them all in the log, the longest first, with each one's share."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._last = self._start = clock()
        self.laps = []  # [(name, seconds)], in the order they ran

    def lap(self, name):
        now = self._clock()
        self.laps.append((name, now - self._last))
        self._last = now

    def report(self, out=sys.stderr):
        total = self._clock() - self._start
        print(f"Phases: {_took(total)} in all", file=out)
        for name, seconds in sorted(self.laps, key=lambda lap: -lap[1]):
            share = 100 * seconds / total if total else 0
            print(f"  {_took(seconds):>8} {share:3.0f}%  {name}", file=out)


def _took(seconds):
    """1.2 s, 47 s, 3 min 05 s."""
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"
