"""Up-to-date rules (nixkeeper/uptodate.py): a version Repology gets wrong,
counted as up to date until nixpkgs moves on or a newer release shows up."""

import io
import unittest
from unittest import mock

from nixkeeper import uptodate
from nixkeeper.changes import is_outdated
from nixkeeper.verdict import decide

RULE = {"version": "2018-05-16", "newest": "1.1.1", "reason": "A snapshot."}


def pacvim(**extra):
    return {
        "name": "pacvim",
        "nixVersion": "2018-05-16",
        "nixStatus": "untrusted",
        "refVersion": "1.1.1",
        **extra,
    }


def apply(rows, rules, community=frozenset()):
    err = io.StringIO()
    with mock.patch("sys.stderr", err):
        marked = uptodate.apply(rows, rules, community)
    return marked, err.getvalue()


class Applies(unittest.TestCase):
    def test_marks_the_row_up_to_date(self):
        row = pacvim()
        marked, notices = apply([row], {"pacvim": RULE})
        self.assertEqual(marked, ["pacvim"])
        self.assertEqual(row["nixStatus"], "newest")
        self.assertIsNone(row["refVersion"])
        self.assertEqual(
            row["upToDate"],
            {
                "status": "untrusted",
                "newest": "1.1.1",
                "ruleNewest": "1.1.1",
                "reason": "A snapshot.",
            },
        )
        self.assertEqual(notices, "")

    def test_an_older_newest_still_applies(self):
        row = pacvim(refVersion="1.0")
        apply([row], {"pacvim": RULE})
        self.assertIn("upToDate", row)

    def test_without_newest_when_repology_shows_none(self):
        row = pacvim(refVersion=None)
        apply([row], {"pacvim": {"version": "2018-05-16", "reason": "x"}})
        self.assertEqual(row["upToDate"], {"status": "untrusted", "reason": "x"})

    def test_a_community_rule_says_so(self):
        row = pacvim()
        apply([row], {"pacvim": RULE}, community={"pacvim"})
        self.assertTrue(row["upToDate"]["community"])

    def test_outdated_rows_too(self):
        # Repology compares with a version that isn't really newer.
        row = pacvim(nixStatus="outdated")
        apply([row], {"pacvim": RULE})
        self.assertFalse(is_outdated(row))

    def test_master_still_counts(self):
        row = pacvim(master="2019-01-01")
        apply([row], {"pacvim": RULE})
        decide(row)
        self.assertTrue(is_outdated(row))


class Ends(unittest.TestCase):
    def test_when_nixpkgs_moves_on(self):
        row = pacvim(nixVersion="2018-06-01")
        marked, notices = apply([row], {"pacvim": RULE})
        self.assertEqual(marked, [])
        self.assertEqual(row["nixStatus"], "untrusted")
        self.assertNotIn("upToDate", row)
        self.assertIn(
            "upToDate.pacvim: nixpkgs is now at 2018-06-01; the rule can go", notices
        )

    def test_when_a_newer_release_shows_up(self):
        row = pacvim(refVersion="1.2.0")
        marked, notices = apply([row], {"pacvim": RULE})
        self.assertEqual(marked, [])
        self.assertEqual(row["refVersion"], "1.2.0")
        self.assertIn("Repology now shows 1.2.0 as newest elsewhere", notices)

    def test_without_newest_any_newest_ends_it(self):
        row = pacvim()
        marked, _ = apply([row], {"pacvim": {"version": "2018-05-16", "reason": "x"}})
        self.assertEqual(marked, [])

    def test_community_rules_are_community_checks_to_report(self):
        row = pacvim(nixVersion="2018-06-01")
        _, notices = apply([row], {"pacvim": RULE}, community={"pacvim"})
        self.assertEqual(notices, "")

    def test_untracked_is_skipped(self):
        marked, notices = apply([pacvim()], {"other": RULE})
        self.assertEqual((marked, notices), ([], ""))
