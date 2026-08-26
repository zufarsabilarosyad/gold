"""Rendering explanations for the command line.

Two audiences, two shapes.  The table is for someone reconciling numbers, and
it has to be scannable and aligned.  The narrative is for someone who does not
believe the number, and it has to be readable in an email.
"""

from ..core.table import Column, Table
from ..core.text import underline
from .narrative import narrate, stage_summary

__all__ = ["trace_table", "explain_run", "trace_overview"]


def trace_table(trace, stage=None, subject=None):
    """Render a trace as a table.

    >>> from ..core.trace import Trace
    >>> trace = Trace()
    >>> trace.record("progress", "03300", "25% complete", {"kind": "lump_sum"})
    >>> print(trace_table(trace))
    #  Stage     Subject  Decision      Values
    -  --------  -------  ------------  -------------
    1  progress  03300    25% complete  kind=lump_sum
    """
    table = Table(
        [
            Column("sequence", "#", "right"),
            Column("stage", "Stage"),
            Column("subject", "Subject"),
            Column("message", "Decision"),
            Column("values", "Values"),
        ]
    )
    for event in trace:
        if stage is not None and event.stage != str(stage):
            continue
        if subject is not None and event.subject != str(subject):
            continue
        table.add(
            {
                "sequence": event.sequence,
                "stage": event.stage,
                "subject": event.subject,
                "message": event.message,
                "values": ", ".join(
                    "%s=%s" % (key, event.values[key]) for key in sorted(event.values)
                ),
            }
        )
    return table.render()


def trace_overview(trace):
    """Render how many decisions each stage made.

    >>> from ..core.trace import Trace
    >>> trace = Trace()
    >>> trace.record("progress", "03300", "a")
    >>> print(trace_overview(trace))
    Stage     Decisions
    --------  ---------
    progress          1
    """
    table = Table([Column("stage", "Stage"), Column("count", "Decisions", "right")])
    for stage, count in stage_summary(trace):
        table.add({"stage": stage, "count": count})
    return table.render()


def explain_run(result, subject=None, as_table=False):
    """Render the explanation of a whole run.

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
    >>> print(explain_run(result).splitlines()[0])
    PA-001 -- Application 1
    """
    header = underline(
        "%s -- %s" % (result.application.id, result.application.period.label), "="
    )
    if as_table:
        body = trace_table(result.trace, subject=subject)
    else:
        body = narrate(result.trace, [subject] if subject else None)
    return "%s\n\n%s" % (header, body)
