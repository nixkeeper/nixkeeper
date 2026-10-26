import io
import re
import unittest
from unittest import mock

from nixkeeper import config, inferred
from nixkeeper.sources import github
from nixkeeper.sources import nixpkgs as nixpkgs_source


def src(version, **fields):
    return {"version": version, **fields}


class GithubCheck(unittest.TestCase):
    def check(self, source):
        return inferred.github_check(source)

    def test_tag_is_the_version(self):
        check, _ = self.check(
            src(
                "1.19.28",
                gitRepoUrl="https://github.com/wesnoth/wesnoth.git",
                tag="1.19.28",
            )
        )
        self.assertEqual(check["github"], "wesnoth/wesnoth")
        self.assertEqual(check["tags"], r"^([0-9]+(?:[\.][0-9]+)+)$")

    def test_prefix_from_the_tag(self):
        check, _ = self.check(
            src(
                "2.34.2",
                gitRepoUrl="https://github.com/psf/requests.git",
                rev="refs/tags/v2.34.2",
            )
        )
        regex = re.compile(check["tags"])
        self.assertEqual(regex.search("v2.35.0").group(1), "2.35.0")
        # Pre-releases, other schemes and other prefixes don't count.
        for tag in ("v2.35.0rc1", "2.35.0", "v2_35_0", "release-2.35.0"):
            self.assertIsNone(regex.search(tag), tag)

    def test_from_a_download_url(self):
        release, _ = self.check(
            src(
                "0.7.2",
                url="https://github.com/a/b/releases/download/v0.7.2/b-0.7.2.tar.gz",
            )
        )
        archive, _ = self.check(
            src("3.0", url="https://github.com/a/b/archive/refs/tags/release-3.0.zip")
        )
        self.assertEqual(
            release, {"github": "a/b", "tags": r"^v([0-9]+(?:[\.][0-9]+)+)$"}
        )
        self.assertEqual(archive["tags"], r"^release\-([0-9]+(?:[\.][0-9]+)+)$")

    def test_separators_follow_the_version(self):
        check, _ = self.check(
            src("7_2", gitRepoUrl="https://github.com/a/b.git", tag="R7_2")
        )
        self.assertEqual(re.search(check["tags"], "R7_3").group(1), "7_3")
        self.assertIsNone(re.search(check["tags"], "R7.3"))

    def test_dotted_versions_skip_single_number_tags(self):
        # vassal and xcpc have old date tags (20240214) beside their releases.
        check, _ = self.check(
            src("3.7.28", gitRepoUrl="https://github.com/a/b.git", tag="3.7.28")
        )
        self.assertIsNone(re.search(check["tags"], "20240214"))
        self.assertEqual(re.search(check["tags"], "3.7.29").group(1), "3.7.29")
        # A version that's a single number keeps taking single numbers.
        build, _ = self.check(
            src("4065", gitRepoUrl="https://github.com/a/b.git", tag="4065")
        )
        self.assertEqual(re.search(build["tags"], "4119").group(1), "4119")

    def test_versioned_attributes_keep_their_series(self):
        tracy = src(
            "0.11.1", gitRepoUrl="https://github.com/w/tracy.git", tag="v0.11.1"
        )
        pinned, _ = inferred.github_check(tracy, "tracy_0_11")
        self.assertEqual(re.search(pinned["tags"], "v0.11.2").group(1), "0.11.2")
        self.assertIsNone(re.search(pinned["tags"], "v0.14.1"))
        self.assertIsNone(re.search(pinned["tags"], "v0.110.1"))
        # Without the suffix: the newest of all.
        newest, _ = inferred.github_check(tracy, "tracy")
        self.assertEqual(re.search(newest["tags"], "v0.14.1").group(1), "0.14.1")

    def test_series(self):
        cases = {
            ("tracy_0_11", "0.11.1"): "0.11",
            ("gcc13", "13.2.0"): "13",
            ("python313", "3.13.7"): "3.13",
            ("lua5_4", "5.4.6"): "5.4",
            ("x16", "48"): None,  # not its version
            ("wine64", "10.16"): None,
            ("uhexen2", "1.5.10"): None,
            ("foo2", "2"): None,  # the whole version: no series to keep
            ("tracy", "0.13.1"): None,
        }
        for (attr, version), expected in cases.items():
            self.assertEqual(inferred.series(attr, version), expected, attr)

    def test_not_worked_out(self):
        gh = "https://github.com/a/b.git"
        cases = {
            "not from GitHub": src(
                "1.0", gitRepoUrl="https://gitlab.com/a/b.git", tag="1.0"
            ),
            "no tag": src("1.0", url="https://github.com/a/b/raw/main/x"),
            "a commit (unstable version)": src(
                "0-unstable-2024-05-01", gitRepoUrl=gh, rev="a" * 40
            ),
            "not a plain version": src("1.0-beta2", gitRepoUrl=gh, tag="v1.0-beta2"),
            "tag doesn't end with the version": src(
                "3.2.6", gitRepoUrl=gh, tag="R3_2_6"
            ),
        }
        for why, source in cases.items():
            self.assertEqual(self.check(source), (None, why), why)

    def test_first_attribute_that_gives_one(self):
        sources = {
            "heroic": src("2.18.1"),
            "heroic-unwrapped": src(
                "2.18.1", gitRepoUrl="https://github.com/H/heroic.git", tag="v2.18.1"
            ),
        }
        row = {"name": "heroic", "attrs": ["heroic", "heroic-unwrapped"]}
        check, _ = inferred.for_row(row, sources)
        self.assertEqual(check["github"], "H/heroic")
        self.assertEqual(
            inferred.for_row({"name": "x", "attrs": ["x"]}, {}), (None, "no source")
        )


class Verdict(unittest.TestCase):
    def test_against_repology(self):
        def v(version, status="newest", ref=None):
            row = {"nixVersion": "1.0", "nixStatus": status, "refVersion": ref}
            return inferred.verdict(row, version, rule=False)

        self.assertEqual(v("1.0"), ("agree", "up to date"))
        self.assertEqual(v("1.1", "outdated", "1.1"), ("agree", "outdated, 1.1"))
        self.assertEqual(v("1.1"), ("disagree", "GitHub 1.1, Repology up to date"))
        self.assertEqual(
            v("1.0", "outdated", "1.2"), ("disagree", "Repology 1.2, GitHub 1.0")
        )
        # An older version kept beside a newer one: Repology's "legacy"
        # isn't outdated, only a newer release in its own series is.
        self.assertEqual(
            v("1.1", "legacy", "1.2"), ("disagree", "GitHub 1.1, Repology up to date")
        )

    def test_against_its_own_rule(self):
        row = {"nixVersion": "1.0", "upstream": {"version": "1.2"}}
        self.assertEqual(
            inferred.verdict(row, "1.2", rule=True), ("agree", "1.2, as its rule")
        )
        self.assertEqual(
            inferred.verdict(row, "1.3", rule=True),
            ("rule differs", "1.3, its rule 1.2"),
        )


class WorkOut(unittest.TestCase):
    ROWS = [
        {"name": "a", "attrs": ["a"], "nixVersion": "1.0", "nixStatus": "newest"},
        {"name": "b", "attrs": ["b"], "nixVersion": "2.0", "nixStatus": "newest"},
        {"name": "c", "attrs": ["c"], "nixVersion": "3.0", "nixStatus": "newest"},
        {"name": "d", "attrs": ["d"], "nixVersion": "1.0", "nixStatus": "newest"},
        {"name": "gone", "attrs": ["gone"], "nixStatus": "missing"},
    ]
    SOURCES = {
        "a": src("1.0", gitRepoUrl="https://github.com/o/a.git", tag="v1.0"),
        "b": src("2.0", gitRepoUrl="https://github.com/o/b.git", tag="2.0"),
        "c": src("3.0", url="https://example.org/c-3.0.tar.gz"),
        "d": src("1.0", gitRepoUrl="https://github.com/o/d.git", tag="1.0"),
    }

    def setUp(self):
        self.stderr = io.StringIO()
        for patcher in (
            mock.patch("sys.stderr", self.stderr),
            mock.patch.object(github, "token", return_value="t"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def work_out(self, lists=None, rules=None, sources=None):
        with mock.patch.object(
            nixpkgs_source, "sources", **(sources or {"return_value": self.SOURCES})
        ) as get_sources:
            worked = inferred.work_out(lists or {}, self.ROWS, rules or {}, "abc123")
        return worked, get_sources

    def test_works_out_checks(self):
        worked, get_sources = self.work_out()
        # Packages nixpkgs doesn't have aren't evaluated.
        get_sources.assert_called_once_with({"a", "b", "c", "d"}, "abc123", None)
        self.assertEqual(sorted(worked.checks), ["a", "b", "d"])
        self.assertEqual(dict(worked.not_worked), {"not from GitHub": 1})
        self.assertEqual(worked.repology, dict.fromkeys("abcd"))

    def test_rules_win_and_follows_is_left_out(self):
        rules = {"a": {"github": "o/a", "tags": "x"}, "b": {"follows": "a"}}
        worked, _ = self.work_out(rules=rules)
        self.assertEqual(sorted(worked.checks), ["a", "d"])
        self.assertEqual(sorted(worked.to_run(rules)), ["d"])

    def test_off_without_a_token_or_an_evaluation(self):
        worked, get_sources = self.work_out(lists={"workedOutChecks": False})
        self.assertIsNone(worked)
        get_sources.assert_not_called()
        with mock.patch.object(github, "token", return_value=None):
            self.assertIsNone(self.work_out()[0])
        error = nixpkgs_source.EvalError("error: boom")
        self.assertIsNone(self.work_out(sources={"side_effect": error})[0])
        self.assertEqual(
            self.stderr.getvalue(),
            "Worked-out update checks: skipped (no GITHUB_TOKEN)\n"
            "Worked-out update checks: skipped (error: boom)\n",
        )

    def test_report(self):
        rules = {"a": {"github": "o/a", "tags": "^v([0-9.]+)$"}}
        worked, _ = self.work_out(rules=rules)
        rows = [dict(r) for r in self.ROWS]
        # What the update checks did: b's ran and found 2.1 (Repology's view
        # is what it was before), d's failed.
        rows[1]["upstream"] = {"version": "2.1", "inferred": True}
        rows[1]["refVersion"] = "2.1"
        rows[0]["upstream"] = {"version": "1.0"}  # a's own rule
        with (
            mock.patch.object(
                github, "latest_tags", return_value={"o/a": ["v1.0", "v1.1rc1"]}
            ) as latest_tags,
            # On GitHub Actions, as the sync runs: folded in a group.
            mock.patch.object(config, "on_github_actions", return_value=True),
        ):
            inferred.report(worked, rows, rules, {"d": "couldn't read the tags"})
        # Only the worked-out checks of packages with a rule are asked here.
        latest_tags.assert_called_once_with("t", ["o/a"])
        out = self.stderr.getvalue()
        self.assertIn(
            "::group::Worked-out update checks: 3 of 4 packages (2 used, 1 with "
            "a rule), 1 agree with Repology or their rule, 1 don't, 0 differ "
            "from their rule (the rule is used), 1 failed",
            out,
        )
        self.assertIn("Not worked out: 1 not from GitHub", out)
        self.assertIn("  b 2.0: GitHub 2.1, Repology up to date  (o/b)", out)
        self.assertIn("  a 1.0: 1.0, as its rule  (o/a)", out)
        self.assertIn("Failed (left to Repology):\n  d: couldn't read the tags", out)
        self.assertTrue(out.rstrip().endswith("::endgroup::"))

    def test_report_a_rule_that_differs(self):
        rules = {"a": {"github": "o/a", "tags": "^v(0\\.[0-9.]+)$"}}
        worked, _ = self.work_out(rules=rules)
        rows = [dict(r) for r in self.ROWS]
        rows[0]["upstream"] = {"version": "0.9"}  # a's rule: another series
        with (
            mock.patch.object(github, "latest_tags", return_value={"o/a": ["v1.1"]}),
            # GitHub's form, the lines not indented in the group.
            mock.patch.object(config, "on_github_actions", return_value=True),
        ):
            inferred.report(worked, rows, rules, {})
        out = self.stderr.getvalue()
        self.assertIn("0 don't, 1 differ from their rule (the rule is used)", out)
        self.assertIn(
            "Disagree:\nRule differs (the rule is used):\n  a 1.0: 1.1, its rule 0.9",
            out,
        )
