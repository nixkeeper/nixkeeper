"""The order of the steps that decide a row's verdict, in sync.py.

A row's verdict (nixStatus, refVersion, and whether it reads as outdated)
is built by several steps in turn, each reading what the ones before it
left. Order reads them from sync.py's source, in the order sync.main runs
them, so moving one (or calling it twice) fails there. Reordered shows why
the order matters, pair by pair: on a few rows, the two steps the other
way round give another verdict. Some neighbours have no such pair (the
two kinds of update checks cover different rows); Order still keeps
them where they are.
"""

import ast
import copy
import inspect
import io
import unittest
from unittest import mock

from nixkeeper import changes, follows, history, sync, uptodate
from nixkeeper.rows import channel_versions
from nixkeeper.shape import Row
from nixkeeper.sources import feeds, nixpkgs_update, upstream
from tests.helpers import pkg

# The steps that change or read a row's verdict, in the order sync.main
# runs them, as sync.py calls them.
VERDICT_STEPS = [
    "rows.channel_versions",
    "feed.apply",
    "uptodate.apply",
    "releases_digest.apply",
    "upstream.add_checks",
    "hydra.add_builds",
    "count_master",
    "follows.apply_versions",
    "history.add_outdated_since",
    "nixpkgs_update.add_attempts",
    "count_prs",
    "follows.apply_prs",
    "nixpkgs_update.recheck_superseded",
]


def called(function, functions):
    """Return the calls function makes, in source order, sync's own expanded.

    Args:
        function: A function definition in sync.py (ast.FunctionDef).
        functions: sync.py's functions, by name: a call of one of them is
            replaced by the calls it makes.

    Returns:
        The called names, dotted as written (rows.channel_versions).
    """
    names = []

    class Calls(ast.NodeVisitor):
        def visit_Call(self, node):
            # The arguments first: they're evaluated before the call.
            for child in [*node.args, *node.keywords]:
                self.visit(child)
            name = ast.unparse(node.func)
            if name in functions:
                names.extend(called(functions[name], functions))
            else:
                names.append(name)
            self.visit(node.func)

    for statement in function.body:
        Calls().visit(statement)
    return names


class Order(unittest.TestCase):
    def test_sync_runs_the_verdict_steps_in_this_order(self):
        tree = ast.parse(inspect.getsource(sync))
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        steps = [
            name
            for name in called(functions["main"], functions)
            if name in VERDICT_STEPS
        ]
        # Each once, in this order. If this fails because a step moved,
        # Reordered's test for that pair, if there is one, says what changes.
        self.assertEqual(
            steps,
            VERDICT_STEPS,
            "a verdict step moved, was renamed, or is called differently in "
            "sync.py: update VERDICT_STEPS (and see Reordered for what the "
            "order changes)",
        )


class Typed(unittest.TestCase):
    def test_every_verdict_step_takes_typed_rows(self):
        # mypy checks a function's body only when it has annotations, so each
        # step takes its rows as Row (shape.Row): a misspelt field in one
        # fails nix flake check. "feed" is each of sync.FEEDS.
        for name in VERDICT_STEPS:
            owner, _, attr = name.rpartition(".")
            if owner == "feed":
                functions = [getattr(feed, attr) for feed in sync.FEEDS]
            else:
                functions = [getattr(getattr(sync, owner) if owner else sync, attr)]
            for function in functions:
                with self.subTest(step=f"{function.__module__}.{attr}"):
                    first = next(iter(inspect.signature(function).parameters.values()))
                    self.assertIn(first.annotation, (Row, list[Row]))


def verdict(row):
    """What a step's order can change: the verdict, and where it came from."""
    return {
        "nixStatus": row.get("nixStatus"),
        "refVersion": row.get("refVersion"),
        "outdated": changes.is_outdated(row),
        "refFromMaster": row.get("refFromMaster"),
        "upToDate": "upToDate" in row,
        "outdatedSince": row.get("outdatedSince"),
        "update": (row.get("update") or {}).get("outcome"),
    }


class Reordered(unittest.TestCase):
    """Each pair of steps, in sync's order and the other way round."""

    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def both_ways(self, make_rows, first, then):
        """Return the rows' verdicts with first then then, and the other way round.

        Args:
            make_rows: Makes the rows afresh, for each order.
            first: A step: it takes the rows and changes them.
            then: Another step, which sync runs after first.

        Returns:
            (in sync's order, reordered): a verdict per row.
        """
        results = []
        for steps in ((first, then), (then, first)):
            rows = make_rows()
            for step in steps:
                step(rows)
            results.append([verdict(row) for row in rows])
        in_order, reordered = results
        self.assertNotEqual(in_order, reordered)
        return in_order, reordered

    def test_the_channels_version_before_an_up_to_date_rule(self):
        # The rule is for Repology's 1.0; the channel has 1.1 already, so it
        # no longer applies. The other way round, it would mark the row.
        rule = {"p": {"version": "1.0", "newest": "1.1", "reason": "x"}}
        (row,), _ = self.both_ways(
            lambda: [
                {
                    "name": "p",
                    "attrs": ["p"],
                    "nixVersion": "1.0",
                    "nixStatus": "outdated",
                    "refVersion": "1.1",
                }
            ],
            lambda rows: channel_versions(rows, {"p": pkg("p", version="1.1")}),
            lambda rows: uptodate.apply(rows, rule),
        )
        self.assertEqual((row["nixStatus"], row["upToDate"]), ("newest", False))

    def test_a_feed_before_an_up_to_date_rule(self):
        # The rule says the feed's 2.0 isn't a real release: it has the last
        # word. The other way round, the feed would.
        rule = {"p": {"version": "1.0", "newest": "2.0", "reason": "x"}}
        (row,), _ = self.both_ways(
            lambda: [{"name": "p", "nixVersion": "1.0", "nixStatus": "newest"}],
            lambda rows: feeds.compare(rows[0], "Feed", "2.0", "https://feed"),
            lambda rows: uptodate.apply(rows, rule),
        )
        self.assertEqual((row["nixStatus"], row["outdated"]), ("newest", False))

    def test_an_up_to_date_rule_before_the_update_checks(self):
        # The rule names 1.1 as not a real release, which silences a
        # worked-out check finding it. The other way round, the check would
        # still make the row outdated.
        rule = {"p": {"version": "1.0", "newest": "1.1", "reason": "x"}}
        (row,), _ = self.both_ways(
            lambda: [
                {
                    "name": "p",
                    "nixVersion": "1.0",
                    "nixStatus": "outdated",
                    "refVersion": "1.1",
                }
            ],
            lambda rows: uptodate.apply(rows, rule),
            lambda rows: upstream.apply(rows[0], {"version": "1.1", "inferred": True}),
        )
        self.assertFalse(row["outdated"])

    def test_the_update_checks_before_master(self):
        # Master's 1.2 is older than the check's 1.5: the version to update
        # to isn't master's. The other way round, the row would say it is.
        (row,), _ = self.both_ways(
            lambda: [
                {
                    "name": "p",
                    "nixVersion": "1.0",
                    "nixStatus": "newest",
                    "master": "1.2",
                }
            ],
            lambda rows: upstream.apply(rows[0], {"version": "1.5"}),
            lambda rows: changes.count_master(rows[0]),
        )
        self.assertEqual((row["refVersion"], row["refFromMaster"]), ("1.5", None))

    def test_hydras_builds_before_master(self):
        # Hydra's builds say what master has (hydra.add_builds sets
        # "master", as the first step here does: test_hydra's
        # test_add_builds_records_it checks it does), which count_master then
        # takes. The other way round, there'd be nothing to take.
        (row,), _ = self.both_ways(
            lambda: [{"name": "p", "nixVersion": "1.0", "nixStatus": "newest"}],
            lambda rows: rows[0].update(master="2.0"),
            lambda rows: changes.count_master(rows[0]),
        )
        self.assertEqual((row["refVersion"], row["refFromMaster"]), ("2.0", True))

    def test_hydras_builds_before_the_update_bot(self):
        # The bot's failed attempt at 2.0 is superseded once master has 2.0
        # (nixpkgs_update.judge, as add_attempts calls it). The other way
        # round, it would still show as failed.
        attempt = {"date": "2026-10-01", "outcome": "failed", "was": "1.0"}
        attempt["to"] = "2.0"
        (row,), _ = self.both_ways(
            lambda: [{"name": "p", "nixVersion": "1.0", "nixStatus": "outdated"}],
            lambda rows: rows[0].update(master="2.0"),
            lambda rows: nixpkgs_update.judge(rows[0], [copy.deepcopy(attempt)]),
        )
        self.assertEqual(row["update"], "superseded")

    def test_master_before_the_follows(self):
        # The follower takes the version master has for the package it
        # follows. The other way round, it would take the channel's.
        def make_rows():
            followed = {"name": "a", "nixVersion": "1.0", "master": "2.0"}
            followed["nixStatus"] = "newest"
            return [followed, {"name": "b", "nixVersion": "1.0", "nixStatus": "newest"}]

        (_, follower), _ = self.both_ways(
            make_rows,
            lambda rows: [changes.count_master(row) for row in rows],
            lambda rows: follows.apply_versions(rows, {"b": "a"}, "NOW"),
        )
        self.assertEqual(
            (follower["nixStatus"], follower["refVersion"]), ("outdated", "2.0")
        )

    def test_the_follows_before_outdated_since(self):
        # Outdated only by the version of the package it follows: it's
        # outdated since now. The other way round, it would have no date.
        # (Master needn't come first: is_outdated counts it either way.)
        def make_rows():
            followed = {"name": "a", "nixVersion": "1.0", "nixStatus": "outdated"}
            followed["refVersion"] = "2.0"
            return [followed, {"name": "b", "nixVersion": "1.0", "nixStatus": "newest"}]

        (_, follower), _ = self.both_ways(
            make_rows,
            lambda rows: follows.apply_versions(rows, {"b": "a"}, "NOW"),
            lambda rows: history.add_outdated_since(rows, {"packages": []}, "NOW"),
        )
        self.assertEqual(follower["outdatedSince"], "NOW")

    def test_master_before_the_update_prs(self):
        # Master's 2.0 is the version to update to; an open PR's 3.0 only
        # counts when nothing else names one. The other way round, the PR's
        # would.
        (row,), _ = self.both_ways(
            lambda: [
                {
                    "name": "p",
                    "nixVersion": "1.0",
                    "nixStatus": "outdated",
                    "master": "2.0",
                    "openPR": {"to": "3.0"},
                }
            ],
            lambda rows: changes.count_master(rows[0]),
            lambda rows: changes.count_prs(rows[0]),
        )
        self.assertEqual((row["refVersion"], row["refFromMaster"]), ("2.0", True))

    def test_the_update_prs_before_the_follows_prs(self):
        # A follower's version comes from the package it follows, not from
        # that package's PRs, which it's given after. The other way round,
        # the PR's version would be the follower's own.
        def make_rows():
            followed = {"name": "a", "nixVersion": "1.0", "nixStatus": "outdated"}
            followed["openPR"] = {"to": "3.0"}
            follower = {"name": "b", "nixVersion": "1.0", "nixStatus": "outdated"}
            return [followed, follower]

        (_, follower), _ = self.both_ways(
            make_rows,
            lambda rows: [changes.count_prs(row) for row in rows],
            lambda rows: follows.apply_prs(rows, {"b": "a"}),
        )
        self.assertIsNone(follower["refVersion"])

    def test_the_follows_prs_before_superseding(self):
        # A PR merged into master for the package it follows supersedes the
        # follower's failed attempt. The other way round, the attempt would
        # still show as failed.
        def make_rows():
            followed = {"name": "a", "nixVersion": "1.0", "nixStatus": "outdated"}
            followed["masterPR"] = {"to": "2.0"}
            follower = {"name": "b", "nixVersion": "1.0", "nixStatus": "outdated"}
            follower["update"] = {"outcome": "failed", "was": "1.0", "to": "2.0"}
            return [followed, follower]

        (_, follower), _ = self.both_ways(
            make_rows,
            lambda rows: follows.apply_prs(rows, {"b": "a"}),
            lambda rows: nixpkgs_update.recheck_superseded(rows),
        )
        self.assertEqual(follower["update"], "superseded")
