"""The command line: an argument surface over the packages, and nothing more.

No arithmetic lives here.  A command loads a context, calls into the engine or
a report, writes text and returns an exit code -- zero for clean, one for
findings, two for a bad invocation.
"""

from .main import build_parser, main

__all__ = ["build_parser", "main"]
