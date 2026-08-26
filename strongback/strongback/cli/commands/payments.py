"""``strongback payments`` -- open items, aging and interest."""

from ...payments.due import due_date
from ...payments.interest import InterestTerms
from ...engine.run import run_contract
from ...report.aging import payments_report
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "payments"
HELP = "report open applications, their aging and any interest"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--as-of", dest="as_of", required=True, help="the date to age against")
    parser.add_argument("--interest", metavar="RATE", default=None, help="accrue interest at a rate")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    results = run_contract(context)
    applications = [result.application for result in results]
    balances = {}
    due_dates = {}
    for result in results:
        application = result.application
        application.submitted_on = application.period.end
        application.certified_on = application.period.end
        balances[application.id] = result.summary.current_payment_due()
        due_dates[application.id] = due_date(
            context.contract.payment_terms,
            application,
            context.contract.calendar,
            context.policy.get("due_roll"),
        )
    terms = None
    if args.interest:
        terms = InterestTerms(
            args.interest,
            day_count=context.policy.get("interest_day_count"),
            compounding=context.policy.get("interest_compounding"),
        )
    out.write(
        payments_report(
            applications,
            balances,
            due_dates,
            args.as_of,
            context.policy.get("aging_basis"),
            terms,
        )
    )
    out.write("\n")
    return 0
