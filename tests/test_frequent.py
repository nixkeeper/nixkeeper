import io
import json
import os
import tempfile
import unittest
from unittest import mock

from nixkeeper import config, datastore, frequent, notify
from nixkeeper.errors import Problem
from nixkeeper.sources import github, http, repology
from nixkeeper.sources import nixpkgs as nixpkgs_source
from tests.helpers import nix, other

CHECKS = {
    "google-chrome": {
        "url": "https://versionhistory.example/chrome",
        "pattern": r'"version": "([0-9.]+)"',
        "frequent": True,
    },
    "bbedit": {"url": "https://example.org/bbedit", "pattern": r"BBEdit ([0-9.]+)"},
}


def chrome_row(**extra):
    return {
        "name": "google-chrome",
        "attrs": ["google-chrome"],
        "project": "google-chrome",
        "dataFile": "google-chrome.json",
        "nixVersion": "154.0.8037.57",
        "nixStatus": "newest",
        "nixVulnerable": False,
        "refVersion": "154.0.8037.57",
        "repoCount": 1,
        "builds": [],
        "unfree": True,
        **extra,
    }


def entries(nix_version, newest):
    return [
        nix(
            "google-chrome",
            nix_version,
            "newest" if nix_version == newest else "outdated",
        ),
        other("arch", newest, "newest"),
    ]


def api(*versions):
    return json.dumps({"versions": [{"version": v} for v in versions]})


class FrequentCheck(unittest.TestCase):
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
        index = {"checkedAt": "2026-09-30T06:00:00+00:00", "packages": list(rows)}
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

    def run_frequent(self, page, nix_version="154.0.8037.57", newest="154.0.8037.57"):
        """frequent.main() with Repology answering nix_version for nixpkgs and
        the check's URL answering page."""
        with (
            mock.patch.object(
                nixpkgs_source, "read_lists", return_value={"updateChecks": CHECKS}
            ),
            mock.patch.object(
                repology,
                "project_by_name",
                return_value=("google-chrome", entries(nix_version, newest)),
            ),
            mock.patch.object(http, "get_page", return_value=(page, {})) as get,
            mock.patch.object(notify, "notify") as notified,
            # Never a GitHub token (nor the local gh login) from the tests.
            mock.patch.object(github, "token", return_value=None),
        ):
            frequent.main()
        return self.written(), notified, get

    def test_new_release_is_written_and_notified(self):
        before = self.publish(chrome_row(), {"name": "bbedit", "attrs": ["bbedit"]})
        index, notified, get = self.run_frequent(api("154.0.8040.12", "154.0.8037.57"))
        chrome = index["packages"][0]
        self.assertEqual(chrome["refVersion"], "154.0.8040.12")
        self.assertTrue(chrome["upstream"]["newer"])
        self.assertIn("outdatedSince", chrome)
        self.assertEqual(index["packages"][1], before["packages"][1])  # untouched
        self.assertEqual(index["checkedAt"], before["checkedAt"])  # the full sync's
        get.assert_called_once_with(
            CHECKS["google-chrome"]["url"], None, False
        )  # not bbedit's
        notified.assert_called_once()
        self.assertEqual(notified.call_args.args[0], before)  # compared with before
        # The subscribers' issues: theirs among every row, only those with news.
        self.assertEqual(
            [r["name"] for r in notified.call_args.kwargs["everyone"]],
            ["google-chrome", "bbedit"],
        )
        self.assertTrue(notified.call_args.kwargs["news_only"])
        self.assertTrue(datastore.entries(chrome, "data"))  # refreshed, in its shard

    def test_other_rows_keep_their_entries_read_once(self):
        """Format 2: the rows not checked keep their Repology entries, read
        from the shards once each, not a shard per row."""
        bbedit = {"name": "bbedit", "attrs": ["bbedit"], "dataFile": "bbedit.json"}
        kept = [other("arch", "15.5", "newest")]
        sources = {"hydra": {"used": True, "eval": 1829817}}
        datastore.write(
            {
                "checkedAt": "2026-09-30T06:00:00+00:00",
                "packages": [chrome_row(), bbedit],
                "sources": sources,
            },
            {
                "google-chrome.json": entries("154.0.8037.57", "154.0.8037.57"),
                "bbedit.json": kept,
            },
        )
        with mock.patch.object(datastore, "entries") as one_by_one:
            self.run_frequent(api("154.0.8040.12", "154.0.8037.57"))
        one_by_one.assert_not_called()
        self.assertEqual(datastore.entries(bbedit), kept)
        # The daily sync's sources stay: an hourly check isn't a sync.
        self.assertEqual(datastore.load()["sources"], sources)

    def test_nothing_changed_writes_nothing(self):
        up = {
            "version": "154.0.8037.57",
            "label": "versionhistory.example",
            "url": CHECKS["google-chrome"]["url"],
            "checkedAt": "2026-09-30T06:00:00+00:00",
            "newer": False,
        }
        before = self.publish(chrome_row(upstream=up))
        index, notified, _ = self.run_frequent(api("154.0.8037.57"))
        self.assertEqual(index, before)
        notified.assert_not_called()
        self.assertIn("Nothing changed", self.stderr.getvalue())

    def test_master_ahead_survives_the_repology_refresh(self):
        """Master has a version Repology and the check haven't seen: the
        refresh puts Repology's refVersion back, then master counts again."""
        self.publish(
            chrome_row(
                master="154.0.8040.12",
                refVersion="154.0.8040.12",
                refFromMaster=True,
                outdatedSince="2026-09-30T07:23:00+00:00",
            )
        )
        index, _, _ = self.run_frequent(api("154.0.8037.57"))
        chrome = index["packages"][0]
        self.assertEqual(chrome["refVersion"], "154.0.8040.12")
        self.assertTrue(chrome["refFromMaster"])
        self.assertEqual(chrome["outdatedSince"], "2026-09-30T07:23:00+00:00")

    def test_nixpkgs_catching_up_clears_outdated(self):
        up = {"version": "154.0.8040.12", "url": "x", "newer": True}
        self.publish(
            chrome_row(
                refVersion="154.0.8040.12",
                upstream=up,
                outdatedSince="2026-09-30T07:23:00+00:00",
            )
        )
        index, _, _ = self.run_frequent(
            api("154.0.8040.12"), nix_version="154.0.8040.12", newest="154.0.8040.12"
        )
        chrome = index["packages"][0]
        self.assertEqual(chrome["nixVersion"], "154.0.8040.12")
        self.assertFalse(chrome["upstream"]["newer"])
        self.assertNotIn("outdatedSince", chrome)

    def test_the_channels_version_survives_the_repology_refresh(self):
        """microsoft-edge, 2026-10-08: the daily sync took .62 from the
        channel, Repology still had .53; the hourly refresh put .53 back and
        the check read it as outdated."""
        self.publish(
            chrome_row(
                nixVersion="154.0.8040.12",
                refVersion="154.0.8040.12",
                repologyVersion="154.0.8037.57",
            )
        )
        index, _, _ = self.run_frequent(
            api("154.0.8040.12"), nix_version="154.0.8037.57", newest="154.0.8040.12"
        )
        chrome = index["packages"][0]
        self.assertEqual(
            (chrome["nixVersion"], chrome["nixStatus"], chrome["repologyVersion"]),
            ("154.0.8040.12", "newest", "154.0.8037.57"),
        )
        self.assertFalse(chrome["upstream"]["newer"])
        self.assertNotIn("outdatedSince", chrome)

    def test_repology_catching_up_drops_its_old_version(self):
        self.publish(
            chrome_row(
                nixVersion="154.0.8040.12",
                refVersion="154.0.8040.12",
                repologyVersion="154.0.8037.57",
            )
        )
        index, _, _ = self.run_frequent(
            api("154.0.8040.12"), nix_version="154.0.8040.12", newest="154.0.8040.12"
        )
        chrome = index["packages"][0]
        self.assertEqual(chrome["nixVersion"], "154.0.8040.12")
        self.assertNotIn("repologyVersion", chrome)

    def test_failing_check_is_marked_and_notified_once(self):
        self.publish(chrome_row())
        index, notified, _ = self.run_frequent("<html>moved</html>")
        failing = index["packages"][0]["notRefreshed"]["upstream"]
        self.assertIn("matches", failing["reason"])
        notified.assert_called_once()
        # Next hour, still failing: nothing new to write or say.
        _, notified, _ = self.run_frequent("<html>moved</html>")
        notified.assert_not_called()

    def test_needs_a_previous_sync(self):
        with self.assertRaises(Problem):
            frequent.main()

    def test_follows_the_new_release(self):
        """A package updated together with one this check refreshes
        (follows.py) gets its new version in the same run."""
        follows = {
            "version": "154.0.8037.57",
            "newer": False,
            "follows": "google-chrome",
        }
        driver = {
            "name": "chromedriver",
            "attrs": ["chromedriver"],
            "nixVersion": "154.0.8037.57",
            "nixStatus": "newest",
            "refVersion": "154.0.8037.57",
            "upstream": follows,
        }
        self.publish(chrome_row(), driver)
        index, notified, _ = self.run_frequent(api("154.0.8040.12", "154.0.8037.57"))
        chrome, driver = index["packages"]
        self.assertEqual(driver["refVersion"], "154.0.8040.12")
        self.assertEqual(driver["upstream"]["follows"], "google-chrome")
        self.assertTrue(driver["upstream"]["newer"])
        self.assertEqual(driver["outdatedSince"], chrome["outdatedSince"])
        notified.assert_called_once()
