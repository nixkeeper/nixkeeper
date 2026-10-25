import io
import json
import os
import re
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

from nixkeeper.sources import nixpkgs
from tests.helpers import response

# The file evaluate puts the attributes in: "(builtins.readFile "<path>")".
READ_FILE = re.compile(r'builtins\.readFile ("[^"]+")')


def listed(cmd):
    """The attributes an eval command reads, from the file it names (read
    while the command runs: the file is gone afterwards)."""
    with open(json.loads(READ_FILE.search(cmd[-1]).group(1))) as f:
        return json.load(f)


class KeptAnswers(unittest.TestCase):
    """Evaluations kept between syncs while nixpkgs' commit hasn't moved."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(nixpkgs.stop_keeping)
        self.asked = []

    def run_eval(self, cmd, **kwargs):
        attrs = listed(cmd)
        self.asked.append(attrs)
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps([a == "broken-one" for a in attrs])
        )

    def test_the_same_commit_evaluated_once(self):
        with mock.patch("subprocess.run", side_effect=self.run_eval):
            self.assertEqual(nixpkgs.keep_answers(self.dir.name), 0)
            first = nixpkgs.broken({"a", "broken-one"}, "abc123")
            # Written for the next sync, which reads them back.
            kept = nixpkgs.kept_answers()
            with open(os.path.join(self.dir.name, nixpkgs.EVALUATIONS), "w") as f:
                json.dump(kept, f)
            self.assertEqual(nixpkgs.keep_answers(self.dir.name), 6)
            self.asked.clear()
            again = nixpkgs.broken({"a", "broken-one"}, "abc123")
            self.assertEqual(again, first)
            self.assertEqual(self.asked, [])  # nothing evaluated again
            # A package new to the lists: only it, once per platform.
            nixpkgs.broken({"a", "new"}, "abc123")
            self.assertEqual(self.asked, [["new"]] * 3)
            # The channel moved: evaluated again; the old commit's answers
            # aren't written any more.
            self.asked.clear()
            nixpkgs.keep_answers(self.dir.name)
            nixpkgs.broken({"a"}, "def456")
            self.assertEqual(self.asked, [["a"]] * 3)
            self.assertTrue(
                all(k.startswith("def456 ") for k in nixpkgs.kept_answers()["answers"])
            )

    def test_not_kept_unless_the_sync_asks(self):
        with mock.patch("subprocess.run", side_effect=self.run_eval):
            nixpkgs.broken({"a"}, "abc123")
            nixpkgs.broken({"a"}, "abc123")
        self.assertEqual(len(self.asked), 6)
        self.assertIsNone(nixpkgs.kept_answers())


class Broken(unittest.TestCase):
    def fake_eval(self, per_system):
        """subprocess.run answering each platform's eval from per_system."""
        calls = []

        def run(cmd, **kwargs):
            system = cmd[cmd.index("--json") + 1].rsplit(".", 1)[1]
            calls.append((cmd, listed(cmd)))
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps(per_system[system])
            )

        return run, calls

    def test_broken_per_platform(self):
        run, calls = self.fake_eval(
            {
                "x86_64-linux": [False, False],
                "aarch64-linux": [False, None],  # null: didn't evaluate
                "aarch64-darwin": [True, False],
            }
        )
        with mock.patch("subprocess.run", side_effect=run):
            result = nixpkgs.broken({"wesnoth", "libfilezilla"}, "abc123")
        # Attributes go in sorted, so the answers line up with them.
        self.assertEqual(result, {"libfilezilla": ["aarch64-darwin"]})
        self.assertIn(
            "github:NixOS/nixpkgs/abc123#legacyPackages.aarch64-darwin", calls[2][0]
        )
        self.assertEqual(calls[0][1], ["libfilezilla", "wesnoth"])

    def test_eval_failure_is_a_warning(self):
        error = subprocess.CalledProcessError(1, "nix", stderr="…\nerror: boom\n")
        with (
            mock.patch("sys.stderr", io.StringIO()) as stderr,
            mock.patch("subprocess.run", side_effect=error),
        ):
            self.assertEqual(nixpkgs.broken({"x"}, "abc123"), {})
        self.assertIn(
            "warning: Couldn't evaluate meta.broken on x86_64-linux: error: boom",
            stderr.getvalue(),
        )


class Sources(unittest.TestCase):
    def test_sources(self):
        answer = [{"version": "1.0", "tag": "v1.0"}, None]  # null: didn't evaluate
        seen = []

        def run(cmd, **kwargs):
            seen.append((cmd, listed(cmd)))
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(answer))

        with mock.patch("subprocess.run", side_effect=run):
            result = nixpkgs.sources({"b", "a"}, "abc123")
        self.assertEqual(result, {"a": {"version": "1.0", "tag": "v1.0"}})
        cmd, attrs = seen[0]
        self.assertIn("github:NixOS/nixpkgs/abc123#legacyPackages.x86_64-linux", cmd)
        self.assertEqual(attrs, ["a", "b"])
        self.assertIn("--impure", cmd)

    def test_many_attributes_stay_off_the_command_line(self):
        # 74,757 attributes, as nixkeeper-versions evaluates (2026-10-07): on
        # the command line, more than Linux allows one argument (128 KB).
        many = {f"python313Packages.package-number-{i}" for i in range(75_000)}
        seen = []

        def run(cmd, **kwargs):
            seen.append((max(len(arg) for arg in cmd), len(listed(cmd))))
            return subprocess.CompletedProcess(cmd, 0, stdout="[]")

        with mock.patch("subprocess.run", side_effect=run):
            nixpkgs.evaluate(
                "abc123", "x86_64-linux", nixpkgs.SOURCES_EXPR, sorted(many)
            )
        longest, count = seen[0]
        self.assertLess(longest, 4096)
        self.assertEqual(count, 75_000)

    def test_eval_failure_raises(self):
        error = subprocess.CalledProcessError(1, "nix", stderr="…\nerror: boom\n")
        with (
            mock.patch("subprocess.run", side_effect=error),
            self.assertRaisesRegex(nixpkgs.EvalError, "^error: boom$"),
        ):
            nixpkgs.sources({"a"}, "abc123")


class ChannelRevision(unittest.TestCase):
    def test_revision(self):
        resp = response("x")
        resp.read.return_value = b"e158d9ed9b51c98974c5e66e1ba1c9e0255fecaa\n"
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(
                nixpkgs.channel_revision(), "e158d9ed9b51c98974c5e66e1ba1c9e0255fecaa"
            )

    def test_falls_back_to_the_branch(self):
        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
            ),
        ):
            self.assertEqual(nixpkgs.channel_revision(), "nixos-unstable")
