"""``strongback export`` -- write the run or its output as data."""

from ...dataio.csvio import write_continuation_csv, write_schedule_csv
from ...dataio.dump import dump_json, dump_result
from ...engine.run import run_contract
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "export"
HELP = "write the run, an application or a sheet as JSON or CSV"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument(
        "what",
        choices=("run", "application", "sheet", "schedule"),
        help="what to export",
    )
    parser.add_argument("--period", type=int, default=None, help="the period to export")
    parser.add_argument("--no-trace", action="store_true", help="leave the trace out")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    if args.what == "run":
        out.write(dump_json(context))
        out.write("\n")
        return 0
    number = args.period or len(context.periods)
    if args.what == "schedule":
        out.write(write_schedule_csv(context.schedule_for(number)))
        return 0
    results = run_contract(context, number)
    result = results[-1]
    if args.what == "application":
        out.write(dump_result(result, not args.no_trace))
        out.write("\n")
        return 0
    out.write(write_continuation_csv(result.sheet))
    return 0
