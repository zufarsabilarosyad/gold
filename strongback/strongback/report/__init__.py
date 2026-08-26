"""Plain-text reports, one module per audience.

Every report here is a pure function of objects the other packages produced.
None of them computes anything a run did not already decide, which is what
makes a report reproducible and a rendered application diffable against the one
from last month.
"""

from .aging import interest_schedule, open_items_table, payments_report
from .closeout import closeout_items, closeout_report, outstanding_documents
from .g702 import application_page, change_order_recap
from .g703 import continuation_page, grouped_sheet, sheet_totals
from .retainage import release_schedule, retainage_by_line, retainage_report
from .summary import job_report, job_summary, period_table
from .waivers import exposure_report, waiver_log, waiver_report

__all__ = [
    "interest_schedule",
    "open_items_table",
    "payments_report",
    "closeout_items",
    "closeout_report",
    "outstanding_documents",
    "application_page",
    "change_order_recap",
    "continuation_page",
    "grouped_sheet",
    "sheet_totals",
    "release_schedule",
    "retainage_by_line",
    "retainage_report",
    "job_report",
    "job_summary",
    "period_table",
    "exposure_report",
    "waiver_log",
    "waiver_report",
]
