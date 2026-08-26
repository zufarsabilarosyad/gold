"""The work-in-progress report, assembled from the pieces above it.

One row per contract: value, cost, forecast, percent complete, earned revenue,
billed, and the over/under position.  The report is the standard artefact a
contractor's surety and bank ask for quarterly, and the reason it is in this
package rather than in ``report`` is that it needs the forecast register, which
nothing else does.
"""

from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..errors import DataError
from .overunder import OverUnder, portfolio_over_under

__all__ = ["wip_rows", "wip_report", "wip_summary"]


def wip_rows(positions):
    """Return the report rows as dictionaries, in contract order.

    >>> from ..core.money import money
    >>> from .overunder import over_under
    >>> rows = wip_rows([over_under("C-1", money("100000"), money("40000"),
    ...                             money("80000"), money("55000"))])
    >>> rows[0]["contract"], rows[0]["complete"]
    ('C-1', '50%')
    """
    rows = []
    for position in sorted(positions, key=lambda item: item.contract_id):
        rows.append(
            {
                "contract": position.contract_id,
                "value": position.contract_value.format(),
                "cost": position.incurred.format(),
                "forecast": position.forecast.format(),
                "complete": str(position.percent_complete()),
                "earned": position.earned().format(),
                "billed": position.billed.format(),
                "position": position.difference().format(parens_for_negative=True),
                "margin": str(position.margin_rate()),
            }
        )
    return rows


def wip_report(positions, title="Work in progress"):
    """Render the full report.

    >>> from ..core.money import money
    >>> from .overunder import over_under
    >>> print(wip_report([over_under("C-1", money("100000"), money("40000"),
    ...                              money("80000"), money("55000"))]))
    Work in progress
    ================
    <BLANKLINE>
    Contract        Value        Cost    Forecast  Complete      Earned      Billed  Over/(Under)  Margin
    --------  -----------  ----------  ----------  --------  ----------  ----------  ------------  ------
    C-1       $100,000.00  $40,000.00  $80,000.00       50%  $50,000.00  $55,000.00     $5,000.00     20%
    """
    table = Table(
        [
            Column("contract", "Contract"),
            Column("value", "Value", "right"),
            Column("cost", "Cost", "right"),
            Column("forecast", "Forecast", "right"),
            Column("complete", "Complete", "right"),
            Column("earned", "Earned", "right"),
            Column("billed", "Billed", "right"),
            Column("position", "Over/(Under)", "right"),
            Column("margin", "Margin", "right"),
        ]
    )
    for row in wip_rows(positions):
        table.add(row)
    return "%s\n%s\n\n%s" % (title, "=" * len(title), table.render())


def wip_summary(positions):
    """Return the portfolio totals as a labelled block.

    >>> from ..core.money import money
    >>> from .overunder import over_under
    >>> print(wip_summary([over_under("C-1", money("100000"), money("40000"),
    ...                               money("80000"), money("55000"))]))
    Contracts      : 1
    Contract value : $100,000.00
    Earned revenue : $50,000.00
    Billed to date : $55,000.00
    Over-billed    : $5,000.00
    Under-billed   : $0.00
    Net position   : $5,000.00
    """
    positions = list(positions)
    if not positions:
        raise DataError("a work-in-progress report needs at least one contract")
    currency = positions[0].contract_value.currency
    totals = portfolio_over_under(positions)
    value = zero(currency)
    earned = zero(currency)
    billed = zero(currency)
    for position in positions:
        value = value + position.contract_value
        earned = earned + position.earned()
        billed = billed + position.billed
    return key_value_block(
        [
            ("Contracts", len(positions)),
            ("Contract value", value.format()),
            ("Earned revenue", earned.format()),
            ("Billed to date", billed.format()),
            ("Over-billed", totals["overbilled"].format()),
            ("Under-billed", totals["underbilled"].format()),
            ("Net position", totals["net"].format()),
        ],
        width=15,
    )
