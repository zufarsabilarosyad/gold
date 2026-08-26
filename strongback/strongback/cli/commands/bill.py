"""``strongback bill`` -- build one period's application and print it."""

from ...engine.run import build_application, run_contract
from ...report.g702 import application_page
from ...report.g703 import continuation_page, grouped_sheet
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "bill"
HELP = "build a pay application for one period and print it"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("period", type=int, help="the billing period to bill")
    parser.add_argument("--sheet", action="store_true", help="print the continuation sheet")
    parser.add_argument("--grouped", action="store_true", help="print the sheet folded by group")
    parser.add_argument("--gates", action="store_true", help="evaluate the payment gates")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    results = run_contract(context, args.period, evaluate=args.gates)
    result = results[-1]
    out.write(application_page(context.contract, result))
    out.write("\n")
    if args.sheet:
        out.write("\n")
        out.write(continuation_page(result.sheet))
        out.write("\n")
    if args.grouped:
        out.write("\n")
        out.write(grouped_sheet(result.sheet))
        out.write("\n")
    if result.diagnostics:
        out.write("\nDiagnostics\n")
        for item in result.diagnostics:
            out.write("- %s\n" % (item,))
    return 0 if result.is_clean() else 1
