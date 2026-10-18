"""nixkeeper-prs' digest: nixpkgs' open PRs and issues and the PRs merged
since the channel's commit, as github_bulk's listings."""

import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, http, prs_digest

NOW = "2026-10-09T12:00:00+00:00"
FILES = {
    "prs.json": {
        "format": 1,
        "prs": [
            {"n": 1, "title": "wine: 10.15 -> 10.16", "draft": False, "base": "master"}
        ],
    },
    "issues.json": {"format": 1, "issues": [{"n": 7, "title": "wine: crashes"}]},
    "merged.json": {
        "format": 1,
        "prs": [{"n": 4, "title": "x: 1 -> 2", "draft": False, "base": "master"}],
    },
    "staging.json": {
        "format": 1,
        "stagingNext": {
            "open": {"n": 571813, "cut": "2026-10-08T00:00:00Z", "open": True},
            "lastMerged": {"n": 566094, "cut": "2026-09-23T00:00:00Z"},
        },
        "prs": [
            {
                "n": 9,
                "title": "meson: 1.12.0 -> 1.12.1",
                "base": "staging",
                "merged": "2026-10-01T00:00:00Z",
                "on": "staging-next",
            }
        ],
    },
}


def meta(at="2026-10-09T10:00:00+00:00", revision="abc", merged_at=None):
    return {
        "format": 1,
        "generatedAt": at,
        "issues": {"count": 1, "at": at},
        "merged": {"count": 1, "at": merged_at or at, "revision": revision},
    }


class Load(unittest.TestCase):
    def load(self, info, revision="abc"):
        def get(url, compressed=False):
            name = url.rsplit("/", 1)[1]
            return json.dumps(info if name == "meta.json" else FILES[name])

        with (
            mock.patch.object(config, "PRS_DIGEST_URL", "https://d/"),
            mock.patch.object(http, "get", side_effect=get),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            return prs_digest.load(NOW, revision)

    def test_current(self):
        found = self.load(meta())
        prs, issues = found["open"]
        self.assertEqual(
            prs,
            [
                {
                    "number": 1,
                    "title": "wine: 10.15 -> 10.16",
                    "url": "https://github.com/NixOS/nixpkgs/pull/1",
                    "isDraft": False,
                    "baseRefName": "master",
                }
            ],
        )
        self.assertEqual(issues, [{"number": 7, "title": "wine: crashes"}])
        self.assertEqual([p["number"] for p in found["merged"]], [4])
        self.assertEqual(
            about.taken()["prs"],
            {
                "used": True,
                "at": "2026-10-09T10:00:00+00:00",
                "prs": 1,
                "issues": 1,
                "merged": 1,
            },
        )

    def test_merged_since_another_channel_commit_isnt_used(self):
        found = self.load(meta(), revision="newer")
        self.assertIsNotNone(found["open"])
        self.assertIsNone(found["merged"])
        self.assertEqual(
            about.taken()["prs"]["partly"], "merged PRs since another channel commit"
        )

    def test_too_old_or_off(self):
        found = self.load(meta(at="2026-10-09T01:00:00+00:00"))
        self.assertEqual(found, {"open": None, "merged": None, "staging": None})
        self.assertFalse(about.taken()["prs"]["used"])
        with mock.patch.object(config, "PRS_DIGEST_URL", ""):
            self.assertIsNone(prs_digest.load(NOW, "abc"))
        self.assertEqual(about.taken(), {})

    def test_unreadable(self):
        self.assertIsNone(self.load({"format": 2}))
        self.assertIn("couldn't be read", about.taken()["prs"]["why"])

    def test_staging(self):
        info = {**meta(), "staging": {"count": 1, "at": "2026-10-09T10:00:00+00:00"}}
        staging = self.load(info)["staging"]
        self.assertEqual(
            [(p["number"], p["on"]) for p in staging["prs"]], [(9, "staging-next")]
        )
        self.assertEqual(staging["stagingNext"]["open"]["n"], 571813)
        self.assertEqual(about.taken()["prs"]["staging"], 1)
        # Too old, or from a digest without it: none.
        old = {**meta(), "staging": {"count": 1, "at": "2026-10-09T01:00:00+00:00"}}
        self.assertIsNone(self.load(old)["staging"])
        self.assertIsNone(self.load(meta())["staging"])


class Removal(unittest.TestCase):
    def test_the_package_itself(self):
        for title in (
            "argo-expr: drop",
            "git-instafix: remove package",
            "sqlite-interactive: drop in favor of enabling readline by default",
            "pokemmo-installer: drop, pokemmo: init at 32920",
            "fmt_9: remove version",
            "foo: drop (unmaintained upstream)",
            "foo: remove as it's broken",
        ):
            self.assertTrue(prs_digest.REMOVAL.match(title), title)

    def test_something_from_it(self):
        for title in (
            "signal-cli: drop unused libmatthew_java and dbus_java",
            "python3Packages.axisregistry: remove meta.changelog",
            "rustc: remove a step of the bootstrap process",
            "mpv: drop dev output from mpv-unwrapped",
        ):
            self.assertFalse(prs_digest.REMOVAL.match(title), title)


class Facts(unittest.TestCase):
    PRS = [
        {
            "n": 1,
            "title": "wine: 10.15 -> 10.16",
            "draft": False,
            "mergeable": "MERGEABLE",
            "mergeBot": {"ready": True, "maintainers": ["a"]},
            "blocksBot": {"title": "wine: 10.15 -> 10.16", "by": "2026-10-12"},
        },
        {
            "n": 2,
            "title": "wine: 10.15 -> 10.16",
            "draft": False,
            "mergeable": "CONFLICTING",
            "mergeBot": {"ready": True},
            "state": "superseded",
            "update": {"now": "10.17"},
        },
        {
            "n": 3,
            "title": "wine: fix the build",
            "draft": False,
            "hydraFailing": {"wine": {"x86_64-linux": "compile"}},
        },
        {"n": 4, "title": "wip", "draft": True, "hydraFailing": {"wine": {}}},
        {"n": 5, "title": "wine: drop", "draft": False, "buckets": ["drop"]},
        {
            "n": 6,
            "title": "treewide: tidy",
            "draft": False,
            "packages": ["wine"],
            "mergeBot": {"ready": True},
        },
        {"n": 10, "title": "wine: drop (draft)", "draft": True, "buckets": ["drop"]},
        {
            "n": 11,
            "title": "fmt_11: remove version",
            "draft": False,
            "buckets": ["drop"],
            "packages": ["fmt_11", "imhex"],
        },
    ]
    GROUPS = [{"kind": "sameDiff", "key": "aa", "prs": [1, 2]}]
    ISSUES = [
        {
            "n": 7,
            "title": "Build failure: wine",
            "hydra": {"package": "wine", "verdict": "builds"},
        },
        {
            "n": 8,
            "title": "Build failure: wine on musl",
            "hydra": {"package": "wine", "verdict": "variant"},
        },
        {
            "n": 9,
            "title": "Update request: python3Packages.foo 1 → 2",
            "update": {
                "package": "python3Packages.foo",
                "verdict": "done",
                "now": "2.1",
            },
        },
    ]

    def test_by_number_and_package(self):
        found = prs_digest.facts(self.PRS, self.GROUPS, self.ISSUES)
        self.assertEqual(
            found["prs"][1],
            {"mergeBot": "ready", "blocksBot": "2026-10-12", "duplicates": [2]},
        )
        # Conflicting: eligible, not ready.
        self.assertEqual(
            found["prs"][2],
            {
                "mergeBot": "eligible",
                "state": "superseded",
                "now": "10.17",
                "duplicates": [1],
            },
        )
        self.assertNotIn(3, found["prs"])
        # Drafts aren't fixes; a variant isn't worth showing.
        self.assertEqual([p["number"] for p in found["fixes"]["wine"]], [3])
        self.assertEqual([i["number"] for i in found["issues"]["wine"]], [7])
        # By Python's versioned set, as rows are named.
        self.assertEqual(
            found["issues"]["python313packages.foo"][0],
            {
                "number": 9,
                "title": "Update request: python3Packages.foo 1 → 2",
                "url": "https://github.com/NixOS/nixpkgs/issues/9",
                "kind": "update",
                "verdict": "done",
                "now": "2.1",
            },
        )

    def test_add_facts(self):
        digest = {"facts": prs_digest.facts(self.PRS, self.GROUPS, self.ISSUES)}
        wine = {
            "name": "wine",
            "attrs": ["wine"],
            "openPR": {"number": 1, "to": "10.16"},
            "fixPRs": [{"number": 99}],  # the last sync's: replaced
        }
        foo = {"name": "python313Packages.foo", "attrs": ["python313Packages.foo"]}
        prs_digest.add_facts([wine, foo], digest)
        self.assertEqual(wine["openPR"]["facts"]["mergeBot"], "ready")
        self.assertNotIn("fixesBuild", wine["openPR"]["facts"])
        self.assertEqual([p["number"] for p in wine["fixPRs"]], [3])
        self.assertEqual([i["number"] for i in wine["issueChecks"]], [7])
        self.assertEqual([i["number"] for i in foo["issueChecks"]], [9])
        # Its other open PRs: a removal first, by title or by-name directory;
        # not the update PR, the fixes, nor drafts.
        self.assertEqual(
            wine["otherPRs"],
            [
                {"number": 5, "title": "wine: drop", "kind": "drop"},
                {"number": 6, "title": "treewide: tidy", "mergeBot": "ready"},
                {
                    "number": 2,
                    "title": "wine: 10.15 -> 10.16",
                    "mergeBot": "eligible",
                },
            ],
        )
        self.assertEqual(wine["dropPR"], {"number": 5, "title": "wine: drop"})
        self.assertNotIn("otherPRs", foo)
        # A removal touching another package: not that one's removal.
        imhex = {"name": "imhex", "attrs": ["imhex"]}
        fmt = {"name": "fmt_11", "attrs": ["fmt_11"]}
        prs_digest.add_facts([imhex, fmt], digest)
        self.assertEqual(
            imhex["otherPRs"], [{"number": 11, "title": "fmt_11: remove version"}]
        )
        self.assertNotIn("dropPR", imhex)
        self.assertEqual(fmt["dropPR"]["number"], 11)
        # Another of its attributes removed: listed, but it isn't being removed.
        sqlite = {"name": "sqlite", "attrs": ["sqlite", "fmt_11"]}
        prs_digest.add_facts([sqlite], digest)
        self.assertEqual(sqlite["otherPRs"][0]["kind"], "drop")
        self.assertNotIn("dropPR", sqlite)
        # The update PR touching the failing build: said once, as the update PR.
        wine["openPR"] = {"number": 3, "to": "10.16"}
        prs_digest.add_facts([wine], digest)
        self.assertEqual(wine["openPR"]["facts"], {"fixesBuild": True})
        self.assertNotIn("fixPRs", wine)
        # Without the digest's facts: the last sync's are dropped.
        prs_digest.add_facts([wine], {})
        self.assertNotIn("fixPRs", wine)
        self.assertNotIn("issueChecks", wine)
        self.assertNotIn("otherPRs", wine)
        self.assertNotIn("dropPR", wine)


class BuildFixPRs(unittest.TestCase):
    MERGED = [
        {
            "number": 1,
            "title": "wine: fix the build",
            "url": "u1",
            "merged": "2026-10-09T10:00:00Z",
            "author": "alice",
            "mergedBy": "bob",
        },
        {
            "number": 2,
            "title": "treewide: tidy",
            "url": "u2",
            "merged": "2026-10-09T12:00:00Z",
            "packages": ["wine"],
            "author": "carol",
            "mergedBy": "nixpkgs-ci",
        },
        {  # treewide, wine only in passing: not credited
            "number": 4,
            "title": "treewide: remove explicit strictDeps",
            "url": "u4",
            "merged": "2026-10-09T13:00:00Z",
            "packages": ["wine", "a", "b", "c"],
        },
        {  # marks it broken: Hydra stops building it, nothing fixed
            "number": 5,
            "title": "treewide: mark as broken on aarch64-linux",
            "url": "u5",
            "merged": "2026-10-09T14:00:00Z",
            "packages": ["wine"],
        },
        {  # merged before the build began failing: not its fix
            "number": 3,
            "title": "foo: 1 -> 2",
            "url": "u3",
            "merged": "2026-10-01T00:00:00Z",
        },
    ]

    def row(self, name, failing=True, since="2026-10-08T00:00:00Z"):
        return {
            "name": name,
            "attrs": [name],
            "builds": [{"status": "failed" if failing else "ok", "system": "x"}],
            "failingSince": since,
        }

    def test_the_newest_merged_since_it_began_failing(self):
        rows = [self.row("wine"), self.row("foo"), self.row("bar", failing=False)]
        prs_digest.build_fix_prs(rows, self.MERGED, {"packages": []})
        wine, foo, bar = rows
        self.assertEqual(
            wine["buildFixPR"],
            {
                "number": 2,
                "title": "treewide: tidy",
                "url": "u2",
                "author": "carol",
                "mergedBy": "nixpkgs-ci",
                "merged": "2026-10-09T12:00:00Z",
            },
        )
        self.assertNotIn("buildFixPR", foo)
        self.assertNotIn("buildFixPR", bar)

    def test_kept_while_failing_once_off_the_list(self):
        kept = {"number": 9, "title": "wine: fix", "url": "u9"}
        previous = {"packages": [{"name": "wine", "buildFixPR": kept}]}
        rows = [self.row("wine"), self.row("gone", failing=False)]
        prs_digest.build_fix_prs(rows, [], previous)
        self.assertEqual(rows[0]["buildFixPR"], kept)


if __name__ == "__main__":
    unittest.main()


class StagingPRs(unittest.TestCase):
    def pr(self, n, title, on):
        return {
            "number": n,
            "title": title,
            "url": f"https://github.com/NixOS/nixpkgs/pull/{n}",
            "isDraft": False,
            "baseRefName": "staging",
            "on": on,
            "merged": "2026-10-01T00:00:00Z",
        }

    STAGING = {
        "stagingNext": {"open": {"n": 571813, "cut": "2026-10-08T00:00:00Z"}},
    }

    def row(self, **extra):
        return {
            "name": "meson",
            "searchTerm": "meson",
            "attrs": ["meson"],
            "nixVersion": "1.12.0",
            **extra,
        }

    def add(self, row, *prs):
        prs_digest.add_staging_prs([row], {**self.STAGING, "prs": list(prs)})
        return row.get("stagingPR")

    def test_on_its_way(self):
        found = self.add(
            self.row(),
            self.pr(1, "meson: 1.12.0 -> 1.12.1", "staging-next"),
            self.pr(2, "meson: fix cross builds", "staging"),  # not an update
            self.pr(3, "mesonlsp: 1.0 -> 1.1", "staging"),  # another package
        )
        self.assertEqual(
            (found["number"], found["to"], found["on"], found["cycle"]["n"]),
            (1, "1.12.1", "staging-next", 571813),
        )

    def test_the_highest_then_the_furthest(self):
        found = self.add(
            self.row(),
            self.pr(1, "meson: 1.12.0 -> 1.12.1", "staging-next"),
            self.pr(2, "meson: 1.12.1 -> 1.12.2", "staging"),
        )
        self.assertEqual((found["number"], found["on"]), (2, "staging"))
        self.assertNotIn("cycle", found)  # staging's: no staging-next yet

    def test_not_when_master_or_the_channel_has_it(self):
        pr = self.pr(1, "meson: 1.12.0 -> 1.12.1", "staging-next")
        self.assertIsNone(self.add(self.row(master="1.12.1"), pr))
        self.assertIsNone(self.add(self.row(nixVersion="1.12.1"), pr))

    def test_its_staging_next_builds_kept_hourly(self):
        # The sync's reading of staging-next's builds, for the same PR: kept
        # (the hourly check doesn't read them).
        builds = [{"system": "x86_64-linux", "status": "ok", "build": "1"}]
        row = self.row(
            stagingPR={
                "number": 1,
                "on": "staging-next",
                "builds": builds,
                "inEval": True,
            }
        )
        found = self.add(row, self.pr(1, "meson: 1.12.0 -> 1.12.1", "staging-next"))
        self.assertEqual((found["builds"], found["inEval"]), (builds, True))
        # Another PR: not carried over.
        row = self.row(stagingPR={"number": 9, "on": "staging-next", "builds": builds})
        found = self.add(row, self.pr(1, "meson: 1.12.0 -> 1.12.1", "staging-next"))
        self.assertNotIn("builds", found)

    def test_without_the_list_none(self):
        row = self.row(stagingPR={"number": 1})
        prs_digest.add_staging_prs([row], None)
        self.assertNotIn("stagingPR", row)


class Mergeable(unittest.TestCase):
    """The PRs maintainers can merge with the merge bot (views/merge.json)."""

    ROWS = [
        {"name": "wine"},
        {"name": "python313Packages.rq", "attrs": ["python313Packages.rq"]},
    ]

    def pr(self, n, **kw):
        found = {
            "n": n,
            "title": f"wine: {n}",
            "author": "r-ryantm",
            "created": f"2026-10-0{n}T00:00:00Z",
            "base": "master",
            "draft": False,
            "mergeable": "UNKNOWN",
            "packages": ["wine"],
            "mergeBot": {"ready": True, "maintainers": ["a", "b"], "label": True},
        }
        found.update(kw)
        return found

    def test_ready_ones_oldest_first(self):
        prs = [
            self.pr(3),
            self.pr(1, approvedBy=["c"], author="a"),
            self.pr(2, packages=["python3Packages.rq"]),
        ]
        found = prs_digest.mergeable(prs, self.ROWS)
        self.assertEqual([p["number"] for p in found], [1, 2, 3])
        self.assertEqual(
            found[0],
            {
                "number": 1,
                "title": "wine: 1",
                "author": "a",
                "created": "2026-10-01T00:00:00Z",
                "base": "master",
                "packages": ["wine"],
                "who": ["a", "b"],
                "approvedBy": ["c"],
            },
        )
        # Python's alias, as the row's versioned set.
        self.assertEqual(found[1]["packages"], ["python313Packages.rq"])

    def test_left_out(self):
        prs = [
            self.pr(1, mergeBot={"ready": False, "maintainers": ["a"]}),  # CI
            self.pr(2, mergeBot={"ready": True, "maintainers": []}),  # committers
            self.pr(3, mergeable="CONFLICTING"),
            self.pr(4, review="CHANGES_REQUESTED"),
            self.pr(5, draft=True),
            self.pr(6, packages=["firefox"]),  # no row of it
            self.pr(7, mergeBot=None),
        ]
        self.assertEqual(prs_digest.mergeable(prs, self.ROWS), [])


class CrossCheck(unittest.TestCase):
    """An update PR behind upstream, or for a vulnerable package."""

    def row(self, **kw):
        found = {
            "name": "wine",
            "nixVersion": "10.15",
            "refVersion": "10.17",
            "openPR": {"number": 1, "to": "10.16", "facts": {"mergeBot": "ready"}},
        }
        found.update(kw)
        return found

    def test_behind_and_vulnerable(self):
        row = self.row(vulnerabilities=[{"id": "CVE-1", "verdict": "affected"}])
        prs_digest.cross_check([row])
        self.assertEqual(
            row["openPR"]["facts"],
            {"mergeBot": "ready", "behind": "10.17", "vulnerable": True},
        )

    def test_up_to_upstream_and_again(self):
        row = self.row(refVersion="10.16")
        row["openPR"]["facts"]["behind"] = "10.16"  # an earlier run's
        prs_digest.cross_check([row])
        self.assertEqual(row["openPR"]["facts"], {"mergeBot": "ready"})
        # Nothing at all: no facts left.
        bare = self.row(refVersion=None, openPR={"number": 2, "to": "10.16"})
        prs_digest.cross_check([bare])
        self.assertNotIn("facts", bare["openPR"])

    def test_in_the_merge_list(self):
        rows = [self.row(markedInsecure=["CVE-2"])]
        prs = [
            {
                "n": 1,
                "title": "wine: 10.15 -> 10.16",
                "created": "2026-10-01T00:00:00Z",
                "packages": ["wine"],
                "update": {"attr": "wine", "to": "10.16"},
                "mergeBot": {"ready": True, "maintainers": ["a"]},
            }
        ]
        found = prs_digest.mergeable(prs, rows)[0]
        self.assertEqual((found["behind"], found["vulnerable"]), ("10.17", True))


class CveIssues(unittest.TestCase):
    """CVE issues nixkeeper finds fixed: candidates to close."""

    def rows(self):
        return [
            {
                "name": "crewai",
                "vulnerabilities": [
                    {"id": "CVE-2026-2275", "verdict": "fixed"},
                    {"id": "CVE-2026-2287", "verdict": "patched"},
                    {"id": "CVE-2026-9999", "verdict": "affected"},
                ],
                "issueChecks": [{"number": 3, "kind": "cve", "verdict": "cveFixed"}],
            },
            {"name": "other"},
        ]

    def test_fixed_ones(self):
        rows = self.rows()
        issues = [
            {"number": 1, "title": "crewai: CVE-2026-2275, cve-2026-2287"},
            {
                "number": 2,
                "title": "crewai: CVE-2026-2275 CVE-2026-9999",
            },  # one affects
            {"number": 4, "title": "CVE-2026-1111 Record"},  # not known
            {"number": 5, "title": "crewai: crashes"},
        ]
        prs_digest.add_cve_issues(rows, issues)
        self.assertEqual(
            rows[0]["issueChecks"],
            [
                {
                    "number": 1,
                    "title": "crewai: CVE-2026-2275, cve-2026-2287",
                    "url": "https://github.com/NixOS/nixpkgs/issues/1",
                    "kind": "cve",
                    "verdict": "cveFixed",
                    "cves": ["CVE-2026-2275", "CVE-2026-2287"],
                }
            ],
        )
        self.assertNotIn("issueChecks", rows[1])
        # The earlier run's (#3) went: worked out again.
        rows[0]["issueChecks"] = [{"number": 9, "kind": "build"}]
        prs_digest.add_cve_issues(rows, [])
        self.assertEqual(rows[0]["issueChecks"], [{"number": 9, "kind": "build"}])
