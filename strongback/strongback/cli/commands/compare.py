"""``strongback compare`` -- two readings of the same job, priced."""

from ...compare.attribute import attribute_difference
from ...compare.diff import diff_results
from ...compare.render import comparison_report
from ...engine.run import build_application, run_contract
from ...policy.resolve import Policy
from ..args import add_input_arguments, context_without_policy

NAME = "compare"
HELP = "run one period under two policies and price the difference"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    parser.add_argument("period", type=int, help="the billing period to compare")
    parser.add_argument("first", help="the first policy profile")
    parser.add_argument("second", help="the second policy profile")
    parser.add_argument(
        "--attribute",
        action="store_true",
        help="price each differing setting on its own",
    )
    return parser


def run(args, out):
    """Run the command."""
    context = context_without_policy(args)
    first_policy = Policy(args.first)
    second_policy = Policy(args.second)
    first = build_application(context.with_policy(first_policy), args.period, evaluate=False)
    second = build_application(context.with_policy(second_policy), args.period, evaluate=False)
    differences, summary = diff_results(first, second)
    attribution = None
    if args.attribute:
        attribution = attribute_difference(context, first_policy, second_policy, args.period)
    out.write(
        comparison_report(
            first, second, differences, summary, attribution, (args.first, args.second)
        )
    )
    out.write("\n")
    return 0
