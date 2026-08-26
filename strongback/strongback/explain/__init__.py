"""Answering "where did that number come from" from the run's own record.

Nothing in this package computes.  It reads the trace and the accrual steps a
run produced and arranges them for a person, which is only useful because the
run recorded its decisions as it made them rather than reconstructing them
afterwards.
"""

from .line import explain_line, line_facts, retainage_steps_table
from .narrative import narrate, narrate_subject, stage_summary
from .render import explain_run, trace_overview, trace_table

__all__ = [
    "explain_line",
    "line_facts",
    "retainage_steps_table",
    "narrate",
    "narrate_subject",
    "stage_summary",
    "explain_run",
    "trace_overview",
    "trace_table",
]
