"""Shared argument handling for the command line.

Every command loads the same things -- a run document or the built-in sample, a
policy possibly modified by ``--set`` -- so that work lives here rather than
being repeated eleven times with eleven small differences.
"""

from ..dataio.loader import read_json_file
from ..dataio.samples import sample_context
from ..errors import InputError, StrongbackError
from ..policy.resolve import Policy

__all__ = [
    "add_input_arguments",
    "add_policy_arguments",
    "context_from_args",
    "context_without_policy",
    "policy_from_args",
    "parse_setting",
]


def add_input_arguments(parser):
    """Add the arguments that say where the run comes from."""
    parser.add_argument(
        "--file",
        "-f",
        metavar="PATH",
        help="a run document in JSON; omit to use the built-in sample job",
    )
    parser.add_argument(
        "--periods",
        type=int,
        default=4,
        help="how many billing periods the sample job runs for (default 4)",
    )
    return parser


def add_policy_arguments(parser):
    """Add the arguments that choose and adjust the policy."""
    parser.add_argument(
        "--profile",
        "-p",
        metavar="NAME",
        help="a named policy profile, such as owner_favorable",
    )
    parser.add_argument(
        "--set",
        "-s",
        metavar="KNOB=VALUE",
        action="append",
        default=[],
        dest="settings",
        help="override one policy setting; may be given more than once",
    )
    return parser


def parse_setting(text):
    """Split a ``knob=value`` override.

    >>> parse_setting("previous_basis=paid")
    ('previous_basis', 'paid')
    >>> parse_setting("nope")
    Traceback (most recent call last):
        ...
    strongback.errors.InputError: an override looks like knob=value, got 'nope'
    """
    text = str(text)
    if "=" not in text:
        raise InputError("an override looks like knob=value, got %r" % (text,))
    name, value = text.split("=", 1)
    return name.strip(), value.strip()


def policy_from_args(args):
    """Build the policy an invocation asks for.

    >>> class Args(object):
    ...     profile = "public_works"
    ...     settings = ["previous_basis=certified"]
    >>> policy = policy_from_args(Args())
    >>> policy.get("previous_basis"), policy.source("previous_basis")
    ('certified', 'override')
    """
    overrides = {}
    for item in getattr(args, "settings", []) or []:
        name, value = parse_setting(item)
        overrides[name] = value
    profile = getattr(args, "profile", None)
    return Policy(profile, overrides)


def context_without_policy(args):
    """Load the run context, ignoring any policy the invocation names.

    ``compare`` needs this: it supplies both policies itself, and a profile on
    the command line would silently become the baseline for both sides.

    >>> class Args(object):
    ...     file = None
    ...     periods = 2
    >>> context_without_policy(Args()).policy.name
    'default'
    """
    path = getattr(args, "file", None)
    if path:
        return read_json_file(path)
    return sample_context(int(getattr(args, "periods", 4) or 4))


def context_from_args(args):
    """Load the run context an invocation asks for.

    >>> class Args(object):
    ...     file = None
    ...     periods = 2
    ...     profile = None
    ...     settings = []
    >>> context = context_from_args(Args())
    >>> len(context.periods)
    2
    """
    policy = policy_from_args(args)
    path = getattr(args, "file", None)
    if path:
        context = read_json_file(path)
        if getattr(args, "profile", None) or getattr(args, "settings", None):
            context.policy = policy
        return context
    return sample_context(int(getattr(args, "periods", 4) or 4), policy)
