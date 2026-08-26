"""The commands, one module each, registered in the order they are listed.

A command module exposes ``NAME``, ``HELP``, ``configure(parser)`` and
``run(args, out)``.  Nothing else; the parser wiring is in ``cli.main`` and the
work is in the packages the command imports.
"""

from . import (
    bill,
    closeout,
    compare,
    demo,
    explain,
    export,
    payments,
    policy,
    progress,
    retainage,
    schedule,
    summary,
    validate,
    waivers,
    wip,
)

COMMANDS = (
    demo,
    validate,
    schedule,
    progress,
    bill,
    retainage,
    waivers,
    payments,
    wip,
    compare,
    explain,
    policy,
    summary,
    closeout,
    export,
)

__all__ = ["COMMANDS"]
