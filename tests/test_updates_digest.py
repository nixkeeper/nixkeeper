"""nixkeeper-updates' digest of nixpkgs-update, and the attempts taken from
it (nixpkgs_update.add_attempts)."""

import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, http, nixpkgs_update, updates_digest
from tests.helpers import pkg

NOW = "2026-10-05T18:00:00+00:00"
LOG = "https://nixpkgs-update-logs.nixos.org"


def read(attr, outcome="failed", day="2026-10-05", parser=nixpkgs_update.PARSER):
    """An attempt as the digest reads it (with its start)."""
    return {
        "attr": attr,
        "date": day,
        "started": 1791210053,
        "log": f"{LOG}/{attr}/{day}.log",
        "parser": parser,
        "outcome": outcome,
    }


class Load(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def serve(self, meta, entries):
        body = gzip.compress(
            "".join(json.dumps(e) + "\n" for e in entries).encode(), mtime=0
        )
        return (
            mock.patch.object(config, "UPDATES_DIGEST_URL", "https://d/"),
            mock.patch.object(http, "get", return_value=json.dumps(meta)),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        )

    def test_current(self):
        meta = {"format": 1, "fetchedAt": "2026-10-05T15:00:00+00:00"}
        patches = self.serve(meta, [{"attr": "wesnoth", "attempt": read("wesnoth")}])
        with patches[0], patches[1], patches[2], patches[3]:
            found = updates_digest.load(NOW)
        self.assertEqual(found, {"wesnoth": {"attempt": read("wesnoth")}})
        # Noted for the page: when it's from, and how many it hasn't read.
        self.assertEqual(
            self.noted["updates"],
            {"used": True, "at": "2026-10-05T15:00:00+00:00", "pending": 0},
        )

    def test_old_or_off_isnt_used(self):
        meta = {"format": 1, "fetchedAt": "2026-10-04T15:00:00+00:00"}
        patches = self.serve(meta, [])
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertIsNone(updates_digest.load(NOW))
        self.assertEqual(
            self.noted["updates"],
            {"used": False, "why": "too old", "at": "2026-10-04T15:00:00+00:00"},
        )
        self.noted.clear()
        with mock.patch.object(config, "UPDATES_DIGEST_URL", ""):
            self.assertIsNone(updates_digest.load(NOW))
        self.assertEqual(self.noted, {})  # turned off: nothing to say

    def test_attempt_only_when_read_with_these_rules(self):
        entry = {"attempt": read("python3Packages.foo")}
        attempt = updates_digest.attempt(
            entry, "python313Packages.foo", nixpkgs_update.PARSER
        )
        self.assertEqual(attempt["attr"], "python313Packages.foo")  # nixkeeper's
        self.assertNotIn("started", attempt)
        self.assertIsNone(updates_digest.attempt({**entry, "pending": "x"}, "a", 2))
        self.assertIsNone(updates_digest.attempt(entry, "a", nixpkgs_update.PARSER + 1))


class AddAttempts(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, rows, digest, bulk=frozenset(), read=None):
        nixpkgs = {a: pkg(a) for row in rows for a in row["attrs"]}
        with (
            mock.patch.object(nixpkgs_update, "directory_dates", return_value=None),
            mock.patch.object(
                nixpkgs_update, "latest_attempt", side_effect=read or AssertionError
            ) as latest,
        ):
            nixpkgs_update.add_attempts(
                rows, nixpkgs, {"packages": []}, NOW, bulk=bulk, digest=digest
            )
        return latest

    def test_from_the_digest_without_reading_a_log(self):
        rows = [{"name": "wesnoth", "attrs": ["wesnoth"], "nixVersion": "1.18.7"}]
        self.add(rows, {"wesnoth": {"attempt": read("wesnoth")}})
        self.assertEqual(rows[0]["update"]["outcome"], "failed")
        self.assertTrue(rows[0]["updateFailure"])

    def test_never_tried(self):
        rows = [{"name": "new", "attrs": ["new"], "nixVersion": "1"}]
        self.add(rows, {})
        self.assertIsNone(rows[0]["update"])

    def test_a_lists_package_pending_there_is_read(self):
        rows = [{"name": "unciv", "attrs": ["unciv"], "nixVersion": "1"}]
        digest = {"unciv": {"attempt": read("unciv", "noChange"), "pending": "x"}}
        fresh = {**read("unciv", "prOpened"), "pr": 1}
        fresh.pop("started")
        latest = self.add(rows, digest, read=lambda *a: dict(fresh))
        latest.assert_called_once()
        self.assertEqual(rows[0]["update"]["outcome"], "prOpened")

    def test_sets_updated_in_bulk_from_the_digest_only(self):
        # The bot tries some (TeX Live, Emacs): their attempts as any
        # package's; none is read from the logs, digest or not.
        rows = [
            {"name": "texlivePackages.a", "attrs": ["texlivePackages.a"], "set": "t"},
            {"name": "texlivePackages.b", "attrs": ["texlivePackages.b"], "set": "t"},
        ]
        names = {row["name"] for row in rows}
        digest = {"texlivePackages.a": {"attempt": read("texlivePackages.a")}}
        self.add(rows, digest, bulk=names)
        self.assertEqual(rows[0]["update"]["outcome"], "failed")
        self.assertIsNone(rows[1]["update"])  # never tried
        for row in rows:
            row.pop("update")
        self.add(rows, None, bulk=names)  # no digest: no logs read either
        self.assertNotIn("update", rows[0])

    def test_in_bulk_the_last_read_or_unread(self):
        rows = [
            {"name": "behind", "attrs": ["behind"], "nixVersion": "1"},
            {"name": "never", "attrs": ["never"], "nixVersion": "1"},
        ]
        digest = {
            "behind": {"attempt": read("behind", "noChange"), "pending": "x"},
            "never": {"pending": "x"},
        }
        self.add(rows, digest, bulk={"behind", "never"})
        self.assertEqual(rows[0]["update"]["outcome"], "noChange")
        self.assertNotIn("unread", rows[0])
        self.assertIsNone(rows[1]["update"])
        self.assertEqual(rows[1]["unread"], ["update"])


# The digest's copy of the bot's queue (nixkeeper-updates' queue.json.gz): a
# 10-day cycle of 1,000 positions, made at noon.
QUEUE = {
    "updatedAt": "2026-10-05T12:00:00+00:00",
    "cycleDays": 10.0,
    "positions": 1000,
    "queue": {
        "proxyman": {
            "position": 1,
            "script": True,
            "candidates": [
                ["3.16.1", "3.21.0", "https://github.com/p/proxyman/releases"],
                ["3.16.1", "26.0.1", "https://repology.org/project/proxyman/versions"],
            ],
        },
        "unciv": {
            "position": 500,
            "candidates": [
                ["4.22.5", "4.22.7", "https://github.com/yairm210/Unciv/releases"],
                ["4.22.5", "4.22.7", "https://repology.org/project/unciv/versions"],
            ],
        },
        "unciv-beta": {"position": 900, "script": True},
        "python3Packages.requests": {"position": 1000, "script": True},
    },
}


class Queue(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def load(self, queue, now=NOW):
        body = gzip.compress(json.dumps(queue).encode(), mtime=0) if queue else None
        with (
            mock.patch.object(config, "UPDATES_DIGEST_URL", "https://d/"),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            return updates_digest.load_queue(now)

    def test_the_day_each_is_expected(self):
        found = self.load(QUEUE)
        # Position p of n: p / n of a cycle after the page was made.
        self.assertEqual(found["proxyman"]["by"], "2026-10-05")
        self.assertEqual(found["unciv"]["by"], "2026-10-10")  # half a cycle
        self.assertEqual(found["python3Packages.requests"]["by"], "2026-10-15")
        self.assertEqual(found["unciv-beta"]["candidates"], [])
        self.assertTrue(found["unciv-beta"]["script"])
        self.assertFalse(found["unciv"]["script"])
        self.assertEqual(
            self.noted["queue"],
            {"used": True, "at": "2026-10-05T12:00:00+00:00", "cycleDays": 10.0},
        )

    def test_none_too_old_or_unreadable(self):
        self.assertIsNone(self.load(None))
        self.assertEqual(self.noted["queue"]["used"], False)
        self.assertIsNone(self.load(QUEUE, now="2026-10-06T13:00:00+00:00"))
        self.assertEqual(self.noted["queue"]["why"], "too old")
        self.assertIsNone(self.load({"nonsense": True}))
        self.assertIn("couldn't be read", self.noted["queue"]["why"])

    def test_rows(self):
        found = self.load(QUEUE)
        nixpkgs = {
            "unciv": pkg("unciv", "4.22.5"),
            "unciv-beta": pkg("unciv", "4.22.7"),
            "python313Packages.requests": pkg("requests", "2.32"),
            "hello": pkg("hello", "2.12"),
        }
        rows = [
            {"name": "unciv", "attrs": ["unciv", "unciv-beta"], "nixVersion": "4.22.5"},
            # The bot's name for it (search_term): python3Packages.
            {
                "name": "python313Packages.requests",
                "attrs": ["python313Packages.requests"],
            },
            {"name": "hello", "attrs": ["hello"], "nixVersion": "2.12"},
            # A set's: queued too, when the bot has it in its queue.
            {"name": "haskellPackages.x", "attrs": ["unciv"], "set": "x"},
            {"name": "gone", "attrs": ["proxyman"]},  # not in nixpkgs
        ]
        nixpkgs_update.add_queue(rows, nixpkgs, found)
        unciv, requests, hello, in_set, gone = rows
        # Its soonest attribute's day, the versions nixpkgs doesn't have.
        self.assertEqual(
            unciv["queued"],
            {
                "by": "2026-10-10",
                "candidates": [
                    ["4.22.7", "https://github.com/yairm210/Unciv/releases"],
                    ["4.22.7", "https://repology.org/project/unciv/versions"],
                ],
            },
        )
        # Its updateScript only: no version, the script decides.
        self.assertEqual(requests["queued"], {"by": "2026-10-15", "script": True})
        self.assertEqual(in_set["queued"]["by"], "2026-10-10")
        for row in (hello, gone):  # not in the queue, gone
            self.assertNotIn("queued", row)
        # Without a queue, nothing.
        rows = [{"name": "unciv", "attrs": ["unciv"]}]
        nixpkgs_update.add_queue(rows, nixpkgs, None)
        self.assertNotIn("queued", rows[0])
