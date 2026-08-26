"""``strongback schedule`` -- print the schedule of values."""

from ...core.table import Column, Table
from ...dataio.csvio import write_schedule_csv
from ..args import add_input_arguments, add_policy_arguments, context_from_args

NAME = "schedule"
HELP = "print the schedule of values as it stands in a period"


def configure(parser):
    """Add this command's arguments."""
    add_input_arguments(parser)
    add_policy_arguments(parser)
    parser.add_argument("--period", type=int, default=None, help="the period to show it at")
    parser.add_argument("--csv", action="store_true", help="write CSV instead of a table")
    return parser


def run(args, out):
    """Run the command."""
    context = context_from_args(args)
    number = args.period or len(context.periods)
    schedule = context.schedule_for(number)
    if args.csv:
        out.write(write_schedule_csv(schedule))
        return 0
    table = Table(
        [
            Column("code", "Item"),
            Column("description", "Description", width=32),
            Column("kind", "Kind"),
            Column("group", "Group"),
            Column("origin", "Origin"),
            Column("value", "Scheduled value", "right"),
        ]
    )
    for line in schedule.ordered():
        table.add(
            {
                "code": line.code,
                "description": line.description,
                "kind": str(line.kind),
                "group": line.group or "-",
                "origin": line.origin,
                "value": line.scheduled_value.format(),
            }
        )
    table.add_separator()
    table.add(
        {
            "code": "",
            "description": "Total",
            "kind": "",
            "group": "",
            "origin": "",
            "value": schedule.total().format(),
        }
    )
    out.write(table.render())
    out.write("\n")
    return 0
