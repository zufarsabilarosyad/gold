"""Waiver reports: the log, and the exposure the log does not show.

The log is a list of documents.  The exposure report is the useful one: money
paid out against which no *effective* release exists, either because the waiver
was never signed or because a conditional one is still waiting on a cheque.
"""

from ..core.dates import format_date
from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..core.text import underline
from ..waivers.ledger import coverage_gap

__all__ = ["waiver_log", "exposure_report", "pending_waivers"]


def waiver_log(ledger):
    """Render the waiver log.

    >>> from ..dataio.samples import sample_waivers
    >>> print(waiver_log(sample_waivers()).splitlines()[0])
    Waiver  Type                    Application  Through          Amount  Signed
    """
    return ledger.as_table()


def pending_waivers(ledger, paid_applications=()):
    """Render the conditional waivers that have not taken effect.

    >>> from ..dataio.samples import sample_waivers
    >>> print(pending_waivers(sample_waivers(), ["PA-001"]))
    Waiver  Application  Through          Amount
    ------  -----------  ----------  -----------
    W-003   PA-002       2024-10-31  $264,000.00
    W-004   PA-003       2024-11-30  $398,000.00
    """
    table = Table(
        [
            Column("id", "Waiver"),
            Column("application", "Application"),
            Column("through", "Through"),
            Column("amount", "Amount", "right"),
        ]
    )
    for waiver in ledger.pending_conditional(paid_applications):
        table.add(
            {
                "id": waiver.id,
                "application": waiver.application_id or "-",
                "through": format_date(waiver.through),
                "amount": waiver.amount.format(),
            }
        )
    return table.render()


def exposure_report(ledger, paid_amount, paid_applications=(), as_of=None):
    """Render what has been paid for and not released.

    >>> from ..core.money import money
    >>> from ..dataio.samples import sample_waivers
    >>> print(exposure_report(sample_waivers(), money("400000"), ["PA-001"]))
    Paid to date      : $400,000.00
    Released by waiver: $304,000.00
    Unreleased        : $96,000.00
    Conditional pending: 2
    """
    released = paid_amount - coverage_gap(ledger, paid_amount, paid_applications, as_of)
    gap = coverage_gap(ledger, paid_amount, paid_applications, as_of)
    return key_value_block(
        [
            ("Paid to date", paid_amount.format()),
            ("Released by waiver", released.format()),
            ("Unreleased", gap.format()),
            ("Conditional pending", len(ledger.pending_conditional(paid_applications))),
        ],
        width=18,
    )


def waiver_report(ledger, paid_amount, paid_applications=(), as_of=None):
    """Render the whole waiver report.

    >>> from ..core.money import money
    >>> from ..dataio.samples import sample_waivers
    >>> report = waiver_report(sample_waivers(), money("400000"), ["PA-001"])
    >>> report.splitlines()[0]
    'Lien waivers'
    """
    return "\n\n".join(
        [
            underline("Lien waivers", "="),
            exposure_report(ledger, paid_amount, paid_applications, as_of),
            underline("Log", "-") + "\n" + waiver_log(ledger),
            underline("Pending conditional", "-")
            + "\n"
            + pending_waivers(ledger, paid_applications),
        ]
    )
