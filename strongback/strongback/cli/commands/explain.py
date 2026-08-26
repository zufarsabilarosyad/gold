"""``strongback explain`` -- where a number came from."""

from ...engine.run import run_contract
from ...explain.line import explain_line
from ...explain.render import explain_run, trace_overview, trace_table
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "explain"
HELP = "explain how a line or a whole application was computed"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("period", type=int, help="the billing period to explain")
    parser.add_argument("--line", metavar="CODE", default=None, help="explain one line")
    parser.add_argument("--table", action="store_true", help="print the trace as a table")
    parser.add_argument("--overview", action="store_true", help="count the decisions by stage")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    results = run_contract(context, args.period)
    result = results[-1]
    if args.overview:
        out.write(trace_overview(result.trace))
        out.write("\n")
        return 0
    if args.line:
        out.write(explain_line(result, args.line))
        out.write("\n")
        return 0
    if args.table:
        out.write(trace_table(result.trace))
        out.write("\n")
        return 0
    out.write(explain_run(result))
    out.write("\n")
    return 0
