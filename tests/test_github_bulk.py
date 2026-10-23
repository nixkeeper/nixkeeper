import io
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import github, github_bulk


def pr(number, title, base="master", draft=False):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/NixOS/nixpkgs/pull/{number}",
        "isDraft": draft,
        "baseRefName": base,
    }


PRS = [
    pr(1, "wine: 10.15 -> 10.16"),
    pr(2, "winetricks: 20250102 -> 20260125"),
    pr(3, "wesnoth-devel: 1.19.24 -> 1.19.28", draft=True),
    pr(4, "wesnoth-devel: 1.19.24 -> 1.19.29"),
    pr(5, "python3Packages.requests: 2.34.2 -> 2.35.0", base="staging"),
    pr(6, "treewide: drop Wine 9 from games"),
    # GitHub's search finds "wine" here (underscores split words).
    pr(9, "winetricks: make WINE_BIN overridable"),
]
ISSUES = [
    {"number": 7, "title": "wine: crashes on start"},
    {"number": 8, "title": "Build failure: winetricks"},
]


class Words(unittest.TestCase):
    def test_as_githubs_search_matched_them(self):
        # Checked against GitHub's answers on 2026-10-05.
        self.assertIn("trigger", github_bulk.title_words("nixos: enable led triggers"))
        self.assertIn(
            "velocity", github_bulk.title_words("MidiMonster: above certain velocities")
        )
        self.assertTrue(
            {"wine", "bin"} <= github_bulk.title_words("make WINE_BIN work")
        )
        self.assertEqual(github_bulk.words("_1password-gui"), {"_1password", "gui"})
        self.assertNotIn(
            "_1password", github_bulk.title_words("nixos/1password-gui: x")
        )

    def test_stem(self):
        for word, stemmed in {
            "velocities": "velocity",
            "triggers": "trigger",
            "patches": "patch",
            "class": "class",
            "nixos": "nixo",  # consistently on both sides, so still a match
            "us": "us",
            "status": "status",
        }.items():
            self.assertEqual(github_bulk.stem(word), stemmed, word)


class Listing(unittest.TestCase):
    listing = github_bulk.Listing(PRS, ISSUES)

    def test_search_whole_words_in_any_case(self):
        # Not winetricks; "Wine 9" and WINE_BIN count, as GitHub's search's do.
        self.assertEqual(self.listing.search_counts("wine"), (3, 1))
        self.assertEqual(self.listing.search_counts("winetricks"), (2, 1))

    def test_search_every_word_of_the_term(self):
        self.assertEqual(self.listing.search_counts("wesnoth-devel"), (2, 0))
        self.assertEqual(self.listing.search_counts("python3Packages.requests"), (1, 0))
        self.assertEqual(self.listing.search_counts("nothing-like-it"), (0, 0))

    def test_counts_titles_naming_it(self):
        row = lambda name, term=None, attrs=(): {  # noqa: E731
            "name": name,
            "searchTerm": term or name,
            "attrs": list(attrs),
        }
        # PRs by nixpkgs' title convention: not "treewide: drop Wine 9" (it
        # mentions wine), nor WINE_BIN (a word); issues with the name whole.
        self.assertEqual(self.listing.counts(row("wine")), (1, 1))
        self.assertEqual(self.listing.counts(row("winetricks")), (2, 1))
        self.assertEqual(self.listing.counts(row("wesnoth")), (0, 0))
        self.assertEqual(
            self.listing.counts(
                row(
                    "python313Packages.requests",
                    "python3Packages.requests",
                    ["python313Packages.requests"],
                )
            ),
            (1, 0),
        )

    def test_title_names(self):
        self.assertEqual(
            github_bulk.title_names("Build failure: pkg-config."),
            {"build", "failure", "pkg-config"},
        )
        self.assertNotIn("pkg", github_bulk.title_names("pkgs/top-level: tidy pkgs"))

    def test_open_update_pr(self):
        row = {
            "name": "wesnoth-devel",
            "searchTerm": "wesnoth-devel",
            "nixVersion": "1.19.24",
        }
        # The one aiming highest, as github.open_update_pr picks among a
        # search's results.
        self.assertEqual(self.listing.open_update_pr(row)["number"], 4)
        self.assertIsNone(
            self.listing.open_update_pr(
                {"name": "x", "searchTerm": "x", "nixVersion": "1"}
            )
        )

    def test_open_update_pr_after_another_change(self):
        # d-seams: listed under every name its title updates, not only the first.
        listing = github_bulk.Listing(
            [pr(10, "minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0")], []
        )
        row = {"name": "d-seams", "searchTerm": "d-seams", "nixVersion": "2.10.0"}
        self.assertEqual(listing.open_update_pr(row)["number"], 10)

    def test_open_update_pr_titled_with_another_attribute(self):
        # heroic: "heroic-unwrapped: 2.22.3 -> 2.22.4", one of its attributes.
        listing = github_bulk.Listing([pr(9, "heroic-unwrapped: 2.22.3 -> 2.22.4")], [])
        row = {
            "name": "heroic",
            "searchTerm": "heroic",
            "attrs": ["heroic", "heroic-unwrapped"],
            "nixVersion": "2.22.3",
        }
        self.assertEqual(listing.open_update_pr(row)["number"], 9)


class ListOpen(unittest.TestCase):
    def page(self, nodes, more, cursor):
        return {"pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}

    def test_pages_both_until_each_ends(self):
        answers = [
            {
                "repository": {
                    "pullRequests": self.page(PRS[:3], True, "p1"),
                    "issues": self.page(ISSUES, False, "i1"),
                }
            },
            {"repository": {"pullRequests": self.page(PRS[3:], False, "p2")}},
        ]
        with mock.patch.object(github, "graphql", side_effect=answers) as graphql:
            prs, issues = github_bulk.list_open("t")
        self.assertEqual((len(prs), len(issues)), (7, 2))
        second = graphql.call_args_list[1].args[2]
        self.assertEqual(
            (second["prs"], second["morePrs"], second["moreIssues"]),
            ("p1", True, False),
        )

    def test_a_missing_answer_fails_the_listing(self):
        with (
            mock.patch.object(github, "graphql", return_value={}),
            self.assertRaises(ValueError),
        ):
            github_bulk.list_open("t")


class AddCounts(unittest.TestCase):
    NOW = "2026-10-05T06:00:00+00:00"

    def test_counts_every_row(self):
        rows = [
            {"name": "wine", "searchTerm": "wine", "nixVersion": "10.15"},
            {"name": "winetricks", "searchTerm": "winetricks", "openPR": {"number": 9}},
        ]
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github_bulk, "list_open", return_value=(PRS, ISSUES)),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertTrue(github_bulk.add_counts(rows, self.NOW))
        wine, winetricks = rows
        self.assertEqual((wine["openPRs"], wine["openIssues"]), (1, 1))
        # GitHub's search, which the page links, also has those mentioning it.
        self.assertEqual(wine["searchShowsMore"], ["pr"])
        self.assertNotIn("searchShowsMore", winetricks)
        self.assertEqual(wine["openPR"]["number"], 1)
        self.assertEqual(wine["countedAt"], self.NOW)
        self.assertEqual((winetricks["openPRs"], winetricks["openIssues"]), (2, 1))
        # Found again: its open update PR now, not the one it had.
        self.assertEqual(winetricks["openPR"]["number"], 2)

    def test_failure_changes_nothing(self):
        rows = [{"name": "wine", "searchTerm": "wine", "openPRs": 5}]
        out = io.StringIO()
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github_bulk, "list_open", side_effect=OSError("down")),
            mock.patch("sys.stderr", out),
        ):
            self.assertFalse(github_bulk.add_counts(rows, self.NOW))
        self.assertEqual(rows, [{"name": "wine", "searchTerm": "wine", "openPRs": 5}])
        self.assertIn("searching per package", out.getvalue())
        with mock.patch.object(github, "token", return_value=None):
            self.assertFalse(github_bulk.add_counts(rows, self.NOW))

    def test_from_the_digests_lists_without_a_token(self):
        rows = [{"name": "wine", "searchTerm": "wine", "nixVersion": "10.15"}]
        with (
            mock.patch.object(github, "token", return_value=None),
            mock.patch.object(github_bulk, "list_open") as list_open,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertTrue(github_bulk.add_counts(rows, self.NOW, (PRS, ISSUES)))
        list_open.assert_not_called()
        self.assertEqual((rows[0]["openPRs"], rows[0]["openIssues"]), (1, 1))
        self.assertEqual(rows[0]["openPR"]["number"], 1)


class MasterPRs(unittest.TestCase):
    NOW = "2026-10-05T06:00:00+00:00"

    def search(self, nodes, more=False, count=None):
        return {
            "search": {
                "issueCount": len(nodes) if count is None else count,
                "pageInfo": {"hasNextPage": more, "endCursor": "c"},
                "nodes": nodes,
            }
        }

    def test_windows_and_pages(self):
        answers = [
            self.search([pr(1, "a: 1 -> 2")], more=True),
            self.search([pr(2, "b: 1 -> 2")]),
            self.search([pr(3, "c: 1 -> 2")]),
        ]
        with mock.patch.object(github, "graphql", side_effect=answers) as graphql:
            found = github_bulk.list_merged("t", "2026-10-04T12:00:00Z", self.NOW)
        self.assertEqual([p["number"] for p in found], [1, 2, 3])
        queries = [c.args[2]["q"] for c in graphql.call_args_list]
        self.assertTrue(
            queries[0].endswith("merged:2026-10-04T12:00:00Z..2026-10-05T00:00:00Z")
        )
        self.assertEqual(graphql.call_args_list[1].args[2]["after"], "c")
        self.assertTrue(
            queries[2].endswith("merged:2026-10-05T00:00:00Z..2026-10-05T06:00:00Z")
        )
        self.assertIn("is:pr is:merged base:master", queries[0])

    def test_over_searchs_limit_fails(self):
        with (
            mock.patch.object(
                github, "graphql", return_value=self.search([], count=1001)
            ),
            self.assertRaises(ValueError),
        ):
            github_bulk.list_merged("t", "2026-10-05T00:00:00Z", self.NOW)

    def test_add_master_prs(self):
        rows = [
            {
                "name": "wesnoth-devel",
                "searchTerm": "wesnoth-devel",
                "nixVersion": "1.19.24",
            },
            {
                "name": "x",
                "searchTerm": "x",
                "nixVersion": "1",
                "masterPR": {"number": 1},
            },
        ]
        merged = [pr(4, "wesnoth-devel: 1.19.24 -> 1.19.29"), pr(5, "wesnoth: 1 -> 2")]
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(
                github_bulk, "channel_date", return_value="2026-10-03T17:36:20Z"
            ),
            mock.patch.object(
                github_bulk, "list_merged", return_value=merged
            ) as listed,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertTrue(github_bulk.add_master_prs(rows, "a7868a7", self.NOW))
        listed.assert_called_once_with("t", "2026-10-03T17:36:20Z", self.NOW)
        self.assertEqual(rows[0]["masterPR"]["number"], 4)
        self.assertNotIn("masterPR", rows[1])  # found again, or not at all

    def test_from_the_digests_list(self):
        rows = [
            {
                "name": "wesnoth-devel",
                "searchTerm": "wesnoth-devel",
                "nixVersion": "1.19.24",
            }
        ]
        merged = [pr(4, "wesnoth-devel: 1.19.24 -> 1.19.29")]
        with (
            mock.patch.object(github, "token", return_value=None),
            mock.patch.object(github_bulk, "list_merged") as listed,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertTrue(github_bulk.add_master_prs(rows, "rev", self.NOW, merged))
        listed.assert_not_called()
        self.assertEqual(rows[0]["masterPR"]["number"], 4)
        # Who opened and merged it, from the digest: kept for the fix's credit.
        merged = [
            {
                **pr(4, "wesnoth-devel: 1.19.24 -> 1.19.29"),
                "author": "r-ryantm",
                "mergedBy": "alice",
            }
        ]
        with mock.patch("sys.stderr", io.StringIO()):
            github_bulk.add_master_prs(rows, "rev", self.NOW, merged)
        self.assertEqual(
            (rows[0]["masterPR"]["author"], rows[0]["masterPR"]["mergedBy"]),
            ("r-ryantm", "alice"),
        )

    def test_failure_changes_nothing(self):
        rows = [{"name": "x", "searchTerm": "x", "masterPR": {"number": 1}}]
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github_bulk, "channel_date", return_value=None),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertFalse(github_bulk.add_master_prs(rows, "rev", self.NOW))
        self.assertEqual(rows[0]["masterPR"], {"number": 1})


class MergedSince(unittest.TestCase):
    """The channel's commit date, bounding the per-package merged PR
    searches (github.add_update_prs)."""

    def test_the_channels_commit_date(self):
        with (
            mock.patch.object(github_bulk.github, "token", return_value="t"),
            mock.patch.object(
                github_bulk, "channel_date", return_value="2026-10-07T12:00:00Z"
            ) as asked,
        ):
            self.assertEqual(github_bulk.merged_since("abc"), "2026-10-07T12:00:00Z")
        asked.assert_called_once_with("t", "abc")

    def test_none_when_it_cant_be_known(self):
        with mock.patch.object(github_bulk.github, "token", return_value=None):
            self.assertIsNone(github_bulk.merged_since("abc"))  # no token
        with mock.patch.object(github_bulk.github, "token", return_value="t"):
            # The revision couldn't be fetched: the branch's name instead.
            self.assertIsNone(github_bulk.merged_since(config.NIXPKGS_BRANCH))
            with (
                mock.patch.object(
                    github_bulk, "channel_date", side_effect=OSError("down")
                ),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                self.assertIsNone(github_bulk.merged_since("abc"))
