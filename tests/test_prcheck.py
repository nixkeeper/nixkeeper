import io
import json
import os
import tempfile
import unittest
from unittest import mock

from nixkeeper import config, datastore, notify, prcheck, verdict
from nixkeeper.sources import github, prs_digest

URL = "https://github.com/NixOS/nixpkgs/pull/"


def pr(number, title, base="master", draft=False):
    """A pull request as the GitHub search returns it."""
    return {
        "number": number,
        "title": title,
        "url": f"{URL}{number}",
        "isDraft": draft,
        "baseRefName": base,
    }


def row(name, status="outdated", **extra):
    return {
        "name": name,
        "searchTerm": name,
        "nixStatus": status,
        "nixVersion": "1.19.24",
        "refVersion": "1.19.28",
        **extra,
    }


SINCE = "2026-10-07T12:00:00Z"


class PRCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, cwd)
        os.mkdir("data")
        # The checkout's data/, as the flake's apps pass it.
        data = mock.patch.object(config, "OUT_DIR", "data")
        data.start()
        self.addCleanup(data.stop)
        self.stderr = io.StringIO()
        patcher = mock.patch("sys.stderr", self.stderr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def publish(self, *rows):
        """The last run's data, in format 1 (as from 0.11.0: still read)."""
        index = {
            "checkedAt": "2026-09-30T06:00:00+00:00",
            "packages": list(rows),
            "verdicts": verdict.FORMAT,
        }
        with open("data/index.json", "w") as f:
            json.dump(index, f)
        self.published = [row["name"] for row in rows]
        return index

    def written(self):
        """The data the check wrote, its rows in the order published."""
        index = datastore.load("data")
        if published := getattr(self, "published", None):
            index["packages"].sort(key=lambda row: published.index(row["name"]))
        return index

    def run_check(self, answers):
        """prcheck.main() with GitHub answering {query part: [pull requests]}."""
        searched = []

        def search_batch(token, searches):
            searched.extend(q for q, _ in searches)
            return [
                next((1, prs) for key, prs in answers.items() if key in q)
                for q, _ in searches
            ]

        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "search_batch", side_effect=search_batch),
            mock.patch.object(notify, "notify") as notified,
            mock.patch.object(prcheck.nixpkgs, "channel_revision", return_value="abc"),
            mock.patch.object(
                prcheck.github_bulk, "merged_since", return_value=SINCE
            ) as since,
        ):
            prcheck.main()
        since.assert_called_once_with("abc")
        self.assertTrue(
            all(f"merged:>={SINCE}" in q for q in searched if "is:merged" in q)
        )
        return self.written(), notified, searched

    def test_open_and_merged_update_prs(self):
        self.publish(
            row("wesnoth-devel"),
            row("unciv"),
            row("backrest", "newest"),  # not outdated: not searched
        )
        index, notified, searched = self.run_check(
            {
                "in:title wesnoth-devel": [],
                "state:open in:title unciv": [pr(7, "unciv: 4.22.1 -> 4.22.5")],
                f"merged:>={SINCE} in:title unciv": [],
            }
        )
        wesnoth, unciv, _ = index["packages"]
        self.assertEqual(unciv["openPR"]["number"], 7)
        self.assertNotIn("openPR", wesnoth)
        self.assertFalse(any("backrest" in q for q in searched))
        notified.assert_called_once()

    def test_the_digests_facts_kept_for_the_same_pr(self):
        facts = {"mergeBot": "ready"}
        self.publish(
            {**row("unciv"), "openPR": {"number": 7, "to": "4.22.5", "facts": facts}},
            {**row("wesnoth-devel"), "openPR": {"number": 8, "facts": facts}},
        )
        index, _, _ = self.run_check(
            {
                "state:open in:title unciv": [pr(7, "unciv: 4.22.1 -> 4.22.5")],
                "state:open in:title wesnoth-devel": [
                    pr(9, "wesnoth-devel: 1.19.24 -> 1.19.29")
                ],
                "is:merged": [],
            }
        )
        unciv, wesnoth = index["packages"]
        self.assertEqual(unciv["openPR"]["facts"], facts)
        self.assertNotIn("facts", wesnoth["openPR"])  # another PR now

    def test_merged_into_master_is_on_master_before_hydra(self):
        self.publish(row("wesnoth-devel"))
        index, _, _ = self.run_check(
            {
                "state:open": [],
                "is:merged": [
                    # Into staging: weeks from master, so not "on master".
                    pr(8, "wesnoth-devel: 1.19.24 -> 1.19.30", base="staging"),
                    pr(6, "wesnoth-devel: 1.19.24 -> 1.19.28"),
                    pr(5, "wesnoth-devel: 1.19.22 -> 1.19.24"),  # already in
                ],
            }
        )
        [wesnoth] = index["packages"]
        self.assertEqual(wesnoth["masterPR"]["number"], 6)
        self.assertNotIn("master", wesnoth)  # Hydra hasn't built it: no matter

    def test_merged_pr_supersedes_the_bots_failure(self):
        failed = {
            "attr": "wesnoth-devel",
            "date": "2026-09-22",
            "outcome": "failed",
            "was": "wesnoth-devel-1.19.24",
        }
        self.publish(row("wesnoth-devel", update=failed, updateFailure=True))
        index, _, _ = self.run_check(
            {
                "state:open": [],
                "is:merged": [pr(6, "wesnoth-devel: 1.19.24 -> 1.19.28")],
            }
        )
        [wesnoth] = index["packages"]
        self.assertFalse(wesnoth["updateFailure"])
        self.assertEqual(
            (wesnoth["update"]["outcome"], wesnoth["update"]["supersededOn"]),
            ("superseded", "master"),
        )

    def test_data_from_before_waits_for_a_sync(self):
        """Rows written before repologyVerdict was: a check's, master's or a
        rule's verdict there can't be told from Repology's, so nothing is
        decided again or published until a sync with this version."""
        said = {"status": "outdated", "newest": "155.0"}
        rows = [
            row("chrome", nixStatus="newest", refVersion=None, repologySaid=said),
            row(
                "unciv",
                nixVersion="4.22.1",
                refVersion="4.22.5",
                master="4.22.5",
                refFromMaster=True,
            ),
        ]
        before = self.publish(*rows)
        del before["verdicts"]
        with open("data/index.json", "w") as f:
            json.dump(before, f)
        with (
            open("data/index.json") as f,
            mock.patch.object(prcheck.nixpkgs, "channel_revision") as asked,
            mock.patch.object(notify, "notify") as notified,
        ):
            written = f.read()
            prcheck.main()
        asked.assert_not_called()
        notified.assert_not_called()
        with open("data/index.json") as f:
            self.assertEqual(f.read(), written)
        self.assertIn("nothing is published until a full sync", self.stderr.getvalue())

    def test_nothing_changed_writes_nothing(self):
        existing = {
            "number": 7,
            "title": "unciv: 4.22.1 -> 4.22.5",
            "url": f"{URL}7",
            "draft": False,
            "base": "master",
            "from": "4.22.1",
            "to": "4.22.5",
        }
        before = self.publish(row("unciv", nixVersion="4.22.1", openPR=existing))
        index, notified, _ = self.run_check(
            {"state:open": [pr(7, "unciv: 4.22.1 -> 4.22.5")], "is:merged": []}
        )
        self.assertEqual(index, before)
        notified.assert_not_called()

    def test_failed_search_keeps_what_was_there(self):
        existing = {"number": 7, "to": "1.19.28", "url": f"{URL}7", "draft": False}
        self.publish(row("wesnoth-devel", openPR=existing))
        with (
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(
                github, "search_batch", side_effect=lambda t, s: [(None, [])] * len(s)
            ),
            mock.patch.object(notify, "notify"),
            mock.patch.object(prcheck.nixpkgs, "channel_revision", return_value="abc"),
            mock.patch.object(prcheck.github_bulk, "merged_since", return_value=SINCE),
        ):
            prcheck.main()
        self.assertEqual(self.written()["packages"][0]["openPR"], existing)

    def test_the_followed_packages_prs(self):
        """A package updated together with another (follows.py) gets its
        update PRs too: their titles name only the other package."""
        follows = {"version": "1.19.28", "newer": True, "follows": "wesnoth"}
        self.publish(row("wesnoth"), row("wesnoth-data", upstream=follows))
        index, _, _ = self.run_check(
            {
                "state:open in:title wesnoth-data": [],
                f"merged:>={SINCE} in:title wesnoth-data": [],
                "state:open in:title wesnoth": [pr(9, "wesnoth: 1.19.24 -> 1.19.28")],
                f"merged:>={SINCE} in:title wesnoth": [],
            }
        )
        wesnoth, data = index["packages"]
        self.assertEqual(data["openPR"], wesnoth["openPR"])
        self.assertEqual(data["openPR"]["number"], 9)

    # With nixkeeper-prs' digest: every outdated package from its lists, the
    # maintainers' packages searched for directly too.
    def run_with(self, digest, answers):
        with mock.patch.object(prs_digest, "load", return_value=digest):
            return self.run_check(answers)

    def test_the_maintainers_searched_the_others_not(self):
        self.publish(
            row("unciv", lists=["maintained"]),
            row("wesnoth-devel", lists=["gaming"]),
            row("xonotic"),  # not on a list: the rest of nixpkgs
        )
        digest = {
            "open": (
                [
                    pr(7, "unciv: 1.19.24 -> 1.19.28"),
                    pr(8, "wesnoth-devel: 1.19.24 -> 1.19.28"),
                    pr(9, "xonotic: 1.19.24 -> 1.19.28"),
                ],
                [],
            ),
            "merged": [
                pr(10, "xonotic: 1.19.24 -> 1.19.27"),
                {
                    **pr(11, "unciv: 1.19.24 -> 1.19.27"),
                    "author": "r-ryantm",
                    "mergedBy": "alice",
                },
            ],
            "facts": prs_digest.facts(
                [
                    {
                        "n": 8,
                        "title": "wesnoth-devel: 1.19.24 -> 1.19.28",
                        "mergeBot": {"ready": True},
                        "mergeable": "MERGEABLE",
                    }
                ],
                [],
                [],
            ),
        }
        index, _, searched = self.run_with(
            digest,
            {
                "state:open in:title unciv": [pr(7, "unciv: 1.19.24 -> 1.19.28")],
                f"merged:>={SINCE} in:title unciv": [
                    pr(11, "unciv: 1.19.24 -> 1.19.27")
                ],
            },
        )
        unciv, wesnoth, xonotic = index["packages"]
        # Found by the search too: who merged it kept, from the digest.
        self.assertEqual(
            (unciv["masterPR"]["number"], unciv["masterPR"]["mergedBy"]), (11, "alice")
        )
        # Only the maintainers' package searched for.
        self.assertTrue(searched)
        self.assertTrue(all("unciv" in q for q in searched))
        self.assertEqual(unciv["openPR"]["number"], 7)
        self.assertEqual(wesnoth["openPR"]["number"], 8)
        self.assertEqual(wesnoth["openPR"]["facts"], {"mergeBot": "ready"})
        self.assertEqual(xonotic["openPR"]["number"], 9)
        self.assertEqual(xonotic["masterPR"]["number"], 10)

    def test_a_stale_digest_searches_as_before(self):
        self.publish(row("wesnoth-devel", lists=["gaming"]))
        index, _, searched = self.run_with(
            {"open": None, "merged": None},
            {
                "state:open in:title wesnoth-devel": [
                    pr(8, "wesnoth-devel: 1.19.24 -> 1.19.28")
                ],
                "is:merged": [],
            },
        )
        self.assertTrue(any("wesnoth-devel" in q for q in searched))
        self.assertEqual(index["packages"][0]["openPR"]["number"], 8)
