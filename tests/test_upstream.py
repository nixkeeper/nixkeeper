import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest import mock

from nixkeeper import config, schedule
from nixkeeper.changes import is_outdated
from nixkeeper.sources import github, http, upstream
from tests.helpers import http_error, response

NOW = "2026-09-30T06:00:00+00:00"

WESNOTH_TAGS = ["1.19.28", "1.18.8", "1.19.27", "1.19.9", "1.19.24", "1.18.7"]
CHECK = {"github": "wesnoth/wesnoth", "tags": r"^(1\.19\.[0-9]+)$"}


def row(name="wesnoth-devel", nix="1.19.24", status="devel", ref="1.19.24"):
    return {"name": name, "nixVersion": nix, "nixStatus": status, "refVersion": ref}


class Versions(unittest.TestCase):
    def test_ordering(self):
        for older, newer in (
            ("1.19.9", "1.19.28"),
            ("1.19.28", "1.20.0"),
            ("1.0rc1", "1.0.1"),
            ("2.1.20221123", "2.1.20260913"),
        ):
            with self.subTest(older=older, newer=newer):
                self.assertTrue(upstream.is_newer(newer, older))
                self.assertFalse(upstream.is_newer(older, newer))
        self.assertFalse(upstream.is_newer("1.0", None))  # nothing to compare

    def test_latest_matching_tag(self):
        self.assertEqual(upstream.latest(WESNOTH_TAGS, CHECK["tags"]), "1.19.28")
        self.assertEqual(
            upstream.latest(["v2.3.0", "v2.10.1"], r"^v([0-9.]+)$"), "2.10.1"
        )
        # Without a capture group the whole match is the version.
        self.assertEqual(upstream.latest(["1.2", "1.10"], r"^[0-9.]+$"), "1.10")
        self.assertIsNone(upstream.latest(["nightly"], r"^[0-9.]+$"))


class Apply(unittest.TestCase):
    def test_newer_release_makes_it_outdated(self):
        r = row()
        upstream.apply(r, {"version": "1.19.28", "repo": "wesnoth/wesnoth"})
        self.assertTrue(r["upstream"]["newer"])
        self.assertEqual(r["refVersion"], "1.19.28")
        self.assertTrue(is_outdated(r))

    def test_up_to_date(self):
        r = row()
        upstream.apply(r, {"version": "1.19.24", "repo": "wesnoth/wesnoth"})
        self.assertFalse(r["upstream"]["newer"])
        self.assertEqual(r["refVersion"], "1.19.24")
        self.assertFalse(is_outdated(r))

    def test_repology_already_ahead_keeps_its_version(self):
        r = row(status="outdated", ref="1.19.30")
        upstream.apply(r, {"version": "1.19.28", "repo": "wesnoth/wesnoth"})
        self.assertEqual(r["refVersion"], "1.19.30")


class Decides(unittest.TestCase):
    """A rule's check decides where it and Repology disagree."""

    CHROME = {"version": "155.0.8059.39", "label": "versionhistory.googleapis.com"}

    def chrome(self):
        # Repology's rule had 155 and up as betas after 155 went stable: it
        # called nixpkgs outdated, against an older stable.
        return row("google-chrome", "155.0.8059.39", "outdated", "154.0.8037.97")

    def test_up_to_date_by_its_rule(self):
        r = self.chrome()
        upstream.apply(r, self.CHROME)
        self.assertEqual(r["nixStatus"], "newest")
        self.assertIsNone(r["refVersion"])
        self.assertEqual(
            r["repologySaid"], {"status": "outdated", "newest": "154.0.8037.97"}
        )
        self.assertFalse(is_outdated(r))

    def test_outdated_by_its_rule(self):
        r = row("bbedit", "15.5.1", "newest", "15.5.1")
        upstream.apply(r, {"version": "15.5.2"})
        self.assertEqual(r["nixStatus"], "outdated")
        self.assertEqual(r["refVersion"], "15.5.2")
        self.assertEqual(r["repologySaid"], {"status": "newest", "newest": "15.5.1"})

    def test_agreeing_keeps_repology(self):
        r = row(status="outdated", ref="1.19.30")
        upstream.apply(r, {"version": "1.19.28"})
        self.assertEqual(r["nixStatus"], "outdated")
        self.assertNotIn("repologySaid", r)

    def test_checked_again_starts_from_repology(self):
        r = self.chrome()
        upstream.apply(r, self.CHROME)
        once = dict(r)
        upstream.apply(r, self.CHROME)  # the hourly check, Repology not refreshed
        self.assertEqual(r, once)
        upstream.apply(r, {"version": "155.0.8059.50"})  # a new stable
        self.assertEqual(r["nixStatus"], "outdated")
        self.assertEqual(r["refVersion"], "155.0.8059.50")
        self.assertNotIn("repologySaid", r)  # agreeing now: nothing overruled

    def test_worked_out_failed_or_kept_dont_decide(self):
        for found, failing, status in (
            ({**self.CHROME, "inferred": True}, False, "outdated"),
            (self.CHROME, True, "outdated"),  # the last result of a failing rule
            (self.CHROME, False, "legacy"),  # kept beside a newer one
        ):
            with self.subTest(found=found, failing=failing, status=status):
                r = self.chrome()
                r["nixStatus"] = status
                if failing:  # as add_checks marks it, keeping its result
                    r["notRefreshed"] = {"upstream": {"since": "x", "reason": "x"}}
                upstream.apply(r, found)
                self.assertEqual(r["nixStatus"], status)
                self.assertEqual(r["refVersion"], "154.0.8037.97")
                self.assertNotIn("repologySaid", r)

    def test_worked_out_adds_nothing_to_a_kept_version(self):
        # fuse 2.9.9 kept beside fuse 3: its repository's newest isn't for it.
        r = row(status="legacy", ref="3.18.3")
        upstream.apply(r, {"version": "3.18.3", "inferred": True})
        self.assertFalse(r["upstream"]["newer"])
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("legacy", "3.18.3"))
        # Nor to one outdated in its own series (electron_42, 2026-10-15):
        # its target stays the series' newest, not the repository's.
        r = {
            **row(
                name="electron_42", nix="42.11.10", status="outdated", ref="42.11.14"
            ),
            "keptBeside": {"attr": "electron_44", "version": "44.5.1"},
        }
        upstream.apply(r, {"version": "44.7.2", "inferred": True})
        self.assertFalse(r["upstream"]["newer"])
        self.assertEqual((r["nixStatus"], r["refVersion"]), ("outdated", "42.11.14"))
        # A devel variant fallen behind still counts.
        r = {**row(status="legacy", ref="3.18.3"), "devel": True}
        upstream.apply(r, {"version": "3.18.3", "inferred": True})
        self.assertTrue(r["upstream"]["newer"])

    def test_an_up_to_date_rule_silences_the_version_it_names(self):
        r = {**row(status="newest", ref=None), "upToDate": {"ruleNewest": "2.0.0"}}
        upstream.apply(r, {"version": "2.0.0", "inferred": True})
        self.assertFalse(r["upstream"]["newer"])
        # A rule's own check still decides.
        upstream.apply(r, {"version": "2.0.0"})
        self.assertTrue(r["upstream"]["newer"])
        # Another version still counts (twinejs: the rule is about
        # Repology's 7.0.0, another project's; 2.12.1 is a real release).
        r = {**row(nix="2.12.0", status="newest", ref=None)}
        r["upToDate"] = {"newest": "7.0.0", "ruleNewest": "7.0.0"}
        upstream.apply(r, {"version": "2.12.1", "inferred": True})
        self.assertTrue(r["upstream"]["newer"])


class AddChecks(unittest.TestCase):
    def setUp(self):
        self.stderr = io.StringIO()
        for patcher in (
            mock.patch("sys.stderr", self.stderr),
            mock.patch.object(github, "token", return_value="t"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_checks(self, rows, checks, tags=None, error=None, previous=None):
        kwargs = {"side_effect": error} if error else {"return_value": tags}
        with mock.patch.object(github, "latest_tags", **kwargs) as latest_tags:
            upstream.add_checks(rows, checks, previous or {"packages": []}, NOW)
        return latest_tags

    def test_worked_out_checks_are_marked_and_fail_quietly(self):
        rows = [row(), row("gone", "1.0", "newest", "1.0")]
        gone = {"github": "o/gone", "tags": "^([0-9.]+)$"}
        with mock.patch.object(
            github, "latest_tags", return_value={"wesnoth/wesnoth": WESNOTH_TAGS}
        ):
            failed = upstream.add_checks(
                rows,
                {"wesnoth-devel": CHECK, "gone": gone},
                {"packages": []},
                NOW,
                inferred={"wesnoth-devel", "gone"},
            )
        self.assertIs(rows[0]["upstream"]["inferred"], True)
        # Nobody wrote it to fix: left to Repology, no warning, not stale.
        self.assertEqual(
            failed, {"gone": "couldn't read the tags of o/gone (renamed or deleted?)"}
        )
        self.assertNotIn("upstream", rows[1])
        self.assertNotIn("notRefreshed", rows[1])
        self.assertNotIn("warning: ", self.stderr.getvalue())

    def test_check(self):
        rows = [row(), row("wesnoth", "1.18.8", "newest", "1.18.8")]
        latest_tags = self.run_checks(
            rows,
            {"wesnoth-devel": CHECK, "not-tracked": CHECK},
            {"wesnoth/wesnoth": WESNOTH_TAGS},
        )
        latest_tags.assert_called_once_with("t", ["wesnoth/wesnoth"])
        self.assertEqual(
            rows[0]["upstream"],
            {
                "version": "1.19.28",
                "repo": "wesnoth/wesnoth",
                "label": "wesnoth/wesnoth tags",
                "url": "https://github.com/wesnoth/wesnoth/tags",
                "newer": True,
                "checkedAt": NOW,
                "rule": upstream.fingerprint(CHECK),
            },
        )
        self.assertNotIn("upstream", rows[1])  # no check for it
        # A check for a package that isn't tracked doesn't run (listcheck.py
        # reports it with the lists).
        self.assertNotIn("not-tracked", self.stderr.getvalue())

    def test_failure_keeps_previous_result_and_says_so(self):
        old = {"version": "1.19.26", "repo": "wesnoth/wesnoth", "newer": True}
        previous = {"packages": [{"name": "wesnoth-devel", "upstream": old}]}
        for reason, kwargs in (
            ("GitHub request failed", {"error": urllib.error.URLError("down")}),
            ("renamed or deleted?", {"tags": {}}),
            ("matches", {"tags": {"wesnoth/wesnoth": ["nightly"]}}),
        ):
            with self.subTest(reason=reason):
                rows = [row()]
                self.run_checks(
                    rows, {"wesnoth-devel": CHECK}, previous=previous, **kwargs
                )
                self.assertEqual(rows[0]["upstream"]["version"], "1.19.26")
                self.assertEqual(rows[0]["refVersion"], "1.19.26")
                failing = rows[0]["notRefreshed"]["upstream"]
                self.assertEqual(failing["since"], NOW)
                self.assertIn(reason, failing["reason"])
        self.assertIn("warning: update check for wesnoth-devel", self.stderr.getvalue())

    def test_no_token_counts_as_failing(self):
        rows = [row()]
        with mock.patch.object(github, "token", return_value=None):
            self.run_checks(rows, {"wesnoth-devel": CHECK}, {})
        self.assertNotIn("upstream", rows[0])  # nothing to fall back on
        self.assertIn("no GITHUB_TOKEN", rows[0]["notRefreshed"]["upstream"]["reason"])

    def test_failing_since_carries_over(self):
        since = "2026-09-28T06:00:00+00:00"
        previous = {
            "packages": [
                {
                    "name": "wesnoth-devel",
                    "notRefreshed": {"upstream": {"since": since, "reason": "x"}},
                }
            ]
        }
        rows = [row()]
        self.run_checks(rows, {"wesnoth-devel": CHECK}, {}, previous=previous)
        self.assertEqual(rows[0]["notRefreshed"]["upstream"]["since"], since)
        # Working again: no marker.
        rows = [row()]
        self.run_checks(
            rows,
            {"wesnoth-devel": CHECK},
            {"wesnoth/wesnoth": WESNOTH_TAGS},
            previous=previous,
        )
        self.assertNotIn("notRefreshed", rows[0])


# Trimmed from https://www.barebones.com/support/bbedit/updates.html (2026-09).
BBEDIT_PAGE = """<h2>BBEdit 16.0.3</h2><p>Fixed a crash in BBEdit 16.0.2 when...</p>
<h2>BBEdit 15.5.5</h2><p>Requires macOS 12 or later.</p><h2>BBEdit 14.6.9</h2>"""
BBEDIT = {
    "url": "https://www.barebones.com/support/bbedit/updates.html",
    "pattern": r"BBEdit ([0-9]+\.[0-9]+\.[0-9]+)",
}


class PageChecks(unittest.TestCase):
    def setUp(self):
        self.stderr = io.StringIO()
        for patcher in (
            mock.patch("sys.stderr", self.stderr),
            mock.patch("time.sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_highest_version_anywhere_on_the_page(self):
        self.assertEqual(
            upstream.latest_on_page(BBEDIT_PAGE, BBEDIT["pattern"]), "16.0.3"
        )
        # Order on the page doesn't matter.
        reversed_page = "BBEdit 15.5.5 ... BBEdit 16.0.3"
        self.assertEqual(
            upstream.latest_on_page(reversed_page, BBEDIT["pattern"]), "16.0.3"
        )

    def run_check(self, rows, urlopen, previous=None):
        with (
            mock.patch("urllib.request.urlopen", **urlopen),
            mock.patch.object(github, "token", return_value="t"),
        ):
            upstream.add_checks(
                rows, {"bbedit": BBEDIT}, previous or {"packages": []}, NOW
            )

    def test_page_check(self):
        page = response("x")
        page.read.return_value = BBEDIT_PAGE.encode()
        rows = [row("bbedit", "16.0.2", "newest", "16.0.2")]
        self.run_check(rows, {"return_value": page})
        self.assertEqual(
            rows[0]["upstream"],
            {
                "version": "16.0.3",
                "label": "www.barebones.com",
                "url": BBEDIT["url"],
                "newer": True,
                "checkedAt": NOW,
                "rule": upstream.fingerprint(BBEDIT),
            },
        )
        self.assertEqual(rows[0]["refVersion"], "16.0.3")

    def test_page_problems_keep_previous_result(self):
        old = {"version": "16.0.3", "label": "www.barebones.com", "newer": False}
        previous = {"packages": [{"name": "bbedit", "upstream": old}]}
        nothing = response("x")
        nothing.read.return_value = b"<p>Page redesigned</p>"
        for why, urlopen in (
            ("answered 404", {"side_effect": http_error(404)}),
            ("couldn't fetch", {"side_effect": urllib.error.URLError("down")}),
            ("matches", {"return_value": nothing}),
        ):
            with self.subTest(why=why), mock.patch.object(config, "RETRY_DELAYS", []):
                rows = [row("bbedit", "16.0.3", "newest", "16.0.3")]
                self.run_check(rows, urlopen, previous)
                self.assertEqual(rows[0]["upstream"]["version"], "16.0.3")
                self.assertIn(why, rows[0]["notRefreshed"]["upstream"]["reason"])
                self.assertIn(why, self.stderr.getvalue())


STEPMANIA = {"github": "stepmania/stepmania", "branch": "5_1-new"}
UNSTABLE = "5.1.0-b2-unstable-2022-11-14"


def head(since=0, until=0, date="2026-08-22T03:31:23Z"):
    """GitHub's answer for a branch: its newest commit, and how many commits
    since nixpkgs' version (and old enough to count)."""
    return {
        "oid": "825467bcd81c",
        "committedDate": date,
        "since": since,
        "until": until,
    }


class UnstableVersions(unittest.TestCase):
    def test_unstable_version(self):
        self.assertEqual(
            upstream.unstable_version(UNSTABLE, "2026-08-22T03:31:23Z"),
            "5.1.0-b2-unstable-2026-08-22",
        )
        # The date is UTC's, as in nixpkgs: 20:31 in UTC-7 is the next day.
        self.assertEqual(
            upstream.unstable_version(UNSTABLE, "2026-08-21T20:31:23-07:00"),
            "5.1.0-b2-unstable-2026-08-22",
        )
        # Never older than nixpkgs' own (another branch's commit, say).
        self.assertEqual(
            upstream.unstable_version(UNSTABLE, "2020-01-01T00:00:00Z"), UNSTABLE
        )
        self.assertIsNone(upstream.unstable_version("5.0.12", "2026-08-22T00:00:00Z"))
        self.assertIsNone(upstream.unstable_version(None, "2026-08-22T00:00:00Z"))

    def test_outdated_after(self):
        self.assertEqual(upstream.outdated_after({}), {"days": 90, "commits": None})
        self.assertEqual(
            upstream.outdated_after({"outdatedAfter": {"commits": 50}}),
            {"days": 90, "commits": 50},
        )
        self.assertEqual(
            upstream.outdated_after({"outdatedAfter": {"days": None, "commits": 5}}),
            {"days": None, "commits": 5},
        )

    def run_checks(self, check=STEPMANIA, nix=UNSTABLE, answer=None, error=None):
        rows = [row("stepmania", nix, "untrusted", "5.0.12")]
        kwargs = {"side_effect": error} if error else {"return_value": [answer]}
        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(github, "latest_tags") as latest_tags,
            mock.patch.object(github, "branch_commits", **kwargs) as branch_commits,
        ):
            upstream.add_checks(rows, {"stepmania": check}, {"packages": []}, NOW)
        latest_tags.assert_not_called()  # no tag checks: no tag request
        return rows[0], branch_commits

    def test_query(self):
        _, branch_commits = self.run_checks(answer=head())
        # From the day after nixpkgs' commit; old enough: before 90 days ago.
        branch_commits.assert_called_once_with(
            "t",
            [
                (
                    "stepmania/stepmania",
                    "5_1-new",
                    "2022-11-15T00:00:00Z",
                    "2026-07-02T06:00:00Z",
                )
            ],
        )

    def test_outdated_once_a_commit_has_waited(self):
        r, _ = self.run_checks(answer=head(since=40, until=12))
        self.assertEqual(
            r["upstream"],
            {
                "version": "5.1.0-b2-unstable-2026-08-22",
                "newer": True,
                "behind": 40,
                "outdatedAfter": {"days": 90, "commits": None},
                "repo": "stepmania/stepmania",
                "label": "stepmania/stepmania 5_1-new branch",
                "url": "https://github.com/stepmania/stepmania/commits/5_1-new",
                "commit": "825467bcd81c",
                "checkedAt": NOW,
                "rule": upstream.fingerprint(STEPMANIA),
            },
        )
        self.assertEqual(r["refVersion"], "5.1.0-b2-unstable-2026-08-22")
        self.assertTrue(is_outdated(r))  # although Repology says untrusted

    def test_newer_commits_not_counted_yet(self):
        r, _ = self.run_checks(answer=head(since=3, until=0))
        self.assertFalse(r["upstream"]["newer"])
        self.assertEqual(r["upstream"]["behind"], 3)
        self.assertEqual(r["refVersion"], "5.0.12")  # untouched
        self.assertFalse(is_outdated(r))

    def test_enough_commits(self):
        check = {**STEPMANIA, "outdatedAfter": {"commits": 50}}
        r, _ = self.run_checks(check, answer=head(since=50, until=0))
        self.assertTrue(r["upstream"]["newer"])
        r, _ = self.run_checks(check, answer=head(since=49, until=0))
        self.assertFalse(r["upstream"]["newer"])

    def test_days_off(self):
        check = {**STEPMANIA, "outdatedAfter": {"days": None, "commits": 50}}
        r, branch_commits = self.run_checks(check, answer=head(since=10))
        self.assertIsNone(branch_commits.call_args.args[1][0][3])  # no until
        self.assertFalse(r["upstream"]["newer"])

    def test_too_recent_to_have_waited(self):
        # nixpkgs' version is from 10 days ago: no commit can have waited 90.
        _, branch_commits = self.run_checks(
            nix="5.1.0-b2-unstable-2026-09-20", answer=head()
        )
        self.assertIsNone(branch_commits.call_args.args[1][0][3])

    def test_up_to_date(self):
        r, _ = self.run_checks(answer=head(date="2022-11-14T10:00:00Z"))
        self.assertEqual(r["upstream"]["version"], UNSTABLE)
        self.assertFalse(r["upstream"]["newer"])

    def test_failures(self):
        for reason, kwargs in (
            ("GitHub request failed", {"error": urllib.error.URLError("x")}),
            ("renamed or deleted?", {"answer": None}),
            ("isn't an unstable version", {"nix": "5.0.12", "answer": head()}),
        ):
            with self.subTest(reason=reason):
                r, _ = self.run_checks(**kwargs)
                self.assertNotIn("upstream", r)  # nothing to fall back on
                self.assertIn(reason, r["notRefreshed"]["upstream"]["reason"])


class BranchCommits(unittest.TestCase):
    def test_query_and_answer(self):
        target = {
            "oid": "abc",
            "committedDate": "2026-08-22T03:31:23Z",
            "since": {"totalCount": 40},
            "until": {"totalCount": 12},
        }
        resp = response(
            {
                "data": {
                    "r0": {"ref": {"target": target}},
                    "r1": {"ref": None},  # no such branch
                }
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            results = github.branch_commits(
                "t",
                [
                    ("a/one", "main", "2022-11-15T00:00:00Z", "2026-07-02T06:00:00Z"),
                    ("b/two", "gone", "2022-11-15T00:00:00Z", None),
                ],
            )
        self.assertEqual(
            results,
            [
                {
                    "oid": "abc",
                    "committedDate": "2026-08-22T03:31:23Z",
                    "since": 40,
                    "until": 12,
                },
                None,
            ],
        )
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body["variables"]["b0"], "refs/heads/main")
        self.assertEqual(body["variables"]["u0"], "2026-07-02T06:00:00Z")
        self.assertNotIn("u1", body["variables"])  # no until: not asked
        self.assertIn("history(since: $s0, until: $u0)", body["query"])
        self.assertNotIn("$u1", body["query"])


class LatestTags(unittest.TestCase):
    def test_query_and_answer(self):
        resp = response(
            {
                "data": {
                    "r0": {"refs": {"nodes": [{"name": "v1.1"}, {"name": "v1.0"}]}},
                    "r1": None,  # not found
                }
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            tags = github.latest_tags("t", ["a/one", "b/missing"])
        self.assertEqual(tags, {"a/one": ["v1.1", "v1.0"]})
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(
            body["variables"], {"o0": "a", "n0": "one", "o1": "b", "n1": "missing"}
        )
        self.assertIn("TAG_COMMIT_DATE", body["query"])


class UnchangedPages(unittest.TestCase):
    """A page check asks the server to send the page only if it changed since
    the last time (its ETag and Last-Modified): if it didn't, what was found
    then still holds."""

    ETAG = '"0x8DF20DCB9D18510"'
    MODIFIED = "Fri, 02 Oct 2026 23:27:29 GMT"

    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("time.sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def check(self, answer, previous=None, check=BBEDIT):
        """Run the bbedit check against a server answering answer (a body, or
        304). Returns (the row, the request's headers)."""
        sent = []

        def urlopen(req, timeout):
            sent.append(dict(req.header_items()))
            if answer == 304:
                e = http_error(304)
                e.headers = {}
                raise e
            resp = response("x")
            resp.read.return_value = answer.encode()
            resp.headers = {"ETag": self.ETAG, "Last-Modified": self.MODIFIED}
            return resp

        rows = [row("bbedit", "16.0.2", "newest", "16.0.2")]
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            upstream.add_checks(
                rows, {"bbedit": check}, {"packages": previous or []}, NOW
            )
        return rows[0], sent[-1]

    def first(self):
        """A row as the first check leaves it, and the request it sent."""
        return self.check(BBEDIT_PAGE)

    def test_the_first_read_remembers_the_page(self):
        first, sent = self.first()
        self.assertNotIn("If-none-match", sent)
        self.assertEqual(
            first["upstream"]["page"],
            {
                "etag": self.ETAG,
                "lastModified": self.MODIFIED,
                "pattern": BBEDIT["pattern"],
            },
        )

    def test_unchanged_keeps_what_was_found(self):
        first, _ = self.first()
        before = {**first["upstream"], "checkedAt": "2026-09-29T06:00:00+00:00"}
        again, sent = self.check(304, [{"name": "bbedit", "upstream": before}])
        self.assertEqual(sent.get("If-none-match"), self.ETAG)
        self.assertEqual(sent.get("If-modified-since"), self.MODIFIED)
        self.assertEqual(again["upstream"]["version"], "16.0.3")
        self.assertEqual(again["upstream"]["checkedAt"], NOW)
        self.assertEqual(again["upstream"]["page"], before["page"])
        self.assertTrue(again["upstream"]["newer"])
        self.assertNotIn("notRefreshed", again)

    def test_changed_is_read_again(self):
        first, _ = self.first()
        page = BBEDIT_PAGE.replace("16.0.3", "16.0.4")
        again, sent = self.check(
            page, [{"name": "bbedit", "upstream": first["upstream"]}]
        )
        self.assertEqual(sent.get("If-none-match"), self.ETAG)
        self.assertEqual(again["upstream"]["version"], "16.0.4")

    def test_a_changed_rule_reads_it_whole(self):
        first, _ = self.first()
        previous = [{"name": "bbedit", "upstream": first["upstream"]}]
        for name, check in (
            ("pattern", {**BBEDIT, "pattern": r"BBEdit ([0-9.]+)"}),
            ("url", {**BBEDIT, "url": BBEDIT["url"] + "?new"}),
        ):
            with self.subTest(name):
                _, sent = self.check(BBEDIT_PAGE, previous, check)
                self.assertNotIn("If-none-match", sent)
                self.assertNotIn("If-modified-since", sent)

    def test_a_server_that_gives_neither_isnt_asked(self):
        def urlopen(req, timeout):
            urlopen.sent = dict(req.header_items())
            resp = response("x")
            resp.read.return_value = BBEDIT_PAGE.encode()
            return resp  # no ETag, no Last-Modified

        rows = [row("bbedit", "16.0.2", "newest", "16.0.2")]
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            upstream.add_checks(rows, {"bbedit": BBEDIT}, {"packages": []}, NOW)
            upstream.add_checks(
                rows, {"bbedit": BBEDIT}, {"packages": [dict(rows[0])]}, NOW
            )
        self.assertNotIn("page", rows[0]["upstream"])
        self.assertNotIn("If-none-match", urlopen.sent)


class QuietChecks(unittest.TestCase):
    """Update checks that found nothing new run every QUIET_DAYS (schedule.py);
    frequent ones, and those with something going on, every time."""

    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(github, "token", return_value="t"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def not_its_day(self, name="bbedit"):
        when = datetime.fromisoformat(NOW)
        while schedule.slot(name, when):
            when += timedelta(days=1)
        return when.isoformat()

    def last(self, now, check=BBEDIT, **changes):
        """bbedit's row as a sync a day before now left it: nothing new."""
        upstream_ = {
            "version": "16.0.2",
            "label": "www.barebones.com",
            "url": check["url"],
            "newer": False,
            "checkedAt": (datetime.fromisoformat(now) - timedelta(days=1)).isoformat(),
            "rule": upstream.fingerprint(check),
        }
        before = {"name": "bbedit", "nixVersion": "16.0.2", "upstream": upstream_}
        for key, value in changes.items():
            (upstream_ if key in upstream_ else before)[key] = value
        return before

    def check(self, check, before, now, nix="16.0.2"):
        """(the row after the checks, whether the page was asked for)."""
        rows = [row("bbedit", nix, "newest", nix)]
        page = BBEDIT_PAGE.replace("16.0.3", "16.0.2")
        with mock.patch.object(http, "get_page", return_value=(page, {})) as get:
            upstream.add_checks(
                rows, {"bbedit": check}, {"packages": [before] if before else []}, now
            )
        return rows[0], get.called

    def test_nothing_new_lately_isnt_run(self):
        now = self.not_its_day()
        before = self.last(now)
        r, asked = self.check(BBEDIT, before, now)
        self.assertFalse(asked)
        self.assertEqual(r["upstream"], before["upstream"])
        self.assertNotIn("notRefreshed", r)

    def test_a_newer_version_found_is_checked_daily(self):
        now = self.not_its_day()
        when = datetime.fromisoformat(now)
        for hours, expected in ((3, False), (22, True)):
            with self.subTest(hours=hours):
                before = self.last(
                    now,
                    newer=True,
                    checkedAt=(when - timedelta(hours=hours)).isoformat(),
                )
                _, asked = self.check(BBEDIT, before, now)
                self.assertEqual(asked, expected)

    def test_frequent_always_runs(self):
        now = self.not_its_day()
        check = {**BBEDIT, "frequent": True}
        _, asked = self.check(check, self.last(now, check), now)
        self.assertTrue(asked)

    def test_something_going_on_runs(self):
        now = self.not_its_day()
        for name, before, nix in (
            ("new", None, "16.0.2"),
            ("never run", self.last(now, checkedAt=None), "16.0.2"),
            ("rule edited", self.last(now, rule="something else"), "16.0.2"),
            ("found a newer one", self.last(now, newer=True), "16.0.2"),
            ("nixpkgs moved", self.last(now), "16.0.3"),
            (
                "failed last time",
                self.last(now, notRefreshed={"upstream": {"since": NOW}}),
                "16.0.2",
            ),
        ):
            with self.subTest(name):
                _, asked = self.check(BBEDIT, before, now, nix)
                self.assertTrue(asked)

    def test_three_days_on_it_runs(self):
        now = self.not_its_day()
        before = self.last(now)
        before["upstream"]["checkedAt"] = (
            datetime.fromisoformat(now) - timedelta(days=3)
        ).isoformat()
        r, asked = self.check(BBEDIT, before, now)
        self.assertTrue(asked)
        self.assertEqual(r["upstream"]["checkedAt"], now)


class BatchedRepositories(unittest.TestCase):
    """Tags and branches are asked GITHUB_REPOS_BATCH repositories at a time;
    a request that fails only affects its own."""

    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(github, "token", return_value="t"),
            mock.patch.object(config, "GITHUB_REPOS_BATCH", 2),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_tags(self):
        names = [f"p{i}" for i in range(5)]
        checks = {n: {"github": f"o/{n}", "tags": r"^v?([0-9.]+)$"} for n in names}
        rows = [row(n, "1.0", "newest", "1.0") for n in names]

        def latest_tags(token, repos):
            if "o/p2" in repos:
                raise urllib.error.URLError("down")
            return {r: ["2.0"] for r in repos}

        with mock.patch.object(github, "latest_tags", side_effect=latest_tags) as asked:
            upstream.add_checks(rows, checks, {"packages": []}, NOW)
        self.assertEqual([len(c.args[1]) for c in asked.call_args_list], [2, 2, 1])
        failed = [r["name"] for r in rows if "notRefreshed" in r]
        self.assertEqual(failed, ["p2", "p3"])  # their request, not the others
        self.assertEqual(rows[0]["upstream"]["version"], "2.0")
        self.assertEqual(rows[4]["upstream"]["version"], "2.0")

    def test_branches(self):
        names = [f"p{i}" for i in range(3)]
        checks = {n: {"github": f"o/{n}", "branch": "main"} for n in names}
        rows = [row(n, UNSTABLE, "newest", UNSTABLE) for n in names]
        with mock.patch.object(
            github, "branch_commits", side_effect=lambda t, b: [head()] * len(b)
        ) as asked:
            upstream.add_checks(rows, checks, {"packages": []}, NOW)
        self.assertEqual([len(c.args[1]) for c in asked.call_args_list], [2, 1])
        self.assertTrue(all(r["upstream"]["commit"] for r in rows))


class Interleaved(unittest.TestCase):
    def test_takes_turns_between_sites(self):
        pages = {
            "a1": {"url": "https://pypi.org/a"},
            "a2": {"url": "https://pypi.org/b"},
            "a3": {"url": "https://PYPI.org/c"},
            "b1": {"url": "https://example.org/x"},
            "c1": {"url": "https://www.barebones.com/y"},
            "b2": {"url": "https://example.org/z"},
        }
        self.assertEqual(
            upstream.interleaved(pages), ["a1", "b1", "c1", "a2", "b2", "a3"]
        )
        self.assertEqual(upstream.interleaved({}), [])
