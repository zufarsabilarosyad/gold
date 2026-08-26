"""The continuation sheet, rendered flat or grouped by trade.

Two views of the same rows.  The flat sheet is the document; the grouped one is
what gets discussed, because nobody argues about line 05100 -- they argue about
whether the structure is really sixty percent done.
"""

from ..core.money import zero
from ..core.table import Column, Table
from ..core.text import underline
from ..errors import DataError
from ..progress.rollup import RollupRow

__all__ = ["continuation_page", "grouped_sheet", "sheet_totals"]


def continuation_page(sheet, title="Continuation sheet"):
    """Render the sheet with a heading.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> result = build_application(sample_context(2), 2, evaluate=False)
    >>> page = continuation_page(result.sheet)
    >>> page.splitlines()[0]
    'Continuation sheet'
    >>> 'Totals' in page
    True
    """
    return "%s\n\n%s" % (underline(title, "="), sheet.as_table())


def grouped_sheet(sheet, key=None):
    """Render the sheet folded into groups.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> result = build_application(sample_context(3), 3, evaluate=False)
    >>> print(grouped_sheet(result.sheet))
    Group       Lines      Scheduled    Completed  Complete      Balance
    ----------  -----  -------------  -----------  --------  -----------
    Structure       3  $1,195,000.00  $617,500.00  44.56%    $577,500.00
    Sitework        3    $403,000.00  $411,000.00  101.99%    -$8,000.00
    General         1    $180,000.00   $86,400.00  48%        $93,600.00
    Electrical      1    $250,000.00        $0.00  0%        $250,000.00
    Envelope        2    $415,000.00        $0.00  0%        $415,000.00
    Finishes        1     $75,000.00        $0.00  0%         $75,000.00
    """
    rows = {}
    for line in sheet.ordered():
        label = key(line) if key else (line.group or line.code[:2])
        if label not in rows:
            rows[label] = RollupRow(label, zero(sheet.currency), zero(sheet.currency), zero(sheet.currency))
        rows[label].add(line.code, line.scheduled_value, line.work_to_date(), line.stored)
    table = Table(
        [
            Column("group", "Group"),
            Column("lines", "Lines", "right"),
            Column("scheduled", "Scheduled", "right"),
            Column("completed", "Completed", "right"),
            Column("complete", "Complete"),
            Column("balance", "Balance", "right"),
        ]
    )
    ordered = sorted(rows.values(), key=lambda row: (-row.earned.amount, row.key))
    for row in ordered:
        completed = row.earned + row.stored
        table.add(
            {
                "group": row.key,
                "lines": len(row),
                "scheduled": row.scheduled.format(),
                "completed": completed.format(),
                "complete": str(row.completion()),
                "balance": (row.scheduled - completed).format(),
            }
        )
    return table.render()


def sheet_totals(sheet):
    """Return the sheet's column totals as ordered pairs.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> result = build_application(sample_context(1), 1, evaluate=False)
    >>> dict(sheet_totals(result.sheet))["Scheduled value"]
    '$2,450,000.00'
    """
    return [
        ("Scheduled value", sheet.total_scheduled().format()),
        ("Previous applications", sheet.total_previous().format()),
        ("This period", sheet.total_this_period().format()),
        ("Stored materials", sheet.total_stored().format()),
        ("Completed and stored", sheet.total_completed_and_stored().format()),
        ("Balance to finish", sheet.total_balance().format()),
        ("Retainage", sheet.total_retainage().format()),
        ("Retainage on work", sheet.retainage_on_work().rounded().format()),
        ("Retainage on stored", sheet.retainage_on_stored().rounded().format()),
    ]
