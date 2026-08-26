"""A one-page picture of the job: billed, held, owed, and where it is going.

This is the report a project executive reads.  It has no columns nobody uses
and it fits on a screen, which means everything on it has to earn its place:
the contract sum, what has been billed, what is held, what is outstanding, and
the two forward-looking numbers -- balance to finish and forecast margin.
"""

from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..core.text import underline

__all__ = ["job_summary", "period_table", "job_report"]


def job_summary(contract, results):
    """Return the headline figures as ordered pairs.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import run_contract
    >>> context = sample_context(3)
    >>> results = run_contract(context)
    >>> dict(job_summary(context.contract, results))["Contract sum to date"]
    '$2,518,000.00'
    """
    latest = results[-1]
    summary = latest.summary
    return [
        ("Contract", "%s %s" % (contract.id, contract.title)),
        ("Original contract sum", summary.original.format()),
        ("Change orders", summary.change_orders.format()),
        ("Contract sum to date", summary.contract_sum().format()),
        ("Completed and stored", summary.completed_and_stored.format()),
        ("Percent complete", str(summary.percent_complete())),
        ("Retainage held", summary.total_retainage().format()),
        ("Earned less retainage", summary.earned_less_retainage().format()),
        ("Certified previously", summary.previous_certificates.format()),
        ("Current payment due", summary.current_payment_due().format()),
        ("Balance to finish", summary.balance_to_finish().format()),
    ]


def period_table(results):
    """Render one row per application.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import run_contract
    >>> print(period_table(run_contract(sample_context(2))))
    App     Period      Completed    Retainage   Payment due
    ------  ----------  -----------  ----------  -----------
    PA-001  2024-09-30  $146,600.00  $14,660.00  $131,940.00
    PA-002  2024-10-31  $487,900.00  $48,790.00  $307,170.00
    """
    table = Table(
        [
            Column("id", "App"),
            Column("period", "Period"),
            Column("completed", "Completed"),
            Column("retainage", "Retainage"),
            Column("payment", "Payment due"),
        ]
    )
    from ..core.dates import format_date

    for result in results:
        table.add(
            {
                "id": result.application.id,
                "period": format_date(result.application.period.end),
                "completed": result.summary.completed_and_stored.format(),
                "retainage": result.summary.total_retainage().format(),
                "payment": result.summary.current_payment_due().format(),
            }
        )
    return table.render()


def job_report(contract, results, policy=None):
    """Render the one-page job report.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import run_contract
    >>> context = sample_context(3)
    >>> report = job_report(context.contract, run_contract(context), context.policy)
    >>> report.splitlines()[0]
    'Job summary'
    """
    blocks = [
        underline("Job summary", "="),
        key_value_block(job_summary(contract, results), width=24),
        underline("Applications", "-") + "\n" + period_table(results),
    ]
    if policy is not None:
        blocks.append(
            underline("Conventions in force", "-")
            + "\n"
            + key_value_block(
                [
                    ("Policy", policy.name),
                    ("Retainage", contract.retainage.describe()),
                    ("Payment terms", contract.payment_terms.describe()),
                    ("Change orders", policy.get("change_order_threshold")),
                    ("Stored materials", policy.get("stored_conversion")),
                    ("Previous certificates", policy.get("previous_basis")),
                ],
                width=24,
            )
        )
    return "\n\n".join(blocks)
