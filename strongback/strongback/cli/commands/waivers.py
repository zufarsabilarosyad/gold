"""``strongback waivers`` -- the log and the unreleased exposure."""

from ...engine.run import run_contract
from ...report.waivers import waiver_report
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "waivers"
HELP = "report the lien waiver log and the unreleased exposure"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument(
        "--paid",
        metavar="APPLICATION",
        action="append",
        default=[],
        help="an application that has been paid; may be given more than once",
    )
    parser.add_argument("--period", type=int, default=None, help="the period to report at")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    number = args.period or len(context.periods)
    results = run_contract(context, number)
    paid_to_date = results[-1].summary.earned_less_retainage()
    out.write(waiver_report(context.waivers, paid_to_date, args.paid))
    out.write("\n")
    pending = context.waivers.pending_conditional(args.paid)
    return 1 if pending else 0
