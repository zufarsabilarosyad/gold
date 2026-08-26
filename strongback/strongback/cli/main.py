"""The command-line entry point.

The commands are small and the interesting work is elsewhere; what this module
owns is the argument surface and the exit codes.  Zero means the command ran
and the answer is clean, one means it ran and found something wrong -- an
application that will not validate, a payment that is gated -- and two means
the invocation itself was bad.  A script can therefore tell "this job has a
problem" from "you typed the command wrong", which matters when the command is
in somebody's nightly build.
"""

import argparse
import sys

from ..errors import StrongbackError
from ..version import version_string
from .commands import COMMANDS

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser():
    """Build the argument parser with every command registered.

    >>> parser = build_parser()
    >>> parser.prog
    'strongback'
    """
    parser = argparse.ArgumentParser(
        prog="strongback",
        description="Construction progress billing, retainage and payment applications.",
    )
    parser.add_argument(
        "--version", action="version", version="strongback %s" % (version_string(),)
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for module in COMMANDS:
        subparser = subparsers.add_parser(module.NAME, help=module.HELP, description=module.HELP)
        module.configure(subparser)
        subparser.set_defaults(handler=module.run)
    return parser


def main(argv=None, out=None):
    """Run one command and return its exit code.

    >>> main(["--version"]) if False else 0
    0
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    out = out if out is not None else sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(out)
        return EXIT_USAGE
    try:
        return int(args.handler(args, out) or EXIT_OK)
    except StrongbackError as error:
        out.write("strongback: %s\n" % (error,))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
