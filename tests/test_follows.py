"""Packages updated together with another (nixkeeper/follows.py), and the
checks of follows rules: the lists' (listcheck.py) and the community's."""

import io
import unittest
from unittest import mock

from nixkeeper import community, community_check, follows, listcheck
from nixkeeper.changes import is_outdated
from nixkeeper.history import add_outdated_since
from nixkeeper.sources import nixpkgs as nixpkgs_source
from nixkeeper.sources import upstream
from nixkeeper.verdict import decide

NOW = "2026-10-02T06:00:00+00:00"
EDGE_PR = {"number": 569248, "title": "microsoft-edge: 154.0.4258.48 -> 154.0.4258.53"}
EDGE_MERGED = {
    "number": 568437,
    "title": "microsoft-edge: 154.0.4258.37 -> 154.0.4258.48",
}


def edge(**extra):
    return {
        "name": "microsoft-edge",
        "nixVersion": "154.0.4258.37",
        "nixStatus": "outdated",
        "refVersion": "154.0.4258.53",
        **extra,
    }


def driver(**extra):
    return {
        "name": "msedgedriver",
        "nixVersion": "154.0.4258.37",
        "nixStatus": "outdated",
        "refVersion": "154.0.4258.48",
        **extra,
    }


RULE = {"msedgedriver": "microsoft-edge"}


class Rules(unittest.TestCase):
    def test_of_update_checks(self):
        checks = {
            "msedgedriver": {"follows": "microsoft-edge"},
            "microsoft-edge": {"url": "https://x", "pattern": "x"},
        }
        self.assertEqual(follows.of(checks), RULE)

    def test_recorded_on_the_rows(self):
        rows = [edge(), driver(upstream={"version": "1", "follows": "microsoft-edge"})]
        self.assertEqual(follows.recorded(rows), RULE)


class Versions(unittest.TestCase):
    def test_takes_the_newest_version_of_the_package_it_follows(self):
        rows = [edge(), driver()]
        changed = follows.apply_versions(rows, RULE, NOW)
        _, d = rows
        self.assertEqual(changed, [d])
        self.assertEqual(d["refVersion"], "154.0.4258.53")
        self.assertEqual(
            d["upstream"],
            {
                "version": "154.0.4258.53",
                "checkedAt": NOW,
                "follows": "microsoft-edge",
                "newer": True,
            },
        )
        self.assertTrue(is_outdated(d))

    def test_once_master_is_counted(self):
        # Edge's newest known only on master: the follower gets that too.
        rows = [edge(refVersion="154.0.4258.37", master="154.0.4258.48"), driver()]
        for row in rows:
            decide(row)
        follows.apply_versions(rows, RULE, NOW)
        self.assertEqual(rows[1]["refVersion"], "154.0.4258.48")

    def test_up_to_date_together(self):
        rows = [
            edge(nixVersion="154.0.4258.53", nixStatus="newest"),
            driver(nixVersion="154.0.4258.53", nixStatus="newest", refVersion=None),
        ]
        follows.apply_versions(rows, RULE, NOW)
        d = rows[1]
        self.assertFalse(d["upstream"]["newer"])
        self.assertFalse(is_outdated(d))

    def test_a_community_rule_says_so(self):
        rows = [edge(), driver()]
        follows.apply_versions(rows, RULE, NOW, community={"msedgedriver"})
        self.assertTrue(rows[1]["upstream"]["community"])

    def test_needs_both_tracked(self):
        rows = [driver()]
        self.assertEqual(follows.apply_versions(rows, RULE, NOW), [])
        self.assertNotIn("upstream", rows[0])

    def test_no_chains_and_not_itself(self):
        rows = [edge(), driver(), {"name": "x", "nixVersion": "1"}]
        chain = {"msedgedriver": "microsoft-edge", "x": "msedgedriver"}
        self.assertEqual(
            [r["name"] for r in follows.apply_versions(rows, chain, NOW)],
            ["msedgedriver"],
        )
        self.assertEqual(follows.apply_versions(rows, {"x": "x"}, NOW), [])

    def test_ages_with_it(self):
        rows = [edge(), driver(nixStatus="newest", refVersion=None)]
        follows.apply_versions(rows, RULE, NOW)
        add_outdated_since(rows, {"packages": []}, NOW)
        self.assertEqual(rows[1]["outdatedSince"], NOW)


class PRs(unittest.TestCase):
    def test_takes_its_update_prs(self):
        rows = [edge(openPR=EDGE_PR, masterPR=EDGE_MERGED), driver()]
        follows.apply_prs(rows, RULE)
        self.assertEqual(rows[1]["openPR"], EDGE_PR)
        self.assertEqual(rows[1]["masterPR"], EDGE_MERGED)

    def test_keeps_its_own_where_the_other_has_none(self):
        own = {"number": 1, "title": "msedgedriver: a -> b"}
        rows = [edge(openPR=EDGE_PR), driver(masterPR=own)]
        follows.apply_prs(rows, RULE)
        self.assertEqual(rows[1]["openPR"], EDGE_PR)
        self.assertEqual(rows[1]["masterPR"], own)


class UpdateChecks(unittest.TestCase):
    def test_follows_isnt_fetched(self):
        rows = [driver()]
        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(upstream, "check_page") as page,
            mock.patch.object(upstream, "check_github") as github,
        ):
            upstream.add_checks(
                rows,
                {"msedgedriver": {"follows": "microsoft-edge"}},
                {"packages": []},
                NOW,
            )
        page.assert_not_called()
        github.assert_not_called()
        self.assertNotIn("upstream", rows[0])


class ListCheck(unittest.TestCase):
    def problems(self, checks, tracked):
        lists = {"maintainers": [], "updateChecks": checks}
        return listcheck.problems(lists, {}, tracked)

    def test_fine(self):
        found = self.problems(
            {"msedgedriver": {"follows": "microsoft-edge"}},
            ["msedgedriver", "microsoft-edge"],
        )
        self.assertEqual(found, [])

    def test_the_package_followed_isnt_tracked(self):
        (found,) = self.problems(
            {"msedgedriver": {"follows": "microsoft-edge"}}, ["msedgedriver"]
        )
        self.assertIn("follows microsoft-edge, which isn't tracked", found)

    def test_itself_and_chains(self):
        found = self.problems(
            {"a": {"follows": "a"}, "b": {"follows": "c"}, "c": {"follows": "d"}},
            ["a", "b", "c", "d"],
        )
        self.assertIn("updateChecks.a: follows itself", found)
        self.assertTrue(
            any(f.startswith("updateChecks.b: follows c, which follows") for f in found)
        )


class Community(unittest.TestCase):
    def test_safety(self):
        self.assertIsNone(community.safety({"follows": "microsoft-edge"}))
        self.assertIsNone(community.safety({"follows": "python313Packages.requests"}))
        self.assertEqual(
            community.safety({"follows": "microsoft-edge", "frequent": True}),
            "follows takes no other fields",
        )
        for bad in ("../x", "a b", "", "x;y"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    community.safety({"follows": bad}),
                    "follows must be a nixpkgs attribute",
                )

    def test_problems(self):
        rules = {"a": {"follows": "a"}, "b": {"follows": "c"}, "c": {"follows": "d"}}
        self.assertEqual(
            community.problems(rules),
            ["a: follows itself", "b: follows c, which follows another package"],
        )

    def test_run_needs_the_package_followed_in_nixpkgs(self):
        rules = {
            "msedgedriver": {"follows": "microsoft-edge"},
            "x": {"follows": "gone"},
        }
        index = {
            "msedgedriver": {"version": "154.0.4258.37"},
            "microsoft-edge": {"version": "154.0.4258.37"},
            "x": {"version": "1"},
        }
        with (
            mock.patch.object(community, "rules", return_value=rules),
            mock.patch.object(nixpkgs_source, "load_index", return_value=index),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            results = community_check.run()
        self.assertEqual(results["msedgedriver"], ("154.0.4258.37", None))
        self.assertEqual(
            results["x"], (None, "follows gone, which isn't in nixpkgs' channel index")
        )
