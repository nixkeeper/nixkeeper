"""GitHub releases from nixkeeper-versions' digest, as worked-out checks."""

import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.changes import is_outdated
from nixkeeper.sources import about, http, releases_digest

NOW = "2026-10-09T06:00:00+00:00"


def entry(version, tag=None, release=None, read="2026-10-09", repo="o/r"):
    found = {"repo": repo, "version": version, "read": read}
    if tag:
        found["tag"] = tag
    if release:
        found["release"] = release
    return found


def row(name, version, status="newest", ref=None, lists=()):
    found = {
        "name": name,
        "attrs": [name],
        "nixVersion": version,
        "nixStatus": status,
        "lists": list(lists),
    }
    if ref:
        found["refVersion"] = ref
    return found


class Result(unittest.TestCase):
    def test_a_release_first(self):
        found = releases_digest.result(entry("2.3.5", tag="2.4.0", release="2.4.0"))
        self.assertEqual(found["version"], "2.4.0")
        self.assertEqual(found["label"], "o/r releases")
        self.assertEqual(found["url"], "https://github.com/o/r/releases")
        self.assertTrue(found["inferred"])
        self.assertEqual(found["checkedAt"], "2026-10-09T00:00:00+00:00")
        self.assertNotIn("tagged", found)

    def test_a_newer_tag_not_released(self):
        found = releases_digest.result(entry("0.21.0", tag="0.22.0", release="0.21.0"))
        self.assertEqual((found["version"], found["tagged"]), ("0.21.0", "0.22.0"))

    def test_tags_only(self):
        found = releases_digest.result(entry("2.1.0", tag="2.1.0"))
        self.assertEqual(found["label"], "o/r tags")
        self.assertIsNone(releases_digest.result(entry("2.1.0")))


class Apply(unittest.TestCase):
    def test_adds_a_newer_version_never_takes_one_away(self):
        digest = {
            "whisky": entry("2.3.5", tag="2.4.0", release="2.4.0"),
            # Repology outdated, GitHub not: Repology's verdict stays.
            "requests-file": entry("2.1.0", tag="2.1.0"),
        }
        rows = [
            row("whisky", "2.3.5"),
            row("requests-file", "2.1.0", "outdated", "3.0.1", lists=["mine"]),
        ]
        answered = releases_digest.apply(rows, digest, {}, NOW)
        whisky, requests_file = rows
        self.assertEqual(answered, {"whisky", "requests-file"})
        self.assertTrue(is_outdated(whisky))
        self.assertEqual(whisky["refVersion"], "2.4.0")
        self.assertEqual(whisky["nixStatus"], "newest")  # Repology's, kept
        self.assertTrue(is_outdated(requests_file))
        self.assertEqual(requests_file["refVersion"], "3.0.1")

    def test_up_to_date_only_for_the_lists(self):
        digest = {"a": entry("1.0", tag="1.0"), "b": entry("1.0", tag="1.0")}
        rows = [row("a", "1.0", lists=["mine"]), row("b", "1.0")]
        self.assertEqual(releases_digest.apply(rows, digest, {}, NOW), {"a"})
        self.assertFalse(rows[0]["upstream"]["newer"])
        self.assertNotIn("upstream", rows[1])  # it adds nothing there

    def test_up_to_date_when_only_nixpkgs_packages_it(self):
        """python313Packages.pbar2, 2026-10-23: Repology's "unique", no other
        repository; GitHub's release is the one thing to compare with."""
        digest = {"pbar2": entry("2.2.1", tag="2.2.1", release="2.2.1")}
        rows = [row("pbar2", "2.2.1", status="unique")]
        rows[0]["onlyNixpkgs"] = True
        self.assertEqual(releases_digest.apply(rows, digest, {}, NOW), {"pbar2"})
        self.assertFalse(rows[0]["upstream"]["newer"])

    def test_not_trusted_or_not_its_own(self):
        digest = {
            # Bumped since the digest's evaluation: another tag scheme maybe.
            "bumped": entry("1.0", tag="1.1"),
            # The scheme matches another series: older than nixpkgs'.
            "older": entry("2.9.1", tag="2.7.0"),
            # A rule of its own wins.
            "ruled": entry("1.0", tag="2.0"),
            # A list's package read too long ago: the sync checks it.
            "stale": entry("1.0", tag="2.0", read="2026-10-06"),
            # Released for each version of the prover: waits on nixpkgs'.
            "rocqPackages.metarocq": entry("1.5.1-9.1", tag="1.5.1-9.2"),
        }
        rows = [
            row("bumped", "1.0.1"),
            row("older", "2.9.1"),
            row("ruled", "1.0"),
            row("stale", "1.0", lists=["mine"]),
            row("rocqPackages.metarocq", "1.5.1-9.1"),
        ]
        answered = releases_digest.apply(rows, digest, {"ruled": {}}, NOW)
        self.assertEqual(answered, set())
        self.assertFalse(any("upstream" in r for r in rows))

    def test_nothing_without_a_digest(self):
        self.assertEqual(releases_digest.apply([row("a", "1")], None, {}, NOW), set())


class Load(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def serve(self, fetched):
        body = gzip.compress(
            json.dumps(
                {
                    "format": 1,
                    "fetchedAt": fetched,
                    "packages": {"whisky": entry("2.3.5", tag="2.4.0")},
                }
            ).encode()
        )
        return (
            mock.patch.object(config, "VERSIONS_DIGEST_URL", "https://example.org/d/"),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        )

    def test_current(self):
        a, b, c = self.serve("2026-10-09T04:15:39+00:00")
        with a, b, c:
            found = releases_digest.load(NOW)
        self.assertEqual(list(found), ["whisky"])
        self.assertEqual(
            self.noted["releases"],
            {"used": True, "at": "2026-10-09T04:15:39+00:00", "packages": 1},
        )

    def test_too_old(self):
        a, b, c = self.serve("2026-10-06T04:15:39+00:00")
        with a, b, c:
            self.assertIsNone(releases_digest.load(NOW))
        self.assertFalse(self.noted["releases"]["used"])


if __name__ == "__main__":
    unittest.main()
