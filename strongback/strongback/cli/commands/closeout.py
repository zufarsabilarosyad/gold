"""``strongback closeout`` -- what is still open at the end of the job."""

from ...engine.run import run_contract
from ...report.closeout import closeout_report
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "closeout"
HELP = "report retainage, waivers and offsets still open at closeout"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument(
        "--paid",
        metavar="APPLICATION",
        action="append",
        default=[],
        help="an application that has been paid",
    )
    parser.add_argument(
        "--deductions", metavar="AMOUNT", default=None, help="final deductions to withhold"
    )
    return parser


def run(args, out):
    """Run the command."""
    from ...core.money import money

    context = context_from_args(args)
    results = run_contract(context)
    held = results[-1].summary.total_retainage()
    deductions = money(args.deductions, context.currency) if args.deductions else None
    out.write(
        closeout_report(context, held, context.punchlist_value, deductions, args.paid)
    )
    out.write("\n")
    return 0
