"""``strongback demo`` -- run the sample job end to end."""

from ...engine.run import run_contract
from ...report.g702 import application_page
from ...report.retainage import retainage_movement
from ...report.summary import job_report
from ..args import add_policy_arguments, policy_from_args

NAME = "demo"
HELP = "run the built-in sample job and print the result"


def configure(parser):
    """Add this command's arguments."""
    add_policy_arguments(parser)
    parser.add_argument("--periods", type=int, default=4, help="how many periods to run")
    parser.add_argument("--full", action="store_true", help="print every application")
    return parser


def run(args, out):
    """Run the command."""
    from ...dataio.samples import sample_context

    context = sample_context(args.periods, policy_from_args(args))
    results = run_contract(context)
    out.write(job_report(context.contract, results, context.policy))
    out.write("\n\n")
    out.write("Retainage movement\n==================\n\n")
    out.write(retainage_movement(results))
    out.write("\n")
    if args.full:
        for result in results:
            out.write("\n")
            out.write(application_page(context.contract, result))
            out.write("\n")
    return 0
