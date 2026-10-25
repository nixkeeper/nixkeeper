"""The settings that let nixkeeper run somewhere other than a checkout on
GitHub: where data and lists live, the token, and how to notify."""

import importlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import tests
from nixkeeper import config, datastore, history, lock, notify
from nixkeeper.errors import Problem
from nixkeeper.sources import github
from nixkeeper.sources import nixpkgs as nixpkgs_source

NOW = "2026-09-30T06:00:00+00:00"
ROWS = [{"name": "unciv", "nixStatus": "newest", "nixVersion": "4.22.4"}]


class Paths(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_data_dir_is_read_at_call_time(self):
        data = os.path.join(self.dir.name, "state", "data")
        with mock.patch.object(config, "OUT_DIR", data):
            datastore.write({"packages": ROWS}, {})
            self.assertEqual(history.load_previous_run()["packages"], ROWS)
            datastore.update({"packages": []}, {})
            self.assertEqual(history.load_previous_run()["packages"], [])
        self.assertTrue(os.path.exists(os.path.join(data, "index.json")))

    def test_lists_from_json(self):
        lists = {"maintainers": ["iedame"], "extraPackages": [], "updateChecks": {}}
        path = os.path.join(self.dir.name, "lists.json")
        with open(path, "w") as f:
            json.dump(lists, f)
        with mock.patch("subprocess.run") as run:
            self.assertEqual(nixpkgs_source.read_lists(path), lists)
            with mock.patch.object(config, "LISTS", path):
                self.assertEqual(nixpkgs_source.read_lists(), lists)
        run.assert_not_called()  # no nix needed

    def test_lists_from_nix_folder(self):
        folder = os.path.join(self.dir.name, "package-lists")
        os.mkdir(folder)
        with mock.patch("subprocess.run") as run:
            run.return_value.stdout = '{"maintainers": []}'
            nixpkgs_source.read_lists(folder)
        self.assertIn(folder, run.call_args.args[0])

    def test_missing_lists_say_how_to_start(self):
        with self.assertRaises(Problem) as exit:
            nixpkgs_source.read_lists(os.path.join(self.dir.name, "nowhere"))
        self.assertIn("nixkeeper init", str(exit.exception))

    def test_lists_that_dont_evaluate(self):
        error = subprocess.CalledProcessError(1, "nix", stderr="error: syntax error\n")
        with (
            mock.patch("subprocess.run", side_effect=error),
            self.assertRaises(Problem) as exit,
        ):
            nixpkgs_source.read_lists(self.dir.name)
        self.assertIn("didn't evaluate", str(exit.exception))
        self.assertIn("syntax error", str(exit.exception))

    def test_lists_without_nix(self):
        with (
            mock.patch("subprocess.run", side_effect=FileNotFoundError),
            self.assertRaises(Problem) as exit,
        ):
            nixpkgs_source.read_lists(self.dir.name)
        self.assertIn("needs nix", str(exit.exception))


class Defaults(unittest.TestCase):
    """The installed command's defaults: the user's own folders (XDG)."""

    def defaults(self, env):
        with mock.patch.dict(os.environ, env, clear=True):
            importlib.reload(config)
        # Reloaded, config has the real addresses again: offline after.
        self.addCleanup(tests.offline)
        self.addCleanup(importlib.reload, config)
        return config.DEFAULTS

    def test_xdg_folders(self):
        with tempfile.TemporaryDirectory() as home:
            found = self.defaults(
                {"XDG_CONFIG_HOME": f"{home}/c", "XDG_STATE_HOME": f"{home}/s"}
            )
        self.assertEqual(found["LISTS"], f"{home}/c/nixkeeper/package-lists")
        self.assertEqual(found["OUT_DIR"], f"{home}/s/nixkeeper/data")

    def test_home_without_xdg_variables(self):
        found = self.defaults({"HOME": "/home/someone", "XDG_CONFIG_HOME": "relative"})
        self.assertEqual(
            found["LISTS"], "/home/someone/.config/nixkeeper/package-lists"
        )
        self.assertEqual(found["OUT_DIR"], "/home/someone/.local/state/nixkeeper/data")

    def test_lists_json_when_theres_no_folder(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(f"{home}/nixkeeper")
            open(f"{home}/nixkeeper/lists.json", "w").close()
            found = self.defaults({"XDG_CONFIG_HOME": home})
            self.assertEqual(found["LISTS"], f"{home}/nixkeeper/lists.json")
            os.makedirs(f"{home}/nixkeeper/package-lists")
            found = self.defaults({"XDG_CONFIG_HOME": home})
            self.assertEqual(found["LISTS"], f"{home}/nixkeeper/package-lists")


class Lock(unittest.TestCase):
    """One run at a time on a data folder."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = os.path.join(self.dir.name, "state", "data")

    def test_next_to_the_data(self):
        with lock.held(self.data):
            self.assertTrue(os.path.exists(self.data + ".lock"))
        self.assertFalse(os.path.exists(self.data))  # only the lock, not the folder

    def test_a_second_run_waits_for_the_first(self):
        order = []
        first = lock.held(self.data)
        first.__enter__()
        stderr = io.StringIO()

        def second():
            with mock.patch("sys.stderr", stderr), lock.held(self.data):
                order.append("second")

        thread = threading.Thread(target=second)
        thread.start()
        thread.join(0.3)
        self.assertTrue(thread.is_alive())  # still waiting
        self.assertIn("Waiting for another nixkeeper run", stderr.getvalue())
        order.append("first done")
        first.__exit__(None, None, None)
        thread.join(5)
        self.assertEqual(order, ["first done", "second"])


class Token(unittest.TestCase):
    def test_token_file_first(self):
        with tempfile.NamedTemporaryFile("w", suffix=".token", delete=False) as f:
            f.write("from-file\n")
        self.addCleanup(os.unlink, f.name)
        env = {"NIXKEEPER_GITHUB_TOKEN_FILE": f.name, "GITHUB_TOKEN": "from-env"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(github.token(), "from-file")

    def test_unreadable_token_file_warns(self):
        env = {"NIXKEEPER_GITHUB_TOKEN_FILE": "/nonexistent/token"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("sys.stderr", io.StringIO()) as stderr,
        ):
            self.assertIsNone(github.token())
        self.assertIn("warning: ", stderr.getvalue())

    def test_gh_login_only_when_allowed(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("subprocess.run") as run,
        ):
            run.return_value.stdout = "from-gh\n"
            self.assertEqual(github.token(), "from-gh")
            self.assertIsNone(github.token(use_gh=False))


class Notify(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        self.stderr = patcher.start()
        self.addCleanup(patcher.stop)

    def run_notify(self, env):
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(github, "update_status_issue", return_value=3) as update,
        ):
            notify.notify({"packages": []}, ROWS, NOW)
        return update

    def test_off_unless_asked(self):
        for env in ({}, {"NIXKEEPER_NOTIFY": "none"}):
            with self.subTest(env=env):
                self.run_notify({**env, "GITHUB_TOKEN": "t"}).assert_not_called()

    def test_github_issue_by_name_or_old_value(self):
        for method in ("github-issue", "1"):
            with self.subTest(method=method):
                update = self.run_notify(
                    {
                        "NIXKEEPER_NOTIFY": method,
                        "GITHUB_REPOSITORY": "nixkeeper/nixkeeper",
                        "GITHUB_TOKEN": "t",
                    }
                )
                self.assertEqual(
                    update.call_args.args[:2], ("nixkeeper/nixkeeper", "t")
                )

    def test_self_hosted_github_issue(self):
        """Outside GitHub Actions: the repository and page named explicitly."""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("secret")
        self.addCleanup(os.unlink, f.name)
        update = self.run_notify(
            {
                "NIXKEEPER_NOTIFY": "github-issue",
                "NIXKEEPER_GITHUB_REPO": "someone/tracker",
                "NIXKEEPER_GITHUB_TOKEN_FILE": f.name,
                "NIXKEEPER_PAGE_URL": "https://nixkeeper.example.org/",
            }
        )
        repo, token, _, body, _ = update.call_args.args
        self.assertEqual((repo, token), ("someone/tracker", "secret"))
        self.assertIn("(https://nixkeeper.example.org/)", body)

    def test_never_posts_with_the_gh_login(self):
        with mock.patch.object(github, "token", wraps=github.token) as token:
            update = self.run_notify(
                {"NIXKEEPER_NOTIFY": "github-issue", "NIXKEEPER_GITHUB_REPO": "o/r"}
            )
        token.assert_called_with(use_gh=False)
        update.assert_not_called()
        self.assertIn("need a repository", self.stderr.getvalue())

    def test_unknown_method_warns(self):
        self.run_notify({"NIXKEEPER_NOTIFY": "carrier-pigeon"}).assert_not_called()
        self.assertIn("isn't a notification method", self.stderr.getvalue())

    def test_page_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(notify.page_url("o/r"), "https://o.github.io/r/")
            self.assertIsNone(notify.page_url())
        with mock.patch.dict(os.environ, {"NIXKEEPER_PAGE_URL": "https://x/"}):
            self.assertEqual(notify.page_url("o/r"), "https://x/")


class UserAgent(unittest.TestCase):
    """How nixkeeper introduces itself to the sources (config.user_agent)."""

    def agent(self, env):
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("nixkeeper.version", return_value="0.9.0"),
        ):
            return config.user_agent()

    def test_the_software_and_its_version(self):
        self.assertEqual(
            self.agent({}), "nixkeeper/0.9.0 (+https://github.com/nixkeeper/nixkeeper)"
        )

    def test_the_repository_running_it_on_github_actions(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "someone/nixkeeper"}
        self.assertEqual(
            self.agent(env),
            "nixkeeper/0.9.0 (+https://github.com/nixkeeper/nixkeeper; "
            "someone/nixkeeper)",
        )
        # Not repeated for nixkeeper's own repository, nor outside Actions.
        env["GITHUB_REPOSITORY"] = "nixkeeper/nixkeeper"
        self.assertNotIn("; ", self.agent(env))
        self.assertNotIn("someone", self.agent({"GITHUB_REPOSITORY": "someone/x"}))

    def test_a_contact_when_chosen(self):
        self.assertEqual(
            self.agent({"NIXKEEPER_CONTACT": "me@example.org"}),
            "nixkeeper/0.9.0 (+https://github.com/nixkeeper/nixkeeper; me@example.org)",
        )

    def test_a_contact_cant_break_the_header(self):
        agent = self.agent(
            {"NIXKEEPER_CONTACT": "me\r\nX-Evil: 1 (a); b) " + "x" * 300}
        )
        self.assertNotIn("\n", agent)
        self.assertNotIn("\r", agent)
        self.assertEqual(agent.count("("), 1)
        self.assertEqual(agent.count(")"), 1)
        self.assertLessEqual(len(agent), 60 + config.CONTACT_MAX)
