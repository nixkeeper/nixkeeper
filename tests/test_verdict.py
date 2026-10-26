"""Deciding a row's verdict from what the sources found (nixkeeper/verdict.py)."""

import ast
import itertools
import pathlib
import types
import unittest
from unittest import mock

from nixkeeper import config, datastore, rows, sync, verdict
from nixkeeper.sources import nixpkgs, upstream
from nixkeeper.verdict import decide


def row(status="newest", ref=None, nix="1.0", **found):
    """A row as Repology left it, with what the other sources found."""
    return {
        "name": "p",
        "nixVersion": nix,
        "nixStatus": status,
        "refVersion": ref,
        **found,
    }


def outcome(r):
    """The verdict, and where its parts came from."""
    return (
        r["nixStatus"],
        r["refVersion"],
        r.get("refFromMaster"),
        r.get("refFromPR"),
        r.get("repologySaid"),
    )


class Rules(unittest.TestCase):
    """Each rule, on its own."""

    def test_repologys_verdict_when_nothing_else_is_found(self):
        r = row("outdated", "1.1")
        decide(r)
        self.assertEqual(outcome(r), ("outdated", "1.1", None, None, None))
        self.assertNotIn("repologyVerdict", r)

    def test_channel_caught_up(self):
        # The channel has 1.1, which Repology hasn't seen yet.
        r = row("outdated", "1.1", nix="1.1", repologyVersion="1.0")
        decide(r)
        self.assertEqual(r["nixStatus"], "newest")
        # A kept series is kept again.
        r = row("outdated", "1.1", nix="1.1", repologyVersion="1.0")
        r["keptBeside"] = {"attr": "q", "version": "2.0"}
        decide(r)
        self.assertEqual(r["nixStatus"], config.KEPT)
        # Not caught up, or no version named: as Repology says.
        r = row("outdated", "1.2", nix="1.1", repologyVersion="1.0")
        decide(r)
        self.assertEqual(r["nixStatus"], "outdated")
        r = row("outdated", None, nix="1.1", repologyVersion="1.0")
        decide(r)
        self.assertEqual(r["nixStatus"], "outdated")

    def test_feed(self):
        r = row("newest", None, feed={"version": "2.0"})
        decide(r)
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("outdated", "2.0"))
        r = row("outdated", "3.0", feed={"version": "1.0"})
        decide(r)
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("newest", "1.0"))
        # Kept beside the newest (typst_digest): kept, against the feed.
        r = row("newest", feed={"version": "2.0"}, keptBeside={"attr": "q"})
        decide(r)
        self.assertEqual((r["nixStatus"], r["refVersion"]), (config.KEPT, "2.0"))

    def test_up_to_date_rule(self):
        r = row("outdated", "1.1", upToDate={"status": "outdated", "reason": "x"})
        decide(r)
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("newest", None))
        # It overrules a feed, too.
        r["feed"] = {"version": "2.0"}
        decide(r)
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("newest", None))

    def check(self, status="newest", ref=None, inferred=False, **more):
        found = {"version": "2.0", "newer": True}
        if inferred:
            found["inferred"] = True
        return row(status, ref, upstream=found, **more)

    def test_update_check_newer(self):
        # A rule's check overrules Repology's "newest", keeping what it said.
        r = self.check("newest", "1.0")
        decide(r)
        self.assertEqual(
            outcome(r),
            ("outdated", "2.0", None, None, {"status": "newest", "newest": "1.0"}),
        )
        # Already outdated against an even newer version: that one stays.
        r = self.check("outdated", "3.0")
        decide(r)
        self.assertEqual(outcome(r), ("outdated", "3.0", None, None, None))

    def test_update_check_not_newer(self):
        r = row("outdated", "1.5", upstream={"version": "1.0", "newer": False})
        decide(r)
        self.assertEqual(
            outcome(r),
            ("newest", None, None, None, {"status": "outdated", "newest": "1.5"}),
        )

    def test_update_checks_that_dont_decide(self):
        cases = {
            # Worked out: only adds the version.
            "worked out": self.check("newest", "1.0", inferred=True),
            # A rule's last result, kept as it failed this time.
            "failing": self.check(
                "newest", "1.0", notRefreshed={"upstream": {"since": "x"}}
            ),
            # A kept version: the newest release isn't the one to compare with.
            "kept": self.check(config.KEPT, "1.0"),
        }
        for name, r in cases.items():
            with self.subTest(name):
                status = r["nixStatus"]
                decide(r)
                self.assertEqual(r["nixStatus"], status)
                self.assertEqual(r["refVersion"], "2.0")
                self.assertNotIn("repologySaid", r)

    def test_master(self):
        r = row("newest", None, master="2.0")
        decide(r)
        self.assertEqual((r["refVersion"], r["refFromMaster"]), ("2.0", True))
        # A newer known release stays (unciv: master 4.22.5, 4.22.6 out).
        r = row("outdated", "4.22.6", nix="4.22.1", master="4.22.5")
        decide(r)
        self.assertEqual((r["refVersion"], r.get("refFromMaster")), ("4.22.6", None))

    def test_master_after_the_update_check(self):
        # The check's 1.5 is newer than master's 1.2: not master's version.
        r = row(
            "newest", None, master="1.2", upstream={"version": "1.5", "newer": True}
        )
        decide(r)
        self.assertEqual((r["refVersion"], r.get("refFromMaster")), ("1.5", None))

    def test_update_prs(self):
        # chatgpt, 2026-10-16: Repology says outdated, names nothing newer.
        r = row("outdated", None, nix="26.1007.21434")
        r["masterPR"], r["openPR"] = {"to": "26.1007.71326"}, {"to": "26.1013.31256"}
        decide(r)
        self.assertEqual((r["refVersion"], r["refFromPR"]), ("26.1013.31256", True))
        # Master's version counts first.
        r = row("outdated", None, master="2.0", openPR={"to": "3.0"})
        decide(r)
        self.assertEqual((r["refVersion"], r.get("refFromPR")), ("2.0", None))

    def test_rules_in_this_order(self):
        names = [rule.__name__ for rule in verdict.RULES]
        self.assertEqual(
            names,
            [
                "_channel",
                "_feed",
                "_up_to_date",
                "_update_check",
                "_master",
                "_update_prs",
            ],
        )


class FromRepologys(unittest.TestCase):
    """Repology's verdict, kept while the verdict differs from it."""

    def test_kept_while_it_differs(self):
        r = row("newest", None, master="2.0")
        decide(r)
        self.assertEqual(r["repologyVerdict"], {"status": "newest"})
        # Master's caught up (the channel has it): Repology's again.
        r["nixVersion"] = "2.0"
        decide(r)
        self.assertEqual(outcome(r), ("newest", None, None, None, None))
        self.assertNotIn("repologyVerdict", r)

    def test_a_finding_gone_goes_back_to_repologys(self):
        # The PR closed, as the hourly check finds.
        r = row("outdated", None, openPR={"to": "2.0"})
        decide(r)
        self.assertEqual(r["refVersion"], "2.0")
        del r["openPR"]
        decide(r)
        self.assertEqual(outcome(r), ("outdated", None, None, None, None))
        self.assertNotIn("repologyVerdict", r)

    def test_deciding_again_changes_nothing(self):
        r = row(
            "newest", "1.0", master="3.0", upstream={"version": "2.0", "newer": True}
        )
        decide(r)
        once = dict(r)
        decide(r)
        self.assertEqual(r, once)

    def test_whatever_order_the_findings_come_in(self):
        # Each source records, then decides: the verdict is the same in any
        # order, as it's worked out from Repology's each time.
        findings = {
            "check": lambda r: upstream.record(r, {"version": "2.0"}),
            "master": lambda r: r.update(master="2.5"),
            "pr": lambda r: r.update(openPR={"to": "3.0"}),
            "channel": lambda r: r.update(nixVersion="1.1", repologyVersion="1.0"),
        }
        results = set()
        for order in itertools.permutations(findings):
            r = row("outdated", None)
            for name in order:
                findings[name](r)
                decide(r)
            results.add(repr(sorted(r.items())))
        self.assertEqual(len(results), 1)


# The fields only verdict.decide writes, once a row's Repology verdict is set.
VERDICT = ("nixStatus", "refVersion")


def writes(node):
    """Return whether an ast node writes one of VERDICT's fields.

    That's an assignment to row["nixStatus"] (plain, augmented or
    annotated), a call of .update naming one, or a dict literal with one.
    A key held in a variable isn't seen (frequent.refresh_repology's
    row[key] = fresh[key]).
    """
    if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(part, ast.Subscript)
            and isinstance(part.slice, ast.Constant)
            and part.slice.value in VERDICT
            for target in targets
            for part in ast.walk(target)
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
    ):
        return any(k.arg in VERDICT for k in node.keywords) or any(
            isinstance(a, ast.Dict) and writes(a) for a in node.args
        )
    if isinstance(node, ast.Dict):
        return any(
            isinstance(k, ast.Constant) and k.value in VERDICT for k in node.keys
        )
    return False


class OnlyHere(unittest.TestCase):
    def test_only_verdict_and_repologys_verdict_write_it(self):
        # Anything else writing nixStatus or refVersion would be undone by the
        # next decide, or would be taken for Repology's verdict.
        allowed = {
            "verdict.py:decide",
            # Repology's verdict, with its corrections.
            "rows.py:make_row",
            *(f"rows.py:{c.__name__}" for c in rows.CORRECTIONS),
            "rows.py:_add_from_index",  # "unlisted", for a row Repology hasn't
            # Repology's fresh verdict.
            "frequent.py:refresh_repology",
            # The rows community-check makes to run the checks on.
            "community_check.py:run",
            # A copy of a row as Repology had it, for the log (not the row).
            "inferred.py:report",
        }
        package = pathlib.Path(verdict.__file__).parent
        writers = set()
        for path in package.rglob("*.py"):
            name = path.relative_to(package).as_posix()
            for function in ast.walk(ast.parse(path.read_text())):
                if not isinstance(function, ast.FunctionDef):
                    continue
                for node in ast.walk(function):
                    if writes(node):
                        writers.add(f"{name}:{function.name}")
        self.assertLessEqual(writers, allowed)

    def test_each_way_of_writing_it_is_seen(self):
        for code in (
            'row["nixStatus"] = "x"',
            'row["refVersion"] += "x"',
            'row["nixStatus"]: str = "x"',
            'row.update(nixStatus="x")',
            'row.update({"refVersion": "x"})',
            'r = {"nixStatus": "x"}',
        ):
            with self.subTest(code):
                self.assertTrue(any(writes(n) for n in ast.walk(ast.parse(code))))
        self.assertFalse(any(writes(n) for n in ast.walk(ast.parse('row["x"] = 1'))))


class Decidable(unittest.TestCase):
    def test_the_sync_says_its_rows_can_be_decided_again(self):
        run = types.SimpleNamespace(
            now="NOW", everything=False, lists={}, evaluations=nixpkgs.Evaluations()
        )
        with mock.patch.object(datastore, "write") as written:
            sync.write(run, {}, [], [], {}, [], {})
        index = written.call_args.args[0]
        self.assertTrue(verdict.decidable(index))
        # Data from before: not.
        self.assertFalse(
            verdict.decidable({k: v for k, v in index.items() if k != "verdicts"})
        )
