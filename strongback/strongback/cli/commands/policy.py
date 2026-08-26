"""``strongback policy`` -- what the conventions are set to, and what they mean."""

from ...policy.describe import differences_table, explain_knob, policy_report
from ...policy.knobs import knob_names
from ...policy.profile import describe_profile, profile_names
from ...policy.resolve import Policy
from ..args import add_policy_arguments

NAME = "policy"
HELP = "show policy profiles, settings and what each one does"


def configure(parser):
    """Add this command's arguments."""
    add_policy_arguments(parser)
    parser.add_argument("--list-profiles", action="store_true", help="list the named profiles")
    parser.add_argument("--knob", metavar="NAME", default=None, help="explain one setting")
    parser.add_argument("--changed", action="store_true", help="show only non-default settings")
    parser.add_argument(
        "--against", metavar="PROFILE", default=None, help="diff against another profile"
    )
    return parser


def run(args, out):
    """Run the command."""
    if args.list_profiles:
        for name in profile_names():
            out.write("%s\n  %s\n" % (name, describe_profile(name)))
        return 0
    if args.knob:
        out.write(explain_knob(args.knob))
        out.write("\n")
        return 0
    overrides = {}
    for item in args.settings or []:
        name, value = item.split("=", 1)
        overrides[name.strip()] = value.strip()
    policy = Policy(args.profile, overrides)
    if args.against:
        out.write(
            differences_table(
                policy, Policy(args.against), policy.name, args.against
            )
        )
        out.write("\n")
        return 0
    out.write(policy_report(policy, args.changed))
    out.write("\n")
    return 0
