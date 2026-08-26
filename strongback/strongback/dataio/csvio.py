"""Comma-separated import and export, because that is what arrives.

Schedules of values and field reports come out of estimating software and
project management systems as spreadsheets, and no amount of preferring JSON
changes that.  The reader here is deliberately narrow: it takes the columns it
knows, it names the row when something is wrong, and it refuses to guess.

Writing is included for the same reason -- the continuation sheet has to go
back into the accounting system, and it goes back as a spreadsheet.
"""

import csv
import io

from ..core.money import money
from ..core.numbers import quantize
from ..core.quantity import quantity
from ..errors import DataError, ParseError
from ..model.sov import ScheduleOfValues, SOVLine
from ..progress.observation import ProgressEntry, ProgressLedger

__all__ = [
    "read_schedule_csv",
    "write_schedule_csv",
    "read_progress_csv",
    "write_continuation_csv",
    "SCHEDULE_COLUMNS",
    "PROGRESS_COLUMNS",
]

SCHEDULE_COLUMNS = (
    "code",
    "description",
    "scheduled_value",
    "cost_code",
    "kind",
    "unit",
    "unit_quantity",
    "unit_rate",
    "stored_eligible",
    "group",
)

PROGRESS_COLUMNS = ("code", "period", "percent", "value", "quantity", "unit", "basis")


def _truthy(value):
    """Read a spreadsheet's idea of a boolean.

    >>> _truthy("yes"), _truthy("FALSE"), _truthy("")
    (True, False, False)
    """
    return str(value).strip().lower() in ("1", "true", "yes", "y", "x")


def read_schedule_csv(text, currency="USD"):
    """Read a schedule of values from CSV text.

    >>> text = '''code,description,scheduled_value,kind
    ... 01000,General conditions,180000,lump_sum
    ... 03300,Slab on grade,265000,lump_sum
    ... '''
    >>> schedule = read_schedule_csv(text)
    >>> str(schedule.total())
    '$445,000.00'
    >>> schedule.require("03300").description
    'Slab on grade'
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise DataError("the schedule CSV has no header row")
    missing = [name for name in ("code", "description", "scheduled_value") if name not in reader.fieldnames]
    if missing:
        raise DataError("the schedule CSV is missing column(s): %s" % (", ".join(missing),))
    schedule = ScheduleOfValues([], currency)
    for number, row in enumerate(reader, start=2):
        try:
            unit_quantity = None
            unit_rate = None
            if row.get("unit_quantity"):
                unit_quantity = quantity(row["unit_quantity"], row.get("unit") or "ea")
            if row.get("unit_rate"):
                unit_rate = money(row["unit_rate"], currency)
            schedule.add(
                SOVLine(
                    row["code"],
                    row.get("description", ""),
                    money(row["scheduled_value"], currency),
                    row.get("cost_code", ""),
                    row.get("kind") or "lump_sum",
                    unit_quantity,
                    unit_rate,
                    _truthy(row.get("stored_eligible", "")),
                    None,
                    "base",
                    "",
                    row.get("group", ""),
                )
            )
        except (DataError, ParseError, ValueError) as error:
            raise DataError("schedule CSV row %d: %s" % (number, error))
    return schedule


def write_schedule_csv(schedule):
    """Write a schedule of values as CSV text.

    >>> from ..core.money import money
    >>> schedule = ScheduleOfValues([SOVLine("01000", "General", money("1000"))])
    >>> print(write_schedule_csv(schedule).strip().splitlines()[1])
    01000,General,1000,,lump_sum,,,,no,
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(SCHEDULE_COLUMNS)
    for line in schedule.ordered():
        writer.writerow(
            [
                line.code,
                line.description,
                str(line.scheduled_value.amount),
                line.cost_code,
                str(line.kind),
                str(line.unit_quantity.unit) if line.unit_quantity else "",
                str(line.unit_quantity.amount) if line.unit_quantity else "",
                str(line.unit_rate.amount) if line.unit_rate else "",
                "yes" if line.stored_eligible else "no",
                line.group,
            ]
        )
    return output.getvalue()


def read_progress_csv(text, currency="USD"):
    """Read field reports from CSV text.

    >>> text = '''code,period,percent
    ... 01000,1,12%
    ... 02200,1,60%
    ... '''
    >>> ledger = read_progress_csv(text)
    >>> str(ledger.latest_percent("02200", 1))
    '60%'
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise DataError("the progress CSV has no header row")
    if "code" not in reader.fieldnames or "period" not in reader.fieldnames:
        raise DataError("the progress CSV needs at least 'code' and 'period' columns")
    ledger = ProgressLedger([], currency)
    for number, row in enumerate(reader, start=2):
        given = [name for name in ("percent", "value", "quantity") if row.get(name)]
        if len(given) != 1:
            raise DataError(
                "progress CSV row %d reports %d of percent, value and quantity"
                % (number, len(given))
            )
        try:
            ledger.record(
                ProgressEntry(
                    row["code"],
                    row["period"],
                    row.get("percent") or None,
                    money(row["value"], currency) if row.get("value") else None,
                    quantity(row["quantity"], row.get("unit") or "ea") if row.get("quantity") else None,
                    None,
                    row.get("basis") or "to_date",
                )
            )
        except (DataError, ParseError, ValueError) as error:
            raise DataError("progress CSV row %d: %s" % (number, error))
    return ledger


def write_continuation_csv(sheet):
    """Write a continuation sheet as CSV text.

    >>> from ..core.money import money
    >>> from ..billing.continuation import ContinuationSheet
    >>> from ..billing.line import ApplicationLine
    >>> sheet = ContinuationSheet([ApplicationLine("01000", "General", money("1000"),
    ...                                            this_period=money("250"))])
    >>> print(write_continuation_csv(sheet).strip().splitlines()[1])
    01000,General,1000,0.00,250.00,0.00,250.00,0.2500,750.00,0.00
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "code",
            "description",
            "scheduled_value",
            "previous",
            "this_period",
            "stored",
            "completed_and_stored",
            "percent",
            "balance",
            "retainage",
        ]
    )
    for line in sheet.ordered():
        writer.writerow(
            [
                line.code,
                line.description,
                str(line.scheduled_value.amount),
                str(line.previous.rounded().amount),
                str(line.this_period.rounded().amount),
                str(line.stored.rounded().amount),
                str(line.completed_and_stored().rounded().amount),
                str(quantize(line.percent_complete().value, 4)),
                str(line.balance_to_finish().rounded().amount),
                str(line.retainage.rounded().amount),
            ]
        )
    return output.getvalue()
