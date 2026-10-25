import io
import unittest
from datetime import datetime, timedelta
from unittest import mock

from nixkeeper import config, schedule
from nixkeeper.sources import github
from tests.helpers import http_error, response

# When the channel's commit was made, for merged PR searches.
SINCE = "2026-10-07T12:00:00Z"


class GitHubCounts(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_counts_line_up_with_rows_across_batches(self):
        rows = [{"searchTerm": t} for t in ("a", "b", "c")]
        seen = []

        def search_batch(token, searches):
            seen.append(len(searches))
            # Encode each query in its count so misalignment would show.
            return [(len(q) + ("is:issue" in q), []) for q, _ in searches]

        with (
            mock.patch.object(config, "GITHUB_SEARCH_BATCH", 4),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "search_batch", side_effect=search_batch),
        ):
            github.add_counts(rows)
        self.assertEqual(seen, [4, 2])
        for row in rows:
            term = f"in:title {row['searchTerm']} sort:updated-desc"
            pr = f"repo:NixOS/nixpkgs is:pr state:open {term}"
            issue = f"repo:NixOS/nixpkgs is:issue state:open {term}"
            self.assertEqual(
                (row["openPRs"], row["openIssues"]), (len(pr), len(issue) + 1)
            )

    def test_no_token_skips_counts(self):
        rows = [{"searchTerm": "a"}]
        with mock.patch.object(github, "token", return_value=None):
            github.add_counts(rows)
        self.assertNotIn("openPRs", rows[0])

    def test_partial_graphql_answer(self):
        resp = response(
            {
                "data": {"s0": {"issueCount": 3}, "s1": None},
                "errors": [{"message": "s1 failed"}],
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(github.search_counts("t", ["q0", "q1"]), [3, None])

    def test_failed_request_blanks_its_batch(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)):
            self.assertEqual(github.search_counts("t", ["q0", "q1"]), [None, None])


class CountWarnings(unittest.TestCase):
    @staticmethod
    def rows(*counts):
        return [
            {"searchTerm": str(i), "openPRs": p, "openIssues": i_}
            for i, (p, i_) in enumerate(counts)
        ]

    def test_prs_mirroring_issues_warns(self):
        [warning] = github.count_warnings(
            self.rows((5, 5), (1, 1), (0, 0), (0, 0), (2, 2))
        )
        self.assertIn("pull-requests: read", warning)

    def test_real_looking_counts_dont_warn(self):
        # 17 of 28 were equal in real data (mostly 0/0): only *all* equal is suspicious.
        self.assertEqual(
            github.count_warnings(self.rows((1, 5), (1, 1), (0, 0), (0, 0), (1, 0))), []
        )

    def test_all_zero_or_too_few_rows_dont_warn(self):
        self.assertEqual(github.count_warnings(self.rows(*[(0, 0)] * 10)), [])
        self.assertEqual(github.count_warnings(self.rows((3, 3), (1, 1))), [])

    def test_failed_searches_warn(self):
        [warning] = github.count_warnings(self.rows((1, None), (None, None), (0, 0)))
        self.assertIn("3 of 6", warning)

    def test_add_counts_prints_warnings(self):
        rows = [{"searchTerm": t} for t in "abcde"]
        stderr = io.StringIO()
        with (
            mock.patch("sys.stderr", stderr),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(
                github, "search_batch", side_effect=lambda tok, s: [(2, [])] * len(s)
            ),
        ):
            github.add_counts(rows)
        self.assertIn(
            "warning: every package's open PR count equals", stderr.getvalue()
        )


def pr(number, title, draft=False, base="master"):
    """A pull request as the GitHub search returns it."""
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/NixOS/nixpkgs/pull/{number}",
        "isDraft": draft,
        "baseRefName": base,
    }


class UpdatePRs(unittest.TestCase):
    ROW = {"searchTerm": "wesnoth-devel", "nixVersion": "1.19.24"}

    def test_only_this_packages_update_prs(self):
        nodes = [
            pr(1, "wesnoth-devel: 1.19.24 -> 1.19.28"),
            pr(2, "wesnoth-devel-extra: 1.0 -> 1.1"),  # another package
            pr(3, "wesnoth-devel: fix build on darwin"),  # not an update
            pr(4, "treewide: bump wesnoth-devel and friends"),
        ]
        self.assertEqual(
            [p["number"] for p in github.update_prs(nodes, "wesnoth-devel")], [1]
        )

    def test_versions_without_the_titles_punctuation(self):
        # "fribidi: 1.0.16 -> 1.0.17, and more", "python313: ... -> 3.13.16;".
        nodes = [
            pr(1, "fribidi: 1.0.16 -> 1.0.17, also fix cross"),
            pr(2, "fribidi: 1.0.16, -> 1.0.18; drop patch"),
            pr(3, "fribidi: 1.0.16 -> 1.0.19:"),
        ]
        self.assertEqual(
            [(p["from"], p["to"]) for p in github.update_prs(nodes, "fribidi")],
            [("1.0.16", "1.0.17"), ("1.0.16", "1.0.18"), ("1.0.16", "1.0.19")],
        )

    def test_an_update_anywhere_in_the_title(self):
        nodes = [
            # Second of two changes (d-seams, 2026-10-16).
            pr(
                1,
                "minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0, enable on darwin",
            ),
            # Several names for one update.
            pr(2, "chromium,chromedriver: 155.0.8059.79 -> 155.0.8059.84"),
            pr(3, "goose-cli, goose-desktop: 1.49.0 -> 1.54.0"),
            # Not an update of these: an init, another package.
            pr(4, "d-seams-extra: init at 1.0"),
        ]

        def found(name):
            return [
                (p["number"], p["from"], p["to"])
                for p in github.update_prs(nodes, name)
            ]

        self.assertEqual(found("d-seams"), [(1, "2.10.0", "2.11.0")])
        self.assertEqual(found("chromedriver"), [(2, "155.0.8059.79", "155.0.8059.84")])
        self.assertEqual(found("goose-desktop"), [(3, "1.49.0", "1.54.0")])
        self.assertEqual(found("minimage"), [])  # its part is an init
        self.assertEqual(
            github.title_packages(nodes[0]["title"]), {"minimage", "d-seams"}
        )
        # After its tags: a backport, a work in progress (libsidplayfp's,
        # 2026-10-23, counted 1 of its 2 PRs).
        for title in (
            "[26.05] libsidplayfp: Apply fix for CVE-2026-111148",
            "[Backport release-26.05] libsidplayfp: Apply fix",
            "[WIP] (Part 2) libsidplayfp: tidy",
        ):
            self.assertEqual(github.title_packages(title), {"libsidplayfp"})

    def test_titled_with_another_of_its_attributes(self):
        """heroic, 2026-10-15: its update was titled "heroic-unwrapped: ...",
        an attribute of the same row, at the same version."""
        row = {
            "searchTerm": "heroic",
            "attrs": ["heroic", "heroic-unwrapped"],
            "nixVersion": "2.22.3",
        }
        nodes = [
            pr(1, "heroic-unwrapped: 2.22.3 -> 2.22.4"),
            pr(2, "heroic-extra: 1.0 -> 1.1"),  # not one of its attributes
        ]
        self.assertEqual(github.open_update_pr(row, nodes)["number"], 1)
        self.assertEqual(github.merged_update_pr(row, nodes)["number"], 1)
        # A row without attributes: its search term alone, as before.
        self.assertIsNone(github.open_update_pr({**row, "attrs": []}, nodes))

    def test_open_update_pr_aims_highest_ready_first(self):
        nodes = [
            pr(1, "wesnoth-devel: 1.19.24 -> 1.19.26"),
            pr(2, "wesnoth-devel: 1.19.24 -> 1.19.28", draft=True),
            pr(3, "wesnoth-devel: 1.19.24 -> 1.19.28"),
            pr(4, "wesnoth-devel: 1.19.20 -> 1.19.22"),  # older than nixpkgs: stale
        ]
        found = github.open_update_pr(self.ROW, nodes)
        self.assertEqual(
            (found["number"], found["to"], found["draft"]), (3, "1.19.28", False)
        )
        self.assertIsNone(github.open_update_pr(self.ROW, [nodes[3]]))

    def test_merged_update_pr_into_master_only(self):
        nodes = [
            pr(5, "wesnoth-devel: 1.19.22 -> 1.19.24"),  # already in the channel
            pr(6, "wesnoth-devel: 1.19.24 -> 1.19.28"),
            pr(8, "wesnoth-devel: 1.19.24 -> 1.19.30", base="staging"),
        ]
        self.assertEqual(github.merged_update_pr(self.ROW, nodes)["number"], 6)
        self.assertIsNone(github.merged_update_pr(self.ROW, [nodes[0], nodes[2]]))

    def test_add_counts_finds_them(self):
        row = {**self.ROW, "master": "1.19.28", "openPR": {"number": 0}}
        answers = {
            "is:pr state:open": (1, [pr(7, "wesnoth-devel: 1.19.24 -> 1.19.30")]),
            "is:issue": (0, []),
            "is:merged": (9, [pr(6, "wesnoth-devel: 1.19.24 -> 1.19.28")]),
        }

        def search_batch(token, searches):
            return [
                next(a for key, a in answers.items() if key in q) for q, _ in searches
            ]

        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "search_batch", side_effect=search_batch),
        ):
            github.add_counts([row])
        self.assertEqual((row["openPRs"], row["openIssues"]), (1, 0))
        self.assertEqual(row["openPR"]["number"], 7)  # replaced, not kept
        self.assertNotIn("masterPR", row)  # add_update_prs' job

    def test_add_update_prs(self):
        row = {**self.ROW}
        answers = {
            "is:pr state:open": (1, [pr(7, "wesnoth-devel: 1.19.24 -> 1.19.30")]),
            "is:merged": (9, [pr(6, "wesnoth-devel: 1.19.24 -> 1.19.28")]),
        }
        searched = []

        def search_batch(token, searches):
            searched.extend(q for q, _ in searches)
            return [
                next(a for key, a in answers.items() if key in q) for q, _ in searches
            ]

        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "search_batch", side_effect=search_batch),
        ):
            github.add_update_prs([row], merged_since=SINCE)
            self.assertEqual(
                (row["openPR"]["number"], row["masterPR"]["number"]), (7, 6)
            )
            # Merged since the channel's commit only: older ones are in it.
            self.assertIn(f"is:merged merged:>={SINCE}", searched[1])
            searched.clear()
            github.add_update_prs([row], open_prs=False, merged_since=SINCE)
            self.assertEqual(len(searched), 1)
            self.assertIn("is:merged", searched[0])
            # The channel's date unknown: merged PRs not searched, the row's
            # masterPR as it was (not one from before the channel).
            searched.clear()
            github.add_update_prs([row])
        self.assertEqual([q for q in searched if "is:merged" in q], [])
        self.assertEqual(row["masterPR"]["number"], 6)

    def test_search_batch_returns_pull_requests(self):
        resp = response(
            {
                "data": {
                    "s0": {"issueCount": 2, "nodes": [pr(1, "a: 1 -> 2"), {}]},
                    "s1": {"issueCount": 5},
                }
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            results = github.search_batch("t", [("q0", 20), ("q1", 0)])
        self.assertEqual(results, [(2, [pr(1, "a: 1 -> 2")]), (5, [])])
        query = urlopen.call_args.args[0].data.decode()
        self.assertIn("first: 20", query)
        self.assertIn("isDraft", query)


class QuietCounts(unittest.TestCase):
    """Packages with no open PRs or issues and nothing pending are searched
    every QUIET_DAYS (schedule.py), not daily."""

    NOW = "2026-10-05T06:00:00+00:00"

    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def count(self, rows, previous, now=None, answer=(0, 0)):
        """add_counts with every search answering answer (PRs, issues):
        (the names searched)."""
        searched = []

        def search_batch(token, searches):
            out = []
            for q, _ in searches:
                name = q.split("in:title ")[1].split(" ")[0]
                if name not in searched:
                    searched.append(name)
                out.append((answer[1] if "is:issue" in q else answer[0], []))
            return out

        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "search_batch", side_effect=search_batch),
        ):
            github.add_counts(rows, {"packages": previous}, now or self.NOW)
        return searched

    def row(self, name="hello", **extra):
        return {"name": name, "searchTerm": name, "nixStatus": "newest", **extra}

    def counted(self, name="hello", days=1, prs=0, issues=0):
        when = datetime.fromisoformat(self.NOW) - timedelta(days=days)
        return {
            "name": name,
            "openPRs": prs,
            "openIssues": issues,
            "countedAt": when.isoformat(),
        }

    def not_its_day(self, name="hello"):
        when = datetime.fromisoformat(self.NOW)
        while schedule.slot(name, when):
            when += timedelta(days=1)
        return when.isoformat()

    def test_quiet_and_counted_recently_isnt_searched(self):
        now = self.not_its_day()
        before = self.counted(days=1)
        before["countedAt"] = (
            datetime.fromisoformat(now) - timedelta(days=1)
        ).isoformat()
        rows = [self.row()]
        self.assertEqual(self.count(rows, [before], now), [])
        self.assertEqual(
            (rows[0]["openPRs"], rows[0]["openIssues"], rows[0]["countedAt"]),
            (0, 0, before["countedAt"]),
        )

    def test_quiet_but_three_days_old_is_searched(self):
        now = self.not_its_day()
        before = self.counted()
        before["countedAt"] = (
            datetime.fromisoformat(now) - timedelta(days=3)
        ).isoformat()
        rows = [self.row()]
        self.assertEqual(self.count(rows, [before], now), ["hello"])
        self.assertEqual(rows[0]["countedAt"], now)

    def test_something_going_on_counted_hours_ago_is_kept(self):
        now = self.not_its_day()
        before = {
            **self.counted(prs=2),
            "countedAt": (datetime.fromisoformat(now) - timedelta(hours=3)).isoformat(),
            "openPR": {"number": 7},
        }
        rows = [self.row()]
        self.assertEqual(self.count(rows, [before], now), [])
        self.assertEqual(rows[0]["openPRs"], 2)
        self.assertEqual(rows[0]["openPR"], {"number": 7})
        self.assertEqual(rows[0]["countedAt"], before["countedAt"])

    def test_something_going_on_is_searched_daily(self):
        now = self.not_its_day()
        recent = (datetime.fromisoformat(now) - timedelta(hours=22)).isoformat()
        for name, row, before in (
            ("open PRs", self.row(), {**self.counted(prs=2), "countedAt": recent}),
            (
                "open issues",
                self.row(),
                {**self.counted(issues=1), "countedAt": recent},
            ),
            (
                "outdated",
                self.row(nixStatus="outdated"),
                {**self.counted(), "countedAt": recent},
            ),
            ("never counted", self.row(), {**self.counted(), "countedAt": None}),
            ("a failed search", self.row(), {**self.counted(prs=None)}),
        ):
            with self.subTest(name):
                self.assertEqual(self.count([row], [before], now), ["hello"])

    def test_new_packages_are_searched(self):
        self.assertEqual(self.count([self.row()], []), ["hello"])

    def test_a_failed_search_isnt_dated(self):
        rows = [self.row()]
        self.count(rows, [], answer=(None, 0))
        self.assertNotIn("countedAt", rows[0])

    def test_without_the_last_run_everything_is_searched(self):
        # As before the schedule: no previous data, no time.
        rows = [self.row()]
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(
                github, "search_batch", return_value=[(0, []), (0, [])]
            ) as search,
        ):
            github.add_counts(rows)
        search.assert_called_once()
        self.assertNotIn("countedAt", rows[0])
