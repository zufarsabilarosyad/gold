"""``strongback summary`` -- the one-page picture of a job."""

from ...engine.run import run_contract
from ...report.summary import job_report
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "summary"
HELP = "print a one-page summary of the job"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--period", type=int, default=None, help="the period to summarise at")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    number = args.period or len(context.periods)
    results = run_contract(context, number)
    out.write(job_report(context.contract, results, context.policy))
    out.write("\n")
    return 0
