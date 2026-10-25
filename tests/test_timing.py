"""nixkeeper.timing: how long each phase of a run took."""

import io
import unittest
from unittest import mock

from nixkeeper import timing


class Phases(unittest.TestCase):
    def test_each_from_the_last_lap_longest_first(self):
        now = [0.0]
        phases = timing.Phases(clock=lambda: now[0])
        for name, seconds in (("nixpkgs", 4.2), ("Repology", 185), ("writing", 30.4)):
            now[0] += seconds
            phases.lap(name)
        self.assertEqual(
            [(n, round(s, 1)) for n, s in phases.laps],
            [("nixpkgs", 4.2), ("Repology", 185), ("writing", 30.4)],
        )
        out = io.StringIO()
        with mock.patch("sys.stderr", out):
            phases.report()
        self.assertEqual(
            out.getvalue().splitlines(),
            [
                "Phases: 3 min 40 s in all",
                "  3 min 05 s  84%  Repology",
                "      30 s  14%  writing",
                "     4.2 s   2%  nixpkgs",
            ],
        )
