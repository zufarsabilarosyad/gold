"""Rules about the source itself, enforced rather than hoped for.

Three of these have caught real problems in this repository: a module that
computed a date from the clock (which makes a run irreproducible), a report
line with trailing whitespace (which makes two renderings of the same
application differ), and a float literal in the money layer (which is the
mistake the whole design exists to prevent).
"""

import ast
import os
import unittest
import warnings

PACKAGE = "strongback"
MAX_LINE = 120
EXACT_PACKAGES = ("core", "retainage", "billing", "deductions", "progress")


def source_files():
    """Return every source file in the package, in path order."""
    found = []
    for root, directories, files in os.walk(PACKAGE):
        directories[:] = [name for name in directories if name != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def read(path):
    """Return a file's text."""
    with open(path, "r") as handle:
        return handle.read()


class LayoutTest(unittest.TestCase):
    """Whitespace and line length, because reports are fixed width."""

    def test_the_package_is_substantial(self):
        self.assertTrue(len(source_files()) > 50)

    def test_no_line_trails_whitespace(self):
        for path in source_files():
            for number, line in enumerate(read(path).splitlines(), start=1):
                self.assertEqual(line, line.rstrip(), "%s:%d" % (path, number))

    def test_no_tabs(self):
        for path in source_files():
            self.assertNotIn("\t", read(path), path)

    def test_lines_are_readable(self):
        for path in source_files():
            for number, line in enumerate(read(path).splitlines(), start=1):
                self.assertTrue(len(line) <= MAX_LINE, "%s:%d is %d characters" % (path, number, len(line)))

    def test_every_file_ends_with_a_newline(self):
        for path in source_files():
            self.assertTrue(read(path).endswith("\n"), path)


class DocumentationTest(unittest.TestCase):
    """Modules, classes and public functions say what they are for."""

    def test_every_module_has_a_docstring(self):
        for path in source_files():
            tree = ast.parse(read(path), path)
            self.assertTrue(ast.get_docstring(tree), path)

    def test_every_class_and_public_function_has_a_docstring(self):
        for path in source_files():
            tree = ast.parse(read(path), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.assertTrue(ast.get_docstring(node), "%s: class %s" % (path, node.name))
                elif isinstance(node, ast.FunctionDef):
                    if node.name.startswith("_"):
                        continue
                    self.assertTrue(
                        ast.get_docstring(node), "%s: def %s" % (path, node.name)
                    )


class DeterminismTest(unittest.TestCase):
    """Nothing reads a clock, a random number or the environment."""

    FORBIDDEN_MODULES = ("random", "time", "uuid", "secrets")
    FORBIDDEN_CALLS = ("now", "today", "utcnow", "monotonic", "getenv")

    def test_no_module_imports_a_source_of_variation(self):
        for path in source_files():
            tree = ast.parse(read(path), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], self.FORBIDDEN_MODULES, path)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split(".")[0], self.FORBIDDEN_MODULES, path)

    def test_nothing_asks_what_time_it_is(self):
        for path in source_files():
            tree = ast.parse(read(path), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(
                        node.func.attr, self.FORBIDDEN_CALLS, "%s calls %s" % (path, node.func.attr)
                    )


class ExactnessTest(unittest.TestCase):
    """No float literal reaches the packages that hold money."""

    def test_the_money_layers_have_no_float_literals(self):
        for path in source_files():
            parts = path.split(os.sep)
            if len(parts) < 2 or parts[1] not in EXACT_PACKAGES:
                continue
            tree = ast.parse(read(path), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    self.fail("%s has the float literal %r" % (path, node.value))


class OutputTest(unittest.TestCase):
    """Only the command line writes to standard output."""

    def test_nothing_outside_the_cli_prints(self):
        for path in source_files():
            if os.sep + "cli" + os.sep in path:
                continue
            tree = ast.parse(read(path), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "print", path)


class ImportTest(unittest.TestCase):
    """The layering runs one way, and policy is not imported from below."""

    LOWER = ("core", "model", "progress", "retainage", "deductions", "billing")

    def test_the_computing_packages_do_not_import_policy(self):
        for path in source_files():
            parts = path.split(os.sep)
            if len(parts) < 2 or parts[1] not in self.LOWER:
                continue
            text = read(path)
            self.assertNotIn("from ..policy", text, path)
            self.assertNotIn("import policy", text, path)

    def test_core_imports_nothing_from_above_it(self):
        for path in source_files():
            if os.sep + "core" + os.sep not in path:
                continue
            text = read(path)
            for package in ("model", "progress", "retainage", "billing", "engine", "report"):
                self.assertNotIn("from ..%s" % (package,), text, "%s imports %s" % (path, package))


class CompileTest(unittest.TestCase):
    """Every module compiles without a warning on a cold run."""

    def test_no_module_raises_a_warning_when_compiled(self):
        for path in source_files():
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                compile(read(path), path, "exec")
            self.assertEqual(
                [str(item.message) for item in caught], [], "%s warns when compiled" % (path,)
            )


if __name__ == "__main__":
    unittest.main()
