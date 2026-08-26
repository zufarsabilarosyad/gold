"""``strongback progress`` -- what the field reported, and what it is worth."""

from ...core.table import Column, Table
from ...engine.stages import value_periods
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "progress"
HELP = "show reported progress and the value it produces"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--period", type=int, default=None, help="the period to show")
    parser.add_argument("--entries", action="store_true", help="show the raw field reports")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    number = args.period or len(context.periods)
    if args.entries:
        table = Table(
            [
                Column("period", "Period", "right"),
                Column("code", "Item"),
                Column("shape", "Reported"),
                Column("basis", "Basis"),
                Column("figure", "Figure"),
            ]
        )
        for entry in context.progress:
            if entry.period > number:
                continue
            if entry.shape == "percent":
                figure = str(entry.percent)
            elif entry.shape == "value":
                figure = entry.value.format()
            elif entry.shape == "quantity":
                figure = str(entry.installed)
            else:
                figure = "achieved" if entry.achieved else "not achieved"
            table.add(
                {
                    "period": entry.period,
                    "code": entry.code,
                    "shape": entry.shape,
                    "basis": entry.basis,
                    "figure": figure,
                }
            )
        out.write(table.render())
        out.write("\n")
        return 0
    series = value_periods(context, number)
    schedule = context.schedule_for(number)
    table = Table(
        [
            Column("code", "Item"),
            Column("description", "Description", width=28),
            Column("scheduled", "Scheduled", "right"),
            Column("earned", "Earned", "right"),
            Column("stored", "Stored", "right"),
            Column("complete", "Complete", "right"),
        ]
    )
    for line in schedule.ordered():
        values = [value for value in series.get(line.code, ()) if value.period == number]
        if not values:
            continue
        value = values[0]
        percent = (
            value.earned.ratio_to(line.scheduled_value)
            if not line.scheduled_value.is_zero()
            else 0
        )
        table.add(
            {
                "code": line.code,
                "description": line.description,
                "scheduled": line.scheduled_value.format(),
                "earned": value.earned.format(),
                "stored": value.stored.format(),
                "complete": "{:.2%}".format(percent),
            }
        )
    out.write(table.render())
    out.write("\n")
    return 0
