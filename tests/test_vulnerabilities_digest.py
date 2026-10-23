import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.changes import is_vulnerable
from nixkeeper.sources import about, http
from nixkeeper.sources import vulnerabilities_digest as vd

NOW = "2026-10-08T15:00:00+00:00"


def suggestion(cve, attr, status, ranges, issue="NIXPKGS-2026-1", **more):
    return {
        "cve": cve,
        "issue": issue,
        "title": f"{cve}'s title",
        "affected": [{"product": "x", "versions": ranges}],
        "packages": {
            attr: {
                "version": "1.0",
                "status": status,
                "branch": "master",
                "branches": {
                    "master": {"version": "1.0", "status": status},
                    "release-26.05": {"version": "0.9", "status": "affected"},
                },
            }
        },
        **more,
    }


# The digest as nixkeeper-vulnerabilities publishes it (its tracker part
# keyed as there: suggestions by id, packages by attribute).
SUGGESTIONS = {
    "1": suggestion(
        "CVE-2026-1",
        "aspell",
        "affected",
        [["affected", "<2.0"]],
        severity="high",
        score=7.5,
    ),
    "2": suggestion("CVE-2026-2", "aspell", "unknown", [["affected", "==< 1.5"]]),
    "3": suggestion("CVE-2026-3", "aspell", "unknown", [["affected", "<0.5"]]),
    "4": suggestion("CVE-2026-4", "aspell", "unknown", [["affected", "1.0, 1.1"]]),
    "5": suggestion("CVE-2026-5", "aspell", "affected", [], issue="NIXPKGS-2026-5"),
}
DIGEST = {
    "tracker": {
        "suggestions": SUGGESTIONS,
        "issues": {
            "NIXPKGS-2026-1": {
                "status": "affected",
                "github": "https://github.com/NixOS/nixpkgs/issues/1",
            },
            "NIXPKGS-2026-5": {"status": "notForUs"},
        },
        "packages": {
            "aspell": [
                {"suggestion": k, "status": s["packages"]["aspell"]["status"]}
                for k, s in SUGGESTIONS.items()
            ]
        },
    },
    "osv": {
        "advisories": {
            "GHSA-a": {
                "cves": ["CVE-2026-1"],
                "summary": "same CVE",
                "ecosystem": "PyPI",
            },
            "GHSA-b": {
                "cves": ["CVE-2026-9"],
                "summary": "another",
                "severity": "moderate",
                "ecosystem": "PyPI",
            },
        },
        "packages": {"aspell": ["GHSA-a", "GHSA-b"]},
    },
}


class Ranges(unittest.TestCase):
    def test_the_shapes_the_tracker_gives(self):
        cases = [
            ("1.2", "<1.3", True),
            ("1.3", "<1.3", False),
            ("1.0.45", "==< 1.0.45", False),
            ("1.0.44", "==< 1.0.45", True),
            ("1.38.1", "==>= 1.38.0, < 1.38.3", True),
            ("1.38.3", "==>= 1.38.0, < 1.38.3", False),
            ("1.011", "=<1.011", True),
            ("0.10", "==0.10", True),
            ("0.10.1", "==0.10", False),
            ("0.24.6", "=== 0.24.6", True),
            ("2026.4.1", "==<= 2026.4.1", True),
            ("1.17", "<v1.18.0", True),
            ("2.540", "<2.541.*", True),
            ("9", "*", True),
        ]
        for version, expression, expected in cases:
            with self.subTest(version=version, expression=expression):
                self.assertIs(vd.matches(version, expression), expected)

    def test_what_cant_be_read(self):
        for expression in ("<x.59.21", "<1.46.0, 1.45.4, 1.44.6", "", "later"):
            with self.subTest(expression=expression):
                self.assertIsNone(vd.matches("1.0", expression))

    def test_affected_unaffected_or_unknown(self):
        ranges = [{"versions": [["affected", "<1.2"], ["unaffected", ">=1.2"]]}]
        self.assertEqual(vd.by_version("1.1", ranges), "affected")
        self.assertEqual(vd.by_version("1.2", ranges), "fixed")
        self.assertIsNone(vd.by_version("1.0", [{"versions": [["affected", "x.1"]]}]))
        self.assertIsNone(vd.by_version("1.0", []))  # no ranges: can't tell
        self.assertIsNone(vd.by_version(None, ranges))

    def test_fixed_in(self):
        self.assertEqual(
            vd.fixed_in("2026.1", [{"versions": [["affected", "<2026.2.16593"]]}]),
            "2026.2.16593",
        )
        # Two affected series: the end of the one it's in.
        two = [
            {"versions": [["affected", ">= 1.0, < 1.7"], ["affected", ">=2.0, <2.3"]]}
        ]
        self.assertEqual(vd.fixed_in("1.5", two), "1.7")
        self.assertEqual(vd.fixed_in("2.1", two), "2.3")
        # An unaffected range's start; a leading v dropped.
        self.assertEqual(
            vd.fixed_in(
                "0.9", [{"versions": [["affected", "<=1.0"], ["unaffected", ">=v1.1"]]}]
            ),
            "1.1",
        )
        # "=<" is an upper bound still affected, not "<": no fix after it.
        self.assertIsNone(
            vd.fixed_in("2.0", [{"versions": [["affected", "=<4.19.4"]]}])
        )
        # Not for a version the ranges call fixed; not a commit.
        self.assertIsNone(vd.fixed_in("1.8", two))
        self.assertIsNone(
            vd.fixed_in("0-unstable", [{"versions": [["affected", "<44b2f096f67d"]]}])
        )
        self.assertIsNone(vd.fixed_in("1.0", [{"versions": [["affected", "*"]]}]))
        self.assertIsNone(vd.fixed_in("1.0", []))


class Verdicts(unittest.TestCase):
    def found(self, **row):
        return {v["id"]: v for v in vd.for_row({"name": "aspell", **row}, DIGEST)}

    def test_each_verdict(self):
        found = self.found(nixVersion="1.0")
        self.assertEqual(found["CVE-2026-1"]["verdict"], "affected")
        self.assertEqual(found["CVE-2026-2"]["verdict"], "affected")  # 1.0 < 1.5
        self.assertEqual(found["CVE-2026-3"]["verdict"], "fixed")  # not < 0.5
        self.assertEqual(found["CVE-2026-4"]["verdict"], "unconfirmed")
        self.assertEqual(found["CVE-2026-5"]["verdict"], "dismissed")  # not for us
        # OSV: not for a CVE the tracker has; another one, counted.
        self.assertNotIn("GHSA-a", found)
        self.assertEqual(found["GHSA-b"]["verdict"], "osv")

    def test_what_an_entry_says(self):
        cve = self.found(nixVersion="1.0")["CVE-2026-1"]
        self.assertEqual((cve["severity"], cve["score"]), ("high", 7.5))
        self.assertEqual(cve["issue"], "NIXPKGS-2026-1")
        self.assertEqual(cve["github"], "https://github.com/NixOS/nixpkgs/issues/1")
        self.assertEqual(cve["releases"], {"release-26.05": "affected"})
        self.assertEqual(cve["fixedIn"], "2.0")  # affected <2.0
        # Not for an older series kept beside a newer one: its ranges are
        # the newer series'.
        kept = self.found(
            nixVersion="1.0", keptBeside={"attr": "aspell2", "version": "3.0"}
        )
        self.assertNotIn("fixedIn", kept["CVE-2026-1"])

    def test_counted_first_worst_first(self):
        ids = [
            v["id"] for v in vd.for_row({"name": "aspell", "nixVersion": "1.0"}, DIGEST)
        ]
        self.assertEqual(ids[0], "CVE-2026-1")  # high, counted
        self.assertLess(ids.index("GHSA-b"), ids.index("CVE-2026-3"))  # counted first

    def test_by_any_attribute(self):
        found = vd.for_row(
            {"name": "aspell-full", "attrs": ["aspell"], "nixVersion": "1.0"}, DIGEST
        )
        self.assertTrue(found)
        self.assertEqual(vd.for_row({"name": "other", "nixVersion": "1.0"}, DIGEST), [])


class OwnCheck(unittest.TestCase):
    """The tracker's status is the range check on an old version: nixkeeper
    checks nixpkgs' current version itself."""

    def test_a_stale_affected_is_fixed_by_the_version(self):
        # The tracker said affected (when nixpkgs had 1.0); nixpkgs has 3.0.
        found = {
            v["id"]: v
            for v in vd.for_row({"name": "aspell", "nixVersion": "3.0"}, DIGEST)
        }
        self.assertEqual(found["CVE-2026-1"]["verdict"], "fixed")  # < 2.0

    def test_the_trackers_status_when_ranges_cant_be_read(self):
        s = suggestion("CVE-2026-7", "aspell", "affected", [["affected", "x.1"]])
        self.assertEqual(
            vd.verdict({"nixVersion": "1.0"}, s, "affected", None), "tracker"
        )
        self.assertEqual(
            vd.verdict({"nixVersion": "1.0"}, s, "unaffected", None), "fixed"
        )
        self.assertEqual(
            vd.verdict({"nixVersion": "1.0"}, s, "unknown", None), "unconfirmed"
        )

    def test_the_newest_release_by_its_version(self):
        # The tracker's 26.05 status is "affected" (an old evaluation); the
        # channel has 2.5 now, past "< 2.0": not to backport.
        digest = {
            **DIGEST,
            "newestRelease": "release-26.05",
            "stable": {"aspell": "2.5"},
        }
        rows = [{"name": "aspell", "nixVersion": "3.0"}]
        vd.add(rows, digest)
        cve = next(v for v in rows[0]["vulnerabilities"] if v["id"] == "CVE-2026-1")
        self.assertEqual(cve["releases"]["release-26.05"], "unaffected")
        self.assertNotIn("CVE-2026-1", rows[0].get("backport", []))
        # 26.05 still at 1.5: fixed on unstable, to backport.
        digest["stable"] = {"aspell": "1.5"}
        vd.add(rows, digest)
        self.assertIn("CVE-2026-1", rows[0]["backport"])


class Patched(unittest.TestCase):
    """A CVE nixpkgs fixes with a patch named after it, without a new
    version: not counted on unstable; not to backport when the release's
    channel has the patch too."""

    def add(self, rows, unstable=(), stable=(), stable_version="1.5"):
        def patches(attrs, revision):
            names = {"unstable": unstable, "stable": stable}[revision]
            return {a: list(names) for a in attrs}

        digest = {
            **DIGEST,
            "newestRelease": "release-26.05",
            "stable": {"aspell": stable_version},
            "stableRevision": "stable",
        }
        with mock.patch.object(vd.nixpkgs, "patches", side_effect=patches):
            vd.add(rows, digest, "unstable")
        return {v["id"]: v for v in rows[0]["vulnerabilities"]}

    def test_patched_on_unstable(self):
        rows = [{"name": "aspell", "nixVersion": "1.0"}]
        found = self.add(
            rows, unstable=["CVE-2026-1.patch", "https://x/fix-cve-2026-2"]
        )
        self.assertEqual(found["CVE-2026-1"]["verdict"], "patched")
        self.assertEqual(found["CVE-2026-2"]["verdict"], "patched")  # any case
        self.assertTrue(is_vulnerable(rows[0]))  # GHSA-b (OSV) still counts

    def test_an_osv_advisory_by_its_cve(self):
        rows = [{"name": "aspell", "nixVersion": "1.0"}]
        found = self.add(rows, unstable=["CVE-2026-9.patch"])
        self.assertEqual(found["GHSA-b"]["verdict"], "patched")

    def test_patched_in_the_release_is_no_backport(self):
        # 3.0: CVE-2026-1 (< 2.0) fixed on unstable; 26.05 at 1.5, in range.
        rows = [{"name": "aspell", "nixVersion": "3.0"}]
        self.add(rows)
        self.assertIn("CVE-2026-1", rows[0]["backport"])
        rows = [{"name": "aspell", "nixVersion": "3.0"}]
        found = self.add(rows, stable=["CVE-2026-1.patch"])
        self.assertNotIn("CVE-2026-1", rows[0].get("backport", []))
        self.assertEqual(found["CVE-2026-1"]["releases"]["release-26.05"], "patched")

    def test_patched_on_unstable_still_to_backport(self):
        # Fixed on unstable by a patch only, 26.05 not patched: backport.
        rows = [{"name": "aspell", "nixVersion": "1.0"}]
        self.add(rows, unstable=["CVE-2026-1.patch"], stable_version="1.0")
        self.assertIn("CVE-2026-1", rows[0]["backport"])

    def test_no_revision_no_check(self):
        rows = [{"name": "aspell", "nixVersion": "1.0"}]
        vd.add(rows, DIGEST)  # no revision: nothing evaluated
        self.assertNotIn("patched", {v["verdict"] for v in rows[0]["vulnerabilities"]})


class Vulnerable(unittest.TestCase):
    def test_any_source(self):
        rows = [{"name": "aspell", "nixVersion": "1.0"}, {"name": "other"}]
        self.assertEqual(vd.add(rows, DIGEST), 1)
        self.assertTrue(is_vulnerable(rows[0]))
        self.assertNotIn("vulnerabilities", rows[1])
        self.assertFalse(is_vulnerable(rows[1]))
        self.assertEqual(
            vd.summary(rows[0]), {"n": 3, "severity": "high", "by": ["osv", "tracker"]}
        )

    def test_repology_still_counts(self):
        # The tracker's entries all fixed: Repology's flag still counts (its
        # CVEs may be others the tracker has no entry for).
        row = {"name": "aspell", "nixVersion": "9.0", "nixVulnerable": True}
        row["vulnerabilities"] = [
            {"id": "CVE-2026-3", "source": "tracker", "verdict": "fixed"}
        ]
        self.assertTrue(is_vulnerable(row))
        self.assertEqual(vd.summary(row), {"n": 0, "by": ["repology"]})
        del row["nixVulnerable"]
        self.assertFalse(is_vulnerable(row))
        self.assertIsNone(vd.summary(row))

    def test_without_a_digest_nothing_changes(self):
        rows = [{"name": "aspell", "nixVulnerable": True}]
        self.assertEqual(vd.add(rows, None), 0)
        self.assertNotIn("vulnerabilities", rows[0])
        self.assertTrue(is_vulnerable(rows[0]))


class Backport(unittest.TestCase):
    def test_fixed_on_master_affected_on_the_newest_release(self):
        self.assertEqual(vd.newest_release(DIGEST), "release-26.05")
        # 9.0: CVE-2026-3 (< 0.5) fixed; its release-26.05 affected.
        rows = [{"name": "aspell", "nixVersion": "9.0"}]
        vd.add(rows, DIGEST)
        self.assertIn("CVE-2026-3", rows[0]["backport"])
        # Not when the newest release isn't affected.
        found = [
            {
                "id": "CVE-1",
                "verdict": "fixed",
                "releases": {"release-25.11": "affected"},
            }
        ]
        self.assertEqual(vd.to_backport(found, "release-26.05"), [])
        self.assertEqual(vd.to_backport(found, None), [])

    def test_the_newest_by_version(self):
        digest = {
            "tracker": {
                "suggestions": {
                    "1": {
                        "packages": {
                            "a": {
                                "branches": {
                                    "release-9.11": {},
                                    "release-10.05": {},
                                    "master": {},
                                }
                            }
                        }
                    }
                }
            }
        }
        self.assertEqual(vd.newest_release(digest), "release-10.05")


class Load(unittest.TestCase):
    def load(self, meta):
        def get(url, *args, **kwargs):
            self.assertTrue(url.endswith("meta.json"))
            return json.dumps(meta)

        body = gzip.compress(json.dumps({"format": 1, **DIGEST}).encode())
        with (
            mock.patch.object(config, "VULNERABILITIES_DIGEST_URL", "https://digest/"),
            mock.patch.object(config, "STABLE_INDEX_URL", ""),  # no 26.05 index
            mock.patch.object(http, "get", side_effect=get),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            about.taken()
            return vd.load(NOW), about.taken()

    def test_used_when_complete_and_recent(self):
        meta = {
            "format": 1,
            "tracker": {
                "complete": True,
                "readAt": "2026-10-08T14:00:00+00:00",
                "suggestions": 5,
                "packages": 1,
            },
            "osv": {"readAt": NOW, "advisories": 2, "packages": 1},
        }
        digest, noted = self.load(meta)
        self.assertIn("aspell", digest["tracker"]["packages"])
        self.assertTrue(noted["tracker"]["used"])
        self.assertTrue(noted["osv"]["used"])
        # The release fixes are to be backported to, for the overview's note.
        self.assertEqual(noted["tracker"]["release"], "26.05")

    def test_not_until_read_through_nor_when_old(self):
        for tracker in (
            {"complete": False, "readAt": NOW},
            {"complete": True, "readAt": "2026-10-01T00:00:00+00:00"},
        ):
            with self.subTest(tracker=tracker):
                digest, noted = self.load({"format": 1, "tracker": tracker})
                self.assertIsNone(digest)
                self.assertFalse(noted["tracker"]["used"])


if __name__ == "__main__":
    unittest.main()
