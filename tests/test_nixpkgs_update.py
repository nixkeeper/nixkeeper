import io
import unittest
import urllib.error
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import nixpkgs_update
from tests.helpers import http_error, pkg

NOW = "2026-09-30T06:00:00+00:00"

# Trimmed from real logs at nixpkgs-update-logs.nixos.org (2026-09).
HEAD = (
    "Running nixpkgs-update (https://nix-community.org/update-bot/) with UPDATE_INFO: "
)
FAILED = f"""{HEAD}egoboo 2.7.3 -> 2.8.1 https://repology.org/project/egoboo/versions
attrpath: egoboo
Received ExitFailure 1 when running
Running phase: buildPhase
@nix {{ "action": "setPhase", "phase": "buildPhase" }}
\x1b[0mno Makefile or custom buildPhase, doing nothing
/nix/store/dp0z-stdenv-linux/setup: line 1770: cd: source: No such file or directory
"""
PR_OPENED = f"""{HEAD}unciv 4.21.19 -> 4.22.1 https://github.com/yairm210/Unciv/releases
Successfully finished processing
https://api.github.com/repos/NixOS/nixpkgs/pulls/565255
"""
PR_EXISTS = f"""{HEAD}bbedit 15.5.5 -> 16.0.3 https://repology.org/project/bbedit/versions
There might already be an open PR for this update:
- bbedit: 15.5.5 -> 16.0.3
  URL "https://api.github.com/repos/NixOS/nixpkgs/issues/558133"
"""
NO_CHANGE = f"""{HEAD}wesnoth 0 -> 1
[updateScript] Success
The diff was empty after rewrites.
"""
ALREADY_UPDATED = f"""{HEAD}libfilezilla 0.56.1 -> 0.57.0 https://repology.org/project/libfilezilla/versions
Old version 0.56.1" not present in master derivation file with contents: {{
"""
# A real version, but no rewriter could update the package (the-legend-of-
# edgar's 1.37 -> 1.38 attempt, 2026-09-26).
CANT_UPDATE = f"""{HEAD}the-legend-of-edgar 1.37 -> 1.38 https://github.com/riksweeney/edgar/releases
attrpath: the-legend-of-edgar
[version]
[version] generic version rewriter does not support multiple hashes
[rustCrateVersion]
[rustCrateVersion] No cargoHash found
[updateScript]
[updateScript] skipping because derivation has no updateScript
The diff was empty after rewrites.
"""
# An updateScript package: "0 -> 1", nixpkgs' version in the package line, and
# the version it updated to in the diff (wesnoth-devel's failed 1.19.24 ->
# 1.19.28 attempt, 2026-09-22).
UPDATE_SCRIPT_FAILED = f"""{HEAD}wesnoth-devel 0 -> 1
attrpath: wesnoth-devel
[updateScript] Success
Going to be running update for following packages:
 - wesnoth-devel-1.19.24

Diff after rewrites:
--- a/pkgs/by-name/we/wesnoth/package.nix
+++ b/pkgs/by-name/we/wesnoth/package.nix
-  version = if enableDevel then "1.19.24" else "1.18.8";
+  version = if enableDevel then "1.19.28" else "1.18.8";

Received ExitFailure 1 when running
-- Configuring incomplete, errors occurred!
"""
# An updateScript that fails before writing a diff: "0 -> 1", and only what
# nixpkgs had in the package line (blackvoxel's 2026-09-27 attempt).
UPDATE_SCRIPT_ERROR = f"""{HEAD}blackvoxel 0 -> 1
attrpath: blackvoxel
[updateScript] Failed with exit code 1
Going to be running update for following packages:
 - blackvoxel-2.5

The update script for blackvoxel-2.5 failed with exit code 1
"""


# Parser 3's outcomes, each trimmed from a log the digest read as "other"
# (2026-09-29 to 10-05).
# karakeep's: the bot had already pushed 0.33.2 to its branch.
BRANCH_EXISTS = f"""{HEAD}karakeep 0.33.1 -> 0.33.2 https://github.com/karakeep-app/karakeep/releases
attrpath: karakeep
Checking auto update branch...
[version] generic version rewriter does not support multiple hashes
[updateScript] Success
Diff after rewrites:
An auto update branch exists with message `karakeep: 0.33.1 -> 0.33.2`. \
New version is 0.33.2.
An auto update branch exists with an equal or greater version
"""
# lilypond-unstable's: an updateScript package, its versions only in the
# branch's message.
BRANCH_EXISTS_SCRIPT = f"""{HEAD}lilypond-unstable 0 -> 1
attrpath: lilypond-unstable
Checking auto update branch...
An auto update branch exists with message `lilypond-unstable: 2.27.2 -> 2.27.3`. \
New version is 2.27.3.
An auto update branch exists with an equal or greater version
"""
NOT_NEWER = f"""{HEAD}xmonad-log 0.1.0-unstable-2024-06-14 -> 0.1.0 https://github.com/xintron/xmonad-log/releases
attrpath: xmonad-log
Checking auto update branch...
No auto update branch exists
0.1.0 is not newer than 0.1.0-unstable-2024-06-14 according to Nix; \
versionComparison: -1 \n"""
HASHES_EQUAL = f"""{HEAD}dislocker 0.7.3-unstable-2025-09-07 -> 2026.08.31 https://repology.org/project/dislocker/versions
attrpath: dislocker
Checking auto update branch...
No auto update branch exists
[version] \nHashes equal; no update necessary
"""
SOURCE_UNCHANGED = f"""{HEAD}mictray 0.2.5 -> 0.3.1 https://github.com/Junker/mictray/releases
attrpath: mictray
Checking auto update branch...
No auto update branch exists
[version] updated version and sha256
Diff after rewrites:
+    sha256 = "sha256-5LAUU43Vh6n4He171ujT4/v8G0YsHU1f1IEVUrKRkCk=";
Source url did not change. \n"""
# Skipped on purpose, after each of the bot's checks.
SKIPPED_OPT_OUT = f"""{HEAD}rakudo 2026.07 -> 2026.09 https://github.com/rakudo/rakudo/releases
attrpath: rakudo
Checking auto update branch...
No auto update branch exists
Derivation file opts-out of auto-updates
"""
SKIPPED_GNOME = f"""{HEAD}errands 0 -> 1
attrpath: errands
Checking auto update branch...
Do not update GNOME during a release cycle
"""
SKIPPED_LOCKSTEP = f"""{HEAD}rocmPackages.miopen 0 -> 1
attrpath: rocmPackages.miopen
rocm packages are upgraded in lockstep https://github.com/NixOS/nixpkgs/issues/385294
"""
SKIPPED_REBUILDS = f"""{HEAD}python3Packages.pint 0 -> 1
attrpath: python3Packages.pint
Checking auto update branch...
   build-system = [

No auto update branch exists
Python package with too many package rebuilds 3150  > 100
"""
# crack-hash's: opening the PR failed, GitHub answering 500.
HTTP_FAILED = f"""{HEAD}crack-hash 1.1.0-unstable-2025-12-31 -> 1.2.0 https://github.com/kOaDT/crack-hash/releases
attrpath: crack-hash
[updateScript] Success
HTTPError (HttpExceptionRequest Request {{
  host                 = "api.github.com"
  port                 = 443
 (StatusCodeException (Response {{responseStatus = Status {{statusCode = 500, \
statusMessage = "Internal Server Error"}}, responseVersion = HTTP/1.1}})
}}) ""))
"""


def listing(*dates):
    return "".join(f'<a href="{d}.log">{d}.log</a>\n' for d in dates)


def fake_site(pages):
    """urlopen answering from pages {url suffix: body}; anything else 404."""
    calls = []

    def urlopen(req, timeout):
        url = req.full_url.removeprefix(config.NIXPKGS_UPDATE_LOGS_URL)
        calls.append(url)
        if url not in pages:
            raise http_error(404)
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = pages[url].encode()
        return resp

    return urlopen, calls


class Parse(unittest.TestCase):
    def test_failed(self):
        self.assertEqual(
            nixpkgs_update.parse(FAILED),
            {
                "from": "2.7.3",
                "to": "2.8.1",
                "was": "2.7.3",
                "outcome": "failed",
                "failedBecause": "build",
                # The line that says what went wrong, without colours.
                "excerpt": [
                    "/nix/store/dp0z-stdenv-linux/setup: line 1770: cd: source: No "
                    "such file or directory",
                ],
            },
        )

    def test_why_it_failed(self):
        # Parser 5: lines from real failed attempts' logs (2026-10), each
        # after the bot's own lines and the update's diff, which no rule
        # reads: the reason, and the excerpt starting at the line that says.
        def log(*lines):
            return (
                f"{HEAD}x 1.0 -> 1.1 https://github.com/x/x/releases\n"
                "attrpath: x\n"
                '[golangModuleVersion] Found old vendorHash = "sha256-A="\n'
                "Diff after rewrites:\n--- a/x.nix\n+++ b/x.nix\n"
                '-  version = "1.0";\n+  version = "1.1";\n'
                '   hash = "sha256-hash mismatch in fixed-output";\n'
                "No auto update branch exists\nReceived ExitFailure 1 when running\n"
                "Raw command: nix-build -A x\nnix build failed.\n"
                + "\n".join(lines)
                + "\n"
            )

        for lines, because, first in (
            (
                [
                    "error: Refusing to evaluate package 'ocaml5.5.0-bz2-0.8.0' in "
                    "/x/default.nix:42 because it has an unsupported platform"
                ],
                "unavailable",
                "error: Refusing to evaluate package 'ocaml5.5.0-bz2-0.8.0' in "
                "/x/default.nix:42 because it has an unsupported platform",
            ),
            (
                [
                    "patching file pytest_notebook/plugin.py",
                    "Hunk #1 FAILED at 11.",
                    "2 out of 2 hunks FAILED -- saving rejects to file plugin.py.rej",
                ],
                "patch",
                "Hunk #1 FAILED at 11.",
            ),
            (
                [
                    "substituteStream() in derivation phart-2.1.0: ERROR: pattern "
                    "hatchling==1.26.3 doesn't match anything in file 'pyproject.toml'"
                ],
                "patch",
                "substituteStream() in derivation phart-2.1.0: ERROR: pattern "
                "hatchling==1.26.3 doesn't match anything in file 'pyproject.toml'",
            ),
            (
                [
                    "Checking runtime dependencies for prefect-3.8.7-py3-none-any.whl",
                    "  - python-slugify<9.1,>=9 not satisfied by version 8.0.4",
                ],
                "dependency",
                "- python-slugify<9.1,>=9 not satisfied by version 8.0.4",
            ),
            (
                ["ERROR Backend 'hatchling.build' is not available."],
                "dependency",
                "ERROR Backend 'hatchling.build' is not available.",
            ),
            (
                [
                    "    > fatal error: fontconfig/fontconfig.h: No such file or "
                    "directory"
                ],
                "dependency",
                "fatal error: fontconfig/fontconfig.h: No such file or directory",
            ),
            (
                [
                    "build succeeded unexpectedlystderr did not split as expected full "
                    "stderr was:",
                    "go: resolving embeds: no matching files found",
                ],
                "hash",
                "build succeeded unexpectedlystderr did not split as expected full "
                "stderr was:",
            ),
            (
                [
                    "stderr did not split as expected full stderr was:",
                    "curl: (22) The requested URL returned error: 404",
                    "error: cannot download x-1.1.tar.gz from any mirror",
                ],
                "source",
                "curl: (22) The requested URL returned error: 404",
            ),
            (
                [
                    "nix_update.errors.VersionError: Please specify the version.",
                    "The update script for x-1.0 failed with exit code 1",
                ],
                "updateScript",
                "nix_update.errors.VersionError: Please specify the version.",
            ),
            (
                ["test result: FAILED. 6 passed; 1 failed; 0 ignored"],
                "tests",
                "test result: FAILED. 6 passed; 1 failed; 0 ignored",
            ),
            (
                ["Ok:                4", "Fail:              1"],
                "tests",
                "Fail:              1",
            ),
            (
                ["error: build log of 'x' is not available"],
                "noLog",
                "error: build log of 'x' is not available",
            ),
            (
                # The bot's machine, not the package: first, whatever follows.
                [
                    "error: the build users group 'nixbld' has no members",
                    "error: Cannot build '/nix/store/x.drv'.",
                ],
                "bot",
                "error: the build users group 'nixbld' has no members",
            ),
            (
                # nix's wrapping isn't the reason, nor the bot's lookup of a Go
                # package's source; the compiler's error is.
                [
                    "error: attribute 'originalSrc' in selection path 'x.originalSrc' "
                    "not found",
                    "../x.c:608:8: error: 'AGB' undeclared (first use in this "
                    "function)",
                    "error: Cannot build '/nix/store/x.drv'.",
                ],
                "build",
                "../x.c:608:8: error: 'AGB' undeclared (first use in this function)",
            ),
        ):
            with self.subTest(because=because, first=first[:30]):
                result = nixpkgs_update.parse(log(*lines))
                self.assertEqual(result["outcome"], "failed")
                self.assertEqual(result["failedBecause"], because)
                self.assertEqual(result["excerpt"][0], first)
                self.assertLessEqual(len(result["excerpt"]), 3)

    def test_bot_reason_from_an_attempt_read_before(self):
        # Read before the "bot" reason was: its excerpt says so, no reread.
        nixbld = "error: the build users group 'nixbld' has no members"
        old = {"outcome": "failed", "failedBecause": "build", "excerpt": [nixbld]}
        self.assertEqual(nixpkgs_update.with_bot_reason(old)["failedBecause"], "bot")
        other = {
            "outcome": "failed",
            "failedBecause": "patch",
            "excerpt": ["Hunk #1 FAILED"],
        }
        self.assertEqual(
            nixpkgs_update.with_bot_reason(other)["failedBecause"], "patch"
        )
        done = {"outcome": "prOpened", "excerpt": [nixbld]}  # not a failure
        self.assertNotIn("failedBecause", nixpkgs_update.with_bot_reason(done))
        self.assertIsNone(nixpkgs_update.with_bot_reason(None))

    def test_no_reason_found(self):
        # None of the rules: "other", and the lines just before nix's
        # wrapping of the failure (not "Reason: builder failed").
        result = nixpkgs_update.parse(
            f"{HEAD}x 1 -> 2\nnix build failed.\n"
            "Running phase: installPhase\nno Makefile, doing nothing\n"
            "Tool 'x' failed to install.\n"
            "error: Cannot build '/nix/store/x.drv'.\n"
            "       Reason: builder failed with exit code 1.\n"
        )
        self.assertEqual(
            (result["failedBecause"], result["excerpt"]),
            (
                "other",
                [
                    "Running phase: installPhase",
                    "no Makefile, doing nothing",
                    "Tool 'x' failed to install.",
                ],
            ),
        )
        # An updateScript that failed without saying why is the script's.
        error = nixpkgs_update.parse(UPDATE_SCRIPT_ERROR)
        self.assertEqual(error["failedBecause"], "updateScript")

    def test_a_url_isnt_a_version(self):
        # No new version in the bot's queue, only where it would come from
        # (ocamlPackages.labltk, 2026-10-03): no "to".
        result = nixpkgs_update.parse(
            f"{HEAD}ocamlPackages.labltk 8.06.16 -> "
            "https://github.com/garrigue/labltk/releases\n"
            "https://github.com/garrigue/labltk/releases is not newer than 8.06.16 "
            "according to Nix; versionComparison: -1\n"
        )
        self.assertEqual((result["from"], result["outcome"]), ("8.06.16", "noChange"))
        self.assertNotIn("to", result)

    def test_cant_update(self):
        self.assertEqual(
            nixpkgs_update.parse(CANT_UPDATE),
            {
                "outcome": "cantUpdate",
                "from": "1.37",
                "to": "1.38",
                "was": "1.37",
                # Why: the generic rewriter's and the updateScript's reasons.
                "excerpt": [
                    "generic version rewriter does not support multiple hashes",
                    "skipping because derivation has no updateScript",
                ],
            },
        )

    def test_empty_diff_after_update_script_is_nothing_to_update(self):
        # wesnoth's "0 -> 1": its updateScript found nothing newer.
        self.assertEqual(nixpkgs_update.parse(NO_CHANGE)["outcome"], "noChange")

    def test_pr_opened(self):
        result = nixpkgs_update.parse(PR_OPENED)
        self.assertEqual((result["outcome"], result["pr"]), ("prOpened", 565255))

    def test_pr_exists(self):
        result = nixpkgs_update.parse(PR_EXISTS)
        self.assertEqual((result["outcome"], result["pr"]), ("prExists", 558133))

    def test_nothing_to_do(self):
        for log in (NO_CHANGE, ALREADY_UPDATED):
            with self.subTest(log=log[:80]):
                self.assertEqual(nixpkgs_update.parse(log)["outcome"], "noChange")

    def test_branch_exists(self):
        result = nixpkgs_update.parse(BRANCH_EXISTS)
        self.assertEqual(
            (result["outcome"], result["from"], result["to"]),
            ("branchExists", "0.33.1", "0.33.2"),
        )
        # An updateScript's versions, from the branch's message.
        result = nixpkgs_update.parse(BRANCH_EXISTS_SCRIPT)
        self.assertEqual(
            (result["outcome"], result["from"], result["to"]),
            ("branchExists", "2.27.2", "2.27.3"),
        )

    def test_nothing_newer_says_why(self):
        for log, why in (
            (
                NOT_NEWER,
                "0.1.0 is not newer than 0.1.0-unstable-2024-06-14 according to "
                "Nix; versionComparison: -1",
            ),
            (HASHES_EQUAL, "Hashes equal; no update necessary"),
        ):
            with self.subTest(why=why[:30]):
                result = nixpkgs_update.parse(log)
                self.assertEqual(
                    (result["outcome"], result["excerpt"]), ("noChange", [why])
                )

    def test_source_unchanged_cant_update(self):
        result = nixpkgs_update.parse(SOURCE_UNCHANGED)
        self.assertEqual(
            (result["outcome"], result["excerpt"]),
            ("cantUpdate", ["Source url did not change."]),
        )

    def test_skipped_after_each_check(self):
        for log, why in (
            (SKIPPED_OPT_OUT, "Derivation file opts-out of auto-updates"),
            (SKIPPED_GNOME, "Do not update GNOME during a release cycle"),
            (
                SKIPPED_LOCKSTEP,
                "rocm packages are upgraded in lockstep "
                "https://github.com/NixOS/nixpkgs/issues/385294",
            ),
            (
                SKIPPED_REBUILDS,
                "Python package with too many package rebuilds 3150  > 100",
            ),
        ):
            with self.subTest(why=why[:30]):
                result = nixpkgs_update.parse(log)
                self.assertEqual(
                    (result["outcome"], result["excerpt"]), ("skipped", [why])
                )

    def test_a_failure_after_the_checks_isnt_a_skip(self):
        # The bot's checks, then a build that failed: its log, not a reason.
        log = f"""{HEAD}x 1 -> 2
attrpath: x
Checking auto update branch...
No auto update branch exists
error: builder for '/nix/store/x.drv' failed with exit code 1
"""
        self.assertEqual(nixpkgs_update.parse(log)["outcome"], "failed")

    def test_failed_request_says_where_and_what(self):
        result = nixpkgs_update.parse(HTTP_FAILED)
        self.assertEqual(
            (result["outcome"], result["excerpt"]),
            ("failed", ["HTTPError from api.github.com: 500 Internal Server Error"]),
        )
        self.assertEqual(result["failedBecause"], "request")
        timeout = (
            'HTTPError (HttpExceptionRequest Request {\n  host = "github.com"\n}\n'
            " ResponseTimeout)"
        )
        self.assertEqual(
            nixpkgs_update.parse(f"{HEAD}x 1 -> 2\n{timeout}\n")["excerpt"],
            ["HTTPError from github.com: ResponseTimeout"],
        )

    def test_nixpkgs_updates_own_messages(self):
        # Parser 4: messages none of the sampled logs had, as nixpkgs-update's
        # source writes them (src/GH.hs, Update.hs, Rewrite.hs, Nix.hs,
        # Check.hs, 2026-10), each where it ends a log: after the bot's
        # checks, so none is taken for a reason to skip.
        def log(last, versions="1.0 -> 1.1"):
            return (
                f"{HEAD}x {versions} https://repology.org/project/x/versions\n"
                "attrpath: x\nChecking auto update branch...\n"
                f"No auto update branch exists\n{last}\n"
            )

        for last, outcome, excerpt, versions in (
            ("Too many open PRs from auto-update/x", "prExists", None, "1.0 -> 1.1"),
            (
                "[version] generic version rewriter does not support multiple hashes\n"
                "No rewrites performed on derivation.",
                "cantUpdate",
                ["generic version rewriter does not support multiple hashes"],
                "1.0 -> 1.1",
            ),
            ("No rewrites performed on derivation.", "noChange", None, "0 -> 1"),
            (
                "rev equal; no update necessary",
                "noChange",
                ["rev equal; no update necessary"],
                "1.0 -> 1.1",
            ),
            (
                "cargo hashes equal; no update necessary: sha256-AAAA",
                "noChange",
                ["cargo hashes equal; no update necessary: sha256-AAAA"],
                "1.0 -> 1.1",
            ),
            (
                "deps hashes equal; no update necessary: sha256-BBBB",
                "noChange",
                ["deps hashes equal; no update necessary: sha256-BBBB"],
                "1.0 -> 1.1",
            ),
            (
                "Update edits cause no rebuilds.",
                "noChange",
                ["Update edits cause no rebuilds."],
                "1.0 -> 1.1",
            ),
            (
                "The derivation has no 'version' attribute, so do not know how to "
                "figure out the version while doing an updateScript update",
                "cantUpdate",
                [
                    "The derivation has no 'version' attribute, so do not know how "
                    "to figure out the version while doing an updateScript update"
                ],
                "0 -> 1",
            ),
            ("nix log failed trying to get build logs ", "failed", None, "1.0 -> 1.1"),
            ("Could not find result link. ", "failed", None, "1.0 -> 1.1"),
            ("build succeeded unexpectedly", "failed", None, "1.0 -> 1.1"),
            ("grep did not find version in file names", "failed", None, "1.0 -> 1.1"),
            ("Failed to read expected nix boolean x ", "failed", None, "1.0 -> 1.1"),
            (
                "nix build failed.\nbuilding '/nix/store/x.drv'... ",
                "failed",
                None,
                "1.0 -> 1.1",
            ),
        ):
            with self.subTest(last=last[:40]):
                result = nixpkgs_update.parse(log(last, versions))
                self.assertEqual(result["outcome"], outcome)
                if excerpt is not None:
                    self.assertEqual(result["excerpt"], excerpt)
                if outcome == "failed":
                    self.assertTrue(result["excerpt"])  # where the log ends
                self.assertNotIn("pr", result)

    def test_unrecognised(self):
        self.assertEqual(nixpkgs_update.parse(f"{HEAD}x 1 -> 2\n")["outcome"], "other")

    def test_update_script_records_what_nixpkgs_had_and_what_the_diff_tried(self):
        result = nixpkgs_update.parse(UPDATE_SCRIPT_FAILED)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["was"], "wesnoth-devel-1.19.24")
        self.assertEqual((result["from"], result["to"]), ("1.19.24", "1.19.28"))
        # Without a diff (the script itself failed), "0 -> 1" stays.
        error = nixpkgs_update.parse(UPDATE_SCRIPT_ERROR)
        self.assertEqual(error["outcome"], "failed")
        self.assertEqual(error["was"], "blackvoxel-2.5")
        self.assertEqual((error["from"], error["to"]), ("0", "1"))

    def test_superseded_when_nixpkgs_moved_on(self):
        superseded = nixpkgs_update.superseded
        # Plain version from UPDATE_INFO.
        self.assertFalse(superseded({"was": "2.7.3"}, "2.7.3"))  # still there
        self.assertTrue(superseded({"was": "2.7.3"}, "2.8.1"))  # updated
        self.assertTrue(superseded({"was": "2.7.3"}, "2.7.4"))  # past its target
        # Name-version from an updateScript log.
        self.assertFalse(superseded({"was": "wesnoth-devel-1.19.24"}, "1.19.24"))
        self.assertTrue(superseded({"was": "wesnoth-devel-1.19.24"}, "1.19.28"))
        # Not knowable: no record of what nixpkgs had, or no version now.
        self.assertFalse(superseded({"to": "1"}, "1.19.28"))
        self.assertFalse(superseded({"was": "2.7.3"}, None))

    def test_superseded_says_where(self):
        superseded = nixpkgs_update.superseded
        was = {"was": "wesnoth-devel-1.19.24"}
        self.assertEqual(superseded(was, "1.19.28"), "nixos-unstable")
        # Merged on master, the channel not there yet.
        self.assertEqual(superseded(was, "1.19.24", "1.19.28"), "master")
        # The channel counts first when both have moved on.
        self.assertEqual(superseded(was, "1.19.28", "1.19.30"), "nixos-unstable")
        self.assertIsNone(superseded(was, "1.19.24", None))


class AddAttempts(unittest.TestCase):
    def setUp(self):
        self.stderr = io.StringIO()
        for patcher in (
            mock.patch("sys.stderr", self.stderr),
            mock.patch("time.sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_attempts(self, rows, pages, previous=None, ignored=None, community=()):
        nixpkgs = {a: pkg(a) for row in rows for a in row["attrs"]}
        urlopen, calls = fake_site(pages)
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            nixpkgs_update.add_attempts(
                rows, nixpkgs, previous or {"packages": []}, NOW, ignored, community
            )
        # Without the site's index ("/", not served here, so every package
        # is listed): see LogIndex.
        return [c for c in calls if c != "/"]

    def test_cant_update_is_not_a_failure_until_nixpkgs_moves_on(self):
        rows = [{"name": "edgar", "attrs": ["edgar"], "nixVersion": "1.37"}]
        pages = {"/edgar/": listing("2026-09-26"), "/edgar/2026-09-26.log": CANT_UPDATE}
        self.run_attempts(rows, pages)
        self.assertEqual(rows[0]["update"]["outcome"], "cantUpdate")
        self.assertFalse(rows[0]["updateFailure"])
        # Updated by hand: the attempt no longer matters.
        rows = [{"name": "edgar", "attrs": ["edgar"], "nixVersion": "1.38"}]
        self.run_attempts(rows, pages)
        update = rows[0]["update"]
        self.assertEqual(update["outcome"], "superseded")
        self.assertEqual(update["supersededOutcome"], "cantUpdate")

    def test_ignored_version_is_superseded_with_its_reason(self):
        """xskat: the bot tried a 4.0-9 upstream never released."""
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"}]
        pages = {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED}
        self.run_attempts(rows, pages, ignored={"egoboo": {"2.8.1": "Never released."}})
        update = rows[0]["update"]
        self.assertEqual(update["outcome"], "superseded")
        self.assertEqual(update["supersededOn"], "ignored")
        self.assertEqual(update["reason"], "Never released.")
        self.assertEqual(update["to"], "2.8.1")  # still says what it tried
        self.assertFalse(rows[0]["updateFailure"])
        self.assertNotIn("the rule can go", self.stderr.getvalue())

    def test_other_versions_still_fail_and_the_rule_can_go(self):
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"}]
        pages = {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED}
        self.run_attempts(rows, pages, ignored={"egoboo": {"2.8.0": "Never released."}})
        self.assertEqual(rows[0]["update"]["outcome"], "failed")
        self.assertTrue(rows[0]["updateFailure"])
        self.assertIn(
            "notice: ignoredUpdates.egoboo: the bot's latest attempt isn't at "
            "2.8.0 anymore; the rule can go",
            self.stderr.getvalue(),
        )

    def test_a_community_rule_says_so(self):
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"}]
        pages = {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED}
        rules = {"egoboo": {"2.8.1": "Never released.", "2.8.0": "Old."}}
        community = {("egoboo", "2.8.1"), ("egoboo", "2.8.0")}
        self.run_attempts(rows, pages, ignored=rules, community=community)
        self.assertTrue(rows[0]["update"]["community"])
        # Stale community rules are listed by community-check, not here.
        self.assertNotIn("the rule can go", self.stderr.getvalue())

    def test_update_script_error_is_ignored_only_while_up_to_date(self):
        """blackvoxel: nix-update fails at 2.5 (the newest), then 2.6 comes out."""
        pages = {
            "/blackvoxel/": listing("2026-09-27"),
            "/blackvoxel/2026-09-27.log": UPDATE_SCRIPT_ERROR,
        }
        rules = {"blackvoxel": {"2.5": "Chases an older v2.42 tag."}}
        row = {
            "name": "blackvoxel",
            "attrs": ["blackvoxel"],
            "nixVersion": "2.5",
            "nixStatus": "newest",
        }
        self.run_attempts(
            [row], pages, ignored=rules, community={("blackvoxel", "2.5")}
        )
        self.assertEqual(row["update"]["outcome"], "superseded")
        self.assertEqual(row["update"]["supersededOn"], "ignored")
        self.assertTrue(row["update"]["community"])
        self.assertFalse(row["updateFailure"])
        self.assertNotIn("the rule can go", self.stderr.getvalue())
        # Once 2.6 is out, the row is outdated and the failure counts again.
        outdated = {**row, "nixStatus": "outdated", "refVersion": "2.6"}
        self.run_attempts(
            [outdated], pages, previous={"packages": [row]}, ignored=rules
        )
        self.assertEqual(outdated["update"]["outcome"], "failed")
        self.assertTrue(outdated["updateFailure"])

    def test_only_failures_are_ignored(self):
        attempt = {"outcome": "prOpened", "to": "2.8.1"}
        self.assertIsNone(nixpkgs_update.ignored(attempt, {"2.8.1": "x"}))
        self.assertIsNone(nixpkgs_update.ignored({"outcome": "failed"}, None))
        # The placeholder "1" of "0 -> 1" never matches a rule called "1".
        script = {"outcome": "failed", "to": "1", "was": "blackvoxel-2.5"}
        self.assertIsNone(nixpkgs_update.ignored(script, {"1": "x"}))

    def test_rows(self):
        rows = [
            {"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"},
            {"name": "unciv", "attrs": ["unciv"], "nixVersion": "4.21.19"},
            {"name": "lincity", "attrs": ["lincity"], "nixVersion": "1.13.1"},
        ]
        self.run_attempts(
            rows,
            {
                "/egoboo/": listing("2026-09-04", "2026-09-15"),
                "/egoboo/2026-09-15.log": FAILED,
                "/unciv/": listing("2026-09-20"),
                "/unciv/2026-09-20.log": PR_OPENED,
            },
        )
        egoboo, unciv, lincity = rows
        self.assertTrue(egoboo["updateFailure"])
        self.assertEqual(egoboo["update"]["date"], "2026-09-15")  # the latest
        self.assertEqual(
            egoboo["update"]["log"],
            f"{config.NIXPKGS_UPDATE_LOGS_URL}/egoboo/2026-09-15.log",
        )
        self.assertFalse(unciv["updateFailure"])
        self.assertEqual(unciv["update"]["outcome"], "prOpened")
        self.assertIsNone(lincity["update"])  # never attempted
        self.assertFalse(lincity["updateFailure"])

    def test_failure_at_a_version_nixpkgs_has_is_superseded(self):
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.8.1"}]
        self.run_attempts(
            rows,
            {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED},
        )
        self.assertEqual(rows[0]["update"]["outcome"], "superseded")
        self.assertFalse(rows[0]["updateFailure"])

    def test_update_script_failure_clears_once_nixpkgs_updates(self):
        """wesnoth-devel: the bot failed 1.19.24 -> 1.19.28, then a manual PR
        got 1.19.28 merged (built on master), then into the channel, before
        the bot tried again."""
        pages = {
            "/wesnoth-devel/": listing("2026-09-22"),
            "/wesnoth-devel/2026-09-22.log": UPDATE_SCRIPT_FAILED,
        }
        stages = (
            # channel, master (from Hydra): failing?, superseded where
            ("1.19.24", None, True, None),  # nothing merged yet
            ("1.19.24", "1.19.28", False, "master"),  # merged
            ("1.19.28", None, False, "nixos-unstable"),  # in the channel
        )
        for nix_version, master, failing, where in stages:
            with self.subTest(nix_version=nix_version, master=master):
                row = {
                    "name": "wesnoth-devel",
                    "attrs": ["wesnoth-devel"],
                    "nixVersion": nix_version,
                }
                if master:
                    row["master"] = master
                self.run_attempts([row], pages)
                self.assertEqual(row["updateFailure"], failing)
                self.assertEqual(
                    row["update"]["outcome"], "failed" if failing else "superseded"
                )
                self.assertEqual(row["update"].get("supersededOn"), where)

    def test_versioned_sets_use_the_alias(self):
        rows = [
            {
                "name": "python313Packages.requests",
                "attrs": ["python313Packages.requests"],
            }
        ]
        calls = self.run_attempts(rows, {})
        self.assertEqual(calls, ["/python3Packages.requests/"])

    def test_several_attrs_take_the_latest_attempt(self):
        rows = [{"name": "heroic", "attrs": ["heroic", "heroic-unwrapped"]}]
        self.run_attempts(
            rows,
            {
                "/heroic/": listing("2026-09-15"),
                "/heroic/2026-09-15.log": NO_CHANGE,
                "/heroic-unwrapped/": listing("2026-09-20"),
                "/heroic-unwrapped/2026-09-20.log": FAILED,
            },
        )
        self.assertEqual(rows[0]["update"]["attr"], "heroic-unwrapped")
        self.assertTrue(rows[0]["updateFailure"])

    def test_site_down_reuses_previous_and_stops_asking(self):
        rows = [{"name": f"p{i}", "attrs": [f"p{i}"]} for i in range(5)]
        old = {"attr": "p0", "date": "2026-09-01", "outcome": "failed"}
        previous = {"packages": [{"name": "p0", "update": old, "updateFailure": True}]}
        nixpkgs = {row["name"]: pkg(row["name"]) for row in rows}
        with (
            mock.patch.object(config, "RETRY_DELAYS", []),
            mock.patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
            ) as urlopen,
        ):
            nixpkgs_update.add_attempts(rows, nixpkgs, previous, NOW)
        self.assertEqual((rows[0]["update"], rows[0]["updateFailure"]), (old, True))
        self.assertIsNone(rows[4]["update"])
        # The site's index first (it fails: every package is listed), then
        # the listings until it stops asking.
        self.assertEqual(
            urlopen.call_count, 1 + config.UPDATE_LOGS_MAX_CONSECUTIVE_FAILURES
        )
        self.assertIn(
            "warning: 5 nixpkgs-update log lookups failed", self.stderr.getvalue()
        )
        for r in rows:
            self.assertEqual(r["notRefreshed"]["update"]["since"], NOW)
        self.assertIn("down", rows[0]["notRefreshed"]["update"]["reason"])


class Judge(unittest.TestCase):
    """Judging a row's attempts, once they're found (no logs read)."""

    def setUp(self):
        self.stderr = io.StringIO()
        patcher = mock.patch("sys.stderr", self.stderr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def judge(self, attempts, rules=None, community=(), **row):
        row = {"name": "egoboo", "nixVersion": "2.7.3", **row}
        nixpkgs_update.judge(row, attempts, rules, community)
        return row

    def failed(self, date="2026-09-15", **extra):
        return {
            "attr": "egoboo",
            "date": date,
            "outcome": "failed",
            "was": "2.7.3",
            "to": "2.8.1",
            **extra,
        }

    def test_the_latest_attempt_counts(self):
        older = {**self.failed("2026-09-01"), "outcome": "prOpened"}
        row = self.judge([older, self.failed()])
        self.assertEqual(row["update"]["date"], "2026-09-15")
        self.assertTrue(row["updateFailure"])

    def test_none_tried(self):
        row = self.judge([])
        self.assertEqual((row["update"], row["updateFailure"]), (None, False))

    def test_superseded_where_nixpkgs_moved_on(self):
        row = self.judge([self.failed()], nixVersion="2.8.1")
        self.assertEqual(row["update"]["supersededOn"], "nixos-unstable")
        row = self.judge([self.failed()], master="2.8.1")
        self.assertEqual(row["update"]["supersededOn"], "master")
        self.assertFalse(row["updateFailure"])

    def test_ignored_by_a_rule(self):
        rules = {"2.8.1": "Never released."}
        row = self.judge([self.failed()], rules)
        update = row["update"]
        self.assertEqual(
            (update["supersededOn"], update["reason"]), ("ignored", "Never released.")
        )
        self.assertNotIn("community", update)
        row = self.judge([self.failed()], rules, {("egoboo", "2.8.1")})
        self.assertTrue(row["update"]["community"])
        # Moved on counts first: no reason given.
        row = self.judge([self.failed()], rules, nixVersion="2.8.1")
        self.assertEqual(row["update"]["supersededOn"], "nixos-unstable")
        self.assertNotIn("reason", row["update"])

    def test_a_rule_that_no_longer_matches_can_go(self):
        self.judge([self.failed()], {"2.8.0": "Never released."})
        self.assertIn("ignoredUpdates.egoboo", self.stderr.getvalue())
        # Unless it's a community rule: community-check lists those.
        self.stderr.truncate(0)
        self.judge([self.failed()], {"2.8.0": "x"}, {("egoboo", "2.8.0")})
        self.assertEqual(self.stderr.getvalue(), "")

    def test_the_bots_own_failure_says_so(self):
        # Read before the "bot" reason was: its excerpt holds the error.
        nixbld = "error: the build users group 'nixbld' has no members"
        row = self.judge([self.failed(failedBecause="build", excerpt=[nixbld])])
        self.assertEqual(row["update"]["failedBecause"], "bot")

    def test_an_update_script_gets_what_nixpkgs_had(self):
        script = {"attr": "egoboo", "date": "2026-09-15", "outcome": "noUpdate"}
        script |= {"from": "0", "to": "1"}
        row = self.judge([script])
        self.assertEqual(row["update"]["was"], "2.7.3")


class Finder(unittest.TestCase):
    """Finding a row's attempts: where from, and what's kept when not read."""

    def setUp(self):
        self.stderr = io.StringIO()
        for patcher in (
            mock.patch("sys.stderr", self.stderr),
            mock.patch.object(nixpkgs_update, "directory_dates", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old = {
            "name": "egoboo",
            "update": {"attr": "egoboo", "date": "2026-09-01", "outcome": "failed"},
            "updateFailure": True,
        }
        self.row = {"name": "egoboo", "attrs": ["egoboo"]}

    def finder(self, bulk=frozenset(), digest=None):
        previous = {"packages": [self.old], "checkedAt": NOW}
        return nixpkgs_update._Finder(
            [self.row], {"egoboo": {}}, previous, NOW, bulk, digest
        )

    def test_read_from_the_logs(self):
        found = [{"attr": "egoboo", "date": "2026-09-15", "outcome": "failed"}]
        with mock.patch.object(
            nixpkgs_update, "read_attempts", return_value=(found, 0)
        ):
            self.assertEqual(self.finder().find(self.row, ["egoboo"]), found)

    def test_unreadable_keeps_the_last_syncs(self):
        with mock.patch.object(
            nixpkgs_update, "read_attempts", side_effect=OSError("down")
        ):
            finder = self.finder()
            self.assertIsNone(finder.find(self.row, ["egoboo"]))
        self.assertEqual(self.row["update"], self.old["update"])
        self.assertTrue(self.row["updateFailure"])
        self.assertIn("update", self.row["notRefreshed"])
        self.assertEqual(finder.failed, 1)
        # Its reason too, as when judged.
        nixbld = "error: the build users group 'nixbld' has no members"
        self.old["update"] |= {"failedBecause": "build", "excerpt": [nixbld]}
        with mock.patch.object(
            nixpkgs_update, "read_attempts", side_effect=OSError("down")
        ):
            self.finder().find(self.row, ["egoboo"])
        self.assertEqual(self.row["update"]["failedBecause"], "bot")

    def test_stops_asking_after_failures_in_a_row(self):
        rows = [{"name": f"p{i}", "attrs": [f"p{i}"]} for i in range(5)]
        limit = config.UPDATE_LOGS_MAX_CONSECUTIVE_FAILURES
        with mock.patch.object(
            nixpkgs_update, "read_attempts", side_effect=OSError("down")
        ) as read:
            finder = self.finder()
            for row in rows + [self.row] * limit:
                finder.find(row, row["attrs"])
        self.assertEqual(read.call_count, limit)
        self.assertIn("not asked", self.row["notRefreshed"]["update"]["reason"])

    def test_in_bulk_from_the_digest(self):
        attempt = {"date": "2026-09-15", "outcome": "failed", "started": "x"}
        finder = self.finder({"egoboo"}, {"egoboo": {"attempt": attempt}})
        (found,) = finder.find(self.row, ["egoboo"])
        self.assertEqual(found["date"], "2026-09-15")
        self.assertNotIn("unread", self.row)
        # Listed there, but none read yet: unread.
        finder = self.finder({"egoboo"}, {"egoboo": {"pending": True}})
        self.assertEqual(finder.find(self.row, ["egoboo"]), [])
        self.assertEqual(self.row["unread"], ["update"])

    def test_in_bulk_waiting_its_turn_keeps_the_last_syncs(self):
        finder = self.finder({"egoboo"})
        finder.turns = set()
        with mock.patch.object(nixpkgs_update, "to_read", return_value=True):
            self.assertIsNone(finder.find(self.row, ["egoboo"]))
        self.assertEqual(self.row["update"], self.old["update"])
        self.assertEqual(self.row["unread"], ["update"])
        self.assertEqual(finder.waited, 1)

    def test_a_set_in_bulk_without_the_digest_gets_nothing(self):
        self.row["set"] = "haskellPackages"
        self.assertIsNone(self.finder({"egoboo"}).find(self.row, ["egoboo"]))
        self.assertNotIn("update", self.row)


class ReuseLogs(unittest.TestCase):
    """A sync reads a log once: next time, if the bot's latest attempt is the
    same (same attribute and date, read by the same rules), it takes the
    previous reading instead of downloading it again, and judges it afresh
    against nixpkgs and the rules now."""

    EGOBOO = {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED}
    LOG = "/egoboo/2026-09-15.log"

    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("time.sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def sync(self, previous=None, pages=None, ignored=None, community=(), **row):
        """One run of add_attempts for egoboo: (its row, the URLs fetched)."""
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3", **row}]
        nixpkgs = {a: pkg(a) for a in rows[0]["attrs"]}
        urlopen, calls = fake_site(pages or self.EGOBOO)
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            nixpkgs_update.add_attempts(
                rows, nixpkgs, {"packages": previous or []}, NOW, ignored, community
            )
        return rows[0], [c for c in calls if c != "/"]  # as in run_attempts

    def test_the_same_attempt_isnt_downloaded_again(self):
        first, calls = self.sync()
        self.assertIn(self.LOG, calls)
        self.assertEqual(first["update"]["parser"], nixpkgs_update.PARSER)
        second, calls = self.sync(previous=[first])
        self.assertEqual(calls, ["/egoboo/"])  # the listing, not the log
        self.assertEqual(second["update"], first["update"])
        self.assertTrue(second["updateFailure"])

    def test_a_new_attempt_is(self):
        first, _ = self.sync()
        pages = {
            **self.EGOBOO,
            "/egoboo/": listing("2026-09-15", "2026-09-25"),
            "/egoboo/2026-09-25.log": PR_OPENED,
        }
        second, calls = self.sync(previous=[first], pages=pages)
        self.assertIn("/egoboo/2026-09-25.log", calls)
        self.assertEqual(second["update"]["outcome"], "prOpened")

    def test_read_again_when_the_rules_changed(self):
        first, _ = self.sync()
        with mock.patch.object(nixpkgs_update, "PARSER", nixpkgs_update.PARSER + 1):
            second, calls = self.sync(previous=[first])
        self.assertIn(self.LOG, calls)
        # And data from before PARSER existed is read again too.
        old = {k: v for k, v in first["update"].items() if k != "parser"}
        third, calls = self.sync(previous=[{**first, "update": old}])
        self.assertIn(self.LOG, calls)
        self.assertEqual(third["update"]["parser"], nixpkgs_update.PARSER)

    def test_judged_afresh_superseded(self):
        # Superseded last time: nixpkgs had moved on.
        first, _ = self.sync(nixVersion="2.8.1")
        self.assertEqual(first["update"]["outcome"], "superseded")
        self.assertEqual(first["update"]["supersededOn"], "nixos-unstable")
        # Reused, it's judged on today's nixpkgs: still superseded...
        second, calls = self.sync(previous=[first], nixVersion="2.8.1")
        self.assertEqual(calls, ["/egoboo/"])
        self.assertEqual(second["update"], first["update"])
        # ...and as the log reads when nothing supersedes it.
        third, _ = self.sync(previous=[first])
        self.assertEqual(third["update"]["outcome"], "failed")
        for judged in nixpkgs_update.JUDGED:
            self.assertNotIn(judged, third["update"])
        self.assertTrue(third["updateFailure"])

    def test_judged_afresh_ignored(self):
        rules = {"egoboo": {"2.8.1": "Never released."}}
        community = {("egoboo", "2.8.1")}
        first, _ = self.sync(ignored=rules, community=community)
        self.assertEqual(first["update"]["supersededOn"], "ignored")
        self.assertTrue(first["update"]["community"])
        # The rule went away: the failure counts again, nothing of the rule left.
        second, calls = self.sync(previous=[first])
        self.assertEqual(calls, ["/egoboo/"])
        self.assertEqual(second["update"]["outcome"], "failed")
        self.assertNotIn("reason", second["update"])
        self.assertNotIn("community", second["update"])
        # Reused and still ignored: as a fresh read would be.
        third, _ = self.sync(previous=[first], ignored=rules, community=community)
        self.assertEqual(third["update"], first["update"])

    def test_the_same_as_reading_the_log(self):
        for log in (FAILED, PR_OPENED, CANT_UPDATE):
            with self.subTest(log=log.splitlines()[-1][:40]):
                pages = {"/egoboo/": listing("2026-09-15"), self.LOG: log}
                first, _ = self.sync(pages=pages)
                second, calls = self.sync(previous=[first], pages=pages)
                self.assertEqual(calls, ["/egoboo/"])
                self.assertEqual(second["update"], first["update"])
                self.assertEqual(second["updateFailure"], first["updateFailure"])

    def test_read_again_when_unsure(self):
        first, _ = self.sync(nixVersion="2.8.1")
        broken = {k: v for k, v in first["update"].items() if k != "supersededOutcome"}
        _, calls = self.sync(previous=[{**first, "update": broken}])
        self.assertIn(self.LOG, calls)

    def test_another_attribute_is_read(self):
        # The stored attempt is egoboo's; egoboo-unwrapped's is its own.
        first, _ = self.sync()
        pages = {
            **self.EGOBOO,
            "/egoboo-unwrapped/": listing("2026-09-15"),
            "/egoboo-unwrapped/2026-09-15.log": FAILED,
        }
        _, calls = self.sync(
            previous=[first], pages=pages, attrs=["egoboo", "egoboo-unwrapped"]
        )
        self.assertNotIn(self.LOG, calls)
        self.assertIn("/egoboo-unwrapped/2026-09-15.log", calls)

    def test_a_reused_attempt_is_a_copy(self):
        first, _ = self.sync()
        excerpt = list(first["update"]["excerpt"])
        second, _ = self.sync(previous=[first])
        second["update"]["excerpt"].append("changed")
        second["update"]["outcome"] = "changed"
        self.assertEqual(first["update"]["excerpt"], excerpt)
        self.assertEqual(first["update"]["outcome"], "failed")


def index_page(dirs):
    """The log site's front page, as nginx writes it: {directory: when}."""
    return "".join(
        f'<a href="{name}/">{name}/</a>{" " * 20}{when}{" " * 19}-\n'
        for name, when in dirs.items()
    )


class LogIndex(unittest.TestCase):
    """The site's index says when each package's logs last changed: a package
    whose logs haven't changed since the last sync listed them isn't listed
    again (one request for the index instead of one per package)."""

    BEFORE = "2026-09-29T06:00:00+00:00"  # the last sync
    OLD = "28-Sep-2026 14:02"  # changed before it
    NEW = "29-Sep-2026 09:15"  # and after

    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("time.sleep"),
            mock.patch.object(nixpkgs_update, "MIN_DIRECTORIES", 1),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def first(self, pages):
        """A first sync (no index), to have a previous row as a sync makes it."""
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"}]
        urlopen, _ = fake_site(pages)
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            nixpkgs_update.add_attempts(
                rows, {"egoboo": pkg("egoboo")}, {"packages": []}, self.BEFORE
            )
        return rows[0]

    def sync(self, previous_rows, dirs, pages=None, rows=None):
        rows = rows or [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.7.3"}]
        nixpkgs = {a: pkg(a) for row in rows for a in row["attrs"]}
        urlopen, calls = fake_site({"/": index_page(dirs), **(pages or {})})
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            nixpkgs_update.add_attempts(
                rows,
                nixpkgs,
                {"checkedAt": self.BEFORE, "packages": previous_rows},
                NOW,
            )
        return rows, calls

    EGOBOO = {"/egoboo/": listing("2026-09-15"), "/egoboo/2026-09-15.log": FAILED}

    def test_unchanged_logs_arent_listed(self):
        before = self.first(self.EGOBOO)
        (row,), calls = self.sync([before], {"egoboo": self.OLD})
        self.assertEqual(calls, ["/"])
        self.assertEqual(row["update"], before["update"])
        self.assertTrue(row["updateFailure"])

    def test_and_judged_afresh(self):
        # Nothing asked, but nixpkgs has moved on since: superseded now.
        before = self.first(self.EGOBOO)
        rows = [{"name": "egoboo", "attrs": ["egoboo"], "nixVersion": "2.8.1"}]
        (row,), calls = self.sync([before], {"egoboo": self.OLD}, rows=rows)
        self.assertEqual(calls, ["/"])
        self.assertEqual(row["update"]["outcome"], "superseded")
        self.assertFalse(row["updateFailure"])

    def test_changed_logs_are_listed(self):
        before = self.first(self.EGOBOO)
        pages = {
            "/egoboo/": listing("2026-09-15", "2026-09-29"),
            "/egoboo/2026-09-29.log": CANT_UPDATE,
        }
        (row,), calls = self.sync([before], {"egoboo": self.NEW}, pages)
        self.assertEqual(calls, ["/", "/egoboo/", "/egoboo/2026-09-29.log"])
        self.assertEqual(row["update"]["date"], "2026-09-29")

    def test_a_change_the_minute_before_counts(self):
        # The index only shows minutes: 05:59 could be 05:59:59.
        before = self.first(self.EGOBOO)
        _, calls = self.sync([before], {"egoboo": "29-Sep-2026 05:59"}, self.EGOBOO)
        self.assertIn("/egoboo/", calls)

    def test_no_logs_nothing_asked(self):
        (row,), calls = self.sync([], {"something-else": self.OLD})
        self.assertEqual(calls, ["/"])
        self.assertIsNone(row["update"])

    def test_new_packages_are_listed(self):
        _, calls = self.sync([], {"egoboo": self.OLD}, self.EGOBOO)
        self.assertEqual(calls, ["/", "/egoboo/", "/egoboo/2026-09-15.log"])

    def test_after_a_failed_read_listed_again(self):
        before = self.first(self.EGOBOO)
        before["notRefreshed"] = {"update": {"since": self.BEFORE, "reason": "down"}}
        _, calls = self.sync([before], {"egoboo": self.OLD}, self.EGOBOO)
        self.assertIn("/egoboo/", calls)

    def test_another_attribute_of_the_row_is_listed(self):
        # The previous attempt is egoboo's: egoboo-data's own isn't known.
        before = self.first(self.EGOBOO)
        rows = [
            {
                "name": "egoboo",
                "attrs": ["egoboo", "egoboo-data"],
                "nixVersion": "2.7.3",
            }
        ]
        _, calls = self.sync(
            [before],
            {"egoboo": self.OLD, "egoboo-data": self.OLD},
            {**self.EGOBOO, "/egoboo-data/": listing("2026-09-01")},
            rows=rows,
        )
        self.assertNotIn("/egoboo/", calls)
        self.assertIn("/egoboo-data/", calls)

    def test_a_page_too_short_to_be_the_index_isnt_used(self):
        before = self.first(self.EGOBOO)
        with mock.patch.object(nixpkgs_update, "MIN_DIRECTORIES", 1000):
            _, calls = self.sync([before], {"egoboo": self.OLD}, self.EGOBOO)
        self.assertIn("/egoboo/", calls)

    def test_reads_the_real_format(self):
        # As the site writes it (the padding shortened), with a log file
        # among the directories, which isn't one.
        page = (
            '<a href="ArchiSteamFarm/">ArchiSteamFarm/</a>          '
            "04-Oct-2026 00:00                   -\n"
            '<a href="python3Packages.requests/">python3Packages.requests/</a> '
            "26-Sep-2026 01:05                   -\n"
            '<a href="2026-01-10.log">2026-01-10.log</a>                    '
            "10-Jan-2026 09:27                5841\n"
        )
        urlopen, _ = fake_site({"/": page})
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            dates = nixpkgs_update.directory_dates()
        self.assertEqual(
            {k: v.isoformat() for k, v in dates.items()},
            {
                "ArchiSteamFarm": "2026-10-04T00:00:00+00:00",
                "python3Packages.requests": "2026-09-26T01:05:00+00:00",
            },
        )
