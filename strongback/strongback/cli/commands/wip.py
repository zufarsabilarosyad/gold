"""``strongback wip`` -- the work-in-progress position."""

from ...engine.run import run_contract
from ...wip.overunder import over_under
from ...wip.report import wip_report, wip_summary
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "wip"
HELP = "report earned revenue against billing"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--period", type=int, default=None, help="the period to report at")
    parser.add_argument(
        "--forecast",
        metavar="AMOUNT",
        default=None,
        help="the total cost forecast; defaults to cost incurred plus the balance to finish",
    )
    return parser


def run(args, out):
    """Run the command."""
    from ...core.money import money

    context = context_from_args(args)
    number = args.period or len(context.periods)
    results = run_contract(context, number)
    result = results[-1]
    incurred = context.costs.total_incurred(number)
    contract_value = result.summary.contract_sum()
    if args.forecast:
        forecast = money(args.forecast, context.currency)
    else:
        forecast = incurred + result.summary.balance_to_finish()
    position = over_under(
        context.contract.id,
        contract_value,
        incurred,
        forecast,
        result.summary.completed_and_stored,
        context.policy.get("wip_percent_basis"),
    )
    out.write(wip_report([position]))
    out.write("\n\n")
    out.write(wip_summary([position]))
    out.write("\n")
    return 0
