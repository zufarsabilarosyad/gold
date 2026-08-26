"""``strongback validate`` -- check a run document without billing anything."""

from ...dataio.schema import check_document
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "validate"
HELP = "check a contract and its ledgers for problems"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--quiet", "-q", action="store_true", help="print nothing when clean")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    problems = context.validate()
    if not problems:
        if not args.quiet:
            out.write("%s: no problems found\n" % (context.contract.id,))
        return 0
    out.write("%s: %d problem(s)\n" % (context.contract.id, len(problems)))
    for problem in problems:
        out.write("- %s\n" % (problem,))
    return 1
