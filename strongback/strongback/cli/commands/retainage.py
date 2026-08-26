"""``strongback retainage`` -- what is held, and when it comes back."""

from ...engine.run import run_contract
from ...report.retainage import retainage_movement, retainage_report
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "retainage"
HELP = "report retainage held, by line and by period"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--period", type=int, default=None, help="the period to report at")
    parser.add_argument("--movement", action="store_true", help="show the balance period by period")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    number = args.period or len(context.periods)
    results = run_contract(context, number)
    if args.movement:
        out.write(retainage_movement(results))
        out.write("\n")
        return 0
    out.write(retainage_report(context.contract, results[-1], context.punchlist_value))
    out.write("\n")
    return 0
