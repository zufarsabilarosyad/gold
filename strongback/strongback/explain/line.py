"""Explaining one line: the arithmetic, in the order it happened.

The question this answers is the one asked in every progress meeting -- "where
did that number come from?" -- and the answer has to be the actual computation
rather than a plausible reconstruction of it.  So the explanation is assembled
from the run's own trace and its own accrual steps, not recomputed here.
"""

from ..core.table import Column, Table, key_value_block
from ..core.text import underline
from ..errors import DataError

__all__ = ["explain_line", "line_facts", "retainage_steps_table"]


def line_facts(result, code):
    """Return the figures behind one continuation row, as ordered pairs.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..engine.context import RunContext
    >>> from ..engine.run import build_application
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> owner, builder = Party("O", "Owner", "owner"), Party("G", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> result = build_application(context, 1, evaluate=False)
    >>> dict(line_facts(result, "03300"))["Completed and stored"]
    '$100,000.00'
    """
    row = result.sheet.get(str(code))
    if row is None:
        raise DataError("application %s has no line %r" % (result.application.id, code))
    return [
        ("Scheduled value", row.scheduled_value.format()),
        ("Previous applications", row.previous.format()),
        ("This period", row.this_period.format()),
        ("Stored materials", row.stored.format()),
        ("Completed and stored", row.completed_and_stored().format()),
        ("Percent complete", str(row.percent_complete())),
        ("Balance to finish", row.balance_to_finish().format()),
        ("Retainage rate", str(row.rate) if row.rate else "-"),
        ("Retainage held", row.retainage.format()),
        ("Retainage this period", row.retainage_this_period().format()),
        ("Net this period", row.net_this_period().format()),
    ]


def retainage_steps_table(result, code):
    """Render the retainage accrual for one line, period by period.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..engine.context import RunContext
    >>> from ..engine.run import build_application
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> owner, builder = Party("O", "Owner", "owner"), Party("G", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%"),
    ...                            ProgressEntry("03300", 2, percent="50%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> result = build_application(context, 2, evaluate=False)
    >>> print(retainage_steps_table(result, "03300"))
    Period         Base  Rate        Held    Movement  Mode
    ------  -----------  ----  ----------  ----------  -----------
         1  $100,000.00  10%   $10,000.00  $10,000.00  prospective
         2  $200,000.00  10%   $20,000.00  $10,000.00  prospective
    """
    steps = result.line_retainage(code)
    if not steps:
        raise DataError("no retainage steps recorded for line %r" % (code,))
    table = Table(
        [
            Column("period", "Period", "right"),
            Column("base", "Base", "right"),
            Column("rate", "Rate"),
            Column("held", "Held", "right"),
            Column("movement", "Movement", "right"),
            Column("mode", "Mode"),
        ]
    )
    for step in steps:
        table.add(
            {
                "period": step.period,
                "base": step.base.format(),
                "rate": str(step.rate),
                "held": step.retained_to_date.format(),
                "movement": step.retained_this_period.format(),
                "mode": step.mode,
            }
        )
    return table.render()


def explain_line(result, code, with_trace=True):
    """Return a full explanation of one line as text.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..engine.context import RunContext
    >>> from ..engine.run import build_application
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> owner, builder = Party("O", "Owner", "owner"), Party("G", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> result = build_application(context, 1, evaluate=False)
    >>> print(explain_line(result, "03300", with_trace=False).splitlines()[0])
    Line 03300 -- Concrete
    """
    row = result.sheet.get(str(code))
    if row is None:
        raise DataError("application %s has no line %r" % (result.application.id, code))
    blocks = [
        underline("Line %s -- %s" % (row.code, row.description), "="),
        key_value_block(line_facts(result, code), width=24),
    ]
    steps = result.line_retainage(code)
    if steps:
        blocks.append(underline("Retainage", "-") + "\n" + retainage_steps_table(result, code))
    if with_trace:
        rendered = result.trace.render(subject=str(code))
        if rendered:
            blocks.append(underline("Trace", "-") + "\n" + rendered)
    return "\n\n".join(blocks)
