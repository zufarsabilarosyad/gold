"""Rendering a comparison so the argument can be had over the right line.

The output that settles a disagreement is not the total.  It is the line that
moved most, the knob that moved it, and the residue that says whether the two
clauses are entangled.
"""

from ..core.table import Column, Table, key_value_block
from ..core.text import underline

__all__ = ["difference_table", "attribution_table", "comparison_report"]


def difference_table(differences):
    """Render line differences, largest payment effect first.

    >>> from ..core.money import money
    >>> from .diff import LineDifference
    >>> rows = [LineDifference("03300", money("100000"), money("90000"),
    ...                        money("10000"), money("9000"))]
    >>> print(difference_table(rows))
    Item   State    First        Second      Billed        Retainage    Payment
    -----  -------  -----------  ----------  ------------  -----------  -----------
    03300  changed  $100,000.00  $90,000.00  ($10,000.00)  ($1,000.00)  ($9,000.00)
    """
    table = Table(
        [
            Column("code", "Item"),
            Column("state", "State"),
            Column("first", "First"),
            Column("second", "Second"),
            Column("billed", "Billed"),
            Column("retainage", "Retainage"),
            Column("payment", "Payment"),
        ]
    )
    ordered = sorted(
        differences, key=lambda item: (-abs(item.payment_delta().amount), item.code)
    )
    for difference in ordered:
        table.add(
            {
                "code": difference.code,
                "state": difference.state,
                "first": difference.first_billed.format(),
                "second": difference.second_billed.format(),
                "billed": difference.billed_delta().format(parens_for_negative=True),
                "retainage": difference.retainage_delta().format(parens_for_negative=True),
                "payment": difference.payment_delta().format(parens_for_negative=True),
            }
        )
    return table.render()


def attribution_table(attribution):
    """Render what each knob was worth, with the residue at the foot.

    >>> from ..core.money import money
    >>> from .attribute import Attribution
    >>> attribution = Attribution(money("-6000"),
    ...                           {"stored_conversion": money("-5000"),
    ...                            "waiver_exchange": money("-500")},
    ...                           money("-500"))
    >>> print(attribution_table(attribution))
    Setting            Effect
    -----------------  -----------
    stored_conversion  ($5,000.00)
    waiver_exchange    ($500.00)
    -----------------  -----------
    interaction        ($500.00)
    total              ($6,000.00)
    """
    table = Table([Column("setting", "Setting"), Column("effect", "Effect")])
    for name, effect in attribution.ranked():
        table.add({"setting": name, "effect": effect.format(parens_for_negative=True)})
    table.add_separator()
    table.add(
        {
            "setting": "interaction",
            "effect": attribution.residue.format(parens_for_negative=True),
        }
    )
    table.add({"setting": "total", "effect": attribution.total.format(parens_for_negative=True)})
    return table.render()


def comparison_report(first_result, second_result, differences, summary, attribution=None, labels=("first", "second")):
    """Render the whole comparison.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> from ..engine.result import RunResult
    >>> from .diff import SummaryDifference
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> def result(due):
    ...     return RunResult(PayApplication("PA-001", 1, period,
    ...         summary=ApplicationSummary(money("100000"),
    ...                                    completed_and_stored=money(due))))
    >>> report = comparison_report(result("40000"), result("35000"), [],
    ...                            SummaryDifference({}))
    >>> print(report.splitlines()[0])
    Comparison of PA-001 under two policies
    """
    blocks = [
        underline("Comparison of %s under two policies" % (first_result.application.id,), "="),
        key_value_block(
            [
                (labels[0], first_result.summary.current_payment_due().format()),
                (labels[1], second_result.summary.current_payment_due().format()),
                (
                    "difference",
                    (
                        second_result.summary.current_payment_due()
                        - first_result.summary.current_payment_due()
                    ).format(parens_for_negative=True),
                ),
            ],
            width=12,
        ),
    ]
    if differences:
        blocks.append(underline("Lines", "-") + "\n" + difference_table(differences))
    if len(summary):
        rows = Table(
            [
                Column("field", "Summary field"),
                Column("first", labels[0]),
                Column("second", labels[1]),
                Column("delta", "Delta"),
            ]
        )
        for field in summary.fields():
            first_value, second_value = summary.values[field]
            rows.add(
                {
                    "field": field,
                    "first": first_value.format(),
                    "second": second_value.format(),
                    "delta": summary.delta(field).format(parens_for_negative=True),
                }
            )
        blocks.append(underline("Summary", "-") + "\n" + rows.render())
    if attribution is not None:
        blocks.append(underline("Attribution", "-") + "\n" + attribution_table(attribution))
    return "\n\n".join(blocks)
