"""Run every doctest in the package as part of the suite.

The doctests are not decoration: most modules explain a convention in prose and
then show it producing a number, and a doctest that has drifted from the code
is a docstring that is lying.  Collecting them here means ``unittest discover``
and ``pytest`` both run them.
"""

import doctest
import importlib
import pkgutil
import unittest

import strongback

OPTIONS = doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL


def module_names():
    """Return every module in the package, in import order."""
    names = ["strongback"]
    for info in pkgutil.walk_packages(strongback.__path__, "strongback."):
        names.append(info.name)
    return names


def load_tests(loader, tests, ignore):
    """Add a doctest suite for every module in the package."""
    for name in module_names():
        module = importlib.import_module(name)
        try:
            tests.addTests(doctest.DocTestSuite(module, optionflags=OPTIONS))
        except ValueError:
            continue
    return tests


class DoctestCoverageTest(unittest.TestCase):
    """The modules that explain a convention carry a worked example."""

    def test_every_module_is_importable(self):
        for name in module_names():
            importlib.import_module(name)

    def test_the_package_has_a_substantial_body_of_examples(self):
        total = 0
        for name in module_names():
            module = importlib.import_module(name)
            for test in doctest.DocTestFinder().find(module):
                total += len(test.examples)
        self.assertTrue(total > 800, "only %d doctest examples" % (total,))


if __name__ == "__main__":
    unittest.main()
