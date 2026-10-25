"""nixkeeper/'s docstrings: every module, class and function has one, in the
layout CONTRIBUTING describes."""

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
    """Return what's wrong with a module's docstrings, as "name: why" lines.

    Dunder methods other than __init__ (__eq__, __repr__, ...) need none.
    A docstring's first line is its summary: a second line must be blank.
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
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            found.append(f"{name}: no docstring")
        elif len(lines := doc.split("\n")) > 1 and lines[1].strip():
            found.append(f"{name}: its summary runs onto a second line")
    return found


class Docstrings(unittest.TestCase):
    def test_every_module_class_and_function(self):
        found = []
        for path in modules():
            with open(os.path.join(PACKAGE, path)) as f:
                found += [f"{path}: {p}" for p in problems(f.read())]
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


class Thing:
    """A thing."""

    def __repr__(self):
        return "thing"
'''
        self.assertEqual(
            problems(source),
            [
                "the module: no docstring",
                "wrapped: its summary runs onto a second line",
                "missing: no docstring",
            ],
        )


if __name__ == "__main__":
    unittest.main()
