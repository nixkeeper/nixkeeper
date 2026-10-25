"""Check nixkeeper/'s docstrings against the layout CONTRIBUTING describes.

Every module, class and function has a docstring, and its first line is the
whole summary.
"""

import ast
import os
import unittest

import nixkeeper

PACKAGE = os.path.dirname(nixkeeper.__file__)


def modules():
    """Yield the path of every Python module in nixkeeper/, relative to it."""
    for folder, _, names in os.walk(PACKAGE):
        for name in sorted(names):
            if name.endswith(".py"):
                yield os.path.relpath(os.path.join(folder, name), PACKAGE)


def problems(source):
    """Return what's wrong with a module's docstrings, as "line: name: why".

    Dunder methods other than __init__ (__eq__, __repr__, ...) need none.
    A docstring's first line is its summary: it can't be blank, and a
    second line must be.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        name = getattr(node, "name", "the module")
        if name.startswith("__") and name.endswith("__") and name != "__init__":
            continue
        line = getattr(node, "lineno", 1)
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            found.append(f"{line}: {name}: no docstring")
        elif not doc.split("\n")[0].strip():
            found.append(f"{line}: {name}: starts with a blank line")
        elif len(lines := doc.split("\n")) > 1 and lines[1].strip():
            found.append(f"{line}: {name}: its summary runs onto a second line")
    return found


class Docstrings(unittest.TestCase):
    def test_every_module_class_and_function(self):
        found = []
        for path in modules():
            with open(os.path.join(PACKAGE, path)) as f:
                found += [f"{path}:{p}" for p in problems(f.read())]
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_the_check_itself(self):
        source = '''
def fine():
    """One line."""


def wrapped():
    """A summary that
    runs on."""


def missing():
    pass


def blank():
    """
    The summary, a line late.
    """


class Thing:
    """A thing."""

    def __repr__(self):
        return "thing"
'''
        self.assertEqual(
            problems(source),
            [
                "1: the module: no docstring",
                "6: wrapped: its summary runs onto a second line",
                "11: missing: no docstring",
                "15: blank: starts with a blank line",
            ],
        )


if __name__ == "__main__":
    unittest.main()
