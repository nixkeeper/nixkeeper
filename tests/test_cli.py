"""The `nixkeeper` command: its subcommands, the old command names, and where
each setting comes from (flag, then environment, then default)."""

import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from nixkeeper import cli, config
from nixkeeper.errors import Problem


class Command(unittest.TestCase):
    def setUp(self):
        # main() sets these from the flags; put them back after each test.
        patcher = mock.patch.multiple(
            config, LISTS=config.LISTS, OUT_DIR=config.OUT_DIR, NOTIFY=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        # The data lock, next to a data folder that isn't the user's.
        self.lock_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.lock_dir.cleanup)
        self.patch(
            "nixkeeper.lock.path",
            lambda out_dir=None: f"{self.lock_dir.name}/data.lock",
        )
        self.stdout = self.patch("sys.stdout", io.StringIO())
        self.stderr = self.patch("sys.stderr", io.StringIO())

    def patch(self, target, new):
        patcher = mock.patch(target, new)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def run_command(self, *argv):
        """main(argv), with each command's main() faked: {module: mock}."""
        mains = {module: mock.Mock() for _, module in cli.COMMANDS.values()}
        modules = {module: mock.Mock(main=fake) for module, fake in mains.items()}
        with mock.patch("importlib.import_module", side_effect=modules.__getitem__):
            cli.main(list(argv))
        return mains

    def test_commands_hold_the_data_lock(self):
        with mock.patch("nixkeeper.lock.held") as held:
            self.run_command("sync")
        held.assert_called_once_with()
        held.return_value.__enter__.assert_called_once()

    def last_sync(self, hours_ago):
        data = os.path.join(self.lock_dir.name, "data")
        os.makedirs(data, exist_ok=True)
        when = datetime.now(UTC) - timedelta(hours=hours_ago)
        with open(os.path.join(data, "index.json"), "w") as f:
            json.dump({"checkedAt": when.isoformat(), "packages": []}, f)
        return data

    def test_if_older_skips_a_recent_sync(self):
        data = self.last_sync(hours_ago=3)
        mains = self.run_command("sync", "--data-dir", data, "--if-older", "20")
        mains["nixkeeper.sync"].assert_not_called()
        self.assertIn("3.0 hours ago (under 20)", self.stderr.getvalue())

    def test_if_older_runs_after_that(self):
        data = self.last_sync(hours_ago=25)
        mains = self.run_command("sync", "--data-dir", data, "--if-older", "20")
        mains["nixkeeper.sync"].assert_called_once_with()

    def test_if_older_runs_the_first_sync(self):
        data = os.path.join(self.lock_dir.name, "none-yet")
        mains = self.run_command("sync", "--data-dir", data, "--if-older", "20")
        mains["nixkeeper.sync"].assert_called_once_with()

    def test_only_sync_takes_if_older(self):
        with self.assertRaises(SystemExit):
            self.run_command("pr-check", "--if-older", "20")

    def test_each_command_runs_its_module(self):
        for command, (_, module) in cli.COMMANDS.items():
            with self.subTest(command=command):
                mains = self.run_command(command)
                mains[module].assert_called_once_with()
                for other, fake in mains.items():
                    if other != module:
                        fake.assert_not_called()

    def test_flags_set_the_settings(self):
        self.run_command(
            "sync", "--lists", "my/lists.json", "--data-dir", "out", "--notify", "none"
        )
        self.assertEqual(
            (config.LISTS, config.OUT_DIR, config.NOTIFY),
            ("my/lists.json", "out", "none"),
        )

    def test_flags_before_the_command(self):
        self.run_command("--data-dir", "before", "pr-check")
        self.assertEqual(config.OUT_DIR, "before")

    def test_flag_after_the_command_wins(self):
        self.run_command("--data-dir", "before", "sync", "--data-dir", "after")
        self.assertEqual(config.OUT_DIR, "after")

    def test_flag_over_environment_over_default(self):
        os.environ["NIXKEEPER_DATA_DIR"] = "from-env"
        os.environ["NIXKEEPER_NOTIFY"] = "github-issue"
        self.run_command("sync", "--data-dir", "from-flag")
        self.assertEqual(config.OUT_DIR, "from-flag")
        self.assertEqual(config.NOTIFY, "github-issue")
        self.assertEqual(config.LISTS, config.DEFAULTS["LISTS"])

    def test_unknown_notify_method_is_refused(self):
        with self.assertRaises(SystemExit) as exit:
            self.run_command("sync", "--notify", "carrier-pigeon")
        self.assertEqual(exit.exception.code, 2)

    def test_no_command_shows_help(self):
        with self.assertRaises(SystemExit) as exit:
            cli.main([])
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("sync", self.stderr.getvalue())

    def test_version(self):
        with self.assertRaises(SystemExit) as exit:
            cli.main(["--version"])
        self.assertEqual(exit.exception.code, 0)
        self.assertTrue(self.stdout.getvalue().startswith("nixkeeper "))

    def test_paths_says_where_and_why(self):
        with tempfile.TemporaryDirectory() as data:
            os.environ["NIXKEEPER_LISTS"] = "/nonexistent/lists"
            mains = self.run_command("paths", "--data-dir", data)
        out = self.stdout.getvalue()
        self.assertIn(f"{os.path.abspath(data)}  (--data-dir)", out)
        self.assertIn("/nonexistent/lists  (NIXKEEPER_LISTS, missing)", out)
        self.assertIn("none  (default)", out)
        for fake in mains.values():
            fake.assert_not_called()

    def test_old_names_still_work(self):
        for alias, command in (
            (cli.sync_alias, "sync"),
            (cli.frequent_check_alias, "frequent-check"),
            (cli.pr_check_alias, "pr-check"),
        ):
            with (
                self.subTest(command=command),
                mock.patch("sys.argv", [f"nixkeeper-{command}", "--data-dir", "x"]),
                mock.patch.object(cli, "main") as main,
            ):
                alias()
            main.assert_called_once_with([command, "--data-dir", "x"])
            self.assertIn(f"`nixkeeper {command}`", self.stderr.getvalue())


class Exits(unittest.TestCase):
    def test_a_problem_is_its_message_and_status_1(self):
        # The one place nixkeeper exits (CONTRIBUTING: The code).
        with (
            mock.patch.object(cli, "_run_command", side_effect=Problem("fix this")),
            self.assertRaises(SystemExit) as exit,
        ):
            cli.main(["sync"])
        # A string exit code: Python prints it and exits with status 1.
        self.assertEqual(exit.exception.code, "fix this")


class Init(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = os.path.join(self.dir.name, "package-lists")
        patcher = mock.patch.multiple(
            config, LISTS=config.LISTS, OUT_DIR=config.OUT_DIR, NOTIFY=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        out = mock.patch("sys.stdout", io.StringIO())
        self.stdout = out.start()
        self.addCleanup(out.stop)

    def read(self, name):
        with open(os.path.join(self.folder, name)) as f:
            return f.read()

    def test_writes_the_starter_lists(self):
        cli.main(["init", "--lists", self.folder, "--maintainer", "iedame"])
        self.assertEqual(
            sorted(os.listdir(self.folder)),
            [
                "default.nix",
                "extra-packages.nix",
                "ignored-updates.nix",
                "up-to-date.nix",
                "update-checks.nix",
            ],
        )
        self.assertIn('maintainers = [\n    "iedame"\n  ];', self.read("default.nix"))
        self.assertIn("nixkeeper sync", self.stdout.getvalue())
        # Writable, even when the package's copy is read-only (the Nix store).
        with open(os.path.join(self.folder, "extra-packages.nix"), "a") as f:
            f.write("")

    def test_several_maintainers(self):
        cli.main(
            ["init", "--lists", self.folder, "--maintainer", "a", "--maintainer", "b-c"]
        )
        self.assertIn('    "a"\n    "b-c"\n', self.read("default.nix"))

    def test_without_maintainers_says_where_to_add_them(self):
        cli.main(["init", "--lists", self.folder])
        self.assertIn("maintainers = [ ];", self.read("default.nix"))
        self.assertIn("Add your GitHub handle", self.stdout.getvalue())

    def test_to_the_environments_folder(self):
        os.environ["NIXKEEPER_LISTS"] = self.folder
        cli.main(["init"])
        self.assertTrue(os.path.exists(os.path.join(self.folder, "default.nix")))

    def test_never_overwrites(self):
        os.mkdir(self.folder)
        with self.assertRaises(SystemExit) as exit:
            cli.main(["init", "--lists", self.folder])
        self.assertIn("already exists", str(exit.exception.code))
        self.assertEqual(os.listdir(self.folder), [])

    def test_refuses_a_json_target(self):
        with self.assertRaises(SystemExit):
            cli.main(["init", "--lists", self.folder + ".json"])

    def test_only_github_handles(self):
        for handle in ('x"; evil = "', "-leading", "trailing-", "a--b", "x" * 40):
            with self.subTest(handle=handle), self.assertRaises(SystemExit):
                cli.main(["init", "--lists", self.folder, "--maintainer", handle])
            self.assertFalse(os.path.exists(self.folder))


if __name__ == "__main__":
    unittest.main()
