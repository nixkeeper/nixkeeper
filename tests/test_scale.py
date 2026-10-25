"""How big a sync is, and its limits (nixkeeper/scale.py)."""

import io
import os
import tempfile
import unittest
from unittest import mock

from nixkeeper import config, listcheck, scale
from nixkeeper.errors import Problem


class Estimate(unittest.TestCase):
    def test_durations_read_as_estimates(self):
        self.assertEqual(scale.duration(30), "about 1 min")
        self.assertEqual(scale.duration(7 * 60), "about 7 min")
        self.assertEqual(scale.duration(90 * 60), "about 1 h 30 min")
        self.assertEqual(scale.duration(121 * 60), "about 2 h")

    def test_describe(self):
        self.assertEqual(
            scale.describe(1500),
            "1,500 packages: a sync takes about 12 min and makes about 600 "
            "requests to public services on a typical day (about 1 h and 4,600 "
            "the first time)",
        )

    def test_new_packages_cost_more(self):
        typical, _ = scale.estimate(1000)
        some_new, _ = scale.estimate(1000, 200)
        all_new, _ = scale.estimate(1000, 1000)
        self.assertLess(typical, some_new)
        self.assertLess(some_new, all_new)
        self.assertEqual(scale.estimate(10, 50), scale.estimate(10, 10))

    def test_requests_read_as_estimates(self):
        self.assertEqual(scale.about(2397), "2,400")
        self.assertEqual(scale.about(113), "110")


class Limit(unittest.TestCase):
    def test_default_and_raised(self):
        self.assertEqual(scale.limit({}), scale.MAX_PACKAGES)
        self.assertEqual(scale.limit({"maxPackages": 3000}), 3000)

    def test_only_a_positive_whole_number_raises_it(self):
        for value in (None, 0, -5, "3000", 2.5, True):
            with self.subTest(value=value):
                self.assertEqual(
                    scale.limit({"maxPackages": value}), scale.MAX_PACKAGES
                )


class Check(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        self.stderr = patcher.start()
        self.addCleanup(patcher.stop)

    def test_says_how_long_it_takes(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            scale.check({}, 300, 50)
        self.assertIn(
            "Tracking 300 packages (50 new: asked about whole, the first time): "
            "this sync should take about 6 min and make about 380 requests",
            self.stderr.getvalue(),
        )

    def test_warns_when_it_may_outlast_github(self):
        github = mock.patch.object(config, "on_github_actions", return_value=True)
        with mock.patch.dict(os.environ, {}, clear=True), github:
            scale.check({}, 4000, 100)
        self.assertNotIn("6-hour", self.stderr.getvalue())
        # Only some 8,000 new packages at once take that long now (raised
        # past the limit with maxPackages).
        with mock.patch.dict(os.environ, {}, clear=True), github:
            scale.check({"maxPackages": 9000}, 9000, 9000)
        self.assertIn("::warning::This sync may outlast", self.stderr.getvalue())

    def test_not_off_github(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            scale.check({}, 5000, 5000)
        self.assertNotIn("6-hour", self.stderr.getvalue())

    def test_and_in_the_github_summary(self):
        with tempfile.NamedTemporaryFile("r") as summary:
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": summary.name}):
                scale.check({}, 47)
            self.assertIn("Tracking 47 packages", summary.read())

    def test_refuses_past_the_limit(self):
        with self.assertRaises(Problem) as stop:
            scale.check({}, 5001)
        self.assertIn("maxPackages = 5001;", str(stop.exception))

    def test_unless_the_lists_raise_it(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            scale.check({"maxPackages": 6000}, 5001)  # no exit


class ListCheck(unittest.TestCase):
    def problems(self, lists, count):
        tracked = [f"p{i}" for i in range(count)]
        return listcheck.problems({"maintainers": [], **lists}, {}, tracked)

    def test_warns_from_1500(self):
        self.assertEqual(self.problems({}, 1499), [])
        found = self.problems({}, 1500)
        self.assertEqual(len(found), 1)
        self.assertIn("1,500 packages", found[0])

    def test_a_bad_limit(self):
        self.assertIn(
            "maxPackages: 'lots' isn't a positive whole number (using 5,000)",
            self.problems({"maxPackages": "lots"}, 1),
        )
