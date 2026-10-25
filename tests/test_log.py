"""What the commands say as they run (nixkeeper/log.py)."""

import ast
import io
import os
import pathlib
import unittest
from unittest import mock

from nixkeeper import log


class Said(unittest.TestCase):
    def said(self, github, say):
        """What say() writes to standard error, on GitHub Actions or not."""
        out = io.StringIO()
        env = {"GITHUB_ACTIONS": "true"} if github else {}
        with (
            mock.patch("sys.stderr", out),
            mock.patch.dict(os.environ, env, clear=True),
        ):
            say()
        return out.getvalue()

    def test_info_is_the_same_everywhere(self):
        for github in (True, False):
            with self.subTest(github=github):
                self.assertEqual(
                    self.said(github, lambda: log.info("Reading\n  two lines")),
                    "Reading\n  two lines\n",
                )

    def test_notice_and_warn_are_annotations_on_github(self):
        self.assertEqual(self.said(True, lambda: log.warn("x")), "::warning::x\n")
        self.assertEqual(self.said(True, lambda: log.notice("x")), "::notice::x\n")

    def test_and_say_so_elsewhere(self):
        self.assertEqual(self.said(False, lambda: log.warn("x")), "warning: x\n")
        self.assertEqual(self.said(False, lambda: log.notice("x")), "notice: x\n")

    def test_a_group_folds_its_lines_on_github(self):
        def grouped():
            with log.group("Checks"):
                log.info("one")

        self.assertEqual(
            self.said(True, grouped), "::group::Checks\none\n::endgroup::\n"
        )
        self.assertEqual(self.said(False, grouped), "Checks\none\n")

    def test_a_group_is_closed_when_it_fails(self):
        def failing():
            with self.assertRaises(ValueError), log.group("Checks"):
                raise ValueError

        self.assertTrue(self.said(True, failing).endswith("::endgroup::\n"))


class OnlyHere(unittest.TestCase):
    def test_nothing_else_writes_the_log_itself(self):
        # The log's form (the annotations, standard error) is log.py's alone.
        package = pathlib.Path(log.__file__).parent
        found = []
        for path in sorted(package.rglob("*.py")):
            if path.name == "log.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                where = f"{path.relative_to(package)}:{getattr(node, 'lineno', 0)}"
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                    and any(ast.unparse(k.value) == "sys.stderr" for k in node.keywords)
                ):
                    found.append(f"{where} prints to sys.stderr")
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith(
                        ("::warning::", "::notice::", "::group::")
                    )
                ):
                    found.append(f"{where} writes an annotation")
        self.assertEqual(found, [])
