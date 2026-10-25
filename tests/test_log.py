"""What the commands say as they run (nixkeeper/log.py)."""

import ast
import io
import os
import pathlib
import unittest
from unittest import mock

from nixkeeper import config, log


class Said(unittest.TestCase):
    def said(self, github, say, journal=False):
        """What say() writes to standard error, on GitHub Actions or not."""
        out = io.StringIO()
        with (
            mock.patch("sys.stderr", out),
            mock.patch.object(config, "on_github_actions", return_value=github),
            mock.patch.object(log, "_to_journal", return_value=journal),
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

    def test_notice_and_warn_are_prefixed_elsewhere(self):
        self.assertEqual(self.said(False, lambda: log.warn("x")), "warning: x\n")
        self.assertEqual(self.said(False, lambda: log.notice("x")), "notice: x\n")

    def test_an_annotation_is_escaped(self):
        # A newline would end it (the rest plain lines); "%" starts an escape.
        self.assertEqual(
            self.said(True, lambda: log.warn("a\nb 100%\r")),
            "::warning::a%0Ab 100%25%0D\n",
        )
        self.assertEqual(
            self.said(False, lambda: log.warn("a\nb 100%")), "warning: a\nb 100%\n"
        )

    def test_the_journal_files_them_by_priority(self):
        self.assertEqual(
            self.said(False, lambda: log.warn("x"), journal=True), "<4>warning: x\n"
        )
        self.assertEqual(
            self.said(False, lambda: log.notice("x"), journal=True), "<5>notice: x\n"
        )
        self.assertEqual(self.said(False, lambda: log.info("x"), journal=True), "x\n")

    def test_the_journal_is_standard_error_only_when_systemd_says(self):
        with mock.patch.dict(os.environ, {"JOURNAL_STREAM": "1:2"}):
            self.assertFalse(log._to_journal())  # a StringIO, not a file
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(log._to_journal())

    def test_a_group_folds_its_lines_on_github(self):
        def grouped():
            with log.group("Checks 100%"):
                log.info("one")

        self.assertEqual(
            self.said(True, grouped), "::group::Checks 100%25\none\n::endgroup::\n"
        )

    def test_and_indents_them_elsewhere(self):
        def grouped():
            with log.group("Checks"):
                log.info("one\ntwo")
                log.warn("three")
            log.info("after")

        self.assertEqual(
            self.said(False, grouped), "Checks\n  one\n  two\n  warning: three\nafter\n"
        )

    def test_a_group_is_closed_when_it_fails(self):
        def failing():
            with self.assertRaises(ValueError), log.group("Checks"):
                raise ValueError

        self.assertTrue(self.said(True, failing).endswith("::endgroup::\n"))
        self.assertEqual(self.said(False, failing), "Checks\n")
        self.assertEqual(log._depth, 0)


# GitHub Actions' workflow commands: only log.py writes them.
WORKFLOW_COMMANDS = tuple(
    f"::{name}"
    for name in (
        "debug",
        "notice",
        "warning",
        "error",
        "group",
        "endgroup",
        "add-mask",
        "stop-commands",
        "echo",
        "add-matcher",
        "remove-matcher",
        "set-output",
        "save-state",
    )
)


class OnlyHere(unittest.TestCase):
    def test_nothing_else_writes_the_log_itself(self):
        # The log's form (the annotations, standard error) is log.py's alone:
        # nothing else names sys.stderr, prints to a file (standard output
        # is a command's answer), or writes a workflow command.
        package = pathlib.Path(log.__file__).parent
        found = []
        for path in sorted(package.rglob("*.py")):
            if path.name == "log.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                where = f"{path.relative_to(package)}:{getattr(node, 'lineno', 0)}"
                if (
                    isinstance(node, ast.Attribute)
                    and ast.unparse(node) == "sys.stderr"
                ):
                    found.append(f"{where} names sys.stderr")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                    and any(k.arg == "file" for k in node.keywords)
                ):
                    found.append(f"{where} prints to a file")
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith(WORKFLOW_COMMANDS)
                ):
                    found.append(f"{where} writes a workflow command")
        self.assertEqual(found, [])
